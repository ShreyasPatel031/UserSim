"""Subgroups of the two big taste groups (k-means on members' taste vectors; k in 3-5 by variance explained), profiles, Gemini names,
separation check, and subgroup-level audience lift for a day's top 10 (kNN over similar past launches, real voters)."""
import json, sys, os, re, subprocess, urllib.request, numpy as np, pandas as pd
from sklearn.cluster import KMeans
SP, DAY, LIVE = sys.argv[1:4]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
O = json.load(open(f"{OUT}/analysis.json")); kn = {k["id"]: k["name"] for k in O["kinds"]}
GN = {0: "AI business & growth crowd", 1: "Model & coding-tool developers", 2: "Occasional business-tool voters", 3: "Indie app & Mac utility fans", 4: "AI creative-tool crowd"}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str); hist = set(L.id[L.day < "2026-11-13"]); U = U[U.target_id.isin(hist) & U.person_id.isin(set(P.index))].reset_index(drop=True)
n = U.groupby("person_id").size(); pid = {p: i for i, p in enumerate(P.index)}; li = dict(zip(L.id, L.i))
M = np.zeros((len(P), X.shape[1]), np.float32); np.add.at(M, U.person_id.map(pid).values, X[U.target_id.map(li).values]); M /= n.reindex(P.index).values[:, None]
U["g"] = U.person_id.map(P.t5); U["k"] = U.target_id.map(dict(zip(L.id, L.kind))); lname = dict(zip(L.id, L.name)); ltag = dict(zip(L.id, L.tagline))
sub = pd.Series("", index=P.index); INFO = {}
for g in (1, 3):
    ix = np.flatnonzero(P.t5.values == g); Mg = M[ix] - M[ix].mean(0); Mg /= np.linalg.norm(Mg, axis=1, keepdims=True) + 1e-9; tss = float(((Mg - Mg.mean(0)) ** 2).sum()); ve, fits = {}, {}
    for k in range(2, 7): fits[k] = KMeans(k, random_state=0, n_init=8).fit(Mg); ve[k] = round(1 - fits[k].inertia_ / tss, 3)
    kc = next((k for k in (3, 4) if ve[k + 1] - ve[k] < 0.02), 5); lb = fits[kc].labels_; sub.iloc[ix] = [f"{g}.{x}" for x in lb]
    Ug = U[U.g == g].copy(); Ug["s"] = Ug.person_id.map(sub); basek = Ug.k.value_counts(normalize=True); pl = Ug.groupby("target_id").size()
    def sep():
        def tv(z):
            ct = pd.crosstab(Ug.target_id.values, z); ct = ct[ct.sum(1) >= 20]; mix = ct.div(ct.sum(1), axis=0); return float((0.5 * (mix - ct.sum(0) / ct.values.sum()).abs().sum(1)).mean())
        o = tv(Ug.s.values); c = np.mean([tv(rng.permutation(Ug.s.values)) for _ in range(5)]); return round(o / c, 2)
    subs = []
    for s in sorted(set(sub.iloc[ix])):
        mem = sub.index[sub == s]; us = Ug[Ug.s == s]; kl = (us.k.value_counts(normalize=True) / basek).dropna(); kl = kl[basek.reindex(kl.index) >= 0.03].sort_values(ascending=False)
        ll = (us.groupby("target_id").size() / len(us)) / (pl / len(Ug)); cnt = us.groupby("target_id").size(); dist = ll[cnt.reindex(ll.index).fillna(0) >= 25].sort_values(ascending=False).head(14)
        al = (A.loc[mem].mean() / A.loc[P.index[ix]].mean())
        subs.append({"id": s, "people": len(mem), "share_of_group_votes": round(len(us) / len(Ug), 3), "median_votes": float(n.reindex(mem).median()),
                     "kinds_more": [(kn[k], round(float(v), 2)) for k, v in kl.head(4).items()], "kinds_less": [(kn[k], round(float(v), 2)) for k, v in kl.tail(3).items()],
                     "attrs": {c: round(float(al[c]), 2) for c in ("developer", "founder", "marketer", "designer", "investor", "student", "has launched a product", "new account (< 1 year)", "veteran (5+ years)", "heavy voter (top 10%)")},
                     "distinctive_launches": [f"{lname[t]}: {ltag[t]}" for t in dist.index]})
    pr = (f"These are subgroups of ONE Product Hunt voter group ('{GN[g]}'), split by which launches they upvote. Name each by what is distinctive about the PRODUCTS it backs "
          "versus its sibling subgroups (2-4 words, concrete, all names clearly different), and say in one sentence what they go for. JSON only: "
          "{\"subgroups\": [{\"id\": \"<id>\", \"name\": \"...\", \"goes_for\": \"...\"}]}\n\n" + "\n\n".join(
          f"[{s['id']}] product kinds over-backed (lift vs group): {s['kinds_more']}; under-backed: {s['kinds_less']}; who (lift vs group): {s['attrs']}; median votes {s['median_votes']}\n  launches they back far more than the rest of the group: " + " | ".join(s["distinctive_launches"]) for s in subs))
    R = {str(x["id"]): x for x in json.loads(llm.gemini_call(pr, 2500))["subgroups"]}
    for s in subs: s["name"] = (R.get(s["id"]) or {}).get("name"); s["goes_for"] = (R.get(s["id"]) or {}).get("goes_for")
    INFO[GN[g]] = {"variance_explained_by_k": ve, "k_chosen": kc, "separation_of_launches_vs_chance": sep(), "subgroups": subs}
    print(GN[g], ve, "k", kc, "sep", INFO[GN[g]]["separation_of_launches_vs_chance"], flush=True)
# ---- subgroup-level audience for the day's top 10
unit = pd.Series([sub[p] if sub[p] else str(g) for p, g in zip(P.index, P.t5)], index=P.index); U["u"] = U.person_id.map(unit)
ct = pd.crosstab(U.target_id, U.u); ct = ct[ct.sum(1) >= 30]; MIX = ct.div(ct.sum(1), axis=0); base = ct.sum(0) / ct.values.sum(); day = dict(zip(L.id, L.day))
cand = list(MIX.index); XC = X[[li[l] for l in cand]]
S = sorted([json.loads(l) for l in open(f"{LIVE}/snap.jsonl")], key=lambda r: -(r.get("votesCount") or 0))[:10]
T0 = {str(x["id"]): x for x in json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{DAY}/today_0005.json"], capture_output=True, text=True).stdout)}
ids = [str(r["id"]) for r in S if str(r["id"]) in T0]
tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
EMB = re.search(r'EMB = "([^"]+)"', open("/home/user/UserSim/experiments/simlab/reactions_v2.py").read()).group(1)
tx = [f"{T0[l]['name']}. {T0[l].get('tagline')}. {(T0[l].get('description') or '')[:900]}" for l in ids]
j = json.load(urllib.request.urlopen(urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "CLUSTERING"} for t in tx], "parameters": {"outputDimensionality": 256}}).encode(),
              {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}), timeout=180))
Z = np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32); Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
NAME = {s["id"]: s["name"] for v in INFO.values() for s in v["subgroups"]}
top = []
for r in S:
    lid = str(r["id"]); row = {"rank": r.get("dailyRank"), "name": r["name"], "votes": r["votesCount"]}
    if lid in ids:
        m = MIX.iloc[np.argsort(-(XC @ Z[ids.index(lid)]))[:30]].mean(0); lf = (m / base)
        row["subgroup_lift"] = {NAME[u]: round(float(lf[u]), 2) for u in lf.index if u in NAME}; row["subgroup_share"] = {NAME[u]: round(float(m[u]), 3) for u in lf.index if u in NAME}
    top.append(row)
out = {"day": DAY, "groups": INFO, "subgroup_base_share_of_all_votes": {NAME[u]: round(float(base[u]), 3) for u in base.index if u in NAME}, "top10": top, "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 4)}
json.dump(out, open(f"{OUT}/subgroups_{DAY}.json", "w"), indent=1)
pd.DataFrame({"person_id": P.index, "unit": unit.values}).to_parquet(f"{OUT}/people_units.parquet")
for gname, v in INFO.items():
    print("\n##", gname)
    for s in v["subgroups"]: print(" -", s["name"], "|", s["people"], "ppl,", s["share_of_group_votes"], "of group votes, median", s["median_votes"], "|", s["goes_for"]); print("     more:", s["kinds_more"], "less:", s["kinds_less"]); print("     who:", {k: x for k, x in s["attrs"].items() if abs(x - 1) >= 0.15}); print("     e.g.", s["distinctive_launches"][:5])
for r in top: print(r["rank"], r["name"], r.get("subgroup_lift"))
