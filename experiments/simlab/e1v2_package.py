"""E1 v2 follow-up 2: package the deployable form ("shadow|pna" in vote_model2_confirm.py) for the pipeline's shadow slot
(pipeline.daily s_shadow, PH agent's commit 0b564e2): installed at ph_predict/data/shadow/e1v2/, run as
`python3 predict.py <day>` from that folder, prints JSON lines {"launch_id", "score"} (score = log expected votes).
Model: Poisson LightGBM offset by the launch model's prediction, corrections from the page-free pool (pna_, live under
pnx_ names) and the day term; 5 seeds, trained on every launch with a finished day in the backtest (Apr–Oct).
usage: SIMLAB_DATA=data_v2 python -m simlab.e1v2_package OUTDIR -> OUTDIR/{predict.py, model_s<seed>.txt, meta.json}"""
import json, os, sys
import numpy as np
from . import vote_model2 as V

FEATS = ["pnx_ev", "day_n", "day_wd", "day_reach", "day_pool_sum", "day_lm_sum"]   # live names (pna_ rows are stored as pnx_)
SEEDS = range(5)

PREDICT = r'''"""E1 v2 shadow forecast (simlab/e1v2_package.py on claude/person-model-v2). Run from this folder:
python3 predict.py <day>   -> JSON lines {"launch_id": "...", "score": float}; score = log expected votes (higher = more).
Inputs (all known before launch): ../../../results/forecast_<day>.parquet (id, day, pred = the launch model's log votes),
../../sim_live/pnx_<day>.json (the page-free pool simulation, pna_ under pnx_ names; falls back to ../../pnx_features.json).
A launch without a pool row is scored with the pool missing (the model's default branch), so every launch in the
forecast is scored."""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def main(day):
    meta = json.load(open(os.path.join(HERE, "meta.json")))
    F = pd.read_parquet(os.path.join(PH, "results", f"forecast_{day}.parquet")); F["id"] = F.id.astype(str)
    F = F[F.day.astype(str) == day] if "day" in F else F
    pool = {}
    for p in (os.path.join(PH, "data", "sim_live", f"pnx_{day}.json"), os.path.join(PH, "data", "pnx_features.json")):
        if os.path.exists(p):
            S = json.load(open(p)); pool = {k: v for k, v in S.items() if k in set(F.id)}
            if pool:
                break
    F["pnx_ev"] = F.id.map(lambda x: pool.get(x, {}).get("pnx_ev", np.nan))
    F["pnx_reach"] = F.id.map(lambda x: pool.get(x, {}).get("pnx_reach", np.nan))
    mu0 = np.expm1(F.pred.astype(float)).clip(lower=0.5)
    F["day_n"] = len(F); F["day_wd"] = pd.Timestamp(day).weekday()
    F["day_reach"] = F.pnx_reach.mean(); F["day_pool_sum"] = F.pnx_ev.sum(min_count=1); F["day_lm_sum"] = mu0.sum()
    X = F[meta["features"]].astype(float)
    raw = np.mean([lgb.Booster(model_file=os.path.join(HERE, f)).predict(X, raw_score=True) for f in meta["models"]], axis=0)
    score = raw + np.log(mu0) + meta["offset_log_scale"]
    for i, s in zip(F.id, score):
        print(json.dumps({"launch_id": str(i), "score": float(s)}))
    print(f"e1v2: {len(F)} launches scored, pool rows for {F.pnx_ev.notna().sum()}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
'''


def main(out):
    import lightgbm as lgb
    os.makedirs(out, exist_ok=True)
    A, _ = V.load(["pna"])
    A = V.day_terms(A, "pna").rename(columns={"pna_ev": "pnx_ev", "pna_reach": "pnx_reach"})
    c = float(np.log(A.votes.sum() / np.expm1(A["all"]).sum()))
    init = np.log(np.expm1(A["all"]).clip(lower=0.5)) + c
    kw = dict(objective="poisson", n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=30, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, verbose=-1, n_jobs=8, monotone_constraints=[1 if f == "pnx_ev" else 0 for f in FEATS])
    models = []
    for s in SEEDS:
        m = lgb.LGBMRegressor(random_state=s, **kw).fit(A[FEATS], A.votes, init_score=init)
        f = f"model_s{s}.txt"; m.booster_.save_model(os.path.join(out, f)); models.append(f)
    meta = {"name": "e1v2", "features": FEATS, "models": models, "offset_log_scale": c, "trained_on": [str(A.day.min()), str(A.day.max())],
            "launches": int(len(A)), "pool": "pna_ (page-free, all earlier months), live file sim_live/pnx_<day>.json",
            "offset": "results/forecast_<day>.parquet pred (the launch model's log1p votes)",
            "evaluation": "simlab/reports/vote_model2_confirm.json, variant shadow|pna"}
    json.dump(meta, open(os.path.join(out, "meta.json"), "w"), indent=1)
    open(os.path.join(out, "predict.py"), "w").write(PREDICT)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
