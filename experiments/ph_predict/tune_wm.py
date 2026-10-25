"""Do classifiers trained directly on 'weekly/monthly top-10' beat the log-votes regression on those lists?"""
import sys
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN

df = RN.load_llm(F.build()); df = df[~df.known]
outs = []
for m, tr, te in RN.folds(df, sys.argv[1:]):
    tr, te = M.add_fold_feats(tr, te)
    c = M.cols(tr, M.SOURCES)
    for d in (tr, te):  # where a launch stands within its week / month on the key signals
        for f in ["ph_hunter_followers", "hist_hunter_rel", "x_hunter_followers", "llm_brand", "ph_n_makers", "txt_ridge"]:
            if f in d:
                d[f"wk_{f}"] = d.groupby("week")[f].rank(pct=True)
                d[f"mo_{f}"] = d.groupby("mon")[f].rank(pct=True)
    cw = c + [x for x in tr.columns if x.startswith(("wk_", "mo_"))]
    te = te.copy()
    reg = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                            subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
    te["pred"] = reg.fit(tr[c], tr.logv).predict(te[c])
    for tgt, col, name in (("week", "weeklyRank", "pred_wk"), ("mon", "monthlyRank", "pred_mo")):
        clf = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
        y = (tr[col] <= (10 if tgt == "week" else 20)).astype(int)
        te[name] = clf.fit(tr[cw], y).predict_proba(te[cw])[:, 1]
    reg2 = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                             subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
    te["pred_reg_wk"] = reg2.fit(tr[cw], tr.logv).predict(te[cw])
    outs.append(te)
te = pd.concat(outs)
for s in ["pred", "pred_wk", "pred_mo", "pred_reg_wk"]:
    r = M.evaluate(te, s); print(s, {k: round(v, 3) for k, v in r.items()})
