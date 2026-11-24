"""Published backer list v2 (BACKER-v2 passed, rule 5; orchestrator 22:29Z Nov 23): for day D, logistic fit walk-forward on re-read truth of days
[Oct 25, D-1], applied to every complete person held before D's start; top 2000 per launch written to tmp/e5/private/backer_pred_v2/<D>.parquet
(private bucket path, salted ids only). Inputs: reads before 00:00 PT of D; follow edges read before D's start; no fields dated on or after D.
    python backer_v2_lists.py <store dir> <D> [<D> ...]"""
import json, os, sys, subprocess, tempfile
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); ST = sys.argv[1]; TARGETS = sys.argv[2:]
os.environ["BV2_LIB"] = "1"; G = {"__file__": os.path.join(HERE, "backer_v2.py")}; sys.argv = ["x", ST, "/dev/null", "2026-11-08", "2026-11-21", "2026-10-25"]
try: exec(open(os.path.join(HERE, "backer_v2.py")).read(), G)
except SystemExit: pass
day_table, B = G["day_table"], G["B"]; rng = np.random.default_rng(0); TR = {}
for D in TARGETS:
    for d in [str(x.date()) for x in pd.date_range("2026-10-25", pd.Timestamp(D) - pd.Timedelta(days=1))]:
        if d not in TR: TR[d] = day_table(d)
    Xs, ys = [], []
    for d, t in TR.items():
        if not t or d >= D: continue
        for x in t["launches"]:
            pos = np.where(x["y"] == 1)[0]; neg = np.where(x["y"] == 0)[0]
            neg = rng.choice(neg, max(1, int(0.05 * len(neg))), replace=False) if len(neg) else neg
            Xs.append(x["X"][np.r_[pos, neg]]); ys.append(np.r_[np.ones(len(pos)), np.zeros(len(neg))])
    if not Xs or sum(len(y) for y in ys) < 1000: print(D, "skipped: no walk-forward training rows yet", flush=True); continue
    m = LogisticRegression(max_iter=1000).fit(np.vstack(Xs), np.concatenate(ys))
    T = day_table(D, score_all=True)
    close = G["PP"].close_utc(D); start = close - pd.Timedelta(days=1)
    pop = sorted(p for p in G["COMPLETE"] if G["first"].get(p, close) < start)
    rows = []; sums = {}
    for x in T["launches"]:
        s = m.decision_function(x["X"]); pf = 1 / (1 + np.exp(-s)); pc = pf / (pf + (1 - pf) / 0.05)   # undo the 5% negative subsampling
        sums[x["lid"]] = {"expected_voters_full_pool": float(pc.sum()), "expected_voters_active7": float(pc[x["n7"] > 0].sum()), "pool": int(len(pc))}
        o = np.argsort(-s)[:2000]; p = 1 / (1 + np.exp(-s[o]))
        rows.append(pd.DataFrame({"launch_id": x["lid"], "person_id": [pop[i] for i in o], "p": p, "rank": np.arange(1, len(o) + 1), "day": D,
                                  "model": "backer_v2 logistic walk-forward", "coef": str([round(float(c), 3) for c in m.coef_[0]])}))
    out = pd.concat(rows); f = os.path.join(tempfile.gettempdir(), f"bv2_{D}.parquet"); out.to_parquet(f, index=False)
    subprocess.run(["gsutil", "-q", "cp", f, f"{B}/tmp/e5/private/backer_pred_v2/{D}.parquet"], check=True); os.remove(f)
    fj = f.replace(".parquet", "_sums.json"); json.dump({"day": D, "launches": sums}, open(fj, "w"))   # aggregates per launch, no person ids
    subprocess.run(["gsutil", "-q", "cp", fj, f"{B}/tmp/e5/private/backer_pred_v2/{D}_launch_sums.json"], check=True); os.remove(fj)
    print(D, "launches", len(T["launches"]), "people", len(pop), "coef", [round(float(c), 3) for c in m.coef_[0]], flush=True)
