"""Nightly per-launch probability files for the website (orchestrator 01:20Z Nov 14). Counts and launch ids only.
  python prob_writer.py 0005 <day> <scratchpad>      -> tmp/e5/website/probabilities/<day>_0005.json
  python prob_writer.py prereveal <day> <scratchpad> -> tmp/e5/website/probabilities/<day>_prereveal.json
00:05 inputs: results/web/predictions/<day>_0005.json ranking[{rank,id,score}] if present, else raw/daily/<day>/forecast_<day>.parquet
pred_arm2 (scores), else results/web/forecast_0005/<day>.json predicted_rank (rank-table fallback). Model: frozen_prob_0005.json.
03:45 inputs: results/web/predictions/<day>_prereveal.json ranking[{rank,id}] if present, else results/early_forecast/<day>_P345.json
pred_rank_hybrid. Model: frozen_prob_prereveal.json (rank table from 11 replay days). Each file carries basis + calibration summary.
"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
KIND, D, SP = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"; PM = os.path.join(HERE, "reports", "prob_model")
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
def rescale(p, k):
    p = np.clip(np.asarray(p, float), 1e-6, 1)
    for _ in range(50):
        p = np.clip(p * k / p.sum(), 0, 1)
        if abs(p.sum() - k) < 1e-6: break
    return p
CAL = json.load(open(os.path.join(PM, "prob_model.json")))
out = {"day": D, "written_at": pd.Timestamp.now(tz="UTC").isoformat()}
if KIND == "0005":
    FZ = json.load(open(os.path.join(PM, "frozen_prob_0005.json"))); src = None; S = None
    raw = gcat(f"{B}/results/web/predictions/{D}_0005.json")
    if raw:
        R = pd.DataFrame(json.loads(raw).get("ranking") or []); src = "results/web/predictions"
        if "score" in R: S = R[["id", "score"]].rename(columns={"score": "s"})
        else: S = R[["id", "rank"]]
    if S is None:
        fc = os.path.join(SP, f"fcp_{D}.parquet")
        if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{D}/forecast_{D}.parquet", fc]).returncode == 0 and os.path.getsize(fc) > 0:
            F = pd.read_parquet(fc)
            if "pred_arm2" in F: S = F[["id", "pred_arm2"]].rename(columns={"pred_arm2": "s"}); src = "raw/daily forecast pred_arm2"
    if S is None:
        raw = gcat(f"{B}/results/web/forecast_0005/{D}.json")
        if raw: S = pd.DataFrame(json.loads(raw)["forecast"]).rename(columns={"predicted_rank": "rank"})[["id", "rank"]]; src = "results/web/forecast_0005 (ranks only)"
    if S is None: out.update({"prediction": "00:05 PT", "status": "not published"})
    else:
        S["id"] = S.id.astype(str); n = len(S)
        if "s" in S:
            S = S.sort_values("s", ascending=False).reset_index(drop=True); z = (S.s - S.s.mean()) / (S.s.std() or 1)
            F_ = pd.DataFrame({"z": z, "lnr": np.log(np.arange(1, n + 1)), "gap_up": np.r_[0.0, z.values[:-1] - z.values[1:]], "gap_dn": np.r_[z.values[:-1] - z.values[1:], 0.0], "lnn": np.log(n)})
            method = "frozen logistic on score position"
            for k in (3, 5, 10):
                m = FZ["models"][f"top{k}"]; lin = m["intercept"] + sum(m["coef"][f] * F_[f] for f in FZ["features"]); S[f"p_top{k}"] = rescale(1 / (1 + np.exp(-lin)), min(k, n))
        else:
            S = S.sort_values("rank").reset_index(drop=True); method = "rank table fallback (no scores published)"
            for k in (3, 5, 10):
                tb = {int(a): b for a, b in FZ["fallback rank table (no scores)"][f"top{k}"].items()}; S[f"p_top{k}"] = rescale(np.minimum(np.arange(1, n + 1), 16).astype(int).tolist() and [tb.get(min(r, 16), 0.0) for r in range(1, n + 1)], min(k, n))
        S["rank"] = np.arange(1, n + 1)
        out.update({"prediction": "00:05 PT", "status": "ok", "source": src, "method": method, "basis": FZ["basis"],
                    "calibration (backtest, May-Oct)": {f"top{k}": {"Brier skill vs base rate": CAL["(1) 00:05 all scored days (May-Oct)"][f"top{k}"]["Brier skill vs base rate [CI]"], "reliability": CAL["(1) 00:05 all scored days (May-Oct)"][f"top{k}"]["reliability (bin: mean predicted %, observed %, n)"]} for k in (3, 5, 10)},
                    "launches": [{"id": r.id, "rank": int(r["rank"]), **{f"p_top{k}": round(float(r[f"p_top{k}"]), 3) for k in (3, 5, 10)}} for _, r in S.iterrows()]})
else:
    FZ = json.load(open(os.path.join(PM, "frozen_prob_prereveal.json"))); S = None
    raw = gcat(f"{B}/results/web/predictions/{D}_prereveal.json")
    if raw: S = pd.DataFrame(json.loads(raw).get("ranking") or [])[["id", "rank"]]; src = "results/web/predictions"
    else:
        raw = gcat(f"{B}/results/early_forecast/{D}_P345.json")
        if raw:
            F = pd.DataFrame(json.loads(raw).get("forecast") or [])
            if "pred_rank_hybrid" in F: S = F[["id", "pred_rank_hybrid"]].dropna().rename(columns={"pred_rank_hybrid": "rank"}); src = "results/early_forecast P345 pred_rank_hybrid"
    if S is None: out.update({"prediction": "03:45 PT", "status": "not published"})
    else:
        S["id"] = S.id.astype(str); S = S.sort_values("rank").reset_index(drop=True); n = len(S); S["rank"] = np.arange(1, n + 1)
        for k in (3, 5, 10):
            tb = {int(a): b for a, b in FZ["table"][f"top{k}"].items()}; S[f"p_top{k}"] = rescale([tb.get(r if r <= 10 else 16, 0.0) for r in S["rank"]], min(k, n))
        cal = CAL["(2) 03:45 replay (hybrid order), rank-only table"]
        out.update({"prediction": "03:45 PT", "status": "ok", "source": src, "method": "rank table (position in the published 03:45 order)", "basis": FZ["basis"],
                    "calibration (replay, leave-one-day-out)": {f"top{k}": {"Brier skill vs base rate": cal[f"top{k}"]["Brier skill vs base rate"], "rank cells % [CI], n": cal[f"top{k}"]["pooled rank cells: % finishing top k [CI], n (positions 1-10, 16+ = 11+)"]} for k in (3, 5, 10)},
                    "caveat": "11 replay days: per-position rates have wide intervals (e.g. position 3: 45% [18, 73] for top 3).",
                    "launches": [{"id": r.id, "rank": int(r["rank"]), **{f"p_top{k}": round(float(r[f"p_top{k}"]), 3) for k in (3, 5, 10)}} for _, r in S.iterrows()]})
p = os.path.join(SP, f"prob_{D}_{KIND}.json"); json.dump(out, open(p, "w"), indent=1, default=float)
subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/website/probabilities/{D}_{KIND}.json"], check=True)
print(json.dumps({k: v for k, v in out.items() if k not in ("launches", "calibration (backtest, May-Oct)", "calibration (replay, leave-one-day-out)")}), "launches", len(out.get("launches", [])))
