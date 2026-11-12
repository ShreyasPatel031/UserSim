import pandas as pd,json,random
P=pd.read_parquet('v2/persons.parquet');H=pd.read_parquet('v2/handles.parquet');Pr=pd.read_parquet('v2/profiles.parquet');E=pd.read_parquet('v2/events.parquet')
v1=pd.read_parquet('t/people.parquet');N=len(P)
def cov(mask_people): return f"{len(mask_people)} ({len(mask_people)/N:.0%})"
out={}
out['v1']=dict(x_handle=int(v1.twitter.notna().sum()),x_bio=int(v1.x_bio.fillna('').ne('').sum()),linkedin=int(v1.li_headline.fillna('').ne('').sum()),github=0,website=0,ph_name='not stored')
hi=H[H.confidence>=0.8]
out['v2']=dict(x_handle=hi[hi.platform=='x'].person_id.nunique(),x_profile=Pr[Pr.platform=='x'].person_id.nunique(),
  linkedin_identity=hi[hi.platform=='linkedin'].person_id.nunique(),linkedin_low_conf_search=H[(H.platform=='linkedin')&(H.confidence<0.8)].person_id.nunique(),
  linkedin_profile_rows=Pr[Pr.platform=='linkedin'].person_id.nunique(),github=hi[hi.platform=='github'].person_id.nunique(),website=H[H.platform=='website'].person_id.nunique(),
  other_links=H[~H.platform.isin(['x','linkedin','github','website','producthunt'])].person_id.nunique(),display_name=int(P.display_name.notna().sum()),
  ph_extended_fields=int(Pr[(Pr.platform=='producthunt')].extra.str.contains('"products_made": [0-9]').sum()),
  x_posts_events=int((E.platform=='x').sum()),ph_events=int((E.platform=='producthunt').sum()),x_people_with_posts=E[E.platform=='x'].person_id.nunique(),
  x_conflicts_demoted=int((H.source=='ph_twitter_field')[H.confidence<0.5].sum()))
li=Pr[Pr.platform=='linkedin']
wispr=li.extra.fillna('').str.contains('Wispr').sum()
out['linkedin_mentioning_wispr_v2']=int(wispr)
# checks
def check(u):
    pid='ph:'+u; h=H[H.person_id==pid]; issues=[]
    x=h[(h.platform=='x')&(h.confidence>=0.8)].handle.tolist()
    if len(set(x))>1: issues.append(f'multiple X {x}')
    p=P[P.person_id==pid].iloc[0]
    if p.display_name in ('Wispr Flow','Lovable'): issues.append('poisoned name')
    l=Pr[(Pr.person_id==pid)&(Pr.platform=='linkedin')]
    if len(l) and 'Wispr Flow' in (l.extra.iloc[0] or '') and 'wispr' not in json.dumps(Pr[(Pr.person_id==pid)&(Pr.platform=='producthunt')].extra.iloc[0]).lower(): issues.append('wispr li')
    xp=Pr[(Pr.person_id==pid)&(Pr.platform=='x')]
    if len(xp) and x and xp.handle.iloc[0] not in x: issues.append('x profile not from accepted handle')
    return dict(person=u,name=p.display_name,x=x,linkedin=h[(h.platform=='linkedin')].assign(s=lambda d:d.handle+'@'+d.confidence.astype(str)).s.tolist(),
                github=h[h.platform=='github'].handle.tolist(),website=h[h.platform=='website'].url.tolist()[:3],x_profile=bool(len(xp)),issues=issues)
sample=json.load(open('reconcile_sample.json'))
ph_s=[s['person'] for s in sample if s['platform_seed']=='producthunt']+['rrhoover','chrismessina']
random.seed(7);rnd=random.sample(P.ph_username.tolist(),50)
out['sample']=[check(u) for u in ph_s]
r=[check(u) for u in rnd];out['random50_issues']=sum(bool(x['issues']) for x in r);out['random50']=r
out['hn_sample_note']='5 HN sample people are not in PH persons; v2 does not yet include HN (unchanged tables/hn_people).'
json.dump(out,open('v2/validation.json','w'),indent=1,default=str)
print(json.dumps({k:v for k,v in out.items() if k!='random50'},indent=1,default=str)[:6000])
