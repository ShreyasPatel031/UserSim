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
rng=np.random.default_rng(0)
def ci(o,c='p5'):
    bs=[o[c].sample(len(o),replace=True,random_state=int(rng.integers(1e9))).mean() for _ in range(400)]
    return f"{o[c].mean()*100:.1f} [{np.percentile(bs,2.5)*100:.1f}, {np.percentile(bs,97.5)*100:.1f}]"
def show(name,o): print(f"{name} | med rank {o['rank'].median():.1f} | top5 {ci(o)} | top10 {ci(o,'p10')} | top3 {o.p3.mean()*100:.1f}",flush=True)
SET=dict(ph_n_media=9,ph_has_video=1,llm_pitch=86,promo_posts=3,promo_posts_launch=2,promo_posts_founder=3,promo_posts_x=2)   # settable: self-hunt, alone, media, pitch, founder posts
COV=dict(promo_cov=3,promo_cov_press=1,promo_cov_hn=1,promo_cov_reddit=1)
print('\n== 1.3 split of the stacked row (all days) and Saturday only')
rows={'A settable only (self-hunt, 1 maker, 9 media+video, pitch 86, founder posts)':SET,'B = A + organic coverage':dict(SET,**COV),
 'C = A + team of 3':dict(SET,ph_n_makers=3),'D = A + coverage + team 3 + company X (old stacked row)':dict(SET,**COV,ph_n_makers=3,x_company_has_x=1,ph_hunter_age_d=1100)}
O={}
for k,v in rows.items():
    O[k]=score(v); show(k,O[k]); show('   Saturday only',O[k][O[k].dow==5]); show('   Tue-Thu only',O[k][O[k].dow.isin([1,2,3])])
print('\n== 1.4 day of week, settable-only launch (A), with intervals (8 days each)')
for d in range(7): g=O[list(rows)[0]]; show(f'dow {d} (0=Mon) n_launches {g[g.dow==d].n.mean():.0f}',g[g.dow==d])
print('same line-ups, weekday input forced (isolates the model weekday input):')
for wd in sorted(te.ph_weekday.unique()): show(f'  forced ph_weekday={wd}',score(SET,force_wd=wd))
day=te.groupby('day').agg(dow=('dow','first'),n=('id','size'),strong_hunters=('hist_hunter_top5',lambda s:(s>=0.5).sum()),pred5=('pred',lambda s:s.nlargest(5).iloc[-1]),pitch75=('llm_pitch',lambda s:(s>=75).sum()),team3=('ph_n_makers',lambda s:(s>=3).sum()))
v=te.assign(votes=np.exp(te.logv))
day['votes_rank5']=v[v.arank==5].groupby('day').votes.first(); day['votes_rank1']=v[v.arank==1].groupby('day').votes.first(); day['votes_all']=v.groupby('day').votes.sum()
print('line-up by dow:'); print(day.groupby('dow').mean().round(2).to_string())
print('\n== 1.1 branches for launch 2 (settable-only A, launch 1 on a Saturday; launch 2 scored on Saturday and on all days)')
o1=O[list(rows)[0]]; s1=o1[o1.dow==5]
w={i:float(s1[f'a{i}'].mean()) for i in range(5)}; print('launch 1 (Saturday) actual-rank distribution',{str(AB[i]):round(x,3) for i,x in w.items()})
exp={'sat':0,'all':0}
for i in range(5):
    o2=score(dict(SET,hist_hunter_n=1,hist_hunter_rel=relb[i],hist_hunter_top5=1.0 if i<2 else 0.0))
    sat=o2[o2.dow==5]; exp['sat']+=w[i]*sat.p5.mean(); exp['all']+=w[i]*o2.p5.mean()
    print(f'  launch 1 finished {AB[i]} (prob {w[i]*100:.0f}%): launch 2 Saturday top5 {ci(sat)}, any day top5 {ci(o2)}, med rank sat {sat["rank"].median():.1f}')
print('  EXPECTED launch 2 P(top 5): Saturday %.1f, any day %.1f' % (exp['sat']*100,exp['all']*100))
print('\n== 1.2 real hunters with 1-3 prior hunts (2026 rows, full data; left-censored: history starts Jan 2025)')
D=df[df.day>='2026-01-01'].copy(); D['top5']=D.dailyRank<=5; D['top10']=D.dailyRank<=10
D['nb']=pd.cut(D.hist_hunter_n,[-1,0,1,3,10,50,1e9],labels=['0','1','2-3','4-10','11-50','51+'])
print(D.groupby('nb').agg(n=('id','size'),top5=('top5','mean'),top10=('top10','mean')).round(3).to_string())
S_=D[D.hist_hunter_n.between(1,3)].copy(); S_['prior']=np.where(S_.hist_hunter_top5>=0.99,'all prior top5',np.where(S_.hist_hunter_top5<=0.01,'no prior top5','mixed'))
print(S_.groupby('prior').agg(n=('id','size'),top5=('top5','mean'),top10=('top10','mean'),age_med=('ph_hunter_age_d','median')).round(3).to_string())
Y=S_[S_.ph_hunter_age_d<=730]; print('same, hunter account <= 2 yrs old (likely true newcomers):'); print(Y.groupby('prior').agg(n=('id','size'),top5=('top5','mean'),top10=('top10','mean')).round(3).to_string())
tt=te[te.hist_hunter_n.between(1,3)].assign(prior=lambda x:np.where(x.hist_hunter_top5>=0.99,'all prior top5','other'))
print('test days, model vs actual for 1-3 prior hunts:'); print(tt.groupby('prior').apply(lambda g:pd.Series(dict(n=len(g),actual_top5=(g.arank<=5).mean(),model_top5=g.b.map(cal[5]).mean()))).round(3).to_string())
print('\n== 3 real launches that look like the plan (2026 rows with promo data)')
Z=D[(D.hist_hunter_n==0)&D.promo_posts.notna()]
for nm,m in (('0-record hunter, all',Z.index==Z.index),('+ pitch>=75',Z.llm_pitch>=75),('+ pitch>=75, 1 maker, founder posts>=1, no coverage',(Z.llm_pitch>=75)&(Z.ph_n_makers<=1)&(Z.promo_posts_founder>=1)&(Z.promo_cov==0)),
   ('+ pitch>=75, founder posts>=1, coverage>=3',(Z.llm_pitch>=75)&(Z.promo_posts_founder>=1)&(Z.promo_cov>=3)),('+ pitch>=75, makers>=3, founder posts>=1, coverage>=3',(Z.llm_pitch>=75)&(Z.ph_n_makers>=3)&(Z.promo_posts_founder>=1)&(Z.promo_cov>=3))):
    g=Z[m]; print(f'  {nm}: n {len(g)}, actual top5 {g.top5.mean()*100:.1f}%, top10 {g.top10.mean()*100:.1f}%, weekend n {int(pd.to_datetime(g.day).dt.dayofweek.ge(5).sum())} top5 {g[pd.to_datetime(g.day).dt.dayofweek>=5].top5.mean()*100:.1f}%')
z0=te[te.hist_hunter_n==0]; print('  calibration on real 0-record launches, test days: n',len(z0),'actual top5 %.1f%%'%((z0.arank<=5).mean()*100),'model %.1f%%'%(z0.b.map(cal[5]).mean()*100))
