"""Line-up thinning: arm 2 vs arm 3, trained on final lists vs on thinned line-ups (orchestrator 14:44Z Nov 14). Held data; counts only.

Live 00:05 line-ups miss ~5.7% of ranked launches, weighted to low final ranks (16 live days; orchestrator lineup_skew_20261114.md).
Thinning draw for a day: missing fraction drawn from the 16 live fractions; that many launches removed without replacement with weight by
final-rank percentile bin (0-.2 .2-.4 .4-.6 .6-.8 .8-1: 0.24 / 0.42 / 0.20 / 1.05 / 2.78; unranked = last bin).
Set-dependent inputs recomputed on the thinned set: ph_day_n_launches, ph_hunter_n_same_day, busy_same_day, every *_dayrank_<base>, and
arm 3's A block (E5 arm3_feats.a_feats with bge-small embeddings). B and C (days <= d-2) come from E5's feature table (strong name rule).
Models (month-forward Apr-Oct 2026, 2025 + 2026 training rows as arm 2 'both', TW.prep, TW.P0, 10 seeds, predictions seed-averaged):
  m1  arm 2, trained on final lists                      (reference = deployed)
  m2d arm 2, trained on thinned days (one draw per training day), removed rows DROPPED
  m2k arm 2, trained on thinned days, removed rows KEPT with features computed on the thinned line-up (set + itself)
  m3  arm 3, trained on final lists
  m4d / m4k  arm 3, trained matched (as m2d / m2k)
Test: every model faces the same 20 thinned draws of each test day (set features recomputed on the draw); removed launches in the true top k
count as misses; per-day hits averaged over draws; also the full (unthinned) test for reference. Paired day bootstrap 10,000.
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<this dir>:~/w/mk:.:~/w/h25:<arm3 dir> H25_SRC=~/w/ph_history/2025 ARM=2
  python3 lineup_thin_arm3.py <arm3_feature_table.parquet> <arm3_emb.npz> <out dir>"""
import json, os, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb
import history_retrain as HR, training_window as TW
import arm3_feats as A3

FT, EMB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]; os.makedirs(OUT, exist_ok=True)
SEEDS = int(os.environ.get("SEEDS", "10")); NDRAW = int(os.environ.get("NDRAW", "20")); NJ = int(os.environ.get("LGB_THREADS", "3"))
LIVE = [0 / 12, 0 / 24, 4 / 20, 0 / 31, 3 / 30, 0 / 20, 2 / 22, 0 / 19, 1 / 18, 2 / 38, 0 / 34, 0 / 17, 2 / 25, 0 / 50, 10 / 26, 0 / 37]
WB = np.array([0.24, 0.42, 0.20, 1.05, 2.78])
t0 = time.time()
df, _ = HR.build(os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025")))
df["id"] = df.id.astype(str); df = df.drop_duplicates("id", keep="last").reset_index(drop=True); old = (df.day < "2026-01-01").values
T = pd.read_parquet(FT); T["id"] = T.id.astype(str); T = T.drop_duplicates("id", keep="last")
BC = [c for c in T.columns if c.startswith("B_")] + [c for c in T.columns if c.startswith("C_") and c.endswith("__strong")]
df = df.merge(T[["id"] + BC], on="id", how="left")
Z = np.load(EMB, allow_pickle=True); pos = {k: i for i, k in enumerate(Z["ids"])}; E = np.zeros((len(df), 384), np.float32)
have = df.id.map(pos); miss = have.isna().values
E[~miss] = Z["E"][have[~miss].astype(int).values]
if miss.any(): E[miss] = A3.embed(A3.text_of(df[miss]))
tops = [set(t) if isinstance(t, (list, tuple, np.ndarray)) else set() for t in df.topics]
hf = df.ph_hunter_followers.fillna(-1).values; hr = df.hist_hunter_rel.fillna(-9).values
DR = [c for c in df.columns if "_dayrank_" in c and c.split("_dayrank_", 1)[1] in df.columns]
print(json.dumps({"rows": len(df), "rows_2025": int(old.sum()), "embedded_now": int(miss.sum()), "bc_cols": len(BC), "dayrank_cols": len(DR),
                  "seconds": round(time.time() - t0)}), flush=True)


def draw(g, rng):
    """Boolean keep-mask for one day's rows (g: frame of the day)."""
    n = len(g); f = rng.choice(LIVE); r = int(round(f * n))
    keep = np.ones(n, bool)
    if r == 0: return keep
    rk = pd.to_numeric(g.dailyRank, errors="coerce").values; nr = np.isfinite(rk).sum()
    b = np.where(np.isfinite(rk), np.minimum(((rk - 0.5) / max(nr, 1) * 5).astype(int), 4), 4)
    w = WB[b] / WB[b].sum(); keep[rng.choice(n, r, replace=False, p=w)] = False
    return keep


def setfeats(idx, keep, X):
    """Recompute set-dependent inputs for rows idx (one day) given keep mask over idx. Kept rows: within the kept set. Removed rows
    (only used by the 'keep' training scheme): within kept set + the row itself. Returns dict col -> array over idx, and A rows."""
    out = {}; k_idx = idx[keep]; n = len(k_idx)
    hid = X.hunter_id.values
    out["ph_day_n_launches"] = np.where(keep, n, n + 1).astype(float)
    cnt = pd.Series(hid[k_idx]).value_counts()
    hn = np.array([cnt.get(hid[i], 0) + (0 if keep[j] else 1) for j, i in enumerate(idx)], float)
    out["ph_hunter_n_same_day"] = hn
    if "busy_same_day" in X: out["busy_same_day"] = hn
    for c in DR:
        base = X[c.split("_dayrank_", 1)[1]].values; vk = base[k_idx]; v = np.empty(len(idx))
        for j, i in enumerate(idx):
            s = vk if keep[j] else np.append(vk, base[i])
            x = base[i]
            if not np.isfinite(x): v[j] = np.nan; continue
            sf = s[np.isfinite(s)]; v[j] = ((sf < x).sum() + ((sf == x).sum() + 1) / 2) / len(sf) if len(sf) else np.nan   # rank(pct, average)
        out[c] = v
    A = {}
    A.update(A3.a_feats(k_idx, E, [tops[i] for i in k_idx], hf, hr))
    for j, i in enumerate(idx):
        if not keep[j]:   # removed row kept for training: A over the kept set plus itself
            ix = np.append(k_idx, i); A[i] = A3.a_feats(ix, E, [tops[q] for q in ix], hf, hr)[i]
    return out, A


AC = list(A3.a_feats(np.array([0, 1]), E, [tops[0], tops[1]], hf, hr)[0].keys())


def apply(X, rows, out, A):
    for c, v in out.items():
        if c in X: X.loc[rows, c] = v
    for c in AC: X.loc[rows, c] = [A[i][c] for i in rows]


# full-list A for every row
for c in AC: df[c] = np.nan
for d, g in df.groupby("day"):
    idx = g.index.values; A = A3.a_feats(idx, E, [tops[i] for i in idx], hf, hr)
    for c in AC: df.loc[idx, c] = [A[i][c] for i in idx]
# training scheme: one thinning draw per day (all days), set features recomputed
rng = np.random.default_rng(12345); TH = df.copy(); KEEP = np.ones(len(df), bool)
for d, g in df.groupby("day"):
    idx = g.index.values; kp = draw(g, rng); KEEP[idx] = kp
    out, A = setfeats(idx, kp, df); apply(TH, idx, out, A)
print(json.dumps({"train_thinning_removed_rows": int((~KEEP).sum()), "seconds": round(time.time() - t0)}), flush=True)
# test draws for 2026 Apr-Oct days
tdays = sorted(df[(df.day >= "2026-04-01") & (df.day <= "2026-10-31")].day.unique())
DRAWS = {}; rng2 = np.random.default_rng(777)
for d in tdays:
    g = df[df.day == d]; idx = g.index.values; DRAWS[d] = []
    for r in range(NDRAW):
        kp = draw(g, rng2); out, A = setfeats(idx[kp], np.ones(kp.sum(), bool), df)
        DRAWS[d].append((idx[kp], out, A))
print(json.dumps({"test_days": len(tdays), "draws": NDRAW, "seconds": round(time.time() - t0)}), flush=True)

P = []; NROWS = {}
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    te_mask = (df.mon == m).values & ~old; tr_mask = (df.mon < m).values
    schemes = {"full": (df[tr_mask], df[te_mask]), "drop": (TH[tr_mask & KEEP], df[te_mask]), "keep": (TH[tr_mask], df[te_mask])}
    for sch, (tr0, te0) in schemes.items():
        tr, te, cols = TW.prep(tr0, te0)
        cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month") and c not in AC + BC]
        NROWS.setdefault(sch, 0); NROWS[sch] += 0
        for arm, cc in (("arm2", cols), ("arm3", cols + AC + BC)):
            name = {"full": {"arm2": "m1", "arm3": "m3"}, "drop": {"arm2": "m2d", "arm3": "m4d"}, "keep": {"arm2": "m2k", "arm3": "m4k"}}[sch][arm]
            if sch == "full" and arm == "arm2": NROWS[f"{m}"] = {"full": len(tr0), "drop": int((tr_mask & KEEP).sum()), "keep": int(tr_mask.sum())}
            models = [lgb.LGBMRegressor(random_state=s, **{**TW.P0, "n_jobs": NJ}).fit(tr[cc], tr.logv) for s in range(SEEDS)]
            te_pos = {i: k for k, i in enumerate(te.index)}
            # full test
            pf = np.mean([mm.predict(te[cc]) for mm in models], 0)
            P.append(pd.DataFrame({"id": te.id.values, "day": te.day.values, "model": name, "draw": -1, "pred": pf}))
            # thinned test draws: rebuild the test rows with the draw's set features
            for d in sorted(te.day.unique()):
                for r, (kidx, out, A) in enumerate(DRAWS[d]):
                    rows = [i for i in kidx if i in te_pos]; Xd = te.loc[rows].copy()
                    for c, v in out.items():
                        if c in Xd: Xd[c] = v
                    for c in AC: Xd[c] = [A[i][c] for i in rows]
                    p = np.mean([mm.predict(Xd[cc]) for mm in models], 0)
                    P.append(pd.DataFrame({"id": Xd.id.values, "day": d, "model": name, "draw": r, "pred": p}))
        print(json.dumps({"month": m, "scheme": sch, "seconds": round(time.time() - t0)}), flush=True)
R = pd.concat(P, ignore_index=True); R.to_parquet(f"{OUT}/preds.parquet")
json.dump(NROWS, open(f"{OUT}/rows.json", "w"), indent=1)
print(json.dumps({"preds": len(R), "seconds": round(time.time() - t0)}))
