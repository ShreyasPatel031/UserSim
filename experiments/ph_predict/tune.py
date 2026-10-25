"""Quick settings sweep for the full model on the given test months (no ablations)."""
import sys
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN

df = RN.load_llm(F.build()); df = df[~df.known]
months = sys.argv[1:]
prep = [(m, *M.add_fold_feats(tr, te)) for m, tr, te in RN.folds(df, months)]
grid = {"base": dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, colsample_bytree=0.8),
        "small": dict(n_estimators=600, learning_rate=0.02, num_leaves=7, min_child_samples=40, colsample_bytree=0.5),
        "tiny": dict(n_estimators=800, learning_rate=0.02, num_leaves=4, min_child_samples=60, colsample_bytree=0.5),
        "big": dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=10, colsample_bytree=0.8)}
for name, prm in grid.items():
    outs = []
    for m, tr, te in prep:
        c = M.cols(tr, M.SOURCES)
        mdl = lgb.LGBMRegressor(subsample=0.8, subsample_freq=1, reg_lambda=1.0, random_state=0, verbose=-1, **prm)
        te = te.assign(pred=mdl.fit(tr[c], tr.logv).predict(te[c]))
        outs.append(te)
    r = M.evaluate(pd.concat(outs))
    print(name, {k: round(v, 3) for k, v in r.items()}, flush=True)
