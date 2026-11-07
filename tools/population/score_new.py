"""Usage: score_new.py WORK SINCE_ISO. Scores every live vm/<h>.json written since SINCE; updates the source=strat ledger. Prints counts only."""
import contextlib,io,json,runpy,sys,re,subprocess,collections,os
W,SINCE=sys.argv[1],sys.argv[2]
FAILS=sys.argv[3] if len(sys.argv)>3 else None  # optional local path: failing handles + reasons (never committed)
CAPS=collections.Counter(); fails=[]
V="gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/people_live/vm"
L="gs://usersim-bakeoff-347838016394/usersim_sim/raw/population/requests/source_strat_people.txt"
ls=subprocess.run(["gsutil","ls","-l",f"{V}/*.json"],capture_output=True,text=True).stdout.splitlines()
new=[l.split()[2] for l in ls if len(l.split())==3 and not l.startswith("TOTAL") and l.split()[1]>=SINCE]
D=f"{W}/score_new_dl"; os.makedirs(D,exist_ok=True)
if new: subprocess.run(["gsutil","-q","-m","cp"]+new+[D+"/"],check=False)
sys.argv=["quality.py",W,"2026-11-05T00:00:00Z","/dev/null","/dev/null"]
with contextlib.redirect_stdout(io.StringIO()):
    g=runpy.run_path("/home/user/UserSim/tools/population/quality.py")
old=set(l.split("\t")[0] for l in subprocess.run(["gsutil","cat",L],capture_output=True,text=True).stdout.splitlines() if l.strip())
c=collections.Counter(); rs=collections.Counter(); vms=collections.Counter(); pg=0; strat=set(old)
for u in new:
    f=u.rsplit("/",1)[1]; p=f"{D}/{f}"
    d=json.load(open(p)); m=str(d.get("method","")); v=re.search(r"\((feeder-[^)]+)\)",m); src=v.group(1) if v else "unknown"
    ok,why=g["person_complete"](d,g["handle_of"](d,p))
    if "pgql" in m.lower() and not (d.get("run") or {}).get("deep_passes"): pg+=1
    c["whole" if ok else "FAIL"]+=1; vms[(src,"whole" if ok else "FAIL")]+=1
    for w in why: rs[w]+=1
    if not ok: fails.append((f[:-5], src, why))
    up=d.get("upvotes") or {}; r=d.get("run") or {}
    if up.get("upvotes_capped"): CAPS["upvotes_capped"]+=1
    if d.get("truncated_budget") or any((d.get(t) or {}).get("status") in ("partial","truncated_budget") for t in ("upvotes","hunted","following","followers","collections","stacks","reviews","activity","forums")): CAPS["truncated_or_partial_tab"]+=1
    if "cap" in str(r.get("followers_cap") or "") or r.get("followers_cap"): CAPS["followers_cap"]+=1
    if "strat" in src: strat.add(f[:-5])
if strat-old:
    open(f"{D}/strat.txt","w").write("".join(h+"\tsource=strat\n" for h in sorted(strat))); subprocess.run(["gsutil","-q","cp",f"{D}/strat.txt",L])
print(f"NEW={len(new)} WHOLE={c['whole']} FAIL={c['FAIL']} PGQL_NO_DEEP={pg} STRAT_LEDGER={len(strat)}")
print("caps:",dict(CAPS))
if FAILS: open(FAILS,"w").write("".join(f"{h}\t{src}\t{','.join(w)}\n" for h,src,w in fails))
print("by_vm:",{f"{k[0]}:{k[1]}":n for k,n in vms.items()}); print("reasons:",dict(rs))
