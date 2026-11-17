"""Metrics for the complaint / question recall experiment. Bootstrap over launches (2000)."""
import json, sys, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/cr"; rng = np.random.default_rng(0)
ld = lambda n: {json.loads(l)["id"]: json.loads(l)["v"] for l in open(f"{OUT}/{n}.jsonl")}
T = ld("truth"); ARMS = {a: ld("arm" + a) for a in ("A", "B", "C", "D", "F", "E", "Bsite")}; JG = ld("judge"); M = json.load(open(f"{OUT}/meta_run.json"))
X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "name", "topics", "day"]); X["id"] = X.id.astype(str); X = X.drop_duplicates("id").set_index("id")
rows = []
for i, t in T.items():
    for kind in ("complaints", "questions"):
        real = t[kind]; m = (JG.get(f"{i}|{kind}") or {}).get("m")
        if not real or m is None: continue
        w = np.array([x["n"] for x in real], float)
        for a, P in ARMS.items():
            if i not in P: continue
            for k in (5, 10):
                hit = [m.get(x) for x in P[i][kind][:k]]; got = {h for h in hit if h is not None}
                rows.append({"id": i, "kind": kind, "arm": a, "k": k, "recall": len(got) / len(real), "recall_w": w[list(got)].sum() / w.sum() if got else 0.0, "precision": np.mean([h is not None for h in hit]) if hit else np.nan, "n_real": len(real)})
R = pd.DataFrame(rows)
def ci(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; return f"{v.mean()*100:.1f} [{np.percentile(b,2.5)*100:.1f}, {np.percentile(b,97.5)*100:.1f}]"
def cid(v):
    v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; return f"{v.mean()*100:+.1f} [{np.percentile(b,2.5)*100:+.1f}, {np.percentile(b,97.5)*100:+.1f}]"
O = {"meta": M, "launches_with_truth": len(T), "real_themes_per_launch": {k: round(float(np.mean([len(t[k]) for t in T.values()])), 2) for k in ("complaints", "questions")},
     "launches_with_no_real_theme": {k: int(sum(1 for t in T.values() if not t[k])) for k in ("complaints", "questions")}, "median_commenters": float(np.median([t["n_commenters"] for t in T.values()]))}
main = ["A", "B", "C", "D", "F"]; common = set.intersection(*[set(ARMS[a]) for a in main]); Rc = R[R.id.isin(common) & R.arm.isin(main)]
tab = {}
for kind in ("complaints", "questions"):
    for k in (5, 10):
        g = Rc[(Rc.kind == kind) & (Rc.k == k)]; tab[f"{kind} @{k}"] = {a: {"n": int((g.arm == a).sum()), "recall": ci(g[g.arm == a].recall), "recall_weighted_by_commenters": ci(g[g.arm == a].recall_w), "precision": ci(g[g.arm == a].precision)} for a in main}
O["main_arms_common_launches"] = tab
pv = lambda kind, k, col, S=Rc: S[(S.kind == kind) & (S.k == k)].pivot(index="id", columns="arm", values=col)
pairs = {}
for kind in ("complaints", "questions"):
    for k in (5, 10):
        p = pv(kind, k, "recall"); q = pv(kind, k, "precision")
        pairs[f"{kind} @{k}"] = {f"{a} minus {b}": {"recall": cid((p[a] - p[b]).dropna()), "precision": cid((q[a] - q[b]).dropna())} for a, b in (("A", "B"), ("C", "B"), ("D", "A"), ("D", "B"), ("F", "B"), ("D", "F"), ("F", "C"))}
O["paired_differences"] = pairs
se = set(ARMS["E"]) & common; Rs = R[R.id.isin(se)]; st = {}
for kind in ("complaints", "questions"):
    for k in (5, 10):
        g = Rs[(Rs.kind == kind) & (Rs.k == k)]; p = g.pivot(index="id", columns="arm", values="recall"); q = g.pivot(index="id", columns="arm", values="precision")
        st[f"{kind} @{k}"] = {**{a: {"n": int((g.arm == a).sum()), "recall": ci(g[g.arm == a].recall), "precision": ci(g[g.arm == a].precision)} for a in ("E", "Bsite", "B", "A", "F")},
                              "E minus Bsite": {"recall": cid((p.E - p.Bsite).dropna()), "precision": cid((q.E - q.Bsite).dropna())}, "E minus B": {"recall": cid((p.E - p.B).dropna())}, "Bsite minus B": {"recall": cid((p.Bsite - p.B).dropna())}, "E minus F": {"recall": cid((p.E - p.F).dropna())}}
O["site_subset"] = st
# union ceiling: any arm
un = {}
for kind in ("complaints", "questions"):
    v = []
    for i in common:
        real = T[i][kind]; m = (JG.get(f"{i}|{kind}") or {}).get("m")
        if not real or m is None: continue
        got = {m.get(x) for a in main for x in ARMS[a][i][kind][:10]} - {None}; v.append(len(got) / len(real))
    un[kind] = ci(v)
O["union_of_five_arms_at_10_each (50 predictions)"] = un
# splits (complaints @10, questions @10) for best arms
top = X.topics.map(lambda t: (list(t) or ["none"])[0]); tc = top[list(common)].value_counts(); big = list(tc[tc >= 15].index)
Rc = Rc.assign(topic=Rc.id.map(lambda i: top[i] if top[i] in big else "other"), nc=Rc.id.map(lambda i: T[i]["n_commenters"])); Rc["size"] = pd.cut(Rc.nc, [0, 11, 19, 1000], labels=["8-11 commenters", "12-19", "20+"]).astype(str)
sp = {}
for kind in ("complaints", "questions"):
    g = Rc[(Rc.kind == kind) & (Rc.k == 10)]
    sp[kind] = {"by first topic": {t: {a: ci(x[x.arm == a].recall) for a in main} | {"n": int(x.id.nunique())} for t, x in g.groupby("topic")}, "by number of real commenters": {t: {a: ci(x[x.arm == a].recall) for a in main} | {"n": int(x.id.nunique())} for t, x in g.groupby("size")}}
O["splits_recall_at_10"] = sp
# share of launches where an arm reaches 40% complaint recall
O["share_of_launches_with_complaint_recall_at_10_of_40pct_or_more"] = {a: ci((Rc[(Rc.kind == "complaints") & (Rc.k == 10) & (Rc.arm == a)].recall >= 0.4).astype(float)) for a in main}
json.dump(O, open(f"{OUT}/results.json", "w"), indent=1); print(json.dumps(O, indent=1)[:9000])
# hand-check sample: 25 matched + 25 unmatched predicted/real pairs
S = []
for key, v in JG.items():
    i, kind = key.split("|"); real = T[i][kind]
    for p, r in v["m"].items():
        if r is not None: S.append((1, X.name[i], kind, p, real[r]["theme"]))
        else: S.append((0, X.name[i], kind, p, " || ".join(x["theme"] for x in real)))
S = pd.DataFrame(S, columns=["match", "product", "kind", "pred", "real"]); hs = pd.concat([S[S.match == 1].sample(25, random_state=1), S[S.match == 0].sample(25, random_state=1)]); hs.to_json(f"{OUT}/handcheck.json", orient="records", indent=1)
print("judge match rate", round(S.match.mean(), 3), len(S))
