"""Do the people the website shows as closest matches actually upvote the product? (orchestrator 00:00Z Nov 12)
People = the 5,096 rows of the website bundle (person_bundle_gemini.npz; row order reconstructed internally from the build
permutation - nothing leaves this script). Launches = Aug-Oct 2026 with >= 30 voters among these people (store_v3 upvotes).
Scoring = the website scorer exactly (gemini-embedding-001 256-d of "name. tagline. description[:1100]", trees, pct99), with
one guard: a person's items whose embedding is near-identical to the launch (cos >= 0.95, i.e. the same product in their
stack) are dropped. Limitation: uses lists are November snapshots (undated) - they are the person's tools, not votes.
Comparisons for the top K (K = 100, 500) by score - pct99 (the page's ranking):
  random      K random people
  activity    for each top-K person, a random person in the same activity decile x recency bucket (dated upvotes before the
              launch day; recency = days since the last such upvote, 4 buckets), excluding the top K
  popular     the K most active people (dated upvotes before the launch day)
Metrics: precision@K (share who upvoted), lift vs base rate, recall@500 of the launch's voters; launch-bootstrap 95% CIs.
Segments: per launch, Spearman across the 9 role segments between the page's predicted likely-share (score >= pct99) and the
actual vote rate (segments with >= 20 people).
    python voters_eval.py <bundle.npz> <uses2 export> <v3 dir> <launches dir> <out dir>
"""
import glob, json, os, subprocess, sys, time, urllib.request
import numpy as np, pandas as pd
from scipy.stats import spearmanr

BUN, EXP, V3, LDIR, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
EMB = "https://us-central1-aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/us-central1/publishers/google/models/gemini-embedding-001:predict"
_tok = {"t": "", "at": 0}


def token():
    if time.time() - _tok["at"] > 300:
        _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
    return _tok["t"]


def embed(texts):
    out = []
    for i in range(0, len(texts), 200):
        for a in range(6):
            try:
                req = urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts[i:i + 200]],
                                                              "parameters": {"outputDimensionality": 256}}).encode(), {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
                out.append(np.array([p["embeddings"]["values"] for p in json.load(urllib.request.urlopen(req, timeout=180))["predictions"]], np.float32)); break
            except Exception as e:  # noqa: BLE001
                print("retry", a, str(e)[:100], flush=True); time.sleep(4 * (a + 1))
    E = np.vstack(out); return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


Z = np.load(BUN); IE = Z["item_emb"].astype(np.float32); PTR, IDX = Z["person_ptr"], Z["person_items"]
TR = {k: Z[k] for k in ("tree_feat", "tree_thr", "tree_left", "tree_right", "tree_value", "tree_roots")}; HI = float(Z["hi"]); THR = Z["pct99_tree"]
Pe = pd.read_parquet(os.path.join(EXP, "people.parquet")); order = np.random.default_rng(0).permutation(len(Pe))   # bundle build order
pid = Pe.person_id.to_numpy()[order]; NP = len(pid); prow = {p: i for i, p in enumerate(pid)}
roles = Z["roles"]; RN = list(Z["role_names"])

ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id", "extra"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(prow)]; ev["target_id"] = ev.target_id.astype(str)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
lday = dict(zip(L.id, L.day))
ev["vday"] = ev.target_id.map(lday).fillna(ev.extra.str.extract(r'"launched_at": "(\d{4}-\d\d-\d\d)')[0])
voters = ev.groupby("target_id").person_id.apply(lambda s: {prow[p] for p in s}).to_dict()
dated = ev.dropna(subset=["vday"]); act = {prow[p]: np.sort(g.vday.to_numpy()) for p, g in dated.groupby("person_id")}
A = L[(L.day >= "2026-08-01") & (L.day <= "2026-10-31")]
A = A[[len(voters.get(i, ())) >= 30 for i in A.id]].reset_index(drop=True)
print("launches", len(A), flush=True)
Q = embed([f"{a}. {b}. {(c or '')[:1100]}" for a, b, c in zip(A.name, A.tagline, A.description)])


def scores(q):
    s = IE @ q; F = np.zeros((NP, 5), np.float32); ok = np.zeros(NP, bool)
    for j in range(NP):
        v = s[IDX[PTR[j]:PTR[j + 1]]]; v = v[v < 0.95]                 # drop the same product if it is in the person's list
        if len(v): vs = np.sort(v); F[j] = [vs[-1], vs[-5:].mean(), v.mean(), (v > HI).mean(), np.log1p(len(v))]; ok[j] = True
    sc = np.zeros(NP)
    for rt in TR["tree_roots"]:
        n = np.full(NP, rt)
        while True:
            f = TR["tree_feat"][n]; leaf = f < 0
            if leaf.all(): break
            n = np.where(leaf, n, np.where(F[np.arange(NP), np.maximum(f, 0)] <= TR["tree_thr"][n], TR["tree_left"][n], TR["tree_right"][n]))
        sc += TR["tree_value"][n]
    sc[~ok] = -1e9; return sc


rows, segr = [], []
for li, r in A.iterrows():
    d = r.day; V = voters[r.id]; base = len(V) / NP
    n_act = np.array([np.searchsorted(act.get(j, np.array([])), d, side="left") for j in range(NP)])
    last = np.array([(pd.Timestamp(d) - pd.Timestamp(act[j][n_act[j] - 1])).days if n_act[j] else 9999 for j in range(NP)])
    adec = np.searchsorted(np.percentile(n_act, np.arange(10, 100, 10)), n_act); rbk = np.digitize(last, [7, 30, 90])
    sc = scores(Q[li]); rank = np.argsort(-(sc - THR)); likely = sc >= THR
    for K in (100, 500):
        top = rank[:K]; tset = set(top.tolist())
        hit = lambda idx: np.mean([j in V for j in idx])
        rnd = rng.choice(NP, K, replace=False)
        cell = {}
        for j in range(NP): cell.setdefault((adec[j], rbk[j]), []).append(j)
        am = [rng.choice([x for x in cell[(adec[j], rbk[j])] if x not in tset] or cell[(adec[j], rbk[j])]) for j in top]
        pop = np.argsort(-n_act)[:K]
        rows.append({"launch": li, "K": K, "base": base, "top": hit(top), "random": hit(rnd), "activity": hit(am), "popular": hit(pop),
                     "recall": len(V & tset) / len(V)})
    pr, ac = [], []
    for k in range(roles.shape[1]):
        m = roles[:, k] == 1
        if m.sum() >= 20: pr.append(likely[m].mean()); ac.append(np.mean([j in V for j in np.flatnonzero(m)]))
    if len(pr) >= 4 and np.std(pr) > 0: segr.append(spearmanr(pr, ac).correlation)
    if li % 20 == 0: print(li, flush=True)
D = pd.DataFrame(rows)


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "launches": int(len(A)), "people": NP, "median_voters_per_launch": float(np.median([len(voters[i]) for i in A.id]))}
for K in (100, 500):
    g = D[D.K == K]
    res[f"K{K}"] = {"base_rate": boot(g.base), **{f"precision {c}": boot(g[c]) for c in ("top", "random", "activity", "popular")},
                   "lift top/base": boot(g.top / g.base), "lift top/activity-matched": boot(g.top - g.activity), "top - popular": boot(g.top - g.popular),
                   "ratio top/activity (mean ratio of means)": round(float(g.top.mean() / max(g.activity.mean(), 1e-9)), 2),
                   "ratio top/popular": round(float(g.top.mean() / max(g.popular.mean(), 1e-9)), 2), "recall of voters": boot(g.recall)}
res["segments: Spearman(predicted likely share, actual vote rate) across role segments"] = boot(segr)
json.dump(res, open(os.path.join(OUT, "voters_eval.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
