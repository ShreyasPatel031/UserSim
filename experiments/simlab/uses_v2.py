"""'Uses' v2 (orchestrator Nov 11, 05:30Z): push the use-taste beyond 0.60 (popularity-matched AUC) on the uses harness.
Steps, all paired by person on the SAME candidate sets (built once, seed 0, as in uses_test.py):
  S0  centroid baseline: mean of top-5 cosine sims, bge-small, card text                    (= uses_test U)
  S1  + richer product text: API products_info name/tagline/description/topics where present
  S2  + stronger embedding: bge-base-en-v1.5 on the S1 text
  S3  learned scorer (LightGBM, person-disjoint 2-fold) on kNN features from the best embedding + topic rates;
      S3np = the same without the popularity features (taste only), S3 = with them
  S4  S3 + who the person is: headline/bio embedding similarity to the candidate, role keyword flags
Primary: popularity-matched negatives (AUC, Hit@10, Hit@1 among 51). Secondary: random negatives.
    python uses_v2.py <person_files_dir> <products_info_dir> <salt> <persons.parquet> <outdir>
"""
import glob, hashlib, json, os, re, sys
import numpy as np, pandas as pd

D, PI, SALT_F, PERS, OUT = sys.argv[1:6]
os.makedirs(OUT, exist_ok=True)
SALT = open(SALT_F).read().strip(); rng = np.random.default_rng(0)
comp = set(pd.read_parquet(PERS).query("complete").person_id)
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
slug_of = lambda u: (re.search(r"/products/([^/?#]+)", str(u or "")) or [None, None])[1]
ROLES = {"dev": r"develop|engineer|programm|coder|software|full.?stack|backend|frontend|devops|\bcto\b",
         "design": r"design|\bux\b|\bui\b|creative|artist", "market": r"market|growth|seo|content|brand|social media",
         "founder": r"founder|\bceo\b|entrepreneur|indie ?hacker|maker|builder|bootstrap", "product": r"product manager|\bpm\b|product lead|head of product",
         "data_ai": r"\bai\b|machine learning|\bml\b|data scien|llm|research", "sales": r"sales|\bbd\b|business develop|revenue",
         "student": r"student|universit|college|learning", "invest": r"invest|\bvc\b|angel|partner at"}

card, people, newest = {}, {}, {}
for f in glob.glob(os.path.join(D, "*.json")):
    try: x = json.load(open(f))
    except Exception: continue
    if not isinstance(x, dict): continue
    h = str(x.get("profile", "")).rstrip("/").split("/")[-1].lstrip("@").lower(); fin = (x.get("run") or {}).get("finished_utc") or ""
    def put(s, name, tag, desc):
        if s and (tag or desc):
            t = f"{name or ''}. {tag or ''}. {(desc or '')[:600]}"
            if len(t) > len(card.get(s, "")): card[s] = t
    rec = {"stack": set(), "review": set(), "collection": set(), "upvote": set()}
    for it in (x.get("stacks") or {}).get("items") or []:
        s = slug_of(it.get("url")); put(s, it.get("name"), it.get("tagline"), it.get("description")); s and rec["stack"].add(s)
    for c in (x.get("collections") or {}).get("items") or []:
        for it in c.get("items") or []:
            s = slug_of(it.get("url")); put(s, it.get("name"), it.get("tagline"), None); s and rec["collection"].add(s)
    for it in (x.get("reviews") or {}).get("items") or []:
        s = slug_of(it.get("url")); s and rec["review"].add(s)
    for it in (x.get("upvotes") or {}).get("items") or []:
        s = slug_of(it.get("product_url")); put(s, it.get("name"), it.get("tagline"), it.get("description")); s and rec["upvote"].add(s)
    a = x.get("about") or {}
    rec["who"] = " ".join(str(v) for v in (a.get("headline"), a.get("bio")) if v and str(v) != "None")
    if h and fin >= newest.get(h, ""):
        newest[h] = fin; people[h] = rec
rich, topics = dict(card), {}
for f in glob.glob(os.path.join(PI, "*.json")):
    try: y = json.load(open(f))
    except Exception: continue
    s = y.get("slug"); tp = [t.get("name") for t in (y.get("topics") or []) if isinstance(t, dict)]
    if s and (y.get("tagline") or y.get("description")):
        rich[s] = f"{y.get('name') or ''}. {y.get('tagline') or ''}. {(y.get('description') or '')[:1200]} Topics: {', '.join(tp)}"
    if s and tp: topics[s] = set(tp)
print("people", len(people), "card text", len(card), "rich text", len(rich), "with topics", len(topics), flush=True)

pop = {}
for rec in people.values():
    for s in set().union(*[rec[k] for k in ("stack", "review", "collection", "upvote")]): pop[s] = pop.get(s, 0) + 1
prods = sorted(card); pix = {s: i for i, s in enumerate(prods)}
popv = np.array([pop.get(s, 0) for s in prods], float); dec = pd.qcut(np.log1p(popv) + rng.random(len(popv)) * 1e-6, 10, labels=False)
by_dec = {d: np.where(dec == d)[0] for d in range(10)}

# ---------- candidate sets (built once)
tasks = []   # (person_idx, holdout prod, profile prods, neg prods, neg_kind)
plist = []
for h, rec in people.items():
    p = pid(h)
    if p not in comp: continue
    uses = [(t, s) for t in ("stack", "review", "collection") for s in rec[t] if s in pix]
    if len(uses) < 5: continue
    allmine = {pix[s] for s in set().union(*[rec[k] for k in ("stack", "review", "collection", "upvote")]) if s in pix}
    pi = len(plist); plist.append((p, rec["who"], allmine))
    for t, s in [uses[i] for i in rng.permutation(len(uses))[:10]]:
        tg = pix[s]; prof = [pix[x] for _, x in uses if x != s]
        for kind in ("pop_matched", "random"):
            pool = rng.choice(by_dec[dec[tg]], min(300, len(by_dec[dec[tg]])), replace=False) if kind == "pop_matched" else rng.choice(len(prods), 300, replace=False)
            negs = [i for i in pool if i not in allmine and i != tg][:50]
            if len(negs) >= 20: tasks.append((pi, t, tg, np.array(prof), np.array(negs), kind))
need = sorted({tg for _, _, tg, _, _, _ in tasks} | {i for *_, pr, ng, _ in tasks for i in pr} | {i for *_, ng, _ in tasks for i in ng})
print("people", len(plist), "tasks", len(tasks), "products needed", len(need), flush=True)

from sentence_transformers import SentenceTransformer
def embed(model, texts, key):
    f = os.path.join(OUT, f"emb_{key}.npy")
    if os.path.exists(f): return np.load(f)
    e = SentenceTransformer(model, device="cpu").encode(texts, batch_size=128, normalize_embeddings=True, show_progress_bar=False); np.save(f, e); return e
nidx = {i: k for k, i in enumerate(need)}
E0 = embed("BAAI/bge-small-en-v1.5", [card[prods[i]] for i in need], "small_card")
E1 = embed("BAAI/bge-small-en-v1.5", [rich.get(prods[i], card[prods[i]]) for i in need], "small_rich")
E2 = embed("BAAI/bge-base-en-v1.5", [rich.get(prods[i], card[prods[i]]) for i in need], "base_rich")
whos = [w for _, w, _ in plist]
W1 = embed("BAAI/bge-small-en-v1.5", [w or "-" for w in whos], "who_small"); W2 = embed("BAAI/bge-base-en-v1.5", [w or "-" for w in whos], "who_base")
roles = np.array([[float(bool(re.search(r, w or "", re.I))) for r in ROLES.values()] for w in whos])
print("embedded", E0.shape, E2.shape, flush=True)


def sims(E, prof, cand):
    S = E[[nidx[i] for i in cand]] @ E[[nidx[i] for i in prof]].T; Ss = np.sort(S, 1)
    k = min(5, S.shape[1])
    return Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1), (S > 0.8).mean(1)


rows = []
for ti, (pi, t, tg, prof, negs, kind) in enumerate(tasks):
    cand = np.r_[tg, negs]; y = np.r_[1, np.zeros(len(negs))]
    own = np.array([1.0 if c in plist[pi][2] else 0.0 for c in cand])
    f = {"task": ti, "person": pi, "type": t, "kind": kind, "y": y, "pop": np.log1p(popv[cand] - own)}
    for nm, E in (("s0", E0), ("s1", E1), ("s2", E2)):
        a, b, c, d = sims(E, prof, cand); f[nm + "_top1"], f[nm + "_top5"], f[nm + "_mean"], f[nm + "_hi"] = a, b, c, d
    pt = [topics.get(prods[i], set()) for i in prof]; ntp = sum(1 for x in pt if x) or 1
    f["topic_rate"] = np.array([sum(1 for x in pt if x & topics.get(prods[c], set())) / ntp if topics.get(prods[c]) else np.nan for c in cand])
    f["n_prof"] = np.full(len(cand), np.log1p(len(prof)))
    f["who_sim_small"] = E1[[nidx[c] for c in cand]] @ W1[pi]; f["who_sim_base"] = E2[[nidx[c] for c in cand]] @ W2[pi]
    f["who_len"] = np.full(len(cand), float(len(whos[pi] or "")))
    for k, r in enumerate(ROLES):
        f["role_" + r] = np.full(len(cand), roles[pi, k])
    rows.append(pd.DataFrame(f))
X = pd.concat(rows, ignore_index=True)
print("feature rows", len(X), flush=True)

import lightgbm as lgb
fold = (X.person % 2).to_numpy()
FS = {"S3np": ["s2_top1", "s2_top5", "s2_mean", "s2_hi", "s1_top5", "topic_rate", "n_prof"],
      "S3": ["s2_top1", "s2_top5", "s2_mean", "s2_hi", "s1_top5", "topic_rate", "n_prof", "pop"],
      "S4np": ["s2_top1", "s2_top5", "s2_mean", "s2_hi", "s1_top5", "topic_rate", "n_prof", "who_sim_small", "who_sim_base", "who_len"] + ["role_" + r for r in ROLES],
      "S4": ["s2_top1", "s2_top5", "s2_mean", "s2_hi", "s1_top5", "topic_rate", "n_prof", "pop", "who_sim_small", "who_sim_base", "who_len"] + ["role_" + r for r in ROLES]}
for nm, cols in FS.items():
    X[nm] = np.nan
    for k in (0, 1):
        tr = (fold != k) & (X.kind == "pop_matched").to_numpy(); te = fold == k
        m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, verbose=-1).fit(X.loc[tr, cols], X.y[tr])
        X.loc[te, nm] = m.predict_proba(X.loc[te, cols])[:, 1]
X["S0"], X["S1"], X["S2"], X["S_pop"] = X.s0_top5, X.s1_top5, X.s2_top5, X["pop"]
X["rand"] = rng.random(len(X))


def per_task(s):
    v = X[s].to_numpy(float) + rng.random(len(X)) * 1e-9; task = X.task.to_numpy(); y = X.y.to_numpy()
    start = np.r_[0, np.flatnonzero(np.diff(task)) + 1]; size = np.diff(np.r_[start, len(X)])
    tgt = np.repeat(v[start], size); neg = y == 0                       # the target is the first row of each task
    above = np.add.reduceat((v > tgt) & neg, start); below = np.add.reduceat((v < tgt) & neg, start); nn = size - 1
    first = X.iloc[start]
    return pd.DataFrame({"auc": below / nn, "hit10": (above + 1 <= 10).astype(float), "hit1": (above == 0).astype(float),
                         "person": first.person.to_numpy(), "kind": first.kind.to_numpy(), "type": first.type.to_numpy()})


def boot(v, B=2000):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]


res = {"people": len(plist), "tasks": len(tasks), "rich_text_share_of_needed": float(np.mean([prods[i] in rich and rich[prods[i]] != card.get(prods[i]) for i in need])),
       "topics_share_of_needed": float(np.mean([prods[i] in topics for i in need])), "results": {}}
T = {s: per_task(s) for s in ("rand", "S_pop", "S0", "S1", "S2", "S3np", "S3", "S4np", "S4")}
for kind in ("pop_matched", "random"):
    out = {}
    for s, d in T.items():
        dk = d[d.kind == kind]; pp = dk.groupby("person")[["auc", "hit10", "hit1"]].mean()
        out[s] = {m: boot(pp[m]) for m in ("auc", "hit10", "hit1")}
        if s not in ("rand", "S_pop", "S0"):
            b = T["S0"][T["S0"].kind == kind].groupby("person").auc.mean()
            out[s]["auc_minus_S0 (paired by person)"] = boot((pp.auc - b).dropna())
    res["results"][kind] = out
for typ in ("stack", "review", "collection"):
    res["results"][f"pop_matched by type: {typ}"] = {s: boot(d[(d.kind == "pop_matched") & (d.type == typ)].groupby("person").auc.mean()) for s, d in T.items()}
json.dump(res, open(os.path.join(OUT, "uses_v2.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
