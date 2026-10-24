"""Temporal-holdout baseline for predicting a launch's within-topic vote percentile.

Reads data/producthunt/*.jsonl (from scripts/ph_crawl.py), trains on 2025-10..2026-06
and tests on 2026-07..2026-09. Needs numpy, scipy and scikit-learn.

    python scripts/ph_baseline_eval.py
"""
import json,glob,re,os
import numpy as np
from datetime import datetime
from scipy.stats import spearmanr,rankdata
from sklearn.linear_model import RidgeCV
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from pathlib import Path
DATA=Path(__file__).resolve().parent.parent/'data'/'producthunt'
rows=[]
for f in sorted(glob.glob(os.path.join(DATA,'*.jsonl'))):
    t,m=os.path.basename(f)[:-6].rsplit('_',1)
    for l in open(f):
        r=json.loads(l); r['_topic']=t; r['_month']=m; rows.append(r)
print('rows',len(rows),'unique launches',len({r['id'] for r in rows}))
# per topic-month percentile target
from collections import defaultdict
g=defaultdict(list)
for i,r in enumerate(rows): g[(r['_topic'],r['_month'])].append(i)
y=np.zeros(len(rows))
for k,ix in g.items():
    v=np.array([rows[i]['votesCount'] for i in ix]); y[ix]=(rankdata(v)-1)/(len(v)-1)
print('median votes by month (AI):',{m:int(np.median([r['votesCount'] for r in rows if r['_topic']=='artificial-intelligence' and r['_month']==m])) for m in sorted({r['_month'] for r in rows})})
def feats(r):
    d=datetime.fromisoformat(r['featuredAt'].replace('Z','+00:00')); mk=r['makers']; fol=[m['followersCount'] or 0 for m in mk] or [0]
    return [np.log1p(max(fol)),np.log1p(sum(fol)),len(mk),len(r['media']),int(any(m['type']=='video' for m in r['media'])),len(r['tagline']),len(r['description'] or ''),d.weekday(),d.hour,
            int(bool(re.search(r'\b\d+(\.\d+)?\b|\bv\d',r['name']))),int('Twitter' in [l['type'] for l in r['productLinks']]),len(r['topics']),
            int(r['_topic']=='artificial-intelligence'),int(r['_topic']=='developer-tools')]
X=np.array([feats(r) for r in rows],float)
months=np.array([r['_month'] for r in rows])
test=np.isin(months,['2026-07','2026-08','2026-09']); train=~test
print('train',train.sum(),'test',test.sum())
def prec(p,m,ix):
    out=[]
    for k,ixs in g.items():
        ixs=np.array([i for i in ixs if m[i]])
        if len(ixs)<20: continue
        top=y[ixs]>=0.75; pick=np.argsort(-p[ixs])[:top.sum()]; out.append(top[pick].mean())
    return np.mean(out)
def ev(name,p):
    sp=spearmanr(p[test],y[test]).statistic
    print(f'{name:34s} spearman={sp:.3f}  top-quartile precision={prec(p,test,None):.2f} (random 0.25)')
names='max_fol sum_fol n_makers n_media video tag_len desc_len weekday hour versioned twitter n_topics isAI isDev'.split()
for i,n in enumerate(names): print(f'  {n:10s} spearman vs pct (all) {spearmanr(X[:,i],y).statistic:+.2f}')
def fit(cols,model):
    m=model().fit(X[train][:,cols],y[train]); p=np.zeros(len(y)); p[test]=m.predict(X[test][:,cols]); return p
allc=list(range(X.shape[1])); nofol=[i for i in allc if i not in (0,1)]
ridge=lambda:make_pipeline(StandardScaler(),RidgeCV(alphas=np.logspace(-1,3,20)))
gbm=lambda:GradientBoostingRegressor(n_estimators=200,max_depth=3,learning_rate=0.05,subsample=0.8,random_state=0)
print('--- temporal holdout: train 2025-10..2026-06, test 2026-07..2026-09')
ev('ridge all features',fit(allc,ridge)); ev('gbm all features',fit(allc,gbm))
ev('ridge w/o maker followers',fit(nofol,ridge)); ev('gbm w/o maker followers',fit(nofol,gbm))
ev('max maker followers alone',X[:,0]-0*y)
