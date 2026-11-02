"""Self-test of the e1v2 package on a backtest day staged in the live layout.
(a) forecast file with the audience columns: predict.py must equal the in-code prediction of the same boosters.
(b) forecast file without them: the fallback path must run and say what it did."""
import json, os, subprocess, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from simlab import vote_model2 as V, e1v2_package as K
PKG, DAY = sys.argv[1], sys.argv[2]
PH = V.PH; SH = os.path.join(PH, "data", "shadow", "e1v2")
A, _ = V.load(["pna"]); A = V.day_terms(A, "pna").rename(columns={"pna_ev": "pnx_ev", "pna_reach": "pnx_reach"})
d = A[A.day == DAY].copy()
meta = json.load(open(os.path.join(PKG, "meta.json")))
raw = np.mean([lgb.Booster(model_file=os.path.join(PKG, f)).predict(d[meta["features"]].astype(float), raw_score=True) for f in meta["models"]], 0)
d["expect"] = raw + np.log(np.expm1(d["all"]).clip(lower=0.5)) + meta["offset_log_scale"]
os.makedirs(os.path.join(PH, "data", "sim_live"), exist_ok=True)
json.dump({r.id: {"pnx_ev": r.pnx_ev, "pnx_reach": r.pnx_reach} for r in d.itertuples()}, open(os.path.join(PH, "data", "sim_live", f"pnx_{DAY}.json"), "w"))
out = {}
for mode, cols in (("a_with_audience", K.AUD), ("b_fallback", [])):
    d[["id", "day"] + cols].assign(pred=d["all"]).to_parquet(os.path.join(PH, "results", f"forecast_{DAY}.parquet"))
    r = subprocess.run([sys.executable, "predict.py", DAY], cwd=SH, capture_output=True, text=True, timeout=3600)
    got = pd.DataFrame([json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")])
    M = d.merge(got, left_on="id", right_on="launch_id", how="left")
    out[mode] = {"exit": r.returncode, "scored": int(got.shape[0]), "lineup": int(len(d)),
                 "max_abs_diff_vs_in_code": float(np.abs(M.score - M.expect).max()) if len(got) else None,
                 "stderr": r.stderr.strip()[-300:]}
print(json.dumps(out, indent=1))
