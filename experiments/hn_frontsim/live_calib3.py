"""Nov 2-4 live calibration of three simulator arms (orchestrator, Nov 6), on live_posts_<tag>.parquet from live_frontsim.py.
Per day and pooled:
- simulated vs real top-30 reach by 15-min score
- 24 h points
- sum of P(daily top 30) vs winners
- Brier and log-loss of P against (a) 24 h top-30 reach and (b) the daily top-30 label
Labels:
  (b-settled)  on a settled daily list (read 48 h after the list day ends): list days d..d+3 that have settled.
  (b-latest)   on the latest read of daily lists d..d+3 (provisional where a list day has not settled).
Pre-registered rescale: if pooled sum P / winners (b-latest) is outside [0.8, 1.25], one logit shift a for the main arm,
fitted on Nov 2-4 so that sum sigmoid(logit P + a) = winners.

    HNMIN=... python live_calib3.py
"""
import glob, json, os
import numpy as np, pandas as pd
from scipy.optimize import brentq

HERE = os.path.dirname(os.path.abspath(__file__))
HNMIN = os.environ["HNMIN"]
ARMS = ["main_l025", "l05", "nofix"]
rng = np.random.default_rng(0)

L = pd.concat([pd.read_json(f, lines=True, dtype={"day": str}, convert_dates=False) for f in glob.glob(os.path.join(HNMIN, "listwatch", "*.jsonl"))])
latest, settled = {}, {}
for d, g in L.groupby("day"):
    s = g[g.read_at == g.read_at.max()]; latest[d] = set(s[s["rank"] <= 30].post_id)
    t_settle = pd.Timestamp(d, tz="UTC").timestamp() + 86400 + 48 * 3600
    if g.read_at.max() >= t_settle:
        settled[d] = latest[d]
lists_read = {d: str(pd.Timestamp(g.read_at.max(), unit="s")) for d, g in L.groupby("day")}

def nxt(d, k):
    return (pd.Timestamp(d) + pd.Timedelta(days=k)).strftime("%Y-%m-%d")

def brier(p, y):
    return float(np.mean((p - y) ** 2))

def logloss(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

def boot(fn, p, y, B=2000):
    n = len(y); v = [fn(p[i], y[i]) for i in (rng.integers(0, n, n) for _ in range(B))]
    return [round(fn(p, y), 4), round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]

def boot_diff(fn, p1, p2, y, B=2000):
    n = len(y); v = []
    for _ in range(B):
        i = rng.integers(0, n, n); v.append(fn(p1[i], y[i]) - fn(p2[i], y[i]))
    return [round(fn(p1, y) - fn(p2, y), 4), round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]

P = {a: pd.read_parquet(os.path.join(HERE, "out", f"live_posts_{a}.parquet")) for a in ARMS}
base = P[ARMS[0]][["id", "day", "score", "done24", "real_top30", "real_p24"]].copy()
for a in ARMS:
    assert (P[a].id.to_numpy() == base.id.to_numpy()).all()
base["y_latest"] = [int(any(i in latest.get(nxt(d, k), ()) for k in range(4))) for i, d in zip(base.id, base.day)]
base["settled_days"] = [",".join(nxt(d, k) for k in range(4) if nxt(d, k) in settled) for d in base.day]
base["y_settled"] = [int(any(i in settled.get(nxt(d, k), ()) for k in range(4))) for i, d in zip(base.id, base.day)]
# share of b-latest winners found only on a later day's list (how much the unsettled later lists matter)
later_only = int(sum(1 for i, d, y in zip(base.id, base.day, base.y_latest) if y and i not in latest.get(d, ())))

res = {"lists_last_read": lists_read, "lists_settled": sorted(settled),
       "label_b_settled": "on a settled daily list among d..d+3; only list days in lists_settled count (Nov 2 posts: Nov 2 list only)",
       "label_b_latest": "on the latest read of daily lists d..d+3 (provisional: those lists are not settled)",
       "winners_found_only_on_a_later_days_list": later_only, "by_day": {}, "pooled": {}}
bins = pd.cut(base.score, [0, 1, 2, 3, 1e9], labels=["1", "2", "3", "4+"])
for scope, m in [(d, (base.day == d).to_numpy()) for d in sorted(base.day.unique())] + [("pooled", np.ones(len(base), bool))]:
    out = {}
    g = base[m]; d24 = g.done24.to_numpy()
    out["posts"] = int(m.sum()); out["posts_with_24h"] = int(d24.sum())
    out["winners_b_latest"] = int(g.y_latest.sum()); out["winners_b_settled"] = int(g.y_settled.sum())
    out["settled_list_days_used"] = sorted({x for s in g.settled_days for x in s.split(",") if x})
    out["reach_top30_real_24h"] = [int(g.real_top30[d24].sum()), round(float(g.real_top30[d24].mean()), 4)]
    out["mean_log1p_p24_real"] = round(float(np.log1p(g.real_p24[d24]).mean()), 3)
    out["median_p24_real"] = float(g.real_p24[d24].median())
    for a in ARMS:
        q = P[a][m]; A = {}
        A["reach_top30_sim_24h"] = [round(float(q.sim_top30[d24].sum()), 1), round(float(q.sim_top30[d24].mean()), 4)]
        A["reach_by_15min_score [real, sim, n]"] = {str(k): [round(float(g.real_top30[d24 & (bins[m] == k).to_numpy()].mean()), 3),
                                                            round(float(q.sim_top30[d24 & (bins[m] == k).to_numpy()].mean()), 3),
                                                            int((d24 & (bins[m] == k).to_numpy()).sum())] for k in ["1", "2", "3", "4+"]}
        A["mean_log1p_p24_sim"] = round(float(q.sim_log1p[d24].mean()), 3); A["median_p24_sim"] = float(q.sim_p24[d24].median())
        p = q.p_iso.to_numpy()
        A["sum_P"] = round(float(p.sum()), 1)
        A["sum_P / winners_b_latest"] = round(float(p.sum() / max(g.y_latest.sum(), 1)), 3)
        yr = g.real_top30.to_numpy(float)[d24]
        A["(a) P vs 24h reach: brier [est, lo, hi]"] = boot(brier, p[d24], yr)
        A["(a) P vs 24h reach: logloss"] = boot(logloss, p[d24], yr)
        A["(a) sim_top30 vs 24h reach: brier"] = boot(brier, q.sim_top30.to_numpy()[d24], yr)
        A["(a) sim_top30 vs 24h reach: logloss"] = boot(logloss, q.sim_top30.to_numpy()[d24], yr)
        yb = g.y_latest.to_numpy(float)
        A["(b-latest) P vs daily label: brier"] = boot(brier, p, yb)
        A["(b-latest) P vs daily label: logloss"] = boot(logloss, p, yb)
        sm = (g.settled_days != "").to_numpy()
        if sm.any():
            ys = g.y_settled.to_numpy(float)[sm]
            A["(b-settled) P vs daily label: brier"] = boot(brier, p[sm], ys)
            A["(b-settled) P vs daily label: logloss"] = boot(logloss, p[sm], ys)
            A["(b-settled) n"] = int(sm.sum())
        out[a] = A
    for a in ARMS[1:]:
        p0, p1 = P[ARMS[0]][m].p_iso.to_numpy(), P[a][m].p_iso.to_numpy()
        out[f"diff {ARMS[0]} - {a} (negative = main better)"] = {
            "(a) brier": boot_diff(brier, p0[d24], p1[d24], g.real_top30.to_numpy(float)[d24]),
            "(a) logloss": boot_diff(logloss, p0[d24], p1[d24], g.real_top30.to_numpy(float)[d24]),
            "(b-latest) brier": boot_diff(brier, p0, p1, g.y_latest.to_numpy(float)),
            "(b-latest) logloss": boot_diff(logloss, p0, p1, g.y_latest.to_numpy(float))}
    res["by_day" if scope != "pooled" else "pooled"][scope] = out
res["pooled"] = res["pooled"]["pooled"]

# pre-registered rescale on the main arm
p = np.clip(P[ARMS[0]].p_iso.to_numpy(), 1e-6, 1 - 1e-6); W = int(base.y_latest.sum()); ratio = p.sum() / W
lg = np.log(p / (1 - p)); sig = lambda x: 1 / (1 + np.exp(-x))
rs = {"pooled_sum_P": round(float(p.sum()), 2), "winners_b_latest": W, "ratio": round(float(ratio), 3), "band": [0.8, 1.25],
      "triggered": bool(ratio < 0.8 or ratio > 1.25)}
if rs["triggered"]:
    a = brentq(lambda a: sig(lg + a).sum() - W, -10, 10); rs["a"] = round(float(a), 4)
    pr = sig(lg + a); y = base.y_latest.to_numpy(float); d24 = base.done24.to_numpy()
    rs["in_sample (b-latest) brier / logloss: before"] = [round(brier(p, y), 4), round(logloss(p, y), 4)]
    rs["in_sample (b-latest) brier / logloss: after"] = [round(brier(pr, y), 4), round(logloss(pr, y), 4)]
res["rescale_preregistered"] = rs
json.dump(res, open(os.path.join(HERE, "live_calib_nov02_04.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
