"""Hidden rank + arm-2 prior blend, independent replication (orchestrator 00:00Z Nov 14). Counts only.
Hidden rank = rank_now in raw/vote_snapshots at 01:00 / 02:00 / 03:00 PT (03:45 = the 03:00 read; votes are 0 on all pre-04:00 reads).
Prior = per-launch arm-2 score (file given; column given). Blend = w x within-day rank(prior) + (1 - w) x hidden rank (rank average),
w from {0, .1, ..., 1} chosen leave-one-day-out (best mean top 3/5/10 on the other days). Truth = warehouse daily_rank. Paired gains vs
plain hidden rank, day bootstrap; also prior alone and the in-fit best w.
    python hidden_blend.py <scratchpad> <prior parquet glob> <prior column> <days comma list> <out json>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
SP, PG, PC, DAYS, OUTF = sys.argv[1:6]; DAYS = DAYS.split(","); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = {d: dict(zip(g.id, g.daily_rank.astype(float))) for d, g in L.groupby("day")}
PR = pd.concat([pd.read_parquet(f) for f in glob.glob(PG) if os.path.getsize(f) > 0]); PR["id"] = PR.id.astype(str); PR = PR.drop_duplicates("id", keep="last").set_index("id")[PC]
V = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in glob.glob(f"{SP}/grow/vs/*.jsonl")]); V["id"] = V.launch_id.astype(str); V["pt"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT)
def hidden(d, h):
    t0 = pd.Timestamp(d, tz=PT); s = V[(V.day == d) & (V.pt <= t0 + pd.Timedelta(hours=h)) & (V.pt > t0 - pd.Timedelta(minutes=5))]
    return s.sort_values("pt").groupby("id").rank_now.last().dropna() if len(s) else None
def hits(score, d):
    t = RK[d]; o = score.sort_values().index.tolist(); tr = sorted(score.index, key=lambda i: t[i]); return np.array([len(set(o[:k]) & set(tr[:k])) / k * 100 for k in (3, 5, 10)])
def ci(A):
    A = np.asarray(A, float); bs = np.array([A[rng.integers(0, len(A), len(A))].mean(0) for _ in range(4000)])
    return [[round(float(A[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
WS = np.round(np.arange(0, 1.01, .1), 1); res = {"design": __doc__.split("\n    python")[0], "prior": [PG, PC], "days requested": DAYS}
for h in (1, 2, 3):
    F = {}
    for d in DAYS:
        hr = hidden(d, h)
        if hr is None or d not in RK: continue
        ids = [i for i in hr.index if i in RK[d] and i in PR.index]
        if len(ids) < 10: continue
        F[d] = (hr.loc[ids].rank(), (-PR.loc[ids]).rank())
    dd = sorted(F); sc = lambda w, d: hits(w * F[d][1] + (1 - w) * F[d][0] + rng.random(len(F[d][0])) * 1e-6, d)
    H0 = np.array([sc(0.0, d) for d in dd]); PO = np.array([sc(1.0, d) for d in dd])
    wb = max(WS, key=lambda w: np.mean([sc(w, d).mean() for d in dd])); IN = np.array([sc(wb, d) for d in dd])
    LO, wl = [], []
    for d in dd:
        tr = [x for x in dd if x != d]; w = max(WS, key=lambda w: np.mean([sc(w, x).mean() for x in tr])); wl.append(float(w)); LO.append(sc(w, d))
    LO = np.array(LO)
    res[f"{h:02d}:00" + (" (also 03:45)" if h == 3 else "")] = {"days": dd, "hidden rank top3/5/10": H0.mean(0).round(1).tolist(), "prior alone": PO.mean(0).round(1).tolist(),
        f"in-fit blend (w={wb})": IN.mean(0).round(1).tolist(), "in-fit blend - hidden [CI]": ci(IN - H0),
        "LODO blend top3/5/10": LO.mean(0).round(1).tolist(), "LODO blend - hidden [CI]": ci(LO - H0), "LODO weights": wl}
json.dump(res, open(OUTF, "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
