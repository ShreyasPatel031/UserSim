"""Materialize frozen split reviews from the source CSV; no model calls."""
import argparse, csv, hashlib, json, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FIELDS=['product_name','reviewer_job_title','reviewer_industry','reviewer_company_size',
 'reviewer_time_used_product','pros','cons','general_comments','reasons_for_choosing',
 'reasons_for_switching','overall_rating','ease_of_use_rating','functionality_rating','value_for_money_rating']
def write(path,records):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records))
def main():
 p=argparse.ArgumentParser();p.add_argument('--csv',type=Path);a=p.parse_args()
 source=json.loads((ROOT/'config/source.json').read_text())
 path=a.csv or ROOT/'local_source/capterra_software_reviews.csv'
 if not path.exists():
  if a.csv:raise SystemExit('Supplied CSV does not exist')
  path.parent.mkdir(exist_ok=True);urllib.request.urlretrieve(source['download_url'],path)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
  raise SystemExit('Snapshot checksum differs. Obtain the frozen source or rebuild/version the entire evaluation; do not silently mix snapshots.')
 rows={r['review_id']:r for r in csv.DictReader(path.open())}
 split=json.loads((ROOT/'config/splits.json').read_text())
 test=set(split['test_review_ids']);dev=set(split['development_review_ids'])
 evidence={x for v in split['evidence_review_ids_by_product'].values() for x in v}
 assert not(test&dev or test&evidence or dev&evidence)
 missing=(test|dev|evidence)-rows.keys()
 if missing:raise SystemExit(f'Missing frozen IDs: {sorted(missing)}')
 for product,ids in split['evidence_review_ids_by_product'].items():
  write(ROOT/f'evidence/reviews/{product}.jsonl',[{'evidence_id':i,**{k:rows[i][k] for k in FIELDS}} for i in ids])
 write(ROOT/'development/reviews.jsonl',[rows[i] for i in sorted(dev)])
 # Never give this directory to the predictor or browser agent.
 write(ROOT/'evaluator_only/raw_test_reviews.jsonl',[rows[i] for i in sorted(test)])
 print(json.dumps({'test':len(test),'development':len(dev),'evidence':len(evidence),'checksum_verified':True}))
if __name__=='__main__':main()
