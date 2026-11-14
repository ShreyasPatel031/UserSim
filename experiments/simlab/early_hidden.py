"""Hidden rank in the first minutes vs the midnight forecast (orchestrator 01:44Z Nov 14). Nov 2-12; direction only. Counts only.
Hidden rank at T: recorder vote_snapshots rank_now (00:06 read, 01:00), and posts_ts daily_rank_at_fetch at 00:15 / 00:30 / 00:45 (15-min
feed, days where present; latest read <= T within 20 min). Label: official daily_rank. Arm 2 = nov_arm2 'both' (month-fold, built from
final-read inputs: a mild advantage). (1) plain hidden order vs final; what the 00:06 order correlates with (within-day Spearman with the
00:05 API list order, launch id order, name alphabetical). (2) arm 2 alone vs hidden order, paired. (3) rank-average blend w x rank(arm2)
+ (1 - w) x hidden rank, w in {0, .1, ..., 1} leave-one-day-out; gain vs arm 2 and vs hidden order.
    python early_hidden.py <scratchpad> <out dir>
"""
import glob, json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); PT = "America/Los_Angeles"; rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
DAYS = [f"2026-11-{x:02d}" for x in range(2, 13)]
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); RK = {i: r for i, r in zip(L.id, L.daily_rank) if pd.notna(r)}; NM = dict(zip(L.id, L.name))
A2 = pd.read_parquet(f"{SP}/a2x/nov_arm2.parquet"); A2["id"] = A2.id.astype(str); PR = dict(zip(A2.id, A2.both))
V = pd.concat([pd.read_json(f"{SP}/grow/vs/{d}.jsonl", lines=True, dtype={"launch_id": str}) for d in DAYS]); V["id"] = V.launch_id.astype(str); V["pt"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT); V = V.drop_duplicates(["id", "at"])
P = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in glob.glob(f"{SP}/pts/*.jsonl")]); P["id"] = P.launch_id.astype(str); P["pt"] = pd.to_datetime(P.fetched_at, utc=True, format="mixed").dt.tz_convert(PT)
def at(S, d, h, col, win):
    t0 = pd.Timestamp(d, tz=PT); th = t0 + pd.Timedelta(hours=h); s = S[(S.day == d) & (S.pt <= th) & (S.pt > max(th - pd.Timedelta(minutes=win), t0 - pd.Timedelta(minutes=5)))]
    return s.sort_values("pt").groupby("id")[col].last().dropna() if len(s) else None
API = {}
for d in DAYS:
    j = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{d}/today_0005.json"], capture_output=True).stdout or b"[]")
    API[d] = {str(x["id"]): k for k, x in enumerate(j)}
def hits(score, d):   # lower score = better
    ids = list(score.index); o = score.sort_values().index.tolist(); t = sorted(ids, key=lambda i: RK[i]); return np.array([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
def ci(A):
    A = np.asarray(A, float); bs = np.array([A[rng.integers(0, len(A), len(A))].mean(0) for _ in range(4000)])
    return [[round(float(A[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(A.shape[1])]
PTS = {"00:06": (V, 0.2, "rank_now", 15), "00:15": (P, 0.25, "daily_rank_at_fetch", 20), "00:30": (P, 0.5, "daily_rank_at_fetch", 20), "00:45": (P, 0.75, "daily_rank_at_fetch", 20), "01:00": (V, 1.0, "rank_now", 65)}
res = {"design": __doc__.split("\n    python")[0]}; WS = np.round(np.arange(0, 1.01, .1), 1)
cor = []
for d in DAYS:
    h = at(V, d, 0.2, "rank_now", 15)
    if h is None: continue
    ids = [i for i in h.index if i in RK]; h = h.loc[ids]
    c = {"final rank": spearmanr(h, [RK[i] for i in ids]).correlation, "launch id order": spearmanr(h, [int(i) for i in ids]).correlation,
         "name alphabetical": spearmanr(h, pd.Series([str(NM.get(i, "")).lower() for i in ids]).rank().values).correlation}
    if API[d]: c["00:05 API list order"] = spearmanr(h, [API[d].get(i, np.nan) for i in ids], nan_policy="omit").correlation
    c["arm 2"] = spearmanr(h, [-PR.get(i, np.nan) for i in ids], nan_policy="omit").correlation; cor.append(c)
res["(1) 00:06 hidden order: mean within-day Spearman with"] = {k: round(float(np.nanmean([c.get(k, np.nan) for c in cor])), 3) for k in cor[0]} | {"days": len(cor)}
for nm, (S, h, col, win) in PTS.items():
    F = {}
    for d in DAYS:
        r = at(S, d, h, col, win)
        if r is None: continue
        ids = [i for i in r.index if i in RK and i in PR]
        if len(ids) < 10: continue
        F[d] = (r.loc[ids].rank(), pd.Series({i: -PR[i] for i in ids}).rank())
    dd = sorted(F)
    if len(dd) < 3: res[nm] = {"days": len(dd)}; continue
    sc = lambda w, d: hits(w * F[d][1] + (1 - w) * F[d][0] + rng.random(len(F[d][0])) * 1e-6, d)
    HR = np.array([sc(0, d) for d in dd]); A = np.array([sc(1, d) for d in dd]); LO, wl = [], []
    for d in dd:
        tr = [x for x in dd if x != d]; w = max(WS, key=lambda w: np.mean([sc(w, x).mean() for x in tr])); wl.append(float(w)); LO.append(sc(w, d))
    LO = np.array(LO)
    res[nm] = {"days": len(dd), "hidden rank top3/5/10": HR.mean(0).round(1).tolist(), "arm 2 top3/5/10": A.mean(0).round(1).tolist(), "arm 2 - hidden": ci(A - HR),
               "LODO blend top3/5/10": LO.mean(0).round(1).tolist(), "blend - arm 2": ci(LO - A), "blend - hidden": ci(LO - HR), "LODO weights on arm 2": wl}
json.dump(res, open(os.path.join(OUT, "early_hidden.json"), "w"), indent=1, default=float)
for k, v in res.items():
    if k != "design": print(k, json.dumps(v, default=float))
