"""Regroup (user 21:30Z Nov 15): fine taste subgroups first (k-means on people's taste vectors), then merge subgroups into 3-5 parent groups by how alike
they vote (Ward on subgroup centroids). Every parent has subgroups; subgroups that vote alike share a parent. Reports variance explained, how much
launches' audiences differ vs chance, and a held-out check of the predicted subgroup mix. Names by Gemini from distinctive launches."""
import json, sys, os, numpy as np, pandas as pd
from sklearn.cluster import KMeans, AgglomerativeClustering
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0); KF = int(os.environ.get("KF", 16))
sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
O = json.load(open(f"{OUT}/analysis.json")); kn = {k["id"]: k["name"] for k in O["kinds"]}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str); hist = set(L.id[L.day < "2026-11-13"]); U = U[U.target_id.isin(hist) & U.person_id.isin(set(P.index))].reset_index(drop=True)
n = U.groupby("person_id").size(); pid = {p: i for i, p in enumerate(P.index)}; li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day))
M = np.zeros((len(P), X.shape[1]), np.float32); np.add.at(M, U.person_id.map(pid).values, X[U.target_id.map(li).values]); M /= n.reindex(P.index).values[:, None]
M -= M.mean(0); M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9; np.save(f"{OUT}/person_taste.npy", M); tss = float(((M - M.mean(0)) ** 2).sum())
VEF = {}
for k in (8, 12, 16, 20, 24): VEF[k] = round(1 - KMeans(k, random_state=0, n_init=4).fit(M).inertia_ / tss, 3)
km = KMeans(KF, random_state=0, n_init=10).fit(M); fine = km.labels_
VEP, PAR = {}, {}
for kp in (3, 4, 5, 6):
    ag = AgglomerativeClustering(kp, linkage="ward").fit(km.cluster_centers_); par = ag.labels_[fine]; PAR[kp] = ag.labels_
    cen = np.array([M[par == j].mean(0) for j in range(kp)]); VEP[kp] = round(1 - float(((M - cen[par]) ** 2).sum()) / tss, 3)
KP = next((k for k in (3, 4) if VEP[k + 1] - VEP[k] < 0.015), 5); parent_of = PAR[KP]
print("VE fine", VEF, "| VE parents", VEP, "-> parents", KP, flush=True)
U["s"] = U.person_id.map(pd.Series(fine, index=P.index)); U["g"] = U.s.map(lambda s: parent_of[s]); U["k"] = U.target_id.map(dict(zip(L.id, L.kind)))
def sep(col):
    def tv(z):
        ct = pd.crosstab(U.target_id.values, z); ct = ct[ct.sum(1) >= 30]; mix = ct.div(ct.sum(1), axis=0); return float((0.5 * (mix - ct.sum(0) / ct.values.sum()).abs().sum(1)).mean())
    return round(tv(U[col].values) / np.mean([tv(rng.permutation(U[col].values)) for _ in range(4)]), 2)
SEP = {"parents": sep("g"), "subgroups": sep("s")}
# held-out: subgroup mix of a launch from its 30 nearest EARLIER launches vs the typical mix
ct = pd.crosstab(U.target_id, U.s); ct = ct[ct.sum(1) >= 30]; MIX = ct.div(ct.sum(1), axis=0); cand = list(MIX.index); XC = X[[li[l] for l in cand]]; dc = np.array([day[l] for l in cand])
tm, tb = [], []
for j, l in enumerate(cand):
    if day[l] < "2026-10-13": continue
    ok = dc < day[l]; s = XC[ok] @ XC[j]; m = MIX.values[ok][np.argsort(-s)[:30]].mean(0); b = MIX.values[ok].mean(0)
    tm.append(0.5 * np.abs(MIX.values[j] - m).sum()); tb.append(0.5 * np.abs(MIX.values[j] - b).sum())
d = np.array(tm) - np.array(tb); bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
VAL = {"launches": len(d), "model": round(float(np.mean(tm)), 3), "typical mix": round(float(np.mean(tb)), 3), "paired": [round(float(d.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)]}
print("sep", SEP, "val", VAL, flush=True)
# profiles
basek = U.k.value_counts(normalize=True); pl = U.groupby("target_id").size(); lname = dict(zip(L.id, L.name)); ltag = dict(zip(L.id, L.tagline)); subs = []
for s in range(KF):
    mem = P.index[fine == s]; us = U[U.s == s]; kl = (us.k.value_counts(normalize=True) / basek).sort_values(ascending=False)
    cnt = us.groupby("target_id").size(); ll = ((cnt / len(us)) / (pl / len(U))); dist = ll[cnt.reindex(ll.index).fillna(0) >= max(15, 0.02 * len(mem))].sort_values(ascending=False).head(14)
    al = A.loc[mem].mean() / A.mean()
    subs.append({"id": int(s), "parent": int(parent_of[s]), "people": len(mem), "share_of_votes": round(len(us) / len(U), 3), "median_votes": float(n.reindex(mem).median()),
                 "kinds_more": [(kn[k], round(float(v), 2)) for k, v in kl.head(4).items()], "kinds_less": [(kn[k], round(float(v), 2)) for k, v in kl.tail(3).items()],
                 "attrs": {c: round(float(al[c]), 2) for c in ("developer", "founder", "marketer", "designer", "investor", "student", "has launched a product", "new account (< 1 year)", "veteran (5+ years)", "heavy voter (top 10%)")},
                 "distinctive_launch_ids": list(dist.index), "distinctive_launches": [f"{lname[t]}: {ltag[t]}" for t in dist.index]})
pr = ("Below are subgroups of Product Hunt voters, found by clustering people on the launches they upvote, and arranged under parent groups (subgroups under one parent vote alike). "
      "Name every subgroup by what is distinctive about the PRODUCTS it backs (2-4 words, concrete, every name clearly different; if a subgroup votes for a bit of everything and has a high median vote count, "
      "call it 'All-round heavy voters' plus a qualifier). Then name each parent by what its subgroups have in common (2-4 words). Give one plain sentence for what each subgroup goes for. JSON only: "
      "{\"parents\": [{\"id\": <n>, \"name\": \"...\"}], \"subgroups\": [{\"id\": <n>, \"name\": \"...\", \"goes_for\": \"...\"}]}\n\n" + "\n\n".join(
      f"PARENT {g}:\n" + "\n".join(f"  [{s['id']}] {s['people']} people, median {s['median_votes']:.0f} votes; over-backs {s['kinds_more']}; under-backs {s['kinds_less']}; who (lift) {s['attrs']}\n     distinctive launches: " + " | ".join(s["distinctive_launches"][:10])
                                 for s in subs if s["parent"] == g) for g in range(KP)))
R = json.loads(llm.gemini_call(pr, 5000)); PN = {int(x["id"]): x["name"] for x in R["parents"]}; SN = {int(x["id"]): x for x in R["subgroups"]}
for s in subs: s["name"] = SN.get(s["id"], {}).get("name") or f"subgroup {s['id']}"; s["goes_for"] = SN.get(s["id"], {}).get("goes_for"); s["parent_name"] = PN.get(s["parent"], f"group {s['parent']}")
parents = [{"id": g, "name": PN.get(g, f"group {g}"), "people": int(sum(s["people"] for s in subs if s["parent"] == g)), "share_of_votes": round(sum(s["share_of_votes"] for s in subs if s["parent"] == g), 3)} for g in range(KP)]
old = pd.read_parquet(f"{OUT}/people_units.parquet").set_index("person_id").unit
xt = pd.crosstab(old.reindex(P.index).values, pd.Series(fine).map(lambda s: f"{PN.get(parent_of[s], parent_of[s])} / {SN.get(s, {}).get('name', s)}").values)
json.dump({"variance_explained_fine": VEF, "variance_explained_parents": VEP, "parents_chosen": KP, "fine_k": KF, "separation_vs_chance": SEP, "held_out_subgroup_mix": VAL, "parents": parents, "subgroups": subs,
           "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 4)}, open(f"{OUT}/regroup.json", "w"), indent=1)
pd.DataFrame({"person_id": P.index, "sub": fine, "parent": parent_of[fine]}).to_parquet(f"{OUT}/people_units2.parquet"); np.save(f"{OUT}/sub_centroids.npy", km.cluster_centers_)
for g in parents:
    print("\n##", g["name"], g["people"], "people,", g["share_of_votes"], "of votes")
    for s in sorted([s for s in subs if s["parent"] == g["id"]], key=lambda s: -s["people"]): print("  -", s["name"], "|", s["people"], "ppl, votes", s["share_of_votes"], "median", s["median_votes"], "|", s["kinds_more"][:3], "| e.g.", [x.split(":")[0] for x in s["distinctive_launches"][:4]])
print("\nwhere the old dev subgroups went:"); print(xt.loc[[i for i in xt.index if i in ("1.0", "1.1", "1.2", "1.3", "3.0", "3.1", "3.2", "3.3")]].T.to_string())
