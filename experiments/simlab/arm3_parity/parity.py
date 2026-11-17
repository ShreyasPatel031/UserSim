"""Arm-3 (and arm-2 control) live vs backtest parity (orchestrator 10:44Z Nov 17). Counts and launch ids only.
Run inside a pipeline-code dir whose data/ is the live input snapshot (raw/model_inputs/arm2/20261116/ph_predict_data):
    cd <run dir> && H25_SRC=... H25_DATA=<fresh dir> ARM3_CACHE=<dir> python parity.py <out dir> <day> [<day> ...]
Paths per day d (launches of d's 00:05 line-up):
  LIVE_PUB  the published / shadow value: raw/daily/<d>/forecast_<d>.parquet pred_arm2 / pred_arm3, results/shadow_arm3/<d>.json
  LIVE_REP  the live code replayed on the snapshot (h25_live.predict / arm3_live.predict logic, copied verbatim, returning inputs too):
            F.build(include_today=True), train = finished days < d, test = data/today/<d>.json rows (the 00:05 view), A over that line-up
  BT        the backtest path (E5 rebuild): history_retrain.build (day files only = the re-read view), TW.prep, e5_abc.py A/B/C code
            (A over the day's final line-up, B over all past rows, NaN handling as e5_abc), same train cutoff (days < d), 5 seeds
Compared on ids present in both: every input column (mismatch = |live - bt| > 1e-6 relative, or null in one only), null rates,
prediction Spearman, top-10 overlap, rank differences, and which mismatching columns move a top-10 pick (swap test: put the BT
value into the live row for one column at a time and re-predict with the live model)."""
import glob, json, os, re, sys
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN
import history_retrain as HR, training_window as TW
import arm3_feats as A3
OUT = sys.argv[1]; DAYS = sys.argv[2:]; os.makedirs(OUT, exist_ok=True)
MP = ("ph_maker", "hist_maker", "hist_dayrank_hist_maker", "x_maker", "x_n_makers")
ID = {"ph_n_makers_new", "ph_maker_has_headline", "x_any_verified", "ph_self_hunted"}
P_ = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=1.0)
SEEDS = 5

def live_frame():
    root = os.path.expanduser(os.environ["H25_DATA"]); src_dir = os.path.expanduser(os.environ["H25_SRC"])
    real = F.D; os.makedirs(f"{root}/days", exist_ok=True)
    for e in os.listdir(real):
        if e != "days" and not e.startswith("build_cache") and not os.path.exists(f"{root}/{e}"): os.symlink(f"{real}/{e}", f"{root}/{e}")
    for fn in glob.glob(f"{real}/days/*.json") + glob.glob(f"{src_dir}/*.json"):
        dst = f"{root}/days/{os.path.basename(fn)}"
        if not os.path.exists(dst): os.symlink(os.path.abspath(fn), dst)
    F.D = root
    try: df = RN.load_llm(F.build(include_today=True))
    finally: F.D = real
    df["id"] = df.id.astype(str); old = df.day < "2026-01-01"
    df.loc[old, [c for c in df.columns if c.startswith(HR.OLD_NAN) or (c.startswith("llm_") and c not in ("llm_pitch", "llm_brand"))]] = np.nan
    return df

def fit_pred(tr, te, cc, seeds=SEEDS):
    ms = [lgb.LGBMRegressor(random_state=s, verbose=-1, n_jobs=8, **P_).fit(tr[cc], tr.logv) for s in range(seeds)]
    return ms, np.mean([m.predict(te[cc]) for m in ms], 0)

# ---------- backtest A/B/C (verbatim semantics of e5_abc.py) ----------
HOST_BT = re.compile(r"(github\.(io|com)|vercel\.app|netlify\.app|apple\.com|google\.com|chromewebstore|notion\.(so|site)|framer\.(app|website)|webflow\.io|producthunt\.com|youtube\.com|x\.com|twitter\.com|linkedin\.com|medium\.com|substack\.com|gumroad\.com|figma\.com|huggingface\.co|play\.google|apps\.apple|pages\.dev|carrd\.co|bubbleapps\.io|replit\.app|lovable\.app)")
def bt_abc(df, E, days_needed):
    dt = pd.to_datetime(df.day); hf = df.ph_hunter_followers.values; hr = df.hist_hunter_rel.fillna(-9).values
    def A_feats(idx):
        out = {}; S = E[idx] @ E[idx].T; np.fill_diagonal(S, np.nan); tops = [set(df.topics[i]) for i in idx]; n = len(idx); cnt = {}
        for t in tops:
            for x in t: cnt[x] = cnt.get(x, 0) + 1
        for a, i in enumerate(idx):
            same = [b for b in range(n) if b != a and tops[a] & tops[b]]; s = S[a][~np.isnan(S[a])] if n > 1 else np.array([0.0])
            st = [b for b in range(n) if b != a and hf[idx[b]] > hf[i]]; intop = same + [a]
            out[i] = {"A_same_n": len(same), "A_same_share": len(same) / max(n - 1, 1), "A_topic_max_share": max([cnt[x] / n for x in tops[a]] or [0]),
                      "A_cos_max": float(np.max(s)) if len(s) else 0.0, "A_cos_mean": float(np.mean(s)) if len(s) else 0.0, "A_cos_top3": float(np.mean(np.sort(s)[-3:])) if len(s) else 0.0,
                      "A_same_strong_fol": sum(hf[idx[b]] > hf[i] for b in same), "A_same_strong_rec": sum(hr[idx[b]] > hr[i] for b in same),
                      "A_cos_to_stronger": float(np.nanmax(S[a][st])) if st else 0.0, "A_fol_pct_in_topic": float(np.mean([hf[idx[b]] <= hf[i] for b in intop]))}
        return out
    logv = np.log1p(pd.to_numeric(df.votes, errors="coerce")).values; rk = pd.to_numeric(df.dailyRank, errors="coerce").values
    key = [A3.norm_name(x, "strong") for x in df.name]   # the __strong C columns
    dom = df.domain.fillna("").astype(str).values if "domain" in df else np.array([""] * len(df))
    BYN, BYD = defaultdict(list), defaultdict(list)
    for j in range(len(df)):
        if key[j]: BYN[key[j]].append(j)
        if dom[j] and not HOST_BT.search(dom[j]): BYD[dom[j]].append(j)
    R = {}
    for d in days_needed:
        cur = df.index[df.day == d].values; dd = pd.Timestamp(d); A = A_feats(cur)
        past = df.index[(dt <= dd - pd.Timedelta(days=2)) & (dt > dd - pd.Timedelta(days=365))].values
        p90 = set(df.index[(dt <= dd - pd.Timedelta(days=2)) & (dt > dd - pd.Timedelta(days=90))].values)
        S = E[cur] @ E[past].T; wm = np.nanmean(logv[past]); m90 = np.array([p in p90 for p in past])
        for a, i in enumerate(cur):
            s = S[a]; nn = np.argsort(-s)[:10]; w = np.clip(s[nn], 0, None)
            o = dict(A[i]); o.update({"B_nn365": float(s.max()), "B_nn90": float(s[m90].max()) if m90.any() else 0.0, "B_n085": int((s > 0.85).sum()),
                      "B_nn10_logv": float(np.nanmean(logv[past[nn]])), "B_nn10_top10": float(np.nanmean(rk[past[nn]] <= 10)),
                      "B_nn10_wlogv": float(np.nansum(w * logv[past[nn]]) / (w.sum() or 1)), "B_nn10_rel": float(np.nanmean(logv[past[nn]]) - wm)})
            cand = set(BYN.get(key[i], [])) | (set(BYD.get(dom[i], [])) if dom[i] and not HOST_BT.search(dom[i]) else set())
            prv = [j for j in cand if dt[j] <= dd - pd.Timedelta(days=2)]
            o.update({"C_prev": int(bool(prv)), "C_prev_n": len(prv), "C_days_since": float((dd - dt[max(prv, key=lambda j: dt[j])]).days) if prv else np.nan,
                      "C_prev_logv": float(logv[max(prv, key=lambda j: dt[j])]) if prv else np.nan, "C_prev_best_rank": float(np.nanmin(rk[prv])) if prv else np.nan})
            R[i] = o
    return R

def bt_text(df): return (df.name.astype(str) + ". " + df.tagline.astype(str) + ". " + df.description.astype(str).str[:400] + ". " + df.topics.map(lambda t: ", ".join(t))).tolist()

LIVE = live_frame()
BTD, _ = HR.build(os.environ["H25_SRC"]); BTD = BTD.reset_index(drop=True); BTD["id"] = BTD.id.astype(str)
emb_cache = {}
def embed(texts, tag):
    if tag not in emb_cache: emb_cache[tag] = A3.embed(texts)
    return emb_cache[tag]
summary = {"days": {}}
for d in DAYS:
    R = {"day": d}
    # ---- live replay (arm 3 and arm 2)
    cut = (pd.Timestamp(d) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")   # live store holds finished days through d-2 at 00:05 (forecast_inputs store.latest_day)
    df = LIVE[(~LIVE.known & (LIVE.day < cut) & ~LIVE.is_today) | (LIVE.is_today & (LIVE.day == d))].reset_index(drop=True)   # deployed r5 rule
    df.loc[(df.is_today & df.known.astype(bool)).values, [c for c in df.columns if c.startswith("llm_")]] = np.nan   # known launches tonight: llm_* blank (live)
    tod = (df.is_today & (df.day == d)).values
    if not tod.any(): R["status"] = "no 00:05 line-up rows in the snapshot"; summary["days"][d] = R; continue
    E = A3.embed(A3.text_of(df))   # fresh embeddings (live uses a cache of the same pinned model for finished days)
    X, NEW = A3.add_feats(df, E, norm="strong", line_up=tod)
    tr, te = X[~tod], X[tod].copy(); tr, te = M.add_fold_feats(tr, te); src, _ = M.live_sources(tr, te, M.LIVE_SOURCES)
    base = [c for c in M.cols(tr, src) if not c.startswith(MP) and c not in ID and c not in ("llm_site", "ph_month")]
    cc3 = base + NEW
    m3, p3 = fit_pred(tr, te, cc3); m2, p2 = fit_pred(tr, te, base)
    L = te[["id"] + cc3].copy(); L["rep3"], L["rep2"] = p3, p2
    # ---- backtest path
    bd = BTD[(BTD.day < cut) | (BTD.day == d)].reset_index(drop=True)
    Eb = A3.embed(bt_text(bd)); abc = bt_abc(bd, Eb, [d]);
    for c in ["A_same_n", "A_same_share", "A_topic_max_share", "A_cos_max", "A_cos_mean", "A_cos_top3", "A_same_strong_fol", "A_same_strong_rec", "A_cos_to_stronger", "A_fol_pct_in_topic",
              "B_n085", "B_nn10_logv", "B_nn10_rel", "B_nn10_top10", "B_nn10_wlogv", "B_nn365", "B_nn90", "C_days_since", "C_prev", "C_prev_best_rank", "C_prev_logv", "C_prev_n"]:
        bd[c] = bd.index.map(lambda i: abc.get(i, {}).get(c, np.nan))
    # B/C for training rows: from the stored rebuild table (same code, computed once over all days) - keeps the BT model = the rebuild model
    T = pd.read_parquet(os.environ["ARM3_TABLE"]); T["id"] = T.id.astype(str)
    trb = bd[bd.day < cut].drop(columns=[c for c in bd.columns if c[:2] in ("A_", "B_", "C_")]).merge(T.drop(columns=["day"]), on="id", how="left")
    for c in ["C_days_since", "C_prev", "C_prev_best_rank", "C_prev_logv", "C_prev_n"]: trb[c] = trb[c + "__strong"]
    teb = bd[bd.day == d].copy()
    trb, teb, cols = TW.prep(trb, teb); bbase = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    NEWB = [c for c in NEW]; cc3b = bbase + NEWB
    _, b3 = fit_pred(trb, teb, cc3b); _, b2 = fit_pred(trb, teb, bbase)
    Bt = teb[["id", "dailyRank"] + [c for c in cc3b if c in teb]].copy(); Bt["bt3"], Bt["bt2"] = b3, b2
    # ---- published
    fp = f"{os.environ['PUB_DIR']}/forecast_{d}.parquet"; P = pd.read_parquet(fp); P["id"] = P.id.astype(str)
    pubc = ["id", "pred_arm2"] + (["pred_arm3"] if "pred_arm3" in P else [])
    sh = f"{os.environ['PUB_DIR']}/{d}.json"
    if "pred_arm3" not in P and os.path.exists(sh): P = P.merge(pd.DataFrame(json.load(open(sh))["ranking"])[["id", "pred_arm3"]].astype({"id": str}), on="id", how="left"); pubc.append("pred_arm3")
    J = L.merge(Bt, on="id", how="outer", suffixes=("_live", "_bt"), indicator=True).merge(P[pubc], on="id", how="left")
    R["ids"] = {"live_lineup": int(len(L)), "bt_rows": int(len(Bt)), "both": int((J._merge == "both").sum()), "live_only": int((J._merge == "left_only").sum()), "bt_only": int((J._merge == "right_only").sum())}
    both = J[J._merge == "both"].copy()
    # column-by-column
    colrep = {}
    for c in sorted(set(cc3) | set(cc3b)):
        a = both.get(c + "_live", both.get(c)) if (c + "_live") in both else None; b = both.get(c + "_bt") if (c + "_bt") in both else None
        if a is None or b is None: colrep[c] = {"in_live": c in cc3, "in_bt": c in cc3b}; continue
        a = pd.to_numeric(a, errors="coerce"); b = pd.to_numeric(b, errors="coerce")
        nul = (a.isna() != b.isna()); dif = (~a.isna() & ~b.isna()) & ((a - b).abs() > 1e-6 * np.maximum(1, b.abs()))
        if nul.sum() or dif.sum():
            colrep[c] = {"mismatch": int(nul.sum() + dif.sum()), "null_only_one_side": int(nul.sum()), "null_rate_live": round(float(a.isna().mean()), 3), "null_rate_bt": round(float(b.isna().mean()), 3)}
    R["column_mismatches"] = colrep
    R["null_rate_flags_5pct"] = {c: v for c, v in colrep.items() if "null_rate_live" in v and ((v["null_rate_live"] > .05) != (v["null_rate_bt"] > .05))}
    # predictions
    def top(s, k=10): return set(both.sort_values(s, ascending=False).id[:k])
    pr = {}
    for a, b in (("pred_arm3", "rep3"), ("rep3", "bt3"), ("pred_arm3", "bt3"), ("pred_arm2", "rep2"), ("rep2", "bt2"), ("pred_arm2", "bt2")):
        if a in both and both[a].notna().any():
            rk_a = both[a].rank(ascending=False); rk_b = both[b].rank(ascending=False)
            pr[f"{a} vs {b}"] = {"spearman": round(float(both[a].corr(both[b], method="spearman")), 3), "top10_overlap": len(top(a) & top(b)), "top3_overlap": len(top(a, 3) & top(b, 3)),
                                 "max_abs_rank_diff": int((rk_a - rk_b).abs().max()), "mean_abs_rank_diff": round(float((rk_a - rk_b).abs().mean()), 2)}
    R["predictions"] = pr
    # swap test: which mismatching columns move a live top-10 pick when the BT value is used (live arm-3 model)
    sw = {}
    base_top = set(both.sort_values("rep3", ascending=False).id[:10]); Xl = te.set_index("id").loc[both.id, cc3].copy()
    for c, v in colrep.items():
        if "mismatch" not in v or c not in cc3 or (c + "_bt") not in both: continue
        Xs = Xl.copy(); Xs[c] = pd.to_numeric(both.set_index("id")[c + "_bt"], errors="coerce").values
        ps = np.mean([m.predict(Xs[cc3]) for m in m3], 0); t2 = set(pd.Series(ps, index=Xs.index).sort_values(ascending=False).index[:10])
        sw[c] = {"top10_changed": len(base_top - t2), "top3_changed": len(set(both.sort_values("rep3", ascending=False).id[:3]) - set(pd.Series(ps, index=Xs.index).sort_values(ascending=False).index[:3]))}
    R["swap_test_arm3"] = sw
    # final-rank hits for each line (where final)
    fin = both[both.dailyRank.notna()]
    if len(fin) >= 10:
        R["hits_top3_5_10"] = {s: [len(set(fin.sort_values(s, ascending=False).id[:k]) & set(fin[fin.dailyRank <= k].id)) / k * 100 for k in (3, 5, 10)]
                               for s in ("pred_arm2", "pred_arm3", "rep2", "rep3", "bt2", "bt3") if s in fin and fin[s].notna().any()}
    both.drop(columns=["_merge"]).to_parquet(f"{OUT}/rows_{d}.parquet"); summary["days"][d] = R; print(json.dumps(R, default=str)[:3000], flush=True)
json.dump(summary, open(f"{OUT}/parity_summary.json", "w"), indent=1, default=str)
