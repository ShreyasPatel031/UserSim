"""Independent replication of the intraday leads (orchestrator 23:50Z Nov 13). Raw files only; PH ops' scoring code not used (only the
velocity rule's definition, from the frozen file + velocity_shadow docstring). Counts only.
Sources: raw/vote_snapshots/<day>.jsonl (hourly, votes + rank_now), raw/ph_at_launch/<day>/live/posts_ts.jsonl (15-min, votes_at_fetch,
daily_rank_at_fetch, hide flag). Truth: official daily_rank from the warehouse launches table (synced now).
(1) plain vote order at h in {04,05,06,08,10,12} PT: last read stamped <= h per launch (vote_snapshots; read must be within 65 min of h);
    field = launches in that day's snapshots joined to the warehouse; top 3/5/10 overlap; day bootstrap. Repeated with posts_ts.
(2) velocity (frozen velocity_20261113.json): score = votes_h x (1 + b x (relv - 1)), relv = (votes_h - votes_{h-1h}) / day mean of that
    gain (M is a constant per hour and cannot change the order); paired gain over plain votes; leave-one-day-out with b refit from
    {0, .05, .1, .2, .3, .5} on the other days (mean top 3/5/10).
(3) hidden rank: while votes are hidden, order by rank_now (vote_snapshots) / daily_rank_at_fetch (posts_ts) at 01:00, 02:00, 03:00, 03:45.
    python intraday_replicate.py <scratchpad> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
L = W.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = {d: dict(zip(g.id, g.daily_rank.astype(float))) for d, g in L.groupby("day")}
V = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in glob.glob(f"{SP}/grow/vs/*.jsonl")]); V["id"] = V.launch_id.astype(str); V["pt"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT)
P = pd.concat([pd.read_json(f, lines=True, dtype={"launch_id": str}) for f in glob.glob(f"{SP}/pts/*.jsonl")]); P["id"] = P.launch_id.astype(str); P["pt"] = pd.to_datetime(P.fetched_at, utc=True, format="mixed").dt.tz_convert(PT)
P = P.rename(columns={"votes_at_fetch": "votes", "daily_rank_at_fetch": "rank_now"})
def at(S, d, h, col):
    t0 = pd.Timestamp(d, tz=PT); th = t0 + pd.Timedelta(hours=h); s = S[(S.day == d) & (S.pt <= th) & (S.pt > t0 - pd.Timedelta(minutes=5))]
    if s.empty or th - s.pt.max() > pd.Timedelta(minutes=65): return None
    return s.sort_values("pt").groupby("id")[col].last()
def hits(score, d, asc=False):
    t = RK.get(d, {}); ids = [i for i in score.index if i in t]
    if len(ids) < 10: return None
    o = score.loc[ids].sort_values(ascending=asc).index.tolist(); tr = sorted(ids, key=lambda i: t[i]); return [len(set(o[:k]) & set(tr[:k])) / k * 100 for k in (3, 5, 10)]
def ci(A):
    A = np.array(A, float); bs = np.array([A[rng.integers(0, len(A), len(A))].mean(0) for _ in range(4000)])
    return [[round(float(A[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(A.shape[1])] + [len(A)]
FZ = {5: 0.1, 8: 0.1, 10: 0.1, 12: 0.05}; res = {"design": __doc__.split("\n    python")[0]}
days = sorted(set(V.day) | set(P.day))
for src, S in (("vote_snapshots", V), ("posts_ts", P)):
    o = {}
    for h in (4, 5, 6, 8, 10, 12):
        rows, used = [], []
        for d in days:
            v = at(S, d, h, "votes")
            if v is None or v.max() <= 0: continue
            x = hits(v.astype(float) + rng.random(len(v)) * 1e-6, d)
            if x: rows.append(x); used.append(d)
        o[f"{h:02d}:00 plain votes"] = {"top3/5/10 [CI], n days": ci(rows) if rows else None, "days": used}
        if h in FZ:
            R = {}
            for d in used:
                v = at(S, d, h, "votes").astype(float); v1 = at(S, d, h - 1, "votes")
                g1 = (v - (v1.reindex(v.index).fillna(0) if v1 is not None else 0)).clip(lower=0); relv = (g1 / (g1.mean() or np.nan)).fillna(1.0)
                R[d] = (v, relv)
            sc = lambda b, d: hits(R[d][0] * (1 + b * (R[d][1] - 1)) + rng.random(len(R[d][0])) * 1e-6, d)
            A = np.array([sc(FZ[h], d) for d in used]); B0 = np.array([sc(0.0, d) for d in used]); df = A - B0
            bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
            lo = []
            for d in used:
                tr = [x for x in used if x != d]; bb = max((0, .05, .1, .2, .3, .5), key=lambda b: np.mean([np.mean(sc(b, x)) for x in tr])); lo.append(np.array(sc(bb, d)) - np.array(sc(0.0, d)))
            lo = np.array(lo); bl = np.array([lo[rng.integers(0, len(lo), len(lo))].mean(0) for _ in range(4000)])
            o[f"{h:02d}:00 velocity (frozen b={FZ[h]})"] = {"top3/5/10": A.mean(0).round(1).tolist(), "paired vs plain [CI]": [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)],
                "leave-one-day-out b refit: paired vs plain [CI]": [[round(float(lo[:, j].mean()), 1), round(float(np.percentile(bl[:, j], 2.5)), 1), round(float(np.percentile(bl[:, j], 97.5)), 1)] for j in range(3)], "n days": len(used)}
    for h in (1, 2, 3, 3.75):
        rows, used = [], []
        for d in days:
            r = at(S, d, h, "rank_now")
            if r is None or r.isna().all(): continue
            x = hits(r.astype(float), d, asc=True)
            if x: rows.append(x); used.append(d)
        o[f"{int(h):02d}:{int(round((h % 1) * 60)):02d} hidden rank order"] = {"top3/5/10 [CI], n days": ci(rows) if rows else None, "days": used}
    res[src] = o
json.dump(res, open(os.path.join(OUT, "intraday_replicate.json"), "w"), indent=1, default=str)
for s in ("vote_snapshots", "posts_ts"):
    for k, v in res[s].items(): print(s, k, json.dumps({kk: vv for kk, vv in v.items() if kk != "days"}), len(v.get("days", [])) if "days" in v else "")
