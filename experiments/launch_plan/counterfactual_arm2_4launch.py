import os,sys,json
sys.path[:0]=['/home/agent/w/arm2_live','/home/agent/w/experiments/ph_predict']
import numpy as np, pandas as pd, lightgbm as lgb
import model as M
from h25_live import P_, P_DET
df=pd.read_pickle('/tmp/cf/df.pkl'); cc=json.load(open('/tmp/cf/cc.json'))
T0='2026-09-21'
tr=df[df.day<T0]; te=df[df.day>=T0]
tr,te=M.add_fold_feats(tr,te)
tr=tr.sort_values(['day','id'],kind='stable'); te=te.sort_values(['day','id'],kind='stable').copy()
P=dict(P_,**P_DET); P['n_jobs']=3
mods=[lgb.LGBMRegressor(random_state=s,verbose=-1,**P).fit(tr[cc],tr.logv) for s in range(5)]
pr=lambda X: np.mean([m.predict(X[cc]) for m in mods],axis=0)
te['pred']=pr(te); te['prank']=te.groupby('day').pred.rank(ascending=False,method='first'); te['arank']=te.dailyRank
te['dow']=pd.to_datetime(te.day).dt.dayofweek
print('WEEKDAY CODING', te.groupby(['ph_weekday','dow']).day.nunique().to_dict())
print('launches per day by dow', te.groupby('day').agg(n=('id','size'),dow=('dow','first')).groupby('dow').n.agg(['mean','min','max']).round(1).to_dict('index'))
def bkt(r): return int(r) if r<=10 else (11 if r<=15 else (16 if r<=25 else 26))
te['b']=te.prank.map(bkt)
cal={k:te.groupby('b').arank.apply(lambda s:(s<=k).mean()).to_dict() for k in (3,5,10)}
AB=[(1,3),(4,5),(6,10),(11,20),(21,999)]
def ab(r):
    for i,(a,b) in enumerate(AB):
        if a<=r<=b: return i
te['ab']=te.arank.map(ab)
trans=te.groupby('b').ab.value_counts(normalize=True).unstack(fill_value=0)   # P(actual bucket | predicted bucket)
te['rel']=te.logv-te.groupby('day').logv.transform('mean')
relb=te.groupby('ab').rel.median().to_dict(); print('rel by actual-rank bucket',{AB[k]:round(v,3) for k,v in relb.items()})
print('real hist_hunter_rel quantiles among hunters with history', te[te.hist_hunter_n>0].hist_hunter_rel.quantile([.1,.5,.9]).round(3).to_dict())
AI=te[(te.topic_is_ai==1)&(te.topic_is_dev==0)]
BASE=dict(ph_n_makers=1,ph_hunter_age_d=60,ph_n_media=6,ph_has_video=1,ph_n_topics=3,ph_desc_len=350,ph_tagline_len=50,ph_name_len=12,
  x_company_has_x=0,busy_same_day=1,busy_7d=0,promo_posts=0,promo_posts_launch=0,promo_posts_li=0,promo_posts_x=0,promo_posts_founder=0,
  promo_cov=0,promo_cov_press=0,promo_cov_hn=0,promo_cov_reddit=0,hist_hunter_n=0,hist_hunter_rel=np.nan,hist_hunter_top5=np.nan,
  ph_hunter_n_same_day=1,llm_pitch=55,llm_brand=0,txt_ridge=float(te.txt_ridge.median()),
  comp_nn_mean=float(te.comp_nn_mean.median()),comp_nn_max=float(te.comp_nn_max.median()),comp_nn_sim=float(te.comp_nn_sim.median()),
  topic_prior_max=float(AI.topic_prior_max.median()),topic_prior_mean=float(AI.topic_prior_mean.median()),topic_is_ai=1,topic_is_dev=0)
def drank(g,col,v):
    s=g[col].dropna(); return np.nan if (pd.isna(v) or len(s)==0) else ((s<v).sum()+0.5*(s==v).sum()+0.5)/(len(s)+1)
def score(cfg,force_wd=None):
    out=[]
    for d,g in te.groupby('day'):
        r={c:g[c].iloc[0] for c in ('ph_weekday','ph_day_n_launches')}; r.update(BASE); r.update(cfg)
        if force_wd is not None: r['ph_weekday']=force_wd
        for a,b in (('ph_dayrank_ph_hunter_age_d','ph_hunter_age_d'),('ph_dayrank_ph_n_makers','ph_n_makers'),('ph_dayrank_ph_n_media','ph_n_media'),('hist_dayrank_hist_hunter_rel','hist_hunter_rel')): r[a]=drank(g,b,r[b])
        p=pr(pd.DataFrame([r])[cc].astype(float))[0]; rk=1+int((g.pred>p).sum()); b=bkt(rk)
        o=dict(day=d,dow=int(g.dow.iloc[0]),n=len(g),rank=rk,**{f'p{k}':cal[k].get(b,0) for k in (3,5,10)})
        for i in range(5): o[f'a{i}']=float(trans.loc[b,i]) if i in trans.columns else 0.
        out.append(o)
    return pd.DataFrame(out)

import itertools
SET=dict(ph_n_media=9,ph_has_video=1,llm_pitch=86,promo_posts=3,promo_posts_launch=2,promo_posts_founder=3,promo_posts_x=2)
HH=te[te.hist_hunter_n>0]
HUNT=dict(hist_hunter_n=float(HH.hist_hunter_n.median()),hist_hunter_rel=float(HH.hist_hunter_rel.median()),hist_hunter_top5=float(HH.hist_hunter_top5.median()),ph_hunter_age_d=float(HH.ph_hunter_age_d.median()))
memo={}
def state(hist):
    key=tuple(sorted(hist))
    if key not in memo:
        cfg=dict(SET)
        if key: cfg.update(hist_hunter_n=len(key),hist_hunter_rel=float(np.mean([relb[i] for i in key])),hist_hunter_top5=float(np.mean([i<2 for i in key])))
        memo[key]=score(cfg)[['day','dow']+[f'a{i}' for i in range(5)]]
    return memo[key]
for h in [()]+[c for n in (1,2,3) for c in itertools.combinations_with_replacement(range(5),n)]: state(h)
print('states',len(memo),flush=True)
K=3.7/4.9
def dist(hist,days,scale):
    o=state(hist); o=o[o.day.isin(days)]
    w=o.day.map(days).values.astype(float); a=np.array([(o[f'a{i}'].values*w).sum()/w.sum() for i in range(5)])
    if scale: t=a[:2].sum(); a[:2]*=K; a[2:]*=(1-t*K)/(1-t)
    return a
def chain(sat,wk,scale):
    # sat, wk: dict day->weight. launches 1-3 Saturday; launch 4 reported for Saturday and Tue-Thu
    H={():1.0}; out=[]; none=1.0
    for k in range(1,5):
        res={}
        for nm,days in (('sat',sat),('wk',wk)):
            p5=0; H2={}; pn=0
            for h,p in H.items():
                a=dist(h,days,scale); p5+=p*a[:2].sum()
                # probability of no top-5 so far needs path tracking: track flag inside history
                for i in range(5): H2[tuple(sorted(h+(i,)))]=H2.get(tuple(sorted(h+(i,))),0)+p*a[i]
            res[nm]=(p5,H2)
        cum_sat=1-sum(p for h,p in res['sat'][1].items() if all(i>=2 for i in h))
        cum_wk=1-sum(p for h,p in res['wk'][1].items() if all(i>=2 for i in h))
        out.append((res['sat'][0],res['wk'][0],cum_sat,cum_wk)); H=res['sat'][1]
    return np.array(out)
dd=te.groupby('day').dow.first(); SAT={d:1 for d in dd[dd==5].index}; WK={d:1 for d in dd[dd.isin([1,2,3])].index}
rng=np.random.default_rng(1)
def boot(scale):
    B=[]
    for _ in range(300):
        s=pd.Series(rng.choice(list(SAT),len(SAT))).value_counts().to_dict(); w=pd.Series(rng.choice(list(WK),len(WK))).value_counts().to_dict()
        B.append(chain(s,w,scale))
    return np.percentile(B,2.5,axis=0),np.percentile(B,97.5,axis=0)
for scale in (False,True):
    c=chain(SAT,WK,scale); lo,hi=boot(scale)
    print('\n== ROW A carried through 4 launches (launches 1-3 on Saturdays), %s' % ('SCALED by 3.7/4.9 for newcomer over-prediction' if scale else 'RAW'))
    for k in range(4):
        f=lambda j: f"{c[k,j]*100:.1f} [{lo[k,j]*100:.1f}, {hi[k,j]*100:.1f}]"
        print(f" launch {k+1}: P(top5) Saturday {f(0)} | Tue-Thu {f(1)} | cumulative >=1 top5 if this one is Saturday {f(2)} | if this one is Tue-Thu {f(3)}")
# branch tables for launches 3 and 4 by number of earlier top-5 finishes
print('\n== launch 3 and 4 by earlier results (Saturday / Tue-Thu P(top5))')
for n in (2,3):
    for t in range(n+1):
        hs=[h for h in memo if len(h)==n and sum(i<2 for i in h)==t]
        print(f" launch {n+1}, {t} of {n} earlier in top 5: Saturday {np.mean([dist(h,SAT,False)[:2].sum() for h in hs])*100:.1f}, Tue-Thu {np.mean([dist(h,WK,False)[:2].sum() for h in hs])*100:.1f} (unweighted over {len(hs)} histories; range Sat {min(dist(h,SAT,False)[:2].sum() for h in hs)*100:.1f}-{max(dist(h,SAT,False)[:2].sum() for h in hs)*100:.1f})")
print('\n== every launch posted by an active hunter (median record), row A otherwise')
o=score(dict(SET,**HUNT)); 
for nm,m in (('Saturday',o.dow==5),('Tue-Thu',o.dow.isin([1,2,3])),('all days',o.dow>=0)):
    p=o[m].p5.mean(); print(f" {nm}: P(top5) {p*100:.1f}, top10 {o[m].p10.mean()*100:.1f}; cumulative over 4 launches {' / '.join(f'{(1-(1-p)**k)*100:.0f}' for k in (1,2,3,4))}")
o=score(dict(SET,ph_n_makers=3)); print(' row C (3 makers with reach) Saturday top5 %.1f, Tue-Thu %.1f'%(o[o.dow==5].p5.mean()*100,o[o.dow.isin([1,2,3])].p5.mean()*100))
