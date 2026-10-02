import ast, numpy as np, pandas as pd
from collections import defaultdict
from human_sim import simbench_ablate as A, simbench_mass_levers as M
from human_sim.simbench_panel_criteria import band
M.EVAL_ARMS={"split":("C7_split_own",M.HAIKU),"plain":("retr6_rev2",M.HAIKU)}
qs=[q for q in M.load("eval") if "split" in q["preds"]]
g=A.load_split("Grouped")
idx=defaultdict(list)
for _,r in g.iterrows():
    vm=r.group_prompt_variable_map; o=[k for k in vm if k not in A._COUNTRY_KEYS]
    if len(o)==1: idx[(r.dataset_name,A._country_of(vm),o[0],A._stem(r.input_template))].append((str(vm[o[0]]),float(r.group_size or 0),r.human_answer))
rows=[]
for q in qs:
    segs=q["traces"]["split"]; segs=ast.literal_eval(segs) if isinstance(segs,str) else segs
    attr=segs[0]["attribute"]; vals={s["desc"].split(" = ",1)[1] for s in segs}
    vm=None
    # country of the target
    cells=idx.get((q["dataset"],A._country_of(dict(A.build_env.__globals__ and {})) if False else None,attr,A._stem(q["question"])),[])
    rows.append((q,attr,vals))
# need country: recover from persona text via sample
sample,_,_=A.build_env(25,100,7,"eval")
out=[]
for q,attr,vals in rows:
    r=sample.loc[q["i"]]; c=A._country_of(r.group_prompt_variable_map)
    cells=[x for x in idx.get((q["dataset"],c,attr,A._stem(q["question"])),[]) if x[0] in vals]
    if len(cells)<2: continue
    D=np.array([[x[2].get(k,0) for k in q["keys"]] for x in cells],float); D/=D.sum(1,keepdims=True); w=np.array([x[1] or 1 for x in cells]); w/=w.sum()
    mean=w@D; between=float(w@(np.abs(D-mean).sum(1)/2))
    out.append((between,M.tvd(q["preds"]["plain"],q["h"]),M.tvd(q["preds"]["split"],q["h"]),band(q)))
o=np.array([x[:3] for x in out])
print(f"questions with real cell answers for the chosen attribute: {len(out)}")
print(f"REAL difference between demographic groups on the target question (TVD to their weighted mean): mean {o[:,0].mean():.3f}, median {np.median(o[:,0]):.3f}")
print(f"model error (TVD to truth): plain {o[:,1].mean():.3f}, demographic split {o[:,2].mean():.3f}")
for b in ("consensus","mixed","divided"):
    m=np.array([x[3]==b for x in out]); print(f"  {b:10s} real group difference {o[m,0].mean():.3f}  plain error {o[m,1].mean():.3f}")
