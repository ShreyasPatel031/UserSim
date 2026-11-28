"""Live BACKER-v2 decision values for every complete person held before D's start x D's launches (STACK-v2's 5th input; PREREG 15).
Same code path as cohort_calibration/backer_v2_lists.py: walk-forward logistic on re-read truth of days [Oct 25, D-1], applied to D.
    python live_v2_scores.py <store dir> <D> <out.parquet>
"""
import os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); CC = os.path.join(HERE, "..", "cohort_calibration"); ST, D, OUT = sys.argv[1:4]
sys.path.insert(0, os.path.join(HERE, "..", "..")); from pipeline import warehouse  # noqa: E402
warehouse.table("launches", do_sync=True)   # a fresh session has no local launches table (Nov 28: CatalogException)
os.environ["BV2_LIB"] = "1"; G = {"__file__": os.path.join(CC, "backer_v2.py")}; sys.argv = ["x", ST, "/dev/null", "2026-11-08", "2026-11-21", "2026-10-25"]
try: exec(open(os.path.join(CC, "backer_v2.py")).read(), G)
except SystemExit: pass
day_table = G["day_table"]; rng = np.random.default_rng(0); Xs, ys = [], []
for d in [str(x.date()) for x in pd.date_range("2026-10-25", pd.Timestamp(D) - pd.Timedelta(days=1))]:
    t = day_table(d)
    for x in (t or {}).get("launches", []):
        pos = np.where(x["y"] == 1)[0]; neg = np.where(x["y"] == 0)[0]
        neg = rng.choice(neg, max(1, int(0.05 * len(neg))), replace=False) if len(neg) else neg
        Xs.append(x["X"][np.r_[pos, neg]]); ys.append(np.r_[np.ones(len(pos)), np.zeros(len(neg))])
m = LogisticRegression(max_iter=1000).fit(np.vstack(Xs), np.concatenate(ys)); T = day_table(D, score_all=True)
close = G["PP"].close_utc(D); start = close - pd.Timedelta(days=1)
pop = np.array(sorted(p for p in G["COMPLETE"] if G["first"].get(p, close) < start))
pd.concat([pd.DataFrame({"launch_id": str(x["lid"]), "person_id": pop, "s_v2": m.decision_function(x["X"]).astype(np.float32)}) for x in T["launches"]],
          ignore_index=True).to_parquet(OUT, index=False)
print("live_v2_scores", D, "launches", len(T["launches"]), "people", len(pop), flush=True)
