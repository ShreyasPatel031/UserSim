import json,re,sys,time,urllib.request as u
def post(p,d): return json.loads(u.urlopen(u.Request("http://localhost:8799/"+p,json.dumps(d).encode())).read())
STOP=re.compile(r"trial|subscri|purchase|premium|annual|billed|/ ?(wk|week|mo|month|yr|year)\b|notification|Alert:|TextField|SecureTextField|Sign in with Apple|Apple ID|Apple Account|Allow|Alert:",re.I)
NEXT=re.compile(r"^(Next|Continue|Done|Got it|Let.s go|Let.s do it|Start|OK|Okay|Skip|Submit)$",re.I)
lastq=None; answered=False; same=0
for i in range(int(sys.argv[1])):
    o=post("observe",{"tag":f"auto{i}"}); el=o["elements"]
    txt=" ".join(e["type"]+":"+e["label"] for e in el)
    q=" | ".join([e["label"][:70] for e in el if e["type"]=="StaticText"][:3])
    print(i,q,flush=True)
    if q==lastq: same+=1
    else: same=0; answered=False
    if STOP.search(txt) or same>=3: print("STOP"); [print(" ",e["type"],repr(e["label"][:90]),e["x"],e["y"]) for e in el if e["type"]!="Key"]; break
    lastq=q
    btn=[e for e in el if e["type"]=="Button" and e["label"]!="Back"]
    n=[e for e in btn if NEXT.match(e["label"].strip())]
    opts=[e for e in btn if e not in n]
    if n and (answered or not opts): pick=n[0]
    elif opts: pick=opts[1] if len(opts)>1 else opts[0]; answered=True
    else: print("STOP nobutton"); [print(" ",e) for e in el]; break
    print("  tap",pick["label"][:50]); post("act",{"action":"tap","x":pick["x"],"y":pick["y"]}); time.sleep(3)
