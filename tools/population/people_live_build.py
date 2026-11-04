import json,gzip,hashlib,glob,os,collections,datetime
salt=open('salt').read().strip()
pid=lambda u:"p_"+hashlib.sha256((salt+"producthunt:"+u.lower().lstrip('@')).encode()).hexdigest()[:16]
assert pid('example_user')=='p_97eb5d57c445ef1f'
rows={}  # key person_id
def R(p): return rows.setdefault(p,{"person_id":p,"ph_user_id":None,"handle":None,"tier":None,"tabs":{}})
for l in open('uidmap.jsonl'):
  d=json.loads(l); r=R(pid(d['username'])); r['handle']=d['username']; r['ph_user_id']=d['user_id']
FAM={"profile":"about","upvotes":"upvotes","comments":"activity","follows":"following","launches_made":"hunted"}
for l in gzip.open('master.gz','rt'):
  d=json.loads(l); r=R(d['person_id']); r['tier']=d.get('tier')
  for f,t in FAM.items():
    v=d['families'].get(f) or {}
    if v.get('have'):
      r['tabs'][t]={"n":v['n'],"header":None,"last_pulled_at":v['last_fetched_at'],"newest_item_ts":v['newest_item'],"status":v['status'],"source":"master:"+",".join(v.get('sources',{}))}
  r['_x']=bool((d['families'].get('x_profile') or {}).get('have'))
# prof2 header counts
HM={"followers":"followers","followings":"following","hunted":"hunted","collections":"collections","reviews_count":"reviews","stacks_count":"stacks","upvotes_total":"upvotes","products_made":"products"}
for l in gzip.open('p2.gz','rt'):
  d=json.loads(l)
  if d.get('status')!=200 or not d.get('username'): continue
  r=R(pid(d['username'])); r['handle']=r['handle'] or d['username']; r['ph_user_id']=r['ph_user_id'] or d.get('user_id')
  for k,t in HM.items():
    if d.get(k) is None: continue
    e=r['tabs'].setdefault(t,{"n":0,"header":None,"last_pulled_at":None,"newest_item_ts":None,"status":"header_only","source":"ph_profiles2_refetch"})
    e['header']=d[k]
  r.setdefault('_hdr_at',d['fetched_at'])
def ts(items):
  v=[i.get('datetime') or i.get('date') for i in items if isinstance(i,dict)]
  v=[x for x in v if x and x[:2]=='20' and '-' in x]; return max(v) if v else None
live=[]
for f in glob.glob('*.json')+glob.glob('boxbrowser/*/*_full.json'):
  d=json.load(open(f))
  if not isinstance(d,dict) or 'upvotes' not in d: continue
  h=os.path.basename(f).replace('_full.json','').replace('.json','')
  at=(d.get('run') or {}).get('finished_utc') or datetime.datetime.utcfromtimestamp(os.path.getmtime(f)).isoformat()+'Z'
  src='people_live/'+('boxbrowser' if 'boxbrowser' in f else 'vm'); live.append(h)
  r=R(pid(h)); r['handle']=h; r['ph_user_id']=r['ph_user_id'] or d.get('ph_user_id') or d.get('user_id')
  for t in ["about","forums","activity","upvotes","hunted","collections","stacks","reviews","followers","following"]:
    v=d.get(t)
    if not isinstance(v,dict): continue
    it=v.get('items') or []
    n=v.get('count',len(it)) if t!='about' else 1; hd=v.get('header')
    # complete = no header shown, or >= 98% of it (de-listed/duplicate items); reviews' header includes unlisted rating-only reviews
    comp=hd is None or t=='reviews' or n>=0.98*hd
    r['tabs'][t]={"n":n,"header":hd,"last_pulled_at":v.get('fetched_at') or at,"fetched_at_estimated":bool(v.get('fetched_at_estimated') or (d.get('run') or {}).get('finished_utc_estimated') or not (v.get('fetched_at') or (d.get('run') or {}).get('finished_utc'))),"newest_item_ts":ts(it),"status":"complete" if comp else "truncated","source":src}
for f in glob.glob('full/*.json'):
  d=json.load(open(f)); r=R(pid(d['username'])); r['handle']=d['username']; r['ph_user_id']=d['ph_user_id']
  for k,v in d['tabs'].items():
    t=k.strip('/'); t='about' if t=='profile' else t
    if t in r['tabs'] and r['tabs'][t]['source'].startswith('people_live'): continue
    r['tabs'][t]={"n":v.get('count',v.get('n')),"header":v.get('header'),"last_pulled_at":v.get('fetched_at'),"newest_item_ts":None,"status":"partial","source":"people_live/full"}
ALL=["about","forums","activity","upvotes","hunted","collections","stacks","reviews","followers","following"]
need=[l.split('\t')[2] for l in open('need.txt') if not l.startswith('#') and l.count('\t')>=2]
needrank={p:i for i,p in enumerate(need) if p.startswith('p_')}
out=open('have_index.jsonl','w'); nl=[]
pre=collections.Counter(); full_items_pre=0
for p,r in rows.items():
  x=r.pop('_x',False); r.pop('_hdr_at',None)
  if r['tier'] is None: r['tier']='non-pool'   # rows outside the pool (known-id makers etc.)
  u=r['tabs'].get('upvotes')
  if u is not None and 'newest_item_ts' in u: u['newest_item_launch_ts']=u.pop('newest_item_ts')
  items=[t for t,e in r['tabs'].items() if e['n']]
  r['tabs_with_items']=sorted(items); r['missing_item_tabs']=[t for t in ALL if t not in items]
  for t,e in r['tabs'].items():
    if not e['source'].startswith('people_live') and (e['n'] or e['header'] is not None): pre[t+(':items' if e['n'] else ':header_only')]+=1
  out.write(json.dumps(r)+"\n")
  rec=(r['tabs'].get('upvotes') or {}).get('newest_item_launch_ts') or ''
  likely=r['tier']=='likely' or p in needrank
  score=(0 if likely else 1, needrank.get(p,10**6), -int(rec[:10].replace('-','')) if rec else 0)
  if r['missing_item_tabs'] and (likely or rec>='2026-10-01'):
    nl.append((score,{"person_id":p,"ph_user_id":r['ph_user_id'],"handle":r['handle'],"tier":'likely' if likely else r['tier'],"missing_tabs":r['missing_item_tabs'],"newest_upvote_launch":rec or None,"reason":("in master need list/likely voter" if likely else "recent upvote activity (launch>=2026-10-01)")+f"; {len(r['missing_item_tabs'])} tabs lack items"}))
nl.sort(key=lambda z:z[0])
with open('need_list.jsonl','w') as f:
  for i,(s,d) in enumerate(nl): d['rank']=i+1; f.write(json.dumps(d)+"\n")
print(len(rows),len(nl),len(live)+len(glob.glob('full/*.json')))
print(sorted(pre.items())); print(collections.Counter(r['tier'] for r in rows.values()))

# self-checks (population agent): a rebuild must not undo the Nov 4 fixes
H=[json.loads(l) for l in open('have_index.jsonl')]; N=[json.loads(l) for l in open('need_list.jsonl')]
assert all(r['tier'] is not None for r in H), 'untiered have_index row'
assert not any('newest_item_ts' in (r['tabs'].get('upvotes') or {}) for r in H), 'upvotes newest_item_ts not renamed'
assert len({r['person_id'] for r in H})==len(H), 'duplicate person_id'
lk=[r['rank'] for r in N if r['tier']=='likely']
assert lk==list(range(1,len(lk)+1)), 'likely voters are not ranks 1..k'
assert [r['rank'] for r in N]==list(range(1,len(N)+1)), 'ranks not contiguous'
assert all(r['tier'] is not None for r in N), 'untiered need_list row'
print('self-checks OK: likely ranks 1..%d, %d have rows, %d need rows' % (len(lk), len(H), len(N)))
