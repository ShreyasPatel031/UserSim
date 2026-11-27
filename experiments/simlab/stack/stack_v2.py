"""STACK-v2 (orchestrator 10:57Z Nov 27, after D-E5-STACK-HOLD; PREREG addendum 15): STACK-1b + the live BACKER-v2 score as a 5th input.
  inputs  : [ln_rw, tm, ln_rw_x_tm, logit P(yes) CHOICE-FT-1 500k] (STACK-1) + s_v2 = the live BACKER-v2 walk-forward decision value
            (backer_v2_lists.py's model for that day, trained on re-read truth of days before it, incl. the team-follow features)
  fit     : logistic on STACK-1's validation pairs only (Nov 1-10, 15% pool sample, standardised), one fit, no refit on test.
  test    : Nov 11-22 full bench pool (STACK-1b scores); lists = top 2000 per launch by the stack-v2 probability.
  score   : the live north-star rule (stack_score.py / backer_score.py) vs the live BACKER-v2 lists, paired by launch, launch bootstrap.
  promote : only if stack-v2 minus live BACKER-v2 has its 95% interval above 0 (orchestrator 10:57Z).
    python stack_v2.py <store dir> <work dir>          (private outputs in the work dir and tmp/e5/private/stack_v2/; aggregates printed)
"""
import glob, json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); ST, WD = sys.argv[1], sys.argv[2]; os.makedirs(WD, exist_ok=True)
CC = os.path.join(HERE, "..", "cohort_calibration"); CV = os.environ.get("FRESH_SIMHARNESS") or os.environ["STACK_CV"]
# ---- live BACKER-v2 decision values for every complete held person x launch, Nov 1-22 (same code path as backer_v2_lists.py)
os.environ["BV2_LIB"] = "1"; G = {"__file__": os.path.join(CC, "backer_v2.py")}; argv0 = sys.argv
sys.argv = ["x", ST, "/dev/null", "2026-11-08", "2026-11-21", "2026-10-25"]
try: exec(open(os.path.join(CC, "backer_v2.py")).read(), G)
except SystemExit: pass
sys.argv = argv0; day_table = G["day_table"]; rng = np.random.default_rng(0); TR = {}
DAYS = [str(x.date()) for x in pd.date_range("2026-11-01", "2026-11-22")]
SV = os.path.join(WD, "v2scores.parquet")
if not os.path.exists(SV):
    out = []
    for D in DAYS:
        for d in [str(x.date()) for x in pd.date_range("2026-10-25", pd.Timestamp(D) - pd.Timedelta(days=1))]:
            if d not in TR: TR[d] = day_table(d)
        Xs, ys = [], []
        for d, t in TR.items():
            if not t or d >= D: continue
            for x in t["launches"]:
                pos = np.where(x["y"] == 1)[0]; neg = np.where(x["y"] == 0)[0]
                neg = rng.choice(neg, max(1, int(0.05 * len(neg))), replace=False) if len(neg) else neg
                Xs.append(x["X"][np.r_[pos, neg]]); ys.append(np.r_[np.ones(len(pos)), np.zeros(len(neg))])
        if not Xs: print(D, "no training rows", flush=True); continue
        m = LogisticRegression(max_iter=1000).fit(np.vstack(Xs), np.concatenate(ys)); T = day_table(D, score_all=True)
        close = G["PP"].close_utc(D); start = close - pd.Timedelta(days=1)
        pop = np.array(sorted(p for p in G["COMPLETE"] if G["first"].get(p, close) < start))
        for x in T["launches"]:
            out.append(pd.DataFrame({"day": D, "launch_id": str(x["lid"]), "person_id": pop, "s_v2": m.decision_function(x["X"]).astype(np.float32)}))
        print(D, "launches", len(T["launches"]), "people", len(pop), flush=True)
    pd.concat(out, ignore_index=True).to_parquet(SV, index=False)
V = pd.read_parquet(SV)
# ---- bench pairs (validation fit / test) with STACK-1 features
sys.path.insert(0, CV)
from simharness.bench import Benchmark  # noqa: E402
from simharness.finetune.stack1 import feats  # noqa: E402
BD = os.environ["STACK_BUILD_DIR"]; b = Benchmark(BD)
PID = pd.read_parquet(f"{BD}/people.parquet", columns=["person_idx", "person_id"]); P2I = dict(zip(PID.person_id.astype(str), PID.person_idx))
I2L = dict(zip(b.items.item_idx, b.items.item_id.astype(str)))
def load(files):
    rows, ps = [], []
    for f in files:
        for l in open(f):
            r = json.loads(l); m = r["meta"]
            for i, s in zip(m["items"], r["p"]): rows.append((m["day"], int(i), int(m["person_idx"]))); ps.append(s)
    R = pd.DataFrame(rows, columns=["day", "item_idx", "person_idx"]); R["pyes"] = ps
    return R.drop_duplicates(["day", "item_idx", "person_idx"]).reset_index(drop=True)
Vk = V.assign(person_idx=V.person_id.astype(str).map(P2I)).dropna(subset=["person_idx"])
Vk = Vk.assign(person_idx=Vk.person_idx.astype(int)).set_index(["day", "launch_id", "person_idx"]).s_v2
def X5(R):
    X = feats(b, R[["day", "item_idx", "person_idx"]], R.pyes.to_numpy())
    key = pd.MultiIndex.from_arrays([R.day, R.item_idx.map(I2L), R.person_idx]); s = Vk.reindex(key).to_numpy().astype(float).copy()
    miss = np.isnan(s); s[miss] = np.nanmin(s) if (~miss).any() else 0.0
    return np.column_stack([X, s]), miss
# PREREG 15a: only people held before D's start (in the live BACKER-v2 population) -- forward-available; the bench also holds people first
# read after D, who cannot be named live and never count under the live rule
val = load([os.path.join(WD, "..", "scores_val_eval.jsonl")]); val["y"] = [int(p in set(b.positives(d, i).tolist())) for d, i, p in zip(val.day, val.item_idx, val.person_idx)]
Xv, mv = X5(val); val, Xv = val[~mv].reset_index(drop=True), Xv[~mv]; mv = float(mv.mean()); mu, sd = Xv.mean(0), Xv.std(0) + 1e-9
clf = LogisticRegression(max_iter=2000).fit((Xv - mu) / sd, val.y.to_numpy())
C = {"features": ["ln_rw", "tm", "ln_rw_x_tm", "logit_pyes", "s_v2_live"], "mu": mu.tolist(), "sd": sd.tolist(), "coef": clf.coef_[0].tolist(),
     "intercept": float(clf.intercept_[0]), "fit_rows": int(len(val)), "fit_positives": int(val.y.sum()), "val_missing_s_v2": round(mv, 4)}
json.dump(C, open(os.path.join(WD, "stack_v2_coef.json"), "w"), indent=1)
print("fit", json.dumps({k: (np.round(v, 4).tolist() if isinstance(v, list) else v) for k, v in C.items() if k in ("coef", "intercept", "fit_rows", "fit_positives", "val_missing_s_v2")}), flush=True)
test = load(sorted(glob.glob(os.path.join(WD, "..", "hist", "scores_*.jsonl")))); Xt, mt = X5(test); test, Xt = test[~mt].reset_index(drop=True), Xt[~mt]; mt = float(mt.mean())
test["p"] = 1 / (1 + np.exp(-(((Xt - mu) / sd) @ clf.coef_[0] + clf.intercept_[0])))
PIDs = PID.set_index("person_idx").person_id.astype(str); od = os.path.join(WD, "lists"); os.makedirs(od, exist_ok=True)
for d, gd in test.groupby("day"):
    out = []
    for i, g in gd.groupby("item_idx"):
        g = g.nlargest(2000, "p"); out.append(pd.DataFrame({"launch_id": I2L[i], "person_id": PIDs.reindex(g.person_idx).to_numpy(), "p": g.p.to_numpy(), "rank": np.arange(1, len(g) + 1)}))
    pd.concat(out).assign(day=d).to_parquet(os.path.join(od, f"{d}.parquet"), index=False)
subprocess.run(["gsutil", "-q", "-m", "cp", *glob.glob(os.path.join(od, "*.parquet")), os.path.join(WD, "stack_v2_coef.json"),
                "gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/private/stack_v2/"], check=True)
print("test pairs", len(test), "missing s_v2 share", round(mt, 4), "lists", sorted(os.listdir(od))[:1], "...", flush=True)
