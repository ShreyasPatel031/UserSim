"""E5 PRE-REGISTERED replication (orchestrator 13:10Z Nov 14) of the subagent's new 00:05 signals A + B + C, written from new_signals.md only
(feats.py not read before this ran). Primary: A+B+C vs base, top 10, 183-day rule (>= 10 ranked), paired day bootstrap, interval clear
of 0. Secondary: top 3 on the last 90 of the 183 days. Fresh seeds 5-9. Arm-2 rebuild harness (HR.build, TW.prep, cols minus ID_COLS /
llm_site / ph_month, TW.P0), month-forward Apr-Oct 2026.
A (within the day's line-up): same-topic count / share, max topic share, max / mean / top-3-mean bge-small cosine to the other launches,
   same-topic launches with more hunter followers / a higher hunter record, max cosine to a launch with more hunter followers, hunter-
   follower percentile inside the topic. A_drop: test rows' A recomputed with 6% of the other launches removed (3 draws).
B (launches on days <= d-2): nearest cosine over 90 / 365 days, count cosine > 0.85 (365), 10 nearest (365): mean log-votes, top-10 rate,
   similarity-weighted log-votes, mean log-votes minus the window mean.
C (days <= d-2): same normalised name or same non-hosting domain: flag, count, days since, previous log-votes, best previous daily rank.
Text for the embedding: name. tagline. description[:400]. topics.     usage: python e5_abc.py <out parquet>"""
import json, os, re, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; rng = np.random.default_rng(5)
df, _ = HR.build(os.environ["H25_SRC"]); old = df.day < "2026-01-01"; df = df.reset_index(drop=True)
EP = OUT.replace(".parquet", "_emb.npy")
if os.path.exists(EP): E = np.load(EP)
else:
    from sentence_transformers import SentenceTransformer
    txt = (df.name.astype(str) + ". " + df.tagline.astype(str) + ". " + df.description.astype(str).str[:400] + ". " + df.topics.map(lambda t: ", ".join(t))).tolist()
    E = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").encode(txt, batch_size=64, normalize_embeddings=True, show_progress_bar=False); np.save(EP, E)
print(json.dumps({"emb": E.shape, "seconds": round(time.time() - t0)}), flush=True)
dt = pd.to_datetime(df.day); hf = df.ph_hunter_followers.values; hr = df.hist_hunter_rel.fillna(-9).values
def A_feats(idx):
    """A for the launches idx (one day's line-up as given)."""
    out = {}; S = E[idx] @ E[idx].T; np.fill_diagonal(S, np.nan); tops = [set(df.topics[i]) for i in idx]; n = len(idx)
    cnt = {}
    for t in tops:
        for x in t: cnt[x] = cnt.get(x, 0) + 1
    for a, i in enumerate(idx):
        same = [b for b in range(n) if b != a and tops[a] & tops[b]]; s = S[a][~np.isnan(S[a])] if n > 1 else np.array([0.0])
        st = [b for b in range(n) if b != a and hf[idx[b]] > hf[i]]
        intop = [b for b in same] + [a]
        out[i] = {"A_same_n": len(same), "A_same_share": len(same) / max(n - 1, 1), "A_topic_max_share": max([cnt[x] / n for x in tops[a]] or [0]),
                  "A_cos_max": float(np.max(s)) if len(s) else 0.0, "A_cos_mean": float(np.mean(s)) if len(s) else 0.0, "A_cos_top3": float(np.mean(np.sort(s)[-3:])) if len(s) else 0.0,
                  "A_same_strong_fol": sum(hf[idx[b]] > hf[i] for b in same), "A_same_strong_rec": sum(hr[idx[b]] > hr[i] for b in same),
                  "A_cos_to_stronger": float(np.nanmax(S[a][st])) if st else 0.0,
                  "A_fol_pct_in_topic": float(np.mean([hf[idx[b]] <= hf[i] for b in intop]))}
    return out
A = {}
for d, g in df.groupby("day"): A.update(A_feats(g.index.values))
AC = list(next(iter(A.values())).keys())
for c in AC: df[c] = df.index.map(lambda i: A[i][c])
# B and C, as of d-2
logv = np.log1p(pd.to_numeric(df.votes, errors="coerce")).values; rk = df.dailyRank.values
norm = df.name.astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True).values
HOST = re.compile(r"(github\.(io|com)|vercel\.app|netlify\.app|apple\.com|google\.com|chromewebstore|notion\.(so|site)|framer\.(app|website)|webflow\.io|producthunt\.com|youtube\.com|x\.com|twitter\.com|linkedin\.com|medium\.com|substack\.com|gumroad\.com|figma\.com|huggingface\.co|play\.google|apps\.apple|pages\.dev|carrd\.co|bubbleapps\.io|replit\.app|lovable\.app)")
dom = df.domain.fillna("").astype(str).values if "domain" in df else np.array([""] * len(df))
BC = {}; from collections import defaultdict
BYN, BYD = defaultdict(list), defaultdict(list)
for j in range(len(df)):
    if norm[j]: BYN[norm[j]].append(j)
    if dom[j] and not HOST.search(dom[j]): BYD[dom[j]].append(j)
days = sorted(df.day.unique())
for d in days:
    cur = df.index[df.day == d].values; dd = pd.Timestamp(d)
    past = df.index[(dt <= dd - pd.Timedelta(days=2)) & (dt > dd - pd.Timedelta(days=365))].values
    p90 = set(df.index[(dt <= dd - pd.Timedelta(days=2)) & (dt > dd - pd.Timedelta(days=90))].values)
    if len(past):
        S = E[cur] @ E[past].T; wm = np.nanmean(logv[past]); m90 = np.array([p in p90 for p in past])
    for a, i in enumerate(cur):
        o = {}
        if len(past):
            s = S[a]; nn = np.argsort(-s)[:10]; w = np.clip(s[nn], 0, None)
            o.update({"B_nn365": float(s.max()), "B_nn90": float(s[m90].max()) if m90.any() else 0.0, "B_n085": int((s > 0.85).sum()),
                      "B_nn10_logv": float(np.nanmean(logv[past[nn]])), "B_nn10_top10": float(np.nanmean(rk[past[nn]] <= 10)),
                      "B_nn10_wlogv": float(np.nansum(w * logv[past[nn]]) / (w.sum() or 1)), "B_nn10_rel": float(np.nanmean(logv[past[nn]]) - wm)})
        cand = set(BYN.get(norm[i], [])) | (set(BYD.get(dom[i], [])) if dom[i] and not HOST.search(dom[i]) else set())
        prv = [j for j in cand if dt[j] <= dd - pd.Timedelta(days=2)]
        o.update({"C_prev": int(bool(prv)), "C_prev_n": len(prv), "C_days_since": float((dd - dt[max(prv, key=lambda j: dt[j])]).days) if prv else np.nan,
                  "C_prev_logv": float(logv[max(prv, key=lambda j: dt[j])]) if prv else np.nan, "C_prev_best_rank": float(np.nanmin(rk[prv])) if prv else np.nan})
        BC[i] = o
BCC = sorted({k for v in BC.values() for k in v})
for c in BCC: df[c] = df.index.map(lambda i: BC[i].get(c, np.nan))
NEW = AC + BCC; print(json.dumps({"features": NEW, "C_prev share 2026 test": round(float(df[(df.day >= "2026-04-01") & ~old].C_prev.mean()), 3), "seconds": round(time.time() - t0)}), flush=True)
rows = []
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    te0 = df[(df.mon == m) & ~old]; tr, te, cols = TW.prep(df[df.mon < m], te0); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    o = te[["id", "day", "dailyRank"]].copy()
    drops = []
    for k in range(3):   # A recomputed on the test line-ups with 6% of the other launches removed (each launch keeps itself)
        Ad = {}
        for d, g in te.groupby("day"):
            ix = g.index.values; keep = ix[rng.random(len(ix)) >= 0.06]
            for i in ix:
                sub = np.unique(np.r_[keep, i]); Ad[i] = A_feats(sub)[i]
        X = te.copy()
        for c in AC: X[c] = X.index.map(lambda i: Ad[i][c])
        drops.append(X)
    for nm, cc in (("base", base), ("abc", base + NEW), ("a_only", base + AC)):   # a_only: extra rows requested 13:20Z (not pre-registered)
        ms = [lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[cc], tr.logv) for s in range(5, 10)]
        o[nm] = np.mean([mm.predict(te[cc]) for mm in ms], axis=0)
        if nm == "abc":
            for k, X in enumerate(drops): o[f"abc_drop_d{k}"] = np.mean([mm.predict(X[cc]) for mm in ms], axis=0)
    rows.append(o); print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
pd.concat(rows).to_parquet(OUT); print("done", flush=True)
