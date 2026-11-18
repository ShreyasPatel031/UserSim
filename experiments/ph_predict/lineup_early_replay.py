"""Replay arm 2 vs arm 3 on REAL early line-ups from held data (orchestrator 15:13Z Nov 14). Counts only.
Line-up membership = the held early read (Wayback homepage capture <= 03:00 PT, or the vote_snapshots first read 00:06 PT for Nov 5-7;
early_members.json). Inputs for launches present come from the day files (text may be later than 00:05; same for both arms). Block A and
arm 2's set-dependent inputs (ph_day_n_launches, ph_hunter_n_same_day, busy_same_day, *_dayrank_*) recomputed on the early membership.
Launches in the early read but not in the final featured list are counted (they were on the board) but cannot be scored or featurised.
Models month-forward (train on months < the test day's month, 2025 + 2026 rows as arm 2 'both', TW.prep, TW.P0, 10 seeds averaged);
arm 3 = arm 2 + A (on membership) + B + C strong (E5 feature table, joined by id with row-count asserts). Truth = official dailyRank;
launches missing from the early read that finish in the true top k count as misses. Primary (pre-registered): arm 3 - arm 2 top 10 on the
19 days (Oct 16 excluded: partial render); extras: with Oct 16, and pooled with E5's 17 (E5 file, if given).
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=<dir>:~/w/mk:.:~/w/h25:<arm3 dir> H25_SRC=~/w/ph_history/2025 ARM=2
  python3 lineup_early_replay.py <arm3_feature_table.parquet> <arm3_emb.npz> <early_members.json> <out dir>"""
import json, os, sys, time
import numpy as np, pandas as pd
import lightgbm as lgb
import history_retrain as HR, training_window as TW
import arm3_feats as A3

FT, EMB, MEM, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); SEEDS = int(os.environ.get("SEEDS", "10")); NJ = int(os.environ.get("LGB_THREADS", "3"))
t0 = time.time()
df, _ = HR.build(os.path.expanduser(os.environ.get("H25_SRC", "~/w/ph_history/2025")))
df["id"] = df.id.astype(str); n0 = len(df); df = df.drop_duplicates("id", keep="last").reset_index(drop=True)
T = pd.read_parquet(FT); T["id"] = T.id.astype(str); T = T.drop_duplicates("id", keep="last")
BC = [c for c in T.columns if c.startswith("B_")] + [c for c in T.columns if c.startswith("C_") and c.endswith("__strong")]
n1 = len(df); df = df.merge(T[["id"] + BC], on="id", how="left"); assert len(df) == n1, "merge changed row count"
Z = np.load(EMB, allow_pickle=True); pos = {k: i for i, k in enumerate(Z["ids"])}; E = np.zeros((len(df), 384), np.float32)
have = df.id.map(pos); miss = have.isna().values; E[~miss] = Z["E"][have[~miss].astype(int).values]
if miss.any(): E[miss] = A3.embed(A3.text_of(df[miss]))
tops = [set(t) if isinstance(t, (list, tuple, np.ndarray)) else set() for t in df.topics]
hf = df.ph_hunter_followers.fillna(-1).values; hr = df.hist_hunter_rel.fillna(-9).values
DR = [c for c in df.columns if "_dayrank_" in c and c.split("_dayrank_", 1)[1] in df.columns]
AC = list(A3.a_feats(np.array([0, 1]), E, [tops[0], tops[1]], hf, hr)[0].keys())
for c in AC: df[c] = np.nan
for d, g in df.groupby("day"):   # full-list A for training rows (arm 3 as backtested)
    idx = g.index.values; A = A3.a_feats(idx, E, [tops[i] for i in idx], hf, hr)
    for c in AC: df.loc[idx, c] = [A[i][c] for i in idx]
MEMB = json.load(open(MEM)); info = {"rows_build": n0, "rows_dedup": n1, "bc_cols": len(BC), "days": {}}


def set_inputs(Xd, n_board):
    """Recompute set-dependent inputs on the early membership (Xd = present launches that are in the final list; n_board = board size)."""
    Xd = Xd.copy(); Xd["ph_day_n_launches"] = float(n_board)
    hn = Xd.groupby("hunter_id").id.transform("count").astype(float); Xd["ph_hunter_n_same_day"] = hn
    if "busy_same_day" in Xd: Xd["busy_same_day"] = hn
    for c in DR: Xd[c] = Xd[c.split("_dayrank_", 1)[1]].rank(pct=True)
    idx = Xd.index.values; A = A3.a_feats(idx, E, [tops[i] for i in idx], hf, hr)
    for c in AC: Xd[c] = [A[i][c] for i in idx]
    return Xd


R = []
for m in sorted({d[:7] for d in MEMB}):
    tr0 = df[df.mon < m]; days = [d for d in sorted(MEMB) if d[:7] == m]; te0 = df[df.day.isin(days)]
    tr, te, cols = TW.prep(tr0, te0)
    cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month") and c not in AC + BC]
    mods = {arm: [lgb.LGBMRegressor(random_state=s, **{**TW.P0, "n_jobs": NJ}).fit(tr[cc], tr.logv) for s in range(SEEDS)]
            for arm, cc in (("arm2", cols), ("arm3", cols + AC + BC))}
    for d in days:
        mem = set(MEMB[d]["ids"]); g = te[te.day == d]; pres = g[g.id.isin(mem)]
        Xd = set_inputs(pres, len(mem))
        ranked = g[pd.to_numeric(g.dailyRank, errors="coerce").notna()]
        info["days"][d] = {"src": MEMB[d]["src"], "pt": MEMB[d]["pt"], "board": len(mem), "present_in_final": len(pres), "ranked": len(ranked),
                           "ranked_missing": int((~ranked.id.isin(mem)).sum()), "board_not_in_final": len(mem - set(g.id))}
        for arm, cc in (("arm2", cols), ("arm3", cols + AC + BC)):
            p = np.mean([mm.predict(Xd[cc]) for mm in mods[arm]], 0)
            R.append(pd.DataFrame({"day": d, "arm": arm, "id": Xd.id.values, "pred": p}))
    print(json.dumps({"month": m, "days": len(days), "train_rows": len(tr0), "seconds": round(time.time() - t0)}), flush=True)
R = pd.concat(R); R.to_parquet(f"{OUT}/preds.parquet")
truth = {d: g.assign(r=pd.to_numeric(g.dailyRank, errors="coerce")).dropna(subset=["r"]).sort_values("r").id.tolist() for d, g in df[df.day.isin(MEMB)].groupby("day")}
KS = (3, 5, 10); H = {}
for (d, arm), g in R.groupby(["day", "arm"]):
    o = g.sort_values(["pred", "id"], ascending=[False, True]).id.tolist(); t = truth[d]
    H[(d, arm)] = [len(set(o[:k]) & set(t[:k])) / k * 100 for k in KS]
rng = np.random.default_rng(0); L = []
def rep(lab, days):
    days = [d for d in days if len(truth[d]) >= 10]
    a2 = np.array([H[(d, "arm2")] for d in days]); a3 = np.array([H[(d, "arm3")] for d in days]); x = a3 - a2
    bs = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
    L.append(f"{lab} ({len(days)} days, >= 10 ranked): arm 2 {a2.mean(0).round(1).tolist()} arm 3 {a3.mean(0).round(1).tolist()}; arm 3 - arm 2 " +
             " / ".join(f"{x[:, k].mean():+.1f} [{np.percentile(bs[:, k], 2.5):+.1f}, {np.percentile(bs[:, k], 97.5):+.1f}]" for k in range(3)))
alld = sorted(MEMB); rep("PRIMARY 19 days (Oct 16 excluded)", [d for d in alld if d != "2026-10-16"]); rep("all 20 incl. Oct 16", alld)
rep("<= 01:00 PT reads only", [d for d in alld if d != "2026-10-16" and MEMB[d]["pt"] <= "01:00"])
json.dump({"days": info["days"], "lines": L, "per_day": {f"{d}|{a}": v for (d, a), v in H.items()}}, open(f"{OUT}/score.json", "w"), indent=1)
print("\n".join(L)); print(json.dumps({k: v for k, v in info.items() if k != "days"}))
