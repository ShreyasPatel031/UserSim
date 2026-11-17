import os,sys,json
sys.path[:0]=['/home/agent/w/arm2_live','/home/agent/w/experiments/ph_predict']
import numpy as np, pandas as pd, lightgbm as lgb
import model as M
from h25_live import P_, P_DET
df=pd.read_pickle('/tmp/cf/df.pkl'); cc=json.load(open('/tmp/cf/cc.json'))
T0='2026-09-21'
tr=df[df.day<T0]; te=df[df.day>=T0]
tr,te=M.add_fold_feats(tr,te)
tr=tr.sort_values(['day','id'],kind='stable'); te=te.sort_values(['day','id'],kind='stable')
P=dict(P_,**P_DET); P['n_jobs']=3
mods=[lgb.LGBMRegressor(random_state=s,verbose=-1,**P).fit(tr[cc],tr.logv) for s in range(5)]
pr=lambda X: np.mean([m.predict(X[cc]) for m in mods],axis=0)
te=te.copy(); te['pred']=pr(te)
te['prank']=te.groupby('day').pred.rank(ascending=False,method='first')
te['arank']=te.dailyRank
# calibration: P(actual top k | predicted rank bucket)
def bkt(r): return int(r) if r<=10 else (11 if r<=15 else (16 if r<=25 else 26))
te['b']=te.prank.map(bkt)
cal={k:te.groupby('b').arank.apply(lambda s:(s<=k).mean()).to_dict() for k in (3,5,10)}
print('model on these days: top3 hit',round(te[te.prank<=3].arank.le(3).mean()*100,1),'days',te.day.nunique())
print('calibration',json.dumps({k:{b:round(v,2) for b,v in d.items()} for k,d in cal.items()}))
hh=te[te.hist_hunter_n>0]
q=lambda c,p: float(hh[c].quantile(p))
AI=te[(te.topic_is_ai==1)&(te.topic_is_dev==0)]; AIDEV=te[(te.topic_is_ai==1)&(te.topic_is_dev==1)]; NONAI=te[te.topic_is_ai==0]
def topic(sub): return dict(topic_prior_max=float(sub.topic_prior_max.median()),topic_prior_mean=float(sub.topic_prior_mean.median()),
  topic_is_ai=float(sub.topic_is_ai.median()),topic_is_dev=float(sub.topic_is_dev.median()))
BASE=dict(ph_n_makers=1,ph_hunter_age_d=60,ph_n_media=6,ph_has_video=1,ph_n_topics=3,ph_desc_len=350,ph_tagline_len=50,ph_name_len=12,
  x_company_has_x=0,busy_same_day=1,busy_7d=0,promo_posts=0,promo_posts_launch=0,promo_posts_li=0,promo_posts_x=0,promo_posts_founder=0,
  promo_cov=0,promo_cov_press=0,promo_cov_hn=0,promo_cov_reddit=0,hist_hunter_n=0,hist_hunter_rel=np.nan,hist_hunter_top5=np.nan,
  ph_hunter_n_same_day=1,llm_pitch=55,llm_brand=0,txt_ridge=float(te.txt_ridge.median()),
  comp_nn_mean=float(te.comp_nn_mean.median()),comp_nn_max=float(te.comp_nn_max.median()),comp_nn_sim=float(te.comp_nn_sim.median()),**topic(AI))
HUNT={'self, new account (0 launches)':dict(hist_hunter_n=0,hist_hunter_rel=np.nan,hist_hunter_top5=np.nan,ph_hunter_age_d=60),
 'self, 3-yr-old account (0 launches)':dict(hist_hunter_n=0,hist_hunter_rel=np.nan,hist_hunter_top5=np.nan,ph_hunter_age_d=1100),
 'active hunter, median record':dict(hist_hunter_n=q('hist_hunter_n',.5),hist_hunter_rel=q('hist_hunter_rel',.5),hist_hunter_top5=q('hist_hunter_top5',.5),ph_hunter_age_d=q('ph_hunter_age_d',.5)),
 'active hunter, top-10% record':dict(hist_hunter_n=q('hist_hunter_n',.9),hist_hunter_rel=q('hist_hunter_rel',.9),hist_hunter_top5=q('hist_hunter_top5',.9),ph_hunter_age_d=q('ph_hunter_age_d',.9))}
print('hunter profiles',json.dumps({k:{a:round(b,3) for a,b in v.items()} for k,v in HUNT.items()}))
def drank(day_rows,col,v):
    s=day_rows[col].dropna()
    return np.nan if (pd.isna(v) or len(s)==0) else ((s<v).sum()+0.5*(s==v).sum()+0.5)/(len(s)+1)
def score(cfg):
    out=[]
    for d,g in te.groupby('day'):
        r={c:g[c].iloc[0] for c in ('ph_weekday','ph_day_n_launches')}; r.update(BASE); r.update(cfg)
        r['ph_dayrank_ph_hunter_age_d']=drank(g,'ph_hunter_age_d',r['ph_hunter_age_d'])
        r['ph_dayrank_ph_n_makers']=drank(g,'ph_n_makers',r['ph_n_makers'])
        r['ph_dayrank_ph_n_media']=drank(g,'ph_n_media',r['ph_n_media'])
        r['hist_dayrank_hist_hunter_rel']=drank(g,'hist_hunter_rel',r['hist_hunter_rel'])
        X=pd.DataFrame([r])[cc].astype(float); p=pr(X)[0]
        rk=1+int((g.pred>p).sum()); b=bkt(rk)
        out.append(dict(day=d,wd=int(r['ph_weekday']),n=len(g),rank=rk,pred=p,**{f'p{k}':cal[k].get(b,0) for k in (3,5,10)}))
    return pd.DataFrame(out)
rng=np.random.default_rng(0)
def summ(o):
    bs=[o.sample(len(o),replace=True,random_state=int(rng.integers(1e9))).p5.mean() for _ in range(300)]
    return dict(med_rank=float(o['rank'].median()),p3=round(o.p3.mean()*100,1),p5=round(o.p5.mean()*100,1),p10=round(o.p10.mean()*100,1),
      p5_lo=round(np.percentile(bs,2.5)*100,1),p5_hi=round(np.percentile(bs,97.5)*100,1),share_pred_top5=round((o['rank']<=5).mean()*100,1))
R={}
def run(name,cfg):
    o=score(cfg); R[name]=summ(o); R[name]['_o']=o; print(name,json.dumps({k:v for k,v in R[name].items() if k!='_o'}),flush=True); return o
run('BASE: self-hunted new maker, team 1, 6 media+video, median pitch, no posts, AI topic',{})
for k,v in HUNT.items(): run('hunter: '+k,v)
for n in (3,5): run(f'team {n}',dict(ph_n_makers=n))
for n,vid in ((3,0),(6,0),(9,1)): run(f'media {n}, video {vid}',dict(ph_n_media=n,ph_has_video=vid))
for p in (40,75,85): run(f'pitch score {p}',dict(llm_pitch=p))
run('txt model 90th pct',dict(txt_ridge=float(te.txt_ridge.quantile(.9))))
run('company X account',dict(x_company_has_x=1))
run('founder posts launch day (3 posts, X)',dict(promo_posts=3,promo_posts_launch=2,promo_posts_founder=3,promo_posts_x=2))
run('founder posts + organic coverage (press 1, HN 1, reddit 1)',dict(promo_posts=3,promo_posts_launch=2,promo_posts_founder=3,promo_posts_x=2,promo_cov=3,promo_cov_press=1,promo_cov_hn=1,promo_cov_reddit=1))
run('topic AI+dev',topic(AIDEV)); run('topic non-AI',topic(NONAI))
# weekday table for BASE and BEST-first
best1=dict(ph_n_makers=3,ph_hunter_age_d=1100,ph_n_media=9,ph_has_video=1,llm_pitch=75,x_company_has_x=1,promo_posts=3,promo_posts_launch=2,promo_posts_founder=3,promo_posts_x=2,promo_cov=3,promo_cov_press=1,promo_cov_hn=1,promo_cov_reddit=1)
ob=run('FIRST LAUNCH, best self-controlled (self-hunt, team 3, 9 media+video, pitch 75, company X, founder posts+coverage)',best1)
oh=run('FIRST LAUNCH, best + top-10% hunter',dict(best1,**HUNT['active hunter, top-10% record']))
# trajectory: maker becomes own hunter with record from previous launches
prev=[]
for i in range(1,5):
    if prev: rel=float(np.mean(prev)); n=i-1; top5=float(np.mean([x<=5 for x in prevr]))
    o=run(f'LAUNCH {i}: self-hunted, record of {i-1} prior launches',dict(best1,**({} if i==1 else dict(hist_hunter_n=n,hist_hunter_rel=rel,hist_hunter_top5=top5))))
    # realized rel ~ predicted logv minus day mean of preds
    m=te.groupby('day').pred.mean(); prev.append(float((o.set_index('day').pred-m).median()))
    prevr=list(o['rank']) if i==1 else prevr+list(o['rank'])
wd={}
for nm,o in (('base',R[list(R)[0]]['_o']),('best_first',ob)):
    wd[nm]=o.groupby('wd').agg(days=('day','size'),med_rank=('rank','median'),p5=('p5','mean'),p10=('p10','mean'),n=('n','mean')).round(3).to_dict('index')
print('WEEKDAY',json.dumps(wd))
json.dump({'cal':cal,'res':{k:{a:b for a,b in v.items() if a!='_o'} for k,v in R.items()},'weekday':wd,'hunters':HUNT},open('/tmp/cf/res.json','w'),default=float,indent=1)
