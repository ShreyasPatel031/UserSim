"""Does training on 2025 too help the clean 00:05 model? (orchestrator 03:51Z / 04:34Z Nov 13; shadow / backtest only; VM, read-only
for the pipeline). 2025 lists: raw/ph_history/2025/<day>.json (Data Feeder, official API v2, featured:true, order RANKING; same
shape as data/days/<day>.json plus reviewsCount / reviewsRating; counts and follower numbers as of fetch).
Build: a private data dir H25_DATA (default ~/w/h25/data) holding symlinks to every entry of ph_predict/data except days/, and a
days/ dir = 2026 day files (symlinks) + the 2025 files; features.D is pointed at it and features.build() + run.load_llm() run as
usual, so hunter history (hist_hunter_*) and topic priors (topic_prior_*, fitted inside M.add_fold_feats on the training rows)
are rebuilt in time order over 2025 + 2026. The pipeline's data/ and build cache are never written.
Old-row rules (rows with day < 2026-01-01): promo_*, busy_*, x_* inputs -> missing (NaN, not 0); ph_month dropped for every row;
follower-count inputs read at fetch (ph_hunter_followers, ph_dayrank_ph_hunter_followers) -> variant with and without (nofol).
Columns = clean_v3_nosite (honest_cols over LIVE + PAGE sources, minus ID_COLS, minus llm_site) minus ph_month.
Test: month-forward over training_window.MONTHS (same as the clean backtest); 2026-only = train rows day >= 2026-01-01 and month
< test month; h25 = train rows of 2025 + 2026 before the test month. 3 seeds. Score on Apr-Oct days: top 3/5/10, daily Spearman,
paired day bootstrap. Output results/history_retrain.md + results/history_retrain_preds.parquet.
usage (VM, from ph_predict): PYTHONPATH=~/w/mk H25_SRC=<dir of 2025 json> python3 history_retrain.py [--probe]
--probe: unit test only (build + old-row rules + feature sanity on whatever 2025 days exist; no fitting)."""
import glob, json, os, sys, time
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import features as F, run as RN, model as M
import training_window as TW
OLD_NAN = ("promo_", "busy_", "x_")
FOL = ["ph_hunter_followers", "ph_dayrank_ph_hunter_followers"]
SEEDS = int(os.environ.get("SEEDS", "5"))   # orchestrator 04:50Z: >= 5 seeds per arm; seed spread reported next to the paired interval


def oof_topic(tr):
    """topic_prior_max / _mean on the TRAINING rows recomputed out of fold (4 whole-day folds, same shrinkage as model.add_fold_feats)."""
    tr = tr.copy(); y = (tr.logv - tr.groupby("day").logv.transform("mean")).values
    folds = np.array(pd.factorize(tr.day)[0]) % 4; mx, mn = np.zeros(len(tr)), np.zeros(len(tr))
    for k in range(4):
        ex = tr[folds != k][["topics"]].assign(rel=y[folds != k]).explode("topics")
        st = ex.groupby("topics").rel.agg(["mean", "count"]); tm = (st["mean"] * st["count"] / (st["count"] + 20)).to_dict()
        sel = folds == k
        mx[sel] = [max([tm.get(t, 0) for t in ts] or [0]) for ts in tr.topics[sel]]
        mn[sel] = [np.mean([tm.get(t, 0) for t in ts] or [0]) for ts in tr.topics[sel]]
    tr["topic_prior_max"], tr["topic_prior_mean"] = mx, mn
    return tr


def build(src):
    root = os.path.expanduser(os.environ.get("H25_DATA", "~/w/h25/data")); os.makedirs(f"{root}/days", exist_ok=True)
    real = F.D
    for e in os.listdir(real):
        if e != "days" and not e.startswith("build_cache") and not os.path.exists(f"{root}/{e}"):
            os.symlink(f"{real}/{e}", f"{root}/{e}")
    for fn in glob.glob(f"{real}/days/*.json") + glob.glob(f"{src}/*.json"):
        dst = f"{root}/days/{os.path.basename(fn)}"
        if not os.path.exists(dst):
            os.symlink(os.path.abspath(fn), dst)
    F.D = root
    df = RN.load_llm(F.build()); df = df[~df.known].copy(); df["id"] = df.id.astype(str)
    df["mon"] = df.day.str[:7]; old = df.day < "2026-01-01"
    # ARM=1 (default): llm_* missing on 2025 rows; ARM=2: keep the 2025 llm_pitch / llm_brand scored by h25_llm.py (llm_site / llm_full
    # stay missing: no 2025 homepage text, no team facts)
    arm2 = os.environ.get("ARM", "1") == "2"
    nan_cols = [c for c in df.columns if c.startswith(OLD_NAN) or (c.startswith("llm_") and not (arm2 and c in ("llm_pitch", "llm_brand")))]
    df.loc[old, nan_cols] = np.nan
    return df, nan_cols


def score(A, col):
    out = []
    for d, g in A.groupby("day"):
        t = g.sort_values("dailyRank").id.tolist(); o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist()
        out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)] + [g[col].corr(-g.dailyRank, method="spearman")])
    return np.array(out)


def main():
    t0 = time.time(); src = os.environ.get("H25_SRC", os.path.expanduser("~/w/ph_history/2025"))
    df, nan_cols = build(src); old = df.day < "2026-01-01"
    info = {"rows": int(len(df)), "rows_2025": int(old.sum()), "days_2025": int(df[old].day.nunique()), "days_2026": int(df[~old].day.nunique()),
            "nan_cols_2025": len(nan_cols), "hist_hunter_rel_filled_2026_2026only_vs_h25": None}
    if "--probe" in sys.argv:
        o, n = df[old], df[~old]
        chk = {c: [round(float(o[c].notna().mean()), 3), round(float(n[c].notna().mean()), 3)] for c in
               ["hist_hunter_n", "hist_hunter_rel", "ph_hunter_followers", "ph_n_makers", "ph_n_topics", "llm_site", "llm_pitch", "dailyRank", "logv"] if c in df}
        info.update({"filled_share_2025_vs_2026": chk, "hunters_2026_with_2025_history": int(n.hunter_id.isin(set(o.hunter_id)).sum()),
                     "hist_hunter_n_mean_2026": round(float(n.hist_hunter_n.mean()), 3), "seconds": round(time.time() - t0)})
        print(json.dumps(info, default=str)); return
    MONTHS = [m for m in TW.MONTHS if m >= "2026-03"]; P = []
    for m in MONTHS:
        te0 = df[df.mon == m]
        if te0.empty:
            continue
        for nm, tr0 in (("only2026", df[(df.mon < m) & ~old]), ("h25", df[df.mon < m])):
            tr, te, cols = TW.prep(tr0, te0)
            cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
            trs = {"": tr}
            if os.environ.get("OOF_TOPIC") == "1":   # orchestrator 04:50Z: training rows must not see their own result in their topic prior
                trs["_ooftopic"] = oof_topic(tr)
            for suf, tr_ in trs.items():
                for var, cc in ((nm + suf, cols), (nm + suf + "_nofol", [c for c in cols if c not in FOL])):
                    for s in range(SEEDS):
                        P.append(pd.DataFrame({"id": te.id.values, "variant": var, "seed": s, "pred": TW.fitw(tr_, te, cc, s)}))
        print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
    R = pd.concat(P)
    SP = {}   # seed spread: each seed's own score, per variant
    for (var, sd), g in R.groupby(["variant", "seed"]):
        g = g.merge(df[["id", "day", "dailyRank"]], on="id"); g = g[(g.day >= "2026-04-01") & (g.day <= "2026-10-31")]
        SP.setdefault(var, []).append(score(g.rename(columns={"pred": "x"}), "x").mean(0))
    P = R.groupby(["id", "variant"]).pred.mean().unstack().reset_index().merge(df[["id", "day", "dailyRank"]], on="id")
    P = P[(P.day >= "2026-04-01") & (P.day <= "2026-10-31")]
    P.to_parquet(f"results/history_retrain{'_arm2' if os.environ.get('ARM') == '2' else ''}_preds.parquet")
    rng = np.random.default_rng(0); md = [f"# 2025 + 2026 training vs 2026-only, clean_nosite ({P.day.nunique()} days Apr-Oct; month-forward; {SEEDS} seeds, mean prediction)", "",
          "```", json.dumps(info), "```", "", "| variant | top 3 | top 5 | top 10 | daily Spearman | diff vs 2026-only (t3 / t5 / t10 / rho, 95%) |", "|---|---|---|---|---|---|"]
    pairs = [("only2026", "h25"), ("only2026_nofol", "h25_nofol")] + ([("only2026_ooftopic", "h25_ooftopic"), ("h25", "h25_ooftopic")] if "h25_ooftopic" in P else [])
    md[-2] = "| variant | top 3 | top 5 | top 10 | daily Spearman | seed spread (sd over seeds: t3 / t5 / t10 / rho) | diff vs base (t3 / t5 / t10 / rho, 95%) |"
    md[-1] = "|---|---|---|---|---|---|---|"
    for base, alt in pairs:
        B_, A_ = score(P, base), score(P, alt); dP = A_ - B_
        b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        for nm, X in ((base, B_), (alt, A_)):
            sd_ = np.std(np.array(SP[nm]), axis=0)
            md.append(f"| {nm} | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {np.nanmean(X[:,3]):.3f} | {sd_[0]:.1f} / {sd_[1]:.1f} / {sd_[2]:.1f} / {sd_[3]:.3f} | " +
                      (" / ".join(f"{dP[:,k].mean():+.{3 if k == 3 else 1}f} [{np.percentile(b[:,k],2.5):+.{3 if k == 3 else 1}f}, {np.percentile(b[:,k],97.5):+.{3 if k == 3 else 1}f}]" for k in range(4)) if nm == alt else "-") + " |")
    open(f"results/history_retrain{'_arm2' if os.environ.get('ARM') == '2' else ''}.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
