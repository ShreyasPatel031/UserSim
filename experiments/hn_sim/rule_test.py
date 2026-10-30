"""Which summary of a story's day on the live front page reproduces HN's daily list (front?day=D)?

Data: Quality News hourly snapshots per story (qn.py: qn_hour0, qn_rank_by_hour = rank on HN's front page at the end of
each UTC hour, 91 = not on it; qn_up_by_hour = upvotes). For list day D, the candidates are every story with a rank
<= 30 in some hour inside D (00:00-24:00 UTC). Candidate rules, each computed only from the hours inside D:
  best_rank, hours_top30, hours_top10, exposure (sum of 1/rank), peak_points, points_end_of_day,
  snapshot_HH (the live page at the end of hour HH)
Scores per rule: membership (share of the real list's top 30 / all entries that are candidates, and vice versa),
overlap of top 30 / top 10, and Spearman correlation between the rule's order and the real order.

    python rule_test.py
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import store as S

C = S.LOCAL
q = pd.read_json(os.path.join(C, "qn_long3.jsonl"), lines=True)
q = q[q.status == 200].drop_duplicates("post_id")
L = pd.read_json(os.path.join(C, "frontday.jsonl"), lines=True, dtype={"day": str})

rows = []   # (post_id, unix hour end, rank, points)
for r in q.itertuples():
    if not isinstance(r.qn_rank_by_hour, list):
        continue
    for h, (rk, up) in enumerate(zip(r.qn_rank_by_hour, r.qn_up_by_hour)):
        if rk is not None:
            rows.append((r.post_id, r.qn_hour0 + (h + 1) * 3600, rk, up))
Hr = pd.DataFrame(rows, columns=["post_id", "t", "rank", "points"])
Hr["day"] = pd.to_datetime(Hr.t - 1, unit="s", utc=True).dt.strftime("%Y-%m-%d")
Hr["hour"] = pd.to_datetime(Hr.t - 1, unit="s", utc=True).dt.hour
covered_from = pd.to_datetime(q.qn_hour0.min(), unit="s", utc=True)
print("stories with hourly ranks:", q.post_id.nunique(), " hours from", covered_from, flush=True)

res = []
for d, real in L.groupby("day"):
    hd = Hr[Hr.day == d]
    if hd.hour.nunique() < 24 or pd.Timestamp(d, tz="UTC") < covered_from + pd.Timedelta(days=2):
        continue                                  # need full coverage of the day and of stories posted 2 days before
    real = real.sort_values("rank")
    on = hd[hd["rank"] <= 30]
    g = on.groupby("post_id")
    allh = hd.groupby("post_id")
    feats = pd.DataFrame({
        "best_rank": -g["rank"].min(),
        "hours_top30": g.size(),
        "hours_top10": hd[hd["rank"] <= 10].groupby("post_id").size(),
        "exposure": g["rank"].apply(lambda x: (1 / x).sum()),
        "peak_points": allh.points.max(),
        "points_end_of_day": allh.apply(lambda x: x.sort_values("t").points.iloc[-1]),
    }).loc[lambda x: x.index.isin(on.post_id)].fillna(0)
    for hh in range(24):
        snap = hd[(hd.hour == hh) & (hd["rank"] <= 30)].set_index("post_id")["rank"]
        feats[f"snapshot_{hh:02d}"] = -snap.reindex(feats.index).fillna(99)
    cand = set(feats.index)
    rl = real.post_id.tolist()
    r30, r10 = rl[:30], rl[:10]
    row = {"day": d, "real_n": len(rl), "candidates": len(cand),
           "real_in_candidates": np.mean([x in cand for x in rl]),
           "real30_in_candidates": np.mean([x in cand for x in r30]),
           "candidates_in_real": np.mean([x in set(rl) for x in cand])}
    for col in feats.columns:
        order = feats[col].sort_values(ascending=False, kind="mergesort").index.tolist()
        row[f"{col}|top30"] = len(set(order[:30]) & set(r30)) / 30
        row[f"{col}|top10"] = len(set(order[:10]) & set(r10)) / 10
        common = [x for x in rl if x in cand]
        if len(common) > 5:
            row[f"{col}|spearman"] = spearmanr(range(len(common)), [-feats[col][x] for x in common]).statistic
    res.append(row)
D = pd.DataFrame(res)
print("days tested:", len(D), D.day.min() if len(D) else "", D.day.max() if len(D) else "")
print("membership: real list entries that were on the live top 30 that day:", round(D.real_in_candidates.mean(), 3),
      "| real top 30:", round(D.real30_in_candidates.mean(), 3),
      "| live-top-30 stories that are on the real list:", round(D.candidates_in_real.mean(), 3),
      "| real list length", round(D.real_n.mean(), 1), "candidates", round(D.candidates.mean(), 1))
summ = []
for col in [c.split("|")[0] for c in D.columns if c.endswith("|top30")]:
    summ.append({"rule": col, "top30": D[f"{col}|top30"].mean(), "top10": D[f"{col}|top10"].mean(),
                 "spearman": D.get(f"{col}|spearman", pd.Series(dtype=float)).mean()})
Sm = pd.DataFrame(summ).sort_values("top30", ascending=False).round(3)
print(Sm.to_string(index=False))
S.write("hn_scores", Sm.assign(kind="list_rule", days=len(D), made_on=S.now()))


# ---- learned rule: a ranker trained on some days to reproduce HN's list order on held-out days ----
import lightgbm as lgb
from scipy.optimize import minimize

mrows, fcols = [], None
for d, real in L.groupby("day"):
    if d not in set(D.day):
        continue
    hd = Hr[Hr.day == d]
    on_ids = set(hd[hd["rank"] <= 30].post_id)
    pos = dict(zip(real.post_id, real["rank"]))
    for pid, g in hd[hd.post_id.isin(on_ids)].groupby("post_id"):
        g = g.sort_values("hour")
        rk = np.full(24, 91.0)
        pt = np.full(24, np.nan)
        rk[g.hour.to_numpy()] = g["rank"].to_numpy()
        pt[g.hour.to_numpy()] = g.points.to_numpy()
        pt = pd.Series(pt).ffill().bfill().fillna(0).to_numpy()
        f = {"day": d, "post_id": pid, "real_pos": pos.get(pid, 999)}
        f.update({f"rank_h{h:02d}": rk[h] for h in range(24)})
        f.update({f"pts_h{h:02d}": pt[h] for h in range(24)})
        f.update(best_rank=rk.min(), hours_top30=(rk <= 30).sum(), hours_top10=(rk <= 10).sum(),
                 exposure=(1 / rk[rk <= 30]).sum(), first_hour=int(np.argmax(rk <= 30)),
                 last_hour=int(23 - np.argmax(rk[::-1] <= 30)), pts_end=pt[-1], pts_start=pt[0])
        mrows.append(f)
M = pd.DataFrame(mrows)
fcols = [c for c in M.columns if c not in ("day", "post_id", "real_pos")]
days = sorted(M.day.unique())
print(f"\nlearned rule: {len(days)} days, {len(M)} (day, story) rows", flush=True)


def eval_order(P, col):
    t30, t10 = [], []
    for _, g in P.groupby("day"):
        o = g.sort_values(col, ascending=False).post_id.tolist()
        r30 = set(g[g.real_pos <= 30].post_id)
        r10 = set(g[g.real_pos <= 10].post_id)
        t30.append(len(set(o[:30]) & r30) / max(len(r30), 1))
        t10.append(len(set(o[:10]) & r10) / max(len(r10), 1))
    return round(float(np.mean(t30)), 3), round(float(np.mean(t10)), 3)


folds = np.array_split(np.array(days), min(5, len(days)))
preds = []
for k, test_days in enumerate(folds):          # leave-days-out cross-validation
    tr, te = M[~M.day.isin(test_days)].sort_values("day"), M[M.day.isin(test_days)]
    grp = tr.groupby("day", sort=False).size().to_numpy()
    lab = np.clip(31 - tr.real_pos, 0, 30).astype(int)
    rk_model = lgb.LGBMRanker(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=10, verbose=-1,
                              label_gain=list(range(31)))
    rk_model.fit(tr[fcols], lab, group=grp)
    preds.append(te.assign(learned=rk_model.predict(te[fcols])))
P = pd.concat(preds)
print("learned ranker (held-out days): real top30 / top10 found:", eval_order(P, "learned"), flush=True)
imp = pd.Series(rk_model.booster_.feature_importance("gain"), index=fcols).sort_values(ascending=False)
print("what it relies on (gain share):", (imp / imp.sum()).round(3).head(12).to_dict(), flush=True)

# compact formula: score = sum_h w_h * (31 - rank_h)^a for rank_h <= 30, w_h = exp(b * h / 24); fit a, b on train folds
R = M[[f"rank_h{h:02d}" for h in range(24)]].to_numpy()


def formula(params, Rm):
    a, b = params
    v = np.where(Rm <= 30, (31 - np.minimum(Rm, 30)) ** a, 0.0)
    return (v * np.exp(b * np.arange(24) / 24)).sum(1)


def loss(params, idx):
    S_ = pd.Series(formula(params, R[idx]), index=M.index[idx])
    sub = M.loc[S_.index].assign(s=S_)
    return -eval_order(sub, "s")[0]


fp = []
for test_days in folds:
    tr_idx = np.flatnonzero(~M.day.isin(test_days).to_numpy())
    best = min(((a, b) for a in (0.5, 1, 1.5, 2, 3) for b in (-2, -1, 0, 1, 2)), key=lambda x: loss(x, tr_idx))
    te_idx = np.flatnonzero(M.day.isin(test_days).to_numpy())
    fp.append(M.iloc[te_idx].assign(formula=formula(best, R[te_idx])))
    print("  fold best (rank exponent a, later-hours weight b):", best, flush=True)
print("compact formula (held-out days): real top30 / top10 found:", eval_order(pd.concat(fp), "formula"), flush=True)
