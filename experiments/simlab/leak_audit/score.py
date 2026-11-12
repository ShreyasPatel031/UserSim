import pandas as pd, numpy as np, sys
A=pd.read_parquet(sys.argv[1]); V=[c for c in A.columns if c not in ('id','day','dailyRank')]
rng=np.random.default_rng(0); per={}
for v in V:
    rows=[]
    for d,g in A.groupby('day'):
        if g.dailyRank.min()!=1: continue
        o=g.sort_values(v,ascending=False); r={'day':d}
        for k in (3,5,10):
            if (g.dailyRank<=k).sum()==k: r[f'top{k}']=len(set(o.id[:k])&set(g.id[g.dailyRank<=k]))/k
        r['p1']=float(o.dailyRank.iloc[0]<=3); r['p2']=float(o.dailyRank.iloc[1]<=3); r['p3']=float(o.dailyRank.iloc[2]<=3); r['win']=float(o.dailyRank.iloc[0]==1)
        rows.append(r)
    per[v]=pd.DataFrame(rows).set_index('day')
def ci(x):
    x=np.asarray(x,float); x=x[~np.isnan(x)]; bs=[x[rng.integers(0,len(x),len(x))].mean() for _ in range(2000)]
    return f"{100*x.mean():.1f} [{100*np.percentile(bs,2.5):.1f},{100*np.percentile(bs,97.5):.1f}]"
for v in V:
    P=per[v]; print(f"{v:28s}", {c: f"{100*P[c].mean():.1f}" for c in ['top3','top5','top10','p1','p2','p3']}, 'win', ci(P.win), '| d win vs honest', ci((P.win-per['honest'].win).values), 'd top3', ci((P.top3-per['honest'].top3).values))
