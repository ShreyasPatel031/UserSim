"""Step 2: product kinds (k-means on launch embeddings) x user attributes: lift of each attribute among a kind's real voters; stability (split-half by
launch); how much each person-grouping separates launches (observed / chance TV distance of a launch's mix from the overall mix); person taste
clusters with variance explained by k."""
import json, os, sys, re, numpy as np, pandas as pd
from sklearn.cluster import KMeans
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0); os.environ["SEG_LOCAL"] = "1"
sys.path.insert(0, "/home/user/UserSim/experiments/simlab"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm, segments_lib
L = pd.read_parquet(f"{OUT}/launches.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); L["i"] = range(len(L)); hist = (L.day < "2026-11-15").values
KK = int(os.environ.get("KINDS", 12)); km = KMeans(KK, random_state=0, n_init=10).fit(X[hist]); L["kind"] = km.predict(X)
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"])
U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(set(L.id[hist]))]
made = set(E[E.kind.isin(["launched", "hunted"])].person_id); del E
U["k"] = U.target_id.map(dict(zip(L.id, L.kind))); n = U.groupby("person_id").size(); U = U[U.person_id.map(n) >= 5].reset_index(drop=True)
PJ = pd.read_parquet(f"{SP}/store_live/persons.parquet", columns=["person_id", "headline", "bio", "joined", "header_json"]).drop_duplicates("person_id").set_index("person_id")
PJ = PJ[PJ.index.isin(set(U.person_id))]; txt = (PJ.headline.fillna("") + " " + PJ.bio.fillna("")).str.lower()
ROLES = [("investor", r"\b(investor|vc|venture|angel)\b"), ("designer", r"(design|\bux\b|\bui\b|figma|illustrat)"),
         ("developer", r"(engineer|developer|\bdev\b|software|full[- ]?stack|backend|frontend|programm|devops|data scien|machine learning|\bml\b)"),
         ("marketer", r"(marketing|marketer|growth|\bseo\b|content|brand|social media|copywrit|community)"),
         ("product manager", r"(product manager|\bpm\b|product lead|product owner|head of product)"),
         ("founder", r"(founder|\bceo\b|indie|maker|solopreneur|bootstrap|entrepreneur)"), ("student", r"(student|university|college)"),
         ("sales / bizdev", r"(sales|business development|account exec|partnerships)"), ("creator / writer", r"(writer|creator|youtuber|podcast|journalist|blogger|newsletter)"),
         ("data / analyst", r"(analyst|analytics|data engineer|\bbi\b)"), ("ops / support", r"(operations|customer success|support|recruit|\bhr\b)")]
A = pd.DataFrame({r: txt.str.contains(rx, regex=True) for r, rx in ROLES}); A["no bio"] = txt.str.strip() == ""
A["has launched a product"] = A.index.isin(made)
yrs = (pd.Timestamp("2026-11-15", tz="UTC") - pd.to_datetime(PJ.joined, utc=True, errors="coerce")).dt.days / 365.25
A["new account (< 1 year)"] = yrs < 1; A["veteran (5+ years)"] = yrs >= 5
fol = pd.to_numeric(PJ.header_json.map(lambda h: json.loads(h).get("followers") if isinstance(h, str) and h.startswith("{") else None), errors="coerce").fillna(0)
A["1k+ followers"] = fol >= 1000; A["heavy voter (top 10%)"] = n.reindex(A.index) >= n.quantile(0.9)
print("people", len(A), "votes", len(U), "launches", U.target_id.nunique(), flush=True)
# ---- name the kinds
samp = {k: L[hist & (L.kind == k).values].sample(min(14, int((L.kind[hist] == k).sum())), random_state=0) for k in range(KK)}
pr = ("Name each cluster of Product Hunt launches by the KIND of product (2-4 words, concrete, distinct from the others; e.g. 'AI coding agents', "
      "'Consumer mobile apps'). Return JSON only: {\"kinds\": [{\"id\": <n>, \"name\": \"...\", \"what\": \"<one short sentence>\"}]}\n\n" +
      "\n".join(f"[{k}] " + " | ".join(f"{a}: {b}" for a, b in zip(s.name, s.tagline)) for k, s in samp.items()))
KN = {int(r["id"]): r for r in json.loads(llm.gemini_call(pr, 3000))["kinds"]}
# ---- lift table: attribute share among a kind's votes / among all votes; split-half by launch for stability
UA = U.join(A, on="person_id"); cols = list(A.columns)
def lift(df): return (df.groupby("k")[cols].mean() / df[cols].mean())
LT = lift(UA); half = pd.Series(rng.integers(0, 2, U.target_id.nunique()), index=U.target_id.unique()); h = UA.target_id.map(half)
L0, L1 = lift(UA[h == 0]), lift(UA[h == 1]); stab = float(np.corrcoef(np.log(L0.values.ravel()), np.log(L1.values.ravel()))[0, 1])
nk = UA.groupby("k").size(); nl = L[hist].groupby("kind").size()
# bootstrap CI over launches for each cell
G = {t: g for t, g in UA.groupby("target_id")}; ids = list(G); lk = dict(zip(L.id, L.kind))
S = pd.DataFrame({t: g[cols].sum() for t, g in G.items()}).T; S["n"] = [len(G[t]) for t in S.index]; S["k"] = [lk[t] for t in S.index]
B_ = []
for _ in range(400):
    s = S.iloc[rng.integers(0, len(S), len(S))]; tot = s[cols].sum() / s.n.sum(); gk = s.groupby("k")[cols + ["n"]].sum(); B_.append((gk[cols].div(gk.n, axis=0) / tot).reindex(range(KK)).values)
B_ = np.array(B_); lo, hi = np.nanpercentile(B_, 2.5, axis=0), np.nanpercentile(B_, 97.5, axis=0)
cells = [{"kind": int(k), "attr": c, "lift": round(float(LT.loc[k, c]), 2), "lo": round(float(lo[k, j]), 2), "hi": round(float(hi[k, j]), 2), "share": round(float(UA[UA.k == k][c].mean()), 3)}
         for k in range(KK) for j, c in enumerate(cols)]
# ---- person taste clusters: mean embedding of upvoted launches, centred; variance explained by k
pid = {p: i for i, p in enumerate(A.index)}; M = np.zeros((len(A), X.shape[1]), np.float32); li = dict(zip(L.id, L.i))
np.add.at(M, U.person_id.map(pid).values, X[U.target_id.map(li).values]); M /= n.reindex(A.index).values[:, None]
M -= M.mean(0); M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9; tss = float(((M - M.mean(0)) ** 2).sum()); VE, TL = {}, {}
for k in range(2, 9):
    m = KMeans(k, random_state=0, n_init=5).fit(M); VE[k] = round(1 - m.inertia_ / tss, 3); TL[k] = m.labels_
# ---- how much does each grouping separate launches? observed mean TV of a launch's mix from the overall mix, divided by the same with labels shuffled
lab, _ = segments_lib.load(f"{SP}/segv4")
def sep(labels):   # labels: Series person -> label
    z = U.person_id.map(labels); ok = z.notna(); z = z[ok]; t = U.target_id[ok]; cats = sorted(z.unique())
    def tv(zz):
        ct = pd.crosstab(t.values, zz); ct = ct[ct.sum(1) >= 30]; mix = ct.div(ct.sum(1), axis=0); return float((0.5 * (mix - ct.sum(0) / ct.values.sum()).abs().sum(1)).mean())
    o = tv(z.values); c = np.mean([tv(rng.permutation(z.values)) for _ in range(5)]); return {"observed": round(o, 4), "chance": round(c, 4), "ratio": round(o / c, 2), "groups": len(cats)}
role1 = pd.Series(np.where(A["no bio"], "no bio", A[[r for r, _ in ROLES]].idxmax(axis=1).where(A[[r for r, _ in ROLES]].any(axis=1), "other")), index=A.index)
SEP = {"main role (first match)": sep(role1), "has launched a product": sep(A["has launched a product"].map(str)), "followers 1k+": sep(A["1k+ followers"].map(str)),
       "account age (new / mid / veteran)": sep(pd.Series(np.where(yrs < 1, "new", np.where(yrs >= 5, "veteran", "mid")), index=A.index)),
       "activity (heavy voter)": sep(A["heavy voter (top 10%)"].map(str)),
       "current v4 groups": sep(pd.Series({p: l.split(" / ")[0] for p, l in lab.items()})), "current v4 subgroups": sep(pd.Series(lab)),
       **{f"taste clusters k={k}": sep(pd.Series(TL[k], index=A.index).map(str)) for k in (3, 4, 5, 8)},
       "role x taste k=4": sep(role1 + "|" + pd.Series(TL[4], index=A.index).map(str))}
out = {"people": len(A), "votes": len(U), "launches": int(U.target_id.nunique()), "kinds": [{"id": k, **{x: KN.get(k, {}).get(x) for x in ("name", "what")}, "launches": int(nl.get(k, 0)), "votes": int(nk.get(k, 0)),
       "examples": list(samp[k].name[:5])} for k in range(KK)], "attr_base_share": {c: round(float(UA[c].mean()), 3) for c in cols}, "cells": cells,
       "lift_table_split_half_correlation": round(stab, 2), "taste_variance_explained_by_k": VE, "separation": SEP}
json.dump(out, open(f"{OUT}/analysis.json", "w"), indent=1)
pd.DataFrame({"person_id": A.index, "role1": role1.values, **{f"t{k}": TL[k] for k in (3, 4, 5)}}).to_parquet(f"{OUT}/people.parquet"); A.to_parquet(f"{OUT}/attrs.parquet")
L.to_parquet(f"{OUT}/launches_k.parquet"); np.save(f"{OUT}/kind_centroids.npy", km.cluster_centers_)
print("stability", stab, "\nVE", VE); print(json.dumps(SEP, indent=0))
for k in out["kinds"]: print(k["id"], k["name"], k["launches"], k["votes"], k["examples"][:3])
C = pd.DataFrame(cells); C = C[(C.lo > 1.1) | (C.hi < 0.9)]; C["kn"] = C.kind.map(lambda k: KN.get(k, {}).get("name"))
print(C.assign(d=(np.log(C.lift)).abs()).sort_values("d", ascending=False).head(45)[["kn", "attr", "lift", "lo", "hi", "share"]].to_string())
