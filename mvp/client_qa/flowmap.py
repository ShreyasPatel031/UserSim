"""Build the review page's flow map (canvas.json): real screens as nodes, branching where runs diverge.

    python -m mvp.client_qa.flowmap flows.json shots.json canvas.json

flows.json: the review page's runs ([{id, title, steps:[{img, url, taps?}]}]).
shots.json: {"<flow id>": ["local/path/of/step0.png", ...]} -- local screenshots, used only to tell screens apart.
Consecutive near-identical screens in a run are folded into one node; runs share a node while their screens match
(perceptual hash, status bar ignored), and a run that starts mid-app grafts onto the closest matching screen.
Edge labels come from the taps bound to each screen (drive.py runs); runs without bound taps get unlabelled arrows.
"""
import json,sys
from PIL import Image
flows=json.load(open(sys.argv[1])); SHOTS=json.load(open(sys.argv[2])); OUT=sys.argv[3]
def path_of(fid,i):
    p=SHOTS.get(fid); return p[i] if p and i<len(p) else None
def dhash(p):
    im=Image.open(p).convert("L"); w,h=im.size
    im=im.crop((0,int(h*0.07),w,h)).resize((17,32)); px=list(im.get_flattened_data() if hasattr(im,"get_flattened_data") else im.getdata())
    return [px[r*17+c]>px[r*17+c+1] for r in range(32) for c in range(16)]
def dist(a,b): return sum(x!=y for x,y in zip(a,b))
SAME, MERGE = 20, 50
fl={f["id"]:f for f in flows}
H={(f["id"],i):(dhash(path_of(f["id"],i)) if path_of(f["id"],i) else None) for f in flows for i in range(len(f["steps"]))}
seqs={}
for f in flows:
    seq=[]
    for i in range(len(f["steps"])):
        h=H[(f["id"],i)]
        if seq and h and seq[-1]["h"] and dist(seq[-1]["h"],h)<=SAME: seq[-1]["steps"].append(i); continue
        seq.append({"h":h,"steps":[i]})
    seqs[f["id"]]=seq
nodes=[]; edges={}; roots=[]
def mk(fid,grp,parent):
    n={"id":f"n{len(nodes)}","members":[{"flow":fid,"steps":grp["steps"]}],"h":grp["h"],"children":[],"parent":parent}
    nodes.append(n); return n
def edge(a,b,fid,lab):
    e=edges.setdefault((a["id"],b["id"]),{"from":a["id"],"to":b["id"],"labels":[],"flows":[]})
    if lab and lab not in e["labels"]: e["labels"].append(lab)
    if fid not in e["flows"]: e["flows"].append(fid)
def label(fid,k):
    if not fl[fid].get("tapsBound") or k==0: return ""
    last=fl[fid]["steps"][seqs[fid][k-1]["steps"][-1]]
    out=[]
    for t in last.get("taps",[]):
        if t["kind"].startswith("tap"): out.append("tap “%s”"%t["label"] if t.get("label") else "tap")
        elif t["kind"] in("type","type_into"): out.append("type")
        else: out.append(t["kind"])
    return ", ".join(out)
# runs with bound taps first, then longer runs (so a run starting mid-app can graft onto one already placed), runs without shots last
order=[f["id"] for f in sorted(flows, key=lambda f: (not f.get("tapsBound"), f["id"] not in SHOTS, -len(f["steps"])))]
for fid in [o for o in order if o in fl]:
    cur=None
    for k,grp in enumerate(seqs[fid]):
        h=grp["h"]; match=None
        if h is not None:
            pool = (roots if cur is None else cur["children"])
            for c in pool:
                if c["h"] and dist(c["h"],h)<=MERGE: match=c; break
            if match is None and cur is None:     # a run that starts mid-app grafts onto the closest matching screen anywhere
                best=min(((dist(n["h"],h),n) for n in nodes if n["h"]), default=(999,None), key=lambda x:x[0])
                if best[0]<=MERGE: match=best[1]
        if match: match["members"].append({"flow":fid,"steps":grp["steps"]}); nxt=match
        else:
            nxt=mk(fid,grp,cur["id"] if cur else None)
            (roots if cur is None else cur["children"]).append(nxt)
        if cur: edge(cur,nxt,fid,label(fid,k))
        cur=nxt
W,Hn,GX,GY=240,520,150,110
row=[0]
def place(n,d):
    n["x"]=d*(W+GX); n["depth"]=d
    if not n["children"]: n["y"]=row[0]*(Hn+GY); row[0]+=1
    else:
        for c in n["children"]: place(c,d+1)
        n["y"]=(n["children"][0]["y"]+n["children"][-1]["y"])/2
for r in roots: place(r,0)
json.dump({"node_w":W,"node_h":Hn,"nodes":[{k:n[k] for k in("id","members","x","y","depth")} for n in nodes],"edges":list(edges.values())},open(OUT,"w"))
sh=[(n["id"],sorted({m["flow"] for m in n["members"]})) for n in nodes if len({m["flow"] for m in n["members"]})>1]
print(len(nodes),"nodes",len(edges),"edges, leaf rows",row[0],"roots",len(roots)); print("shared:",sh)
