"""Value of the extra 03:30 / 03:45 recorder read (orchestrator 01:36Z Nov 14). Counts only. Direction only at this n.
(a) posts_ts (15-min, daily_rank_at_fetch, fetched_at) on days with pre-reveal ranks: hidden order at 03:00 vs 03:30 vs 03:45 PT (latest
    read <= T within 20 min); top-10 position changes; top 3/5/10 vs official daily_rank, paired; comment counts 03:00 -> 03:45.
(b) vote_snapshots (hourly rank_now) on the 11 recorder days: 01:00 vs 02:00 vs 03:00, same metrics (does the order converge?).
    python read_345.py <scratchpad> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); PT = "America/Los_Angeles"; rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); RK = dict(zip(L.id, L.daily_rank))
def at(S, d, h, col, win):
    t0 = pd.Timestamp(d, tz=PT); th = t0 + pd.Timedelta(hours=h); s = S[(S.day == d) & (S.pt <= th) & (S.pt > th - pd.Timedelta(minutes=win))]
    return s.sort_values("pt").groupby("id")[col].last().dropna() if len(s) else None
def hits(r):
    ids = [i for i in r.index if pd.notna(RK.get(i))]; o = r.loc[ids].sort_values().index.tolist(); t = sorted(ids, key=lambda i: RK[i])
    return np.array([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
def moves(a, b):
    ta, tb = a.sort_values().index[:10].tolist(), b.sort_values().index[:10].tolist(); return sum(1 for i, x in enumerate(ta) if i >= len(tb) or tb[i] != x)
def ci(A):
    A = np.asarray(A, float); bs = np.array([A[rng.integers(0, len(A), len(A))].mean(0) for _ in range(4000)])
    return [[round(float(A[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(A.shape[1])]
P = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in glob.glob(f"{SP}/pts/*.jsonl")]); P["id"] = P.launch_id.astype(str)
P["pt"] = pd.to_datetime(P.fetched_at, utc=True, format="mixed").dt.tz_convert(PT)
res = {"design": __doc__.split("\n    python")[0]}; A, Bm, C = {}, [], []
for d in sorted(P.day.unique()):
    r = {h: at(P, d, h, "daily_rank_at_fetch", 20) for h in (3.0, 3.5, 3.75)}
    if any(v is None or len(v) < 10 for v in r.values()): continue
    if r[3.75].index.isin([i for i in RK if pd.notna(RK[i])]).sum() < 10: continue
    for h, v in r.items(): A.setdefault(h, []).append(hits(v))
    Bm.append([moves(r[3.0], r[3.5]), moves(r[3.0], r[3.75])])
    c3, c4 = at(P, d, 3.0, "comments_count_at_fetch", 20), at(P, d, 3.75, "comments_count_at_fetch", 20)
    j = c3.index.intersection(c4.index); C.append([int((c4[j] - c3[j]).sum()), float(((c4[j] - c3[j]) > 0).mean())])
    res.setdefault("(a) days", []).append(d)
if A:
    a0, a1, a2 = (np.array(A[h]) for h in (3.0, 3.5, 3.75))
    res["(a) posts_ts 15-min"] = {"days": len(a0), "03:00 top3/5/10": a0.mean(0).round(1).tolist(), "03:30": a1.mean(0).round(1).tolist(), "03:45": a2.mean(0).round(1).tolist(),
        "03:45 - 03:00 [CI]": ci(a2 - a0), "top-10 positions changed 03:00->03:30 / ->03:45 (mean per day)": np.array(Bm).mean(0).round(2).tolist(),
        "comments 03:00->03:45: new comments per day, share of launches gaining": np.array(C).mean(0).round(2).tolist()}
V = pd.concat([pd.read_json(f"{SP}/grow/vs/{d}.jsonl", lines=True, dtype={"launch_id": str}) for d in [f"2026-11-{x:02d}" for x in range(2, 13)]]); V["id"] = V.launch_id.astype(str)
V["pt"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT); V = V.drop_duplicates(["id", "at"])
H, M = {}, []
for d in sorted(V.day.unique()):
    r = {h: at(V, d, h, "rank_now", 65) for h in (1, 2, 3)}
    if any(v is None or len(v) < 10 for v in r.values()): continue
    for h, v in r.items(): H.setdefault(h, []).append(hits(v))
    M.append([moves(r[1], r[2]), moves(r[2], r[3])])
h1, h2, h3 = (np.array(H[h]) for h in (1, 2, 3))
res["(b) vote_snapshots hourly"] = {"days": len(h1), "01:00": h1.mean(0).round(1).tolist(), "02:00": h2.mean(0).round(1).tolist(), "03:00": h3.mean(0).round(1).tolist(),
    "02:00 - 01:00 [CI]": ci(h2 - h1), "03:00 - 02:00 [CI]": ci(h3 - h2), "top-10 positions changed 01->02 / 02->03 (mean per day)": np.array(M).mean(0).round(2).tolist()}
json.dump(res, open(os.path.join(OUT, "read_345.json"), "w"), indent=1, default=float)
for k, v in res.items():
    if k != "design": print(k, json.dumps(v, default=float))
