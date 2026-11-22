"""Score the Decisions API answers against the no-LLM baseline (metrics fixed in preregistration.json).

  python score.py <out dir> <results.json>

Reads persondays.jsonl, api_answers.jsonl, fit_rows.parquet from <out dir> (scratchpad); writes aggregates only.
"""
import json, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

OUT, RES = sys.argv[1:3]
rng = np.random.default_rng(0); B = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
FEATS = ["l7", "l30", "overlap", "lhn", "lhmed", "lline"]


def feats(df):
    return pd.DataFrame({"l7": np.log1p(df.n7), "l30": np.log1p(df.n30), "overlap": df.overlap, "lhn": np.log1p(df.h_n),
                         "lhmed": np.log1p(df.h_med.clip(lower=0)), "lline": np.log(df.lineup)})


R = [json.loads(l) for l in open(f"{OUT}/persondays.jsonl")]
A = {(a["day"], a["pid"]): a for a in map(json.loads, open(f"{OUT}/api_answers.jsonl"))}
rows = []
for r in R:
    a = A[(r["day"], r["pid"])]
    for k, lid in enumerate(r["launch_ids"]):
        rows.append({"day": r["day"], "pid": r["pid"], "group": r["group"], "lid": lid, "y": r["labels"][k], "api": a["p"].get(lid),
                     "n7": r["n7"], "n30": r["n30"], "overlap": r["overlap"][k], "h_n": r["h_n"][k], "h_med": r["h_med"][k],
                     "lineup": len(r["launch_ids"])})
T = pd.DataFrame(rows)
assert T.api.notna().all(), "missing API answers"
F = pd.read_parquet(f"{OUT}/fit_rows.parquet")
assert F.day.max() < T.day.min(), "baseline fitted on a test day"
lr = LogisticRegression(C=1.0, max_iter=2000).fit(feats(F), F.y)
T["base"] = lr.predict_proba(feats(T))[:, 1]
# secondary: API after leave-one-day-out Platt scaling (logit of API P, fitted on the other two test days)
T["lapi"] = np.log(T.api / (1 - T.api)); T["api_platt"] = np.nan
for d in T.day.unique():
    m = LogisticRegression(max_iter=1000).fit(T.loc[T.day != d, ["lapi"]], T.loc[T.day != d, "y"])
    T.loc[T.day == d, "api_platt"] = m.predict_proba(T.loc[T.day == d, ["lapi"]])[:, 1]

ARMS = ["api", "base", "api_platt"]


# Every metric takes a per-row weight (bootstrap count of the row's person), so the person bootstrap needs no re-grouping.
PD = T.groupby(["day", "pid"]).ngroup().to_numpy()          # person-day index per row
GL = T.groupby(["day", "lid"]).ngroup().to_numpy()          # launch index per row
Y = T.y.to_numpy()
ORD = {a: {g: idx[np.argsort(-T[a].to_numpy()[idx], kind="mergesort")] for g, idx in pd.Series(np.arange(len(T))).groupby(GL).groups.items()}
       for a in ARMS}
WPD = {}  # within-person AUC per backer person-day (fixed), averaged with weights
for a in ARMS:
    v = np.full(PD.max() + 1, np.nan)
    for k, g in T.assign(pd_=PD).groupby("pd_"):
        if g.group.iloc[0] == "backer" and 0 < g.y.sum() < len(g): v[k] = roc_auc_score(g.y, g[a])
    WPD[a] = v
PD_W_ROW = pd.Series(np.arange(len(T))).groupby(PD).first().to_numpy()   # one row per person-day, to read its weight


def auc(w, a): return roc_auc_score(Y, T[a].to_numpy(), sample_weight=w)
def brier(w, a): return float(np.sum(w * (T[a].to_numpy() - Y) ** 2) / np.sum(w))


def recall_at_n(w, a):
    hits = tot = 0.0
    for g, idx in ORD[a].items():
        ww = w[idx]; yy = Y[idx]; n = float(np.sum(ww * yy))
        if n <= 0: continue
        cw = np.cumsum(ww); take = np.clip(n - (cw - ww), 0, ww)   # weight taken from each row in rank order, up to N
        hits += float(np.sum(take * yy)); tot += n
    return hits / tot


def within_auc(w, a):
    v = WPD[a]; wp = w[PD_W_ROW]; m = ~np.isnan(v)
    return float(np.sum(v[m] * wp[m]) / np.sum(wp[m]))


METRICS = {"auc": auc, "brier": brier, "recall_at_N": recall_at_n, "within_person_auc_backers": within_auc}
ONE = np.ones(len(T))
point = {m: {a: f(ONE, a) for a in ARMS} for m, f in METRICS.items()}

# bootstrap over people (all of a person's person-days resampled together), as row weights
pids = T.pid.unique(); pidx = pd.Index(pids).get_indexer(T.pid)
draws = {m: {a: [] for a in ARMS + ["api-base"]} for m in METRICS}
for b in range(B):
    cnt = np.bincount(rng.integers(0, len(pids), len(pids)), minlength=len(pids)).astype(float)
    w = cnt[pidx]
    for m, f in METRICS.items():
        v = {a: f(w, a) for a in ARMS}
        for a in ARMS: draws[m][a].append(v[a])
        draws[m]["api-base"].append(v["api"] - v["base"])


def ci(x): return [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]


summary = {m: {**{a: {"value": round(point[m][a], 4), "ci95": ci(draws[m][a])} for a in ARMS},
               "api_minus_baseline": {"value": round(point[m]["api"] - point[m]["base"], 4), "ci95": ci(draws[m]["api-base"])}}
           for m in METRICS}
per_day = {d: {m: {a: round(f((T.day == d).to_numpy().astype(float), a), 4) for a in ARMS} for m, f in METRICS.items()} for d in sorted(T.day.unique())}


def calib(c):
    q = pd.qcut(T[c].rank(method="first"), 10, labels=False)
    g = T.groupby(q).agg(mean_p=(c, "mean"), observed=("y", "mean"), pairs=("y", "size"))
    return [{k: (round(float(v), 4) if k != "pairs" else int(v)) for k, v in r.items()} for r in g.to_dict("records")]


# where does the API's signal come from? AUC within activity tertiles, and AUC of a person-only score (n30)
T["act_tertile"] = pd.qcut(T.n30.rank(method="first"), 3, labels=["low", "mid", "high"])
by_act = {str(t): {a: round(roc_auc_score(g.y, g[a]), 4) for a in ["api", "base"]} | {"pairs": len(g), "positives": int(g.y.sum())}
          for t, g in T.groupby("act_tertile", observed=True)}
res = {
    "test": "Gemini Decisions API (gemini-decision-1) vs no-LLM baseline: which held people upvote which launches",
    "preregistration": "preregistration.json (committed before scoring)",
    "days": sorted(T.day.unique().tolist()), "person_days": len(R), "people": int(len(pids)),
    "person_launch_pairs": len(T), "positive_pairs": int(T.y.sum()), "base_rate": round(float(T.y.mean()), 4),
    "summary": summary, "per_day": per_day,
    "calibration_deciles": {a: calib(a) for a in ARMS},
    "auc_by_person_activity_tertile_30d": by_act,
    "exploratory_not_preregistered": {"auc_rank_average_api_and_baseline": round(roc_auc_score(T.y, T.api.rank() + T.base.rank()), 4),
                                      "auc_api_within_day": {d: round(roc_auc_score(g.y, g.api), 4) for d, g in T.groupby("day")}},
    "person_only_auc_log_upvotes_30d": round(roc_auc_score(T.y, T.n30), 4),
    "baseline_coefficients": dict(zip(FEATS, [round(float(x), 4) for x in lr.coef_[0]])),
    "baseline_fit": {"days": sorted(F.day.unique().tolist()), "pairs": len(F), "positives": int(F.y.sum())},
    "api_p_range": [round(float(T.api.min()), 4), round(float(T.api.max()), 4)],
    "bootstrap": f"{B} draws over people; person-days of a person resampled together; paired",
}
json.dump(res, open(RES, "w"), indent=1)
print(json.dumps({"summary": summary, "per_day": per_day, "by_act": by_act, "person_only": res["person_only_auc_log_upvotes_30d"],
                  "coef": res["baseline_coefficients"]}, indent=1))
