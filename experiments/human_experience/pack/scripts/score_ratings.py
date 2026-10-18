"""Score actual JSONL predictions; reports weighted and diagnostic metrics."""
import argparse,csv,json,math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TARGETS=['ease_of_use_rating','functionality_rating','overall_rating','value_for_money_rating']
def read(p):return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]
def main():
 p=argparse.ArgumentParser();p.add_argument('predictions',type=Path);p.add_argument('--output',type=Path,default=Path('rating_metrics.csv'));a=p.parse_args()
 gold={x['case_id']:x for x in read(ROOT/'evaluator_only/outcomes.jsonl')}
 tasks=read(ROOT/'inputs/e2e_tasks.jsonl');config=json.loads((ROOT/'config/experiment.json').read_text())
 valid={x['id'] for key in ['phase_a','phase_b'] for x in config[key]}
 seen=set();groups=defaultdict(list);observed=defaultdict(set)
 for x in read(a.predictions):
  c=x['condition'];cid=x['case_id'];rep=x.get('replicate',1)
  if c not in valid or cid not in gold:raise ValueError('Unknown condition/case')
  key=(c,cid,rep)
  if key in seen:raise ValueError(f'Duplicate prediction {key}')
  seen.add(key);observed[(c,rep)].add(cid);g=gold[cid]
  for target in TARGETS:
   y=g['ratings'][target];item=x.get('ratings',{}).get(target)
   if y is None or item is None:continue
   ps=item.get('probabilities')
   if ps is None:continue
   if len(ps)!=5 or any(not isinstance(v,(float,int)) or not math.isfinite(v) or not 0<=v<=1 for v in ps) or abs(sum(ps)-1)>1e-6:
    raise ValueError(f'Invalid probability vector {key} {target}')
   if y not in [1,2,3,4,5]:raise ValueError('Unexpected target scale')
   expected=sum((i+1)*v for i,v in enumerate(ps));mae=abs(expected-y)
   rps=sum((sum(ps[:k])-int(y<=k))**2 for k in range(1,5))/4
   row={'case_id':cid,'mae':mae,'rps':rps,'weight':g['sampling_weight']}
   groups[(c,rep,g['product'],target)].append(row)
   groups[(c,rep,'ALL',target)].append(row)
 out=[]
 for (c,rep,product,target),rs in sorted(groups.items()):
  weight=sum(x['weight'] for x in rs)
  expected_ids={cid for cid,g in gold.items() if (product=='ALL' or g['product']==product) and g['ratings'][target] is not None}
  if c.startswith('B'):expected_ids&={x['case_id'] for x in tasks if x['core_smoke_subset']}
  is_complete=expected_ids<={x['case_id'] for x in rs}
  out.append({'condition':c,'replicate':rep,'product':product,'target':target,'n':len(rs),
   'core_expected_n':len(expected_ids),'core_complete':is_complete,
   'diagnostic_mae':sum(x['mae'] for x in rs)/len(rs),'diagnostic_rps':sum(x['rps'] for x in rs)/len(rs),
   'weighted_mae':sum(x['mae']*x['weight'] for x in rs)/weight if c.startswith('A') and is_complete else '',
   'weighted_rps':sum(x['rps']*x['weight'] for x in rs)/weight if c.startswith('A') and is_complete else '',
   'warning':'B is a purposeful task subset; no population-weighted claim' if c.startswith('B') else ('incomplete cases: compare matched available IDs only' if not is_complete else '')})
 if not out:raise SystemExit('No valid rating forecasts found')
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
 print(json.dumps({'predictions':len(seen),'metric_rows':len(out),'output':str(a.output)}))
if __name__=='__main__':main()
