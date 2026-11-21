import json,gzip,glob,re,difflib,datetime as dt,collections
import pandas as pd
from urllib.parse import urlparse, unquote
R='raw/'; NOW=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'); POISON_ID='606339'; POISON_NAMES={'Wispr Flow','Lovable'}
def jl(fn):
    op=gzip.open if fn.endswith('.gz') else open
    for l in op(fn,'rt'):
        try: yield json.loads(l)
        except ValueError: pass
def slug(url,plat):
    if not url: return None
    try: p=urlparse(url if '://' in url else 'https://'+url)
    except Exception: return None
    parts=[x for x in unquote(p.path).split('/') if x]
    h=p.netloc.lower()
    if plat=='x':
        if not any(d in h for d in('twitter.com','x.com')) or not parts: return None
        s=parts[0].lstrip('@').lower()
        return s if re.fullmatch(r'[a-z0-9_]{1,15}',s) and s not in('intent','share','home','i','search','hashtag') else None
    if plat=='linkedin':
        if 'linkedin.com' not in h or len(parts)<2 or parts[0] not in('in','pub'): return None
        return parts[1].lower()
    if plat=='github':
        if 'github.com' not in h or not parts: return None
        return parts[0].lower()
    return None
def norm(s): return ' '.join(re.findall(r'[a-z]+',(s or '').lower()))
def namesim(a,b):
    a,b=norm(a),norm(b)
    if not a or not b: return 0.0
    ta,tb=set(a.split()),set(b.split())
    tok=len(ta&tb)/max(1,min(len(ta),len(tb)))
    return round(max(difflib.SequenceMatcher(None,a,b).ratio(),tok),3)
# ---- PH raw
old={};p2={}
for fn in [R+'ph_profiles.jsonl.gz',R+'ph_profiles_rest.jsonl.gz']:
    for r in jl(fn):
        if r.get('username'): old[r['username']]=r
for r in jl(R+'ph_profiles2.jsonl.gz'): p2[r['username']]=r
tabs={r['username']:r for r in jl(R+'profile_tabs.jsonl.gz') if r.get('username')}
v1=pd.read_parquet('t/people.parquet').set_index('person')
users=sorted(set(old)|set(p2)|set(v1.index))
X={}
for r in jl(R+'x_people.jsonl.gz'):
    if r.get('handle'): X[r['handle'].lower()]=r
XP=collections.defaultdict(list)
for r in jl(R+'x_posts.jsonl.gz'):
    for p in (r.get('posts') or []):
        XP[(p.get('author') or r.get('handle') or '').lower()].append(p)
for h,r in X.items():
    for p in (r.get('posts') or []): XP[(p.get('author') or h).lower()].append(p)
LS={}
for fn in ['li/li_search.jsonl','li/li_search_retry.jsonl']:
    for r in jl(fn):
        if r.get('username'): LS[r['username']]=r
LA={}
for r in jl('li/li_apify.jsonl'):
    if r.get('u') and r.get('profile'): LA[r['u']]=r['profile']
persons=[];handles=[];profiles=[];stats=collections.Counter()
def H(pid,plat,h,url,src,conf,note=None):
    handles.append(dict(person_id=pid,platform=plat,handle=h,url=url,source=src,confidence=conf,note=note,observed_on=NOW[:10]))
for u in users:
    pid='ph:'+u; o=old.get(u,{}); g=p2.get(u); base=g or o
    poisoned=(not g) and (o.get('user_id')==POISON_ID or o.get('name') in POISON_NAMES)
    ph_name=None if poisoned else base.get('name'); ph_uid=None if poisoned else base.get('user_id')
    links=[];seen=set()
    for l in (base.get('links') or [])+(o.get('links') or []):
        k=(l.get('kind'),l.get('url'))
        if l.get('url') and k not in seen: seen.add(k); links.append(l)
    H(pid,'producthunt',u,f'https://www.producthunt.com/@{u}','ph_username',1.0)
    own={'x':set(),'linkedin':set(),'github':set()}
    for l in links:
        k=l.get('kind'); url=l['url']
        for plat in ('x','linkedin','github'):
            s=slug(url,plat)
            if s: own[plat].add(s)
        if k not in('twitter','linkedin','github'): H(pid,k,None,url,'ph_self_link',0.95)
    for plat,src in (('x','ph_self_link'),('linkedin','ph_self_link'),('github','ph_self_link')):
        for s in sorted(own[plat]):
            H(pid,plat,s,{'x':'https://x.com/','linkedin':'https://www.linkedin.com/in/','github':'https://github.com/'}[plat]+s,src,0.95)
    tw=(base.get('twitter') or (v1.loc[u,'twitter'] if u in v1.index else None)) 
    tw=tw.lower() if isinstance(tw,str) and tw else None
    if tw and tw not in own['x']:
        if own['x']: H(pid,'x',tw,'https://x.com/'+tw,'ph_twitter_field',0.2,'conflicts with self link; not used'); stats['x_field_conflict']+=1
        else: H(pid,'x',tw,'https://x.com/'+tw,'ph_twitter_field',0.8)
    x_primary=sorted(own['x'])[0] if own['x'] else (tw if tw else None)
    # X profile
    xname=None
    if x_primary and x_primary in X and X[x_primary].get('profile'):
        xp=X[x_primary]['profile']; xname=xp.get('name')
        profiles.append(dict(person_id=pid,platform='x',handle=x_primary,observed_on=NOW[:10],source='raw/x_people',
            name=xp.get('name'),bio=xp.get('description'),location=xp.get('location') or None,website=xp.get('website'),
            joined=xp.get('joined'),followers=xp.get('followers'),following=xp.get('following'),post_count=xp.get('tweets'),
            likes_count=xp.get('likes'),media_count=xp.get('media_count'),verified=bool((xp.get('verification') or {}).get('verified')),
            protected=xp.get('protected'),extra=None))
    # LinkedIn
    li_slug=None;li_conf=None;li_src=None;li_row=None
    ref=[n for n in (ph_name,xname) if n]
    ls=LS.get(u)
    if ls and ls.get('found') and ls.get('url'):
        s=slug(ls['url'],'linkedin')
        if s and s in own['linkedin']: li_slug,li_conf,li_src,li_row=s,0.95,'li_search_url_matches_self_link',ls
        else:
            sc=max([namesim(ls.get('name'),n) for n in ref]+[0])
            if sc>=0.85 and ls.get('ph_name') not in POISON_NAMES:
                li_slug,li_conf,li_src,li_row=s,round(0.6*sc,3),'li_search_name_match',ls
                H(pid,'linkedin',s,ls['url'],'li_search_name_match',round(0.6*sc,3),f'name_sim={sc}')
            else: stats['li_search_rejected']+=1
    if not li_slug and own['linkedin']: li_slug,li_conf,li_src=sorted(own['linkedin'])[0],0.95,'ph_self_link'
    la=LA.get(u)
    if la and (la.get('publicIdentifier') or '').lower() in own['linkedin']|({li_slug} if li_slug else set()):
        cp=(la.get('currentPosition') or [{}]); cp=cp[0] if cp else {}
        profiles.append(dict(person_id=pid,platform='linkedin',handle=(la.get('publicIdentifier') or '').lower(),observed_on=NOW[:10],source='raw/li_apify',
            name=' '.join(x for x in (la.get('firstName'),la.get('lastName')) if x),bio=la.get('about'),location=((la.get('location') or {}).get('linkedinText')),
            website=json.dumps(la.get('websites')),joined=la.get('registeredAt'),followers=la.get('followerCount'),following=None,post_count=None,likes_count=None,media_count=None,
            verified=la.get('verified'),protected=None,extra=json.dumps(dict(headline=la.get('headline'),company=cp.get('companyName'),connections=la.get('connectionsCount'),
            top_skills=la.get('topSkills'),experience=la.get('experience'),education=la.get('education')),default=str)))
    elif li_row:
        profiles.append(dict(person_id=pid,platform='linkedin',handle=li_slug,observed_on=NOW[:10],source=li_src,name=None if li_row.get('name') in POISON_NAMES else li_row.get('name'),bio=None,
            location=None if li_row.get('ph_name') in POISON_NAMES else li_row.get('location'),website=None,joined=None,followers=None,following=None,post_count=None,likes_count=None,media_count=None,verified=None,protected=None,
            extra=json.dumps(dict(headline=None,company=None,role=None,education=None,confidence=li_conf,text_dropped='search query used poisoned PH name') if (li_row.get('ph_name') in POISON_NAMES or ('wispr' in str(li_row.get('headline')).lower() and 'wispr' not in (str(base.get('headline'))+str(base.get('about'))).lower())) else dict(headline=li_row.get('headline'),company=li_row.get('company'),role=li_row.get('role'),education=li_row.get('education'),confidence=li_conf))))
    # PH profile
    v=v1.loc[u] if u in v1.index else None; t=tabs.get(u,{})
    def g2(k): return g.get(k) if g else None
    profiles.append(dict(person_id=pid,platform='producthunt',handle=u,observed_on=NOW[:10],source='raw/ph_profiles2' if g else 'raw/ph_profiles(+rest)',
        name=ph_name,bio=base.get('about') or (v['about'] if v is not None else None),location=None,website=None,
        joined=g2('joined') or (v['joined'] if v is not None else None),followers=base.get('followers'),following=base.get('followings'),post_count=None,likes_count=None,media_count=None,
        verified=g2('verified'),protected=None,extra=json.dumps(dict(ph_user_id=ph_uid,headline=base.get('headline'),is_maker=base.get('is_maker'),
          upvotes_total=g2('upvotes_total') if g else (None if v is None else v['upvotes_total']),products_made=g2('products_made'),hunted=g2('hunted'),collections=g2('collections'),
          reviews_count=g2('reviews_count'),stacks_count=g2('stacks_count'),visit_streak_days=g2('visit_streak_days'),community_rank_year=g2('community_rank_year'),
          current_product=g2('current_product'),badges_total=g2('badges_total'),badges=base.get('badges'),voted_recent=base.get('voted_recent'),
          stacks=t.get('stacks'),reviews=t.get('reviews'),segments=(None if v is None else v['segments'])),default=str)))
    persons.append(dict(person_id=pid,display_name=ph_name or xname,ph_username=u,ph_name_poisoned_in_v1=bool(poisoned or (u in LS and LS[u].get('ph_name') in POISON_NAMES)),
        first_seen=(None if v is None else v['first_seen']),built_at=NOW))
P=pd.DataFrame(persons);Hd=pd.DataFrame(handles).drop_duplicates(['person_id','platform','handle','url','source']);Pr=pd.DataFrame(profiles)
for c in ['followers','following','post_count','likes_count','media_count']: Pr[c]=pd.to_numeric(Pr[c],errors='coerce')
for c in ['name','bio','location','website','extra','handle']:
    Pr[c]=Pr[c].map(lambda x: x if (x is None or isinstance(x,str)) else json.dumps(x,default=str))
for c in ['verified','protected']: Pr[c]=Pr[c].astype('boolean')
for c in ['joined','first_seen']:
    if c in Pr: Pr[c]=Pr[c].astype('string')
P['first_seen']=P['first_seen'].astype('string')
# events
pidset=set(P.ph_username)
E=pd.concat([pd.read_parquet(f) for f in glob.glob('ev/*.parquet')]).drop_duplicates(['person','launch_id','date','kind'])
ev=pd.DataFrame(dict(person_id='ph:'+E.person.astype(str),platform='producthunt',event_id=None,ts=E.date.astype(str),ts_quality=E.date_quality.map({'exact':'exact','launch_day':'day'}).fillna(E.date_quality),
    kind=E.kind,target_id=E.launch_id.astype(str),text=None,metrics=None,source='tables/events'))
xh=Hd[(Hd.platform=='x')&(Hd.confidence>=0.8)][['person_id','handle']].drop_duplicates('handle')
h2p=dict(zip(xh.handle,xh.person_id)); xr=[];seenp=set()
for h,ps in XP.items():
    if h in h2p:
        for p in ps:
            if p.get('id') in seenp: continue
            seenp.add(p.get('id'))
            xr.append(dict(person_id=h2p[h],platform='x',event_id=str(p.get('id')),ts=str(p.get('created_at')),ts_quality='day',kind='post',target_id=None,text=p.get('text'),
              metrics=json.dumps({k:p.get(k) for k in('likes','reposts','replies','quotes','views','bookmarks')}),source='raw/x_posts+x_people'))
ev=pd.concat([ev,pd.DataFrame(xr)],ignore_index=True); ev['event_id']=ev['event_id'].astype('string')
for name,df in (('persons',P),('handles',Hd),('profiles',Pr),('events',ev)): df.to_parquet(f'v2/{name}.parquet',index=False); print(name,len(df))
print(dict(stats))
