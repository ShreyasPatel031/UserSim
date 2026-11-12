"""Recompute every count in claims 1-4 from the raw GCS captures.
Inputs (<GCS-BUCKET>/<PROJECT>/raw/ph_predict_data/): ph_profiles.jsonl.gz,
ph_profiles2.jsonl.gz, ph_profiles_rest.jsonl.gz, li_search.jsonl. Also tables/people (v1 people.parquet).
Run: python count_claims.py RAW_DIR PEOPLE_PARQUET"""
import json,gzip,sys,collections
import pandas as pd
RAW,PEOPLE=sys.argv[1],sys.argv[2]
def jl(fn):
    op=gzip.open if fn.endswith('.gz') else open
    for l in op(fn,'rt'):
        try: yield json.loads(l)
        except ValueError: pass
# merged view = what v1 build used: later file wins, username key (ph_profiles, ph_profiles2, ph_profiles_rest in that order)
P={}
per_file={}
for fn in ['ph_profiles.jsonl.gz','ph_profiles2.jsonl.gz','ph_profiles_rest.jsonl.gz']:
    n=bad=0
    for r in jl(f'{RAW}/{fn}'):
        n+=1; bad+=(r.get('user_id')=='606339' or r.get('name') in ('Wispr Flow','Lovable'))
        if r.get('username'): P[r['username']]=r
    per_file[fn]=dict(records=n,poisoned=bad)
out={'per_file':per_file,'merged_people':len(P)}
names=collections.Counter(r.get('name') for r in P.values())
out['claim1_name_Wispr_Flow']=names['Wispr Flow']; out['claim1_name_Lovable']=names['Lovable']
out['claim1_user_id_606339']=sum(r.get('user_id')=='606339' for r in P.values())
S=[r for r in jl(f'{RAW}/li_search.jsonl')]
out['claim2_li_searches']=len(S); out['claim2_ph_name_Wispr_Flow']=sum(r.get('ph_name')=='Wispr Flow' for r in S)
out['claim2_found_with_poisoned_name']=sum(1 for r in S if r.get('ph_name')=='Wispr Flow' and r.get('found'))
v1=pd.read_parquet(PEOPLE); has=v1[v1.li_headline.fillna('')!='']
poison={r['username'] for r in S if r.get('ph_name')=='Wispr Flow' and r.get('found')}
out['claim3_v1_people_with_li']=len(has); out['claim3_from_poisoned_query']=int(has.person.isin(poison).sum())
out['claim3_li_company_top']=v1.li_company.value_counts().head(5).to_dict()
both=mis=0
for r in P.values():
    lt=[x['url'].rstrip('/').split('/')[-1].lower() for x in r.get('links') or [] if x.get('kind')=='twitter']
    if lt and r.get('twitter'):
        both+=1; mis+=r['twitter'].lower() not in lt
out['claim4_twitter_field_and_link']=both; out['claim4_mismatch']=mis
kinds=collections.Counter(); anyl=0
for r in P.values():
    ks={x.get('kind') for x in (r.get('links') or [])}; kinds.update(ks); anyl+=bool(ks)
out['claim5_people_with_links']=anyl; out['claim5_by_kind']=dict(kinds.most_common())
print(json.dumps(out,indent=1))
