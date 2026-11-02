# hn-agent copy of Grok Bot's wb25.py for Jul-Dec 2025 (split agreed via the orchestrator 2026-11-02); parse() unchanged.
# Wayback /newest 2025 fetcher (same parse as raw/hn_early_votes/work/fetch.py). Resumable, month-ordered, 2 threads.
import socket;socket.setdefaulttimeout(60)
import gzip,re,json,time,sys,os,urllib.request,urllib.parse,subprocess,datetime as dt,threading
from concurrent.futures import ThreadPoolExecutor
GS='gs://usersim-bakeoff-347838016394/usersim_sim/raw/hn_early_votes_2025/hn_agent_h2/'   # hn-agent's half: Jul-Dec 2025
MONTHS=[f'2025{m:02d}' for m in range(7,13)]
def log(*a): print(dt.datetime.utcnow().strftime('%H:%M:%SZ'),*a,flush=True)
def up(f,dst=None): subprocess.run(['gsutil','-q','cp',f,GS+(dst or f)])
# 1. CDX lists per month (status 200, collapse per minute)
for mo in MONTHS:
  f=f'cdx/cdx_newest_{mo}.txt'; os.makedirs('cdx',exist_ok=True)
  if os.path.exists(f): continue
  for a in range(6):
    try:
      q=urllib.parse.urlencode({'url':'news.ycombinator.com/newest','from':mo,'to':mo,'fl':'timestamp,original,digest','filter':'statuscode:200','collapse':'timestamp:12'})
      t=urllib.request.urlopen('https://web.archive.org/cdx/search/cdx?'+q,timeout=180).read().decode()
      break
    except Exception as e: log('cdx err',mo,e); time.sleep(30*(a+1))
  else: sys.exit('cdx failed '+mo)
  open(f+'.tmp','w').write(t); os.rename(f+'.tmp',f); log('cdx',mo,len(t.splitlines())); time.sleep(3)
with open('cdx_newest.txt','w') as fo:
  for mo in MONTHS: fo.write(open(f'cdx/cdx_newest_{mo}.txt').read())
up('cdx_newest.txt','work/cdx_newest_h2.txt')
# 2. fetch
out='snapshots.jsonl'; done=set()
if os.path.exists(out):
  for l in open(out):
    try: d=json.loads(l); done.add((d['page'],d['capture_ts']))
    except: pass
fo=open(out,'a'); n=0; lk=threading.Lock()
def parse(html,ts,page):
  cap=dt.datetime.strptime(ts,'%Y%m%d%H%M%S').replace(tzinfo=dt.timezone.utc)
  rows=[]
  for m in re.finditer(r"<tr class=['\"]athing[^>]*id=['\"](\d+)['\"]>(.*?)</tr>\s*<tr>(.*?)</tr>",html,re.S):
    iid,top,sub=m.groups()
    rk=re.search(r'class="rank">(\d+)\.',top)
    sc=re.search(r'id="score_\d+">(\d+) point',sub)
    age=re.search(r'class="age" title="([^"]+)"',sub)
    cm=re.search(r'>(\d+)&nbsp;comment',sub)
    created=None;agem=None
    if age:
      t=age.group(1).split()[0]
      try:
        c=dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc);created=c.isoformat();agem=round((cap-c).total_seconds()/60,1)
      except: pass
    rows.append(dict(item_id=int(iid),page=page,capture_ts=ts,rank=int(rk.group(1)) if rk else None,score=int(sc.group(1)) if sc else None,comments=int(cm.group(1)) if cm else (0 if sub and 'discuss' in sub else None),created_at=created,age_min=agem))
  return rows
def job(page,ts,orig):
    global n
    html=None
    for a in range(4):
      try:
        b=urllib.request.urlopen(f'https://web.archive.org/web/{ts}id_/{orig}',timeout=60).read()
        if b[:2]==b'\x1f\x8b': b=gzip.decompress(b)
        html=b.decode('utf8','replace');break
      except Exception as e:
        if '429' in str(e): log('429, sleep 300'); time.sleep(300)
        else: time.sleep(10*(a+1))
    rows=parse(html,ts,page) if html else []
    with lk:
      fo.write(json.dumps(dict(page=page,capture_ts=ts,ok=html is not None,items=rows))+'\n');fo.flush();n+=1
      if n%500==0: log('fetched',n)
    time.sleep(1.5)
for mo in MONTHS:
  tasks=[('newest',*l.split()[:2]) for l in open(f'cdx/cdx_newest_{mo}.txt') if l.strip() and ('newest',l.split()[0]) not in done]
  if tasks:
    log('month',mo,'todo',len(tasks))
    with ThreadPoolExecutor(2) as ex: list(ex.map(lambda t:job(*t),tasks))
  # month done -> analyze + upload partial
  # flat rows (same columns as raw/hn_early_votes/early_snapshots.jsonl)
  with open('early_snapshots.jsonl','w') as ff:
    for l in open(out):
      try: d=json.loads(l)
      except: continue
      for r in d.get('items') or []: ff.write(json.dumps(r)+'\n')
  up('snapshots.jsonl','work/snapshots.jsonl'); up('early_snapshots.jsonl')
  open('months_done.txt','a').write(mo+'\n'); log('month done',mo)
print('DONE',flush=True)
