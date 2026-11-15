"""Score e5_faithful.py. Per launch (2026 Apr-Oct, all launches; plus the subset on days with >= 10 ranked, the 184 scored days):
  shown top 3 = the readable_v2 inputs with the largest |attribution| (what the site lists); arm-2 top 3 = the readable-input groups with the
  largest |grouped SHAP| (the 10 groups; "other" reported separately as the share of |arm-2 attribution| outside the readable inputs)
  - share of launches whose #1 shown driver is not in arm 2's top 3 (and not arm 2's #1)
  - sign agreement: for each shown top-3 driver, same sign in arm 2's grouped SHAP
  - top-3 overlap (|shown top3 ∩ arm2 top3| / 3) and Spearman of |attribution| over the 10 inputs
  - per input: how often shown in the top 3 vs how often in arm 2's top 3, sign agreement when shown; worst inputs
  - share of arm-2 |attribution| mass on inputs readable_v2 does not have ("other"), and whether "other" would be arm 2's #1 driver
Intervals: day bootstrap 2000.      python score_faithful.py <parquet> <out json> [truth_daily.json]"""
import json, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
PQ, OUT = sys.argv[1:3]; rng = np.random.default_rng(0)
X10 = ["hist_hunter_rel", "hist_hunter_n", "hist_hunter_top5", "llm_pitch", "topic_prior_mean", "txt_ridge", "ph_n_media", "ph_n_makers", "ph_hunter_age_d", "promo_cov"]
LAB = {"hist_hunter_rel": "hunter track record (relative)", "hist_hunter_n": "hunter launches before", "hist_hunter_top5": "hunter top-5 rate before",
       "llm_pitch": "Gemini pitch score", "topic_prior_mean": "topic prior", "txt_ridge": "text model score", "ph_n_media": "media items",
       "ph_n_makers": "team size", "ph_hunter_age_d": "hunter account age", "promo_cov": "pre-launch coverage"}
D = pd.read_parquet(PQ); D["day"] = D.day.astype(str).str[:10]
if len(sys.argv) > 3:   # keep the scored days (>= 10 ranked in truth_daily: the 184 days of the 2026 backtest)
    TD = json.load(open(sys.argv[3]))["days"]; D = D[D.day.map(lambda d: (TD.get(d) or {}).get("status") == "counts")].reset_index(drop=True)
import os
if os.environ.get("DAY_CENTER") == "1":   # within-day view: subtract each day's mean attribution per input (day-constant inputs drop out)
    for c in [f"r_{x}" for x in X10] + [f"a_{x}" for x in X10] + ["a_other"]: D[c] = D[c] - D.groupby("day")[c].transform("mean")
R = D[[f"r_{c}" for c in X10]].values; A = D[[f"a_{c}" for c in X10]].values; O = D.a_other.values
rows = []
for k in range(len(D)):
    sr = np.argsort(-np.abs(R[k]))[:3]; sa = np.argsort(-np.abs(A[k]))[:3]
    full = np.append(np.abs(A[k]), abs(O[k]))
    rows.append({"day": D.day.iloc[k], "first_not_in_arm2_top3": float(sr[0] not in set(sa)), "first_not_arm2_first": float(sr[0] != sa[0]),
                 "overlap": len(set(sr) & set(sa)) / 3, "sign_agree": np.mean([np.sign(R[k, j]) == np.sign(A[k, j]) for j in sr]),
                 "spearman": spearmanr(np.abs(R[k]), np.abs(A[k])).correlation, "other_share": abs(O[k]) / max(full.sum(), 1e-12),
                 "other_is_arm2_first": float(abs(O[k]) > np.abs(A[k]).max()), "shown": list(sr), "arm2": list(sa)})
P = pd.DataFrame(rows)
def ci(col):
    days = P.day.unique(); g = {d: P[P.day == d][col].values for d in days}; m = float(np.nanmean(P[col]))
    bs = [np.nanmean(np.concatenate([g[d] for d in rng.choice(days, len(days))])) for _ in range(2000)]
    return [round(100 * m, 1), round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1)]
per = []
for j, c in enumerate(X10):
    shown = P.shown.map(lambda s: j in s); inA = P.arm2.map(lambda s: j in s)
    sg = [np.sign(R[k, j]) == np.sign(A[k, j]) for k in range(len(D)) if j in P.shown.iloc[k]]
    per.append({"input": LAB[c], "shown in top 3 %": round(100 * shown.mean(), 1), "in arm 2 top 3 %": round(100 * inA.mean(), 1),
                "shown #1 %": round(100 * P.shown.map(lambda s: s[0] == j).mean(), 1), "arm 2 #1 %": round(100 * P.arm2.map(lambda s: s[0] == j).mean(), 1),
                "sign agreement when shown %": round(100 * float(np.mean(sg)), 1) if sg else None,
                "mean |shown| / mean |arm 2|": round(float(np.abs(R[:, j]).mean() / max(np.abs(A[:, j]).mean(), 1e-12)), 2)})
per.sort(key=lambda r: -(r["shown in top 3 %"] - r["in arm 2 top 3 %"]))
res = {"launches": int(len(P)), "days": int(P.day.nunique()),
       "#1 shown driver NOT in arm 2's top 3 (% of launches) [day CI]": ci("first_not_in_arm2_top3"),
       "#1 shown driver differs from arm 2's #1 (%)": ci("first_not_arm2_first"),
       "top-3 overlap (%)": ci("overlap"), "sign agreement of shown top-3 drivers (%)": ci("sign_agree"),
       "Spearman of |attribution| over the 10 inputs (x100)": ci("spearman"),
       "share of arm 2 |attribution| on inputs readable_v2 does not have (%)": ci("other_share"),
       "arm 2's largest group is an input readable_v2 does not have (% of launches)": ci("other_is_arm2_first"),
       "per input (sorted: most over-shown vs arm 2 first)": per}
json.dump(res, open(OUT, "w"), indent=1, default=float); print(json.dumps(res, indent=1, default=float))
