"""The 03:45 PT before-reveal call (orchestrator 00:58Z Nov 14). Raw recorder files, agreed read rule: hidden rank at T = latest
raw/vote_snapshots rank_now with at <= T (dedup launch, at); 03:45 = the 03:00 read. Days Nov 2-12 (11). Label: warehouse daily_rank, all
featured launches. Every parameter chosen leave-one-day-out (best mean top 3/5/10 on the other 10 days). Counts only.
Features at 03:00: r3 (hidden rank), r0/r1/r2 (00:06/01:00/02:00), comments (total comment count on the same read; distinct non-team
commenters are not recorded on Nov 5 and 9, so the total is used everywhere), growth since 01:00, prior = arm 2 (PH ops nov_arm2 'both',
month-fold, final-read inputs).
Lines: PLAIN = r3. HYBRID (re-implemented from its definition: hidden top 5 + hr_clean order for slots 6+; hr_clean = LODO ridge alpha 3 on
within-day z of log r3, r1 - r3, log1p comments, log1p growth, prior; target z(-ln rank)).
(a) MOMENTUM: r3 - k (r3 - r_e), e in {00:06, 01:00, 02:00}, k in {-1, -.5, .25, .5, 1}; persistence first: within-day Spearman of
    (r1 - r3) with (r3 - final rank).
(b) COMMENT tie-break (adjacent only): r3 - d x clip(z, -1, 1) with d in {.25, .5, .75, .99} (each shift < 1, so only neighbours can swap); z = within-day
    z of log1p comments or of log1p growth. (c) ARM-2 tie-break, same form with z(prior). (d) slots 6-10 with the hidden top 5 kept:
    by r3 (= plain), hr_clean (= hybrid), prior only, comments only, momentum (LODO).
Ceiling: share of final top 3 already in the hidden top 3 at 03:00; where the misses sit at 03:00 (4-5, 6-10, 11+).
    python prereveal_345.py <scratchpad> <nov_arm2 parquet> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
SP, A2P, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse as W
DAYS = [f"2026-11-{d:02d}" for d in range(2, 13)]
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = dict(zip(L.id, L.daily_rank.astype(float)))
V = pd.concat([pd.read_json(f"{SP}/grow/vs/{d}.jsonl", lines=True, dtype={"launch_id": str}) for d in DAYS]); V["id"] = V.launch_id.astype(str)
V["pt"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT); V = V.drop_duplicates(["id", "at"])
A2 = pd.read_parquet(A2P); A2["id"] = A2.id.astype(str); PRI = dict(zip(A2.id, A2.both))
def read(d, h):
    t0 = pd.Timestamp(d, tz=PT); s = V[(V.day == d) & (V.pt <= t0 + pd.Timedelta(hours=h)) & (V.pt > t0 - pd.Timedelta(minutes=5))]
    return s.sort_values("pt").groupby("id")[["rank_now", "comments"]].last()
z = lambda s: (s - s.mean()) / (s.std() or 1)
D = {}
for d in DAYS:
    r3, r1, r2, r0 = read(d, 3), read(d, 1), read(d, 2), read(d, 0.15)
    X = pd.DataFrame({"r3": r3.rank_now, "c3": r3.comments}).dropna(subset=["r3"])
    X["r0"], X["r1"], X["r2"] = r0.rank_now.reindex(X.index), r1.rank_now.reindex(X.index), r2.rank_now.reindex(X.index)
    for c in ("r0", "r1", "r2"): X[c] = X[c].fillna(X.r3)
    X["g"] = (X.c3 - r1.comments.reindex(X.index).fillna(0)).clip(lower=0); X["prior"] = X.index.map(PRI); X["prior"] = X.prior.fillna(X.prior.median())
    X["rank"] = X.index.map(RK); X = X[X["rank"].notna()]
    X["zc"] = z(np.log1p(X.c3)); X["zg"] = z(np.log1p(X.g)); X["zp"] = z(X.prior); X["y"] = z(-np.log(X["rank"]))
    X["f1"], X["f2"] = z(np.log(X.r3)), z(X.r1 - X.r3); D[d] = X
def hits(order, X):
    t = X.sort_values("rank").index.tolist(); return np.array([len(set(order[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
def by(score, X): return X.assign(s=score + rng.random(len(X)) * 1e-9).sort_values("s").index.tolist()   # ascending: lower = better
def ci(A):
    A = np.asarray(A, float); bs = np.array([A[rng.integers(0, len(A), len(A))].mean(0) for _ in range(4000)])
    return [[round(float(A[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
res = {"design": __doc__.split("\n    python")[0], "days": DAYS, "launches": int(sum(len(x) for x in D.values()))}
# ceiling
c3, miss = [], {"4-5": 0, "6-10": 0, "11+": 0}
for d, X in D.items():
    t3 = X.sort_values("rank").index[:3]; h3 = set(X.sort_values("r3").index[:3]); c3.append(len(set(t3) & h3) / 3 * 100)
    for i in t3:
        if i not in h3:
            r = X.r3[i]; miss["4-5" if r <= 5 else ("6-10" if r <= 10 else "11+")] += 1
res["ceiling: final top 3 already in hidden top 3 at 03:00 (mean %)"] = round(float(np.mean(c3)), 1); res["final top-3 misses by 03:00 hidden rank"] = miss
res["days where hidden top 3 == final top 3 (as sets)"] = int(sum(x == 100 for x in c3))
sp = [spearmanr(X.r1 - X.r3, X.r3 - X["rank"]).correlation for X in D.values() if (X.r1 - X.r3).nunique() > 1]
res["persistence: within-day Spearman of (01:00->03:00 climb) with (03:00 -> final climb)"] = [round(float(np.nanmean(sp)), 3), round(float(np.nanpercentile(sp, 10)), 3), round(float(np.nanpercentile(sp, 90)), 3), len(sp)]
# line families: f(params, X) -> order
def hrclean_w(train):
    T = pd.concat([D[d] for d in train]); return Ridge(alpha=3).fit(T[["f1", "f2", "zc", "zg", "zp"]], T.y)
def hybrid_order(X, m, slots_by=None):
    top5 = X.sort_values("r3").index[:5].tolist(); rest = X.drop(top5)
    if slots_by is None: s = -m.predict(rest[["f1", "f2", "zc", "zg", "zp"]])
    else: s = slots_by(rest)
    return top5 + by(s, rest)
FAM = {"(a) momentum": [(e, k) for e in ("r0", "r1", "r2") for k in (-1, -.5, .25, .5, 1)],
       "(b) comments tie-break (total)": [("zc", d_) for d_ in (.25, .5, .75, .99)], "(b) comments tie-break (growth since 01:00)": [("zg", d_) for d_ in (.25, .5, .75, .99)],
       "(c) arm-2 tie-break": [("zp", d_) for d_ in (.25, .5, .75, .99)]}
def order(fam, p, X):
    if fam == "(a) momentum": e, k = p; return by(X.r3 - k * (X.r3 - X[e]), X)
    c, d_ = p; return by(X.r3 - d_ * X[c].clip(-1, 1), X)   # shifts < 1 each: only neighbours can swap
PL = np.array([hits(by(X.r3, X), X) for X in D.values()])
HY = np.array([hits(hybrid_order(D[d], hrclean_w([x for x in DAYS if x != d])), D[d]) for d in DAYS])
res["PLAIN hidden rank top3/5/10"] = PL.mean(0).round(1).tolist(); res["HYBRID (LODO hr_clean slots 6+) top3/5/10"] = HY.mean(0).round(1).tolist(); res["HYBRID - PLAIN"] = ci(HY - PL)
for fam, grid in FAM.items():
    A, ch = [], []
    for d in DAYS:
        tr = [x for x in DAYS if x != d]; p = max(grid, key=lambda p: np.mean([hits(order(fam, p, D[x]), D[x]).mean() for x in tr])); ch.append(p); A.append(hits(order(fam, p, D[d]), D[d]))
    A = np.array(A); res[fam] = {"LODO top3/5/10": A.mean(0).round(1).tolist(), "vs PLAIN": ci(A - PL), "vs HYBRID": ci(A - HY), "chosen per held-out day": [list(map(str, c)) for c in ch]}
# (d) slots 6-10 alternatives with hidden top 5 kept
SL = {"prior only": lambda r: -r.zp.values, "comments only": lambda r: -r.zc.values, "hidden rank (= plain)": lambda r: r.r3.values}
for nm, f in SL.items():
    A = np.array([hits(hybrid_order(D[d], None, f), D[d]) for d in DAYS]); res[f"(d) slots 6+ by {nm}"] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs PLAIN": ci(A - PL), "vs HYBRID": ci(A - HY)}
res["per day (plain, hybrid) top3/5/10 hits %"] = {d: {"plain": PL[i].tolist(), "hybrid": HY[i].tolist(), "n launches": len(D[d])} for i, d in enumerate(DAYS)}
json.dump(res, open(os.path.join(OUT, "prereveal_345.json"), "w"), indent=1, default=str)
for k, v in res.items():
    if k not in ("design",): print(k, json.dumps(v, default=str)[:700])
