import json,sys,numpy as np,pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
exec(open("experiments/decisions_api/score.py").read().split("ARMS =")[0].replace("OUT, RES = sys.argv[1:3]","OUT='%s'; RES=None"%sys.argv[1]))
X=feats(T); X["lapi"]=T.lapi.values
T["base_l"]=np.nan; T["stack"]=np.nan
for d in T.day.unique():
    tr=T.day!=d; te=~tr
    m0=LogisticRegression(max_iter=3000).fit(X.loc[tr,FEATS],T.y[tr]); T.loc[te,"base_l"]=m0.predict_proba(X.loc[te,FEATS])[:,1]
    m1=LogisticRegression(max_iter=3000).fit(X.loc[tr],T.y[tr]); T.loc[te,"stack"]=m1.predict_proba(X.loc[te])[:,1]
pids=T.groupby(["day","pid"]).ngroup().to_numpy(); n=pids.max()+1; rng=np.random.default_rng(1); d=[]
for _ in range(1000):
    w=np.bincount(rng.integers(0,n,n),minlength=n)[pids]
    d.append(roc_auc_score(T.y,T["stack"],sample_weight=w)-roc_auc_score(T.y,T.base_l,sample_weight=w))
print("baseline(LODO on test days) AUC",round(roc_auc_score(T.y,T.base_l),4),"| baseline+API AUC",round(roc_auc_score(T.y,T["stack"]),4),"| diff",round(np.mean(d),4),np.percentile(d,[2.5,97.5]).round(4))
print("orig baseline AUC",round(roc_auc_score(T.y,T.base),4))
