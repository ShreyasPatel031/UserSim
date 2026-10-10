# 0 = absent, 1 = partial, 2 = strong. "?" marks a cell not yet verified against the data itself (scored as 1).
C = ["real_humans","competing_alts","brand_neutral","first_impr","task_compl","overall_choice","who_attrs","why","startup_realism","no_contam","evaluable","license","mcp_arm"]
W = dict(real_humans=0, competing_alts=2, brand_neutral=2, first_impr=1.5, task_compl=1.5, overall_choice=3, who_attrs=2, why=1, startup_realism=2, no_contam=1.5, evaluable=1, license=1, mcp_arm=1)
S = {
 "HUMAINE (Prolific)":            [2,2,"2?",0,2,2,2,2,1,1,2,2,2],
 "PRISM (Kirk 2024)":             [2,2,"2?",2,1,1,2,2,1,1,2,"1?",2],
 "Chatbot Arena votes":           [2,2,2,0,1,2,0,0,1,0,2,"1?",1],
 "Twin-2K-500 pricing":           [2,0,0,1,0,1,2,0,0,1,2,2,2],
 "SimBench":                      [2,0,1,0,0,0,1,0,0,1,2,1,2],
 "OPeRA shopping":                [2,1,0,1,2,1,2,2,1,2,1,2,1],
 "ShopCART":                      [2,1,0,0,2,1,1,0,1,2,2,0,1],
 "Online-Mind2Web":               [2,0,1,0,2,0,0,0,2,1,2,1,1],
 "Upworthy A/B":                  [2,2,2,2,0,1,0,0,0,1,2,2,2],
 "WiserUI-Bench":                 [2,2,2,2,1,1,0,1,2,1,1,1,1],
 "Show HN (live)":                [2,1,2,2,0,1,0,2,2,2,1,2,2],
 "Product Hunt (live)":           [2,1,1,2,0,1,0,1,2,2,1,0,2],
 "Kickstarter":                   [2,1,2,2,0,2,0,0,1,1,2,"1?",2],
 "LabInTheWild web appeal":       [2,1,1,2,0,0,2,0,2,2,2,0,2],
 "G2/Capterra reviews":           [2,2,1,0,1,2,1,2,2,1,1,0,1],
 "App store reviews":             [2,1,1,0,1,1,0,2,2,1,1,1,1],
}
num = lambda x: 1 if isinstance(x,str) else x
rows=[]
for k,v in S.items():
    v=[num(x) for x in v]
    tot=sum(W[c]*x for c,x in zip(C,v)); mx=sum(W[c]*2 for c in C)
    stage = {"P1 dist":"", "P2 first":v[3], "P3 task":v[4], "P4 choice":v[5]}
    rows.append((round(100*tot/mx), k, v))
rows.sort(reverse=True)
hdr="score | benchmark | " + " | ".join(C)
print(hdr)
for s,k,v in rows: print(s,"|",k,"|"," | ".join(str(x) for x in v))
