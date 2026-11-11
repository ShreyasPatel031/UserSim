"""'Uses' test for the user simulation (orchestrator Nov 11). Do people's stacks / reviews / collections ("wants or uses",
not leaderboard-driven) follow a content taste we can model, and is it the same taste as their upvotes?
Design fixed before running (log 2026-11-11 "uses test"):
  products   slug from product URLs; text = name. tagline. description, from every card in the person files (stack cards,
             upvote cards, collection item cards). Review text written by the person is NEVER used.
  people     store_v3 complete people with >= 5 uses items (stack + review + collection) whose product has text.
  holdout    up to 10 uses items per person, each held out in turn; profile = the person's other items.
  negatives  (a) 50 random products with text, not in the person's lists; (b) 50 popularity-matched products: same decile of
             pool popularity (number of distinct people in the files listing the product anywhere, leave-this-person-out).
  scorers    taste = mean of the top-5 cosine similarities (bge-small) between the candidate and the profile;
             popularity = leave-person-out pool count; random.
  profiles   U = other uses items; V = the person's upvoted products (cross-signal: do upvotes predict uses?); UV = both.
  reverse    hold out an upvoted product, profile = the person's uses items only (do uses predict upvotes?).
  metrics    Hit@1 and Hit@10 among 51 candidates, AUC (share of negatives scored below), means with person-bootstrap CIs,
             split by held-out item type (stack / review / collection).
    python uses_test.py <person_files_dir> <salt> <store_v3 persons.parquet> <out.json>
"""
import glob, hashlib, json, os, re, sys
import numpy as np, pandas as pd

D, SALT_F, PERS, OUT = sys.argv[1:5]
SALT = open(SALT_F).read().strip(); rng = np.random.default_rng(0)
comp = set(pd.read_parquet(PERS).query("complete").person_id)
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
slug_of = lambda u: (re.search(r"/products/([^/?#]+)", str(u or "")) or [None, None])[1]

text, people, newest = {}, {}, {}
for f in glob.glob(os.path.join(D, "*.json")):
    try: x = json.load(open(f))
    except Exception: continue
    if not isinstance(x, dict): continue
    h = str(x.get("profile", "")).rstrip("/").split("/")[-1].lstrip("@").lower(); fin = (x.get("run") or {}).get("finished_utc") or ""
    def card(s, name, tag, desc):
        if s and (tag or desc):
            t = f"{name or ''}. {tag or ''}. {(desc or '')[:600]}"
            if len(t) > len(text.get(s, "")): text[s] = t
    rec = {"stack": set(), "review": set(), "collection": set(), "upvote": set()}
    for it in (x.get("stacks") or {}).get("items") or []:
        s = slug_of(it.get("url")); card(s, it.get("name"), it.get("tagline"), it.get("description")); s and rec["stack"].add(s)
    for c in (x.get("collections") or {}).get("items") or []:
        for it in c.get("items") or []:
            s = slug_of(it.get("url")); card(s, it.get("name"), it.get("tagline"), None); s and rec["collection"].add(s)
    for it in (x.get("reviews") or {}).get("items") or []:
        s = slug_of(it.get("url")); s and rec["review"].add(s)
    for it in (x.get("upvotes") or {}).get("items") or []:
        s = slug_of(it.get("product_url")); card(s, it.get("name"), it.get("tagline"), it.get("description")); s and rec["upvote"].add(s)
    if h and fin >= newest.get(h, ""):
        newest[h] = fin; people[h] = rec
print("files", len(people), "products with text", len(text), flush=True)

pop = {}
for rec in people.values():
    for s in set().union(*rec.values()): pop[s] = pop.get(s, 0) + 1
prods = sorted(text); pix = {s: i for i, s in enumerate(prods)}
from sentence_transformers import SentenceTransformer
E = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").encode([text[s] for s in prods], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
popv = np.array([pop.get(s, 0) for s in prods], float); dec = pd.qcut(np.log1p(popv) + rng.random(len(popv)) * 1e-6, 10, labels=False)
by_dec = {d: np.where(dec == d)[0] for d in range(10)}
print("embedded", E.shape, flush=True)


def taste(prof, cand):
    S = E[cand] @ E[prof].T; k = min(5, S.shape[1])
    return np.sort(S, 1)[:, -k:].mean(1)


def evaluate(target, prof_idx, excl, own_pop):
    out = {}
    for neg in ("random", "pop_matched"):
        if neg == "random":
            pool = rng.choice(len(prods), 300, replace=False)
        else:
            pool = rng.choice(by_dec[dec[target]], min(300, len(by_dec[dec[target]])), replace=False)
        negs = [i for i in pool if i not in excl and i != target][:50]
        if len(negs) < 20: continue
        cand = np.array([target] + negs)
        sc = {"taste": taste(prof_idx, cand) if len(prof_idx) else rng.random(len(cand)),
              "popularity": popv[cand] - own_pop[cand] + rng.random(len(cand)) * 1e-6, "random": rng.random(len(cand))}
        for m, s in sc.items():
            r = 1 + int((s[1:] > s[0]).sum()); out[(neg, m)] = (float(r == 1), float(r <= 10), float((s[1:] < s[0]).mean()))
    return out


rows = []
for h, rec in people.items():
    p = pid(h)
    if p not in comp: continue
    uses = [(t, s) for t in ("stack", "review", "collection") for s in rec[t] if s in pix]
    ups = [s for s in rec["upvote"] if s in pix]
    allmine = {pix[s] for s in set().union(*rec.values()) if s in pix}
    own = np.zeros(len(prods)); own[list(allmine)] = 1           # leave-this-person-out popularity
    if len(uses) >= 5:
        sel = [uses[i] for i in rng.permutation(len(uses))[:10]]
        for t, s in sel:
            tg = pix[s]; others = [pix[x] for _, x in uses if x != s]
            for prof_name, prof in (("U", others), ("V", [pix[x] for x in ups if x != s]), ("UV", others + [pix[x] for x in ups if x != s])):
                if not prof: continue
                for (neg, m), v in evaluate(tg, np.array(prof), allmine, own).items():
                    if m != "taste" and prof_name != "U": continue
                    rows.append({"person": p, "task": "uses", "type": t, "profile": prof_name if m == "taste" else "-", "neg": neg, "scorer": m, "hit1": v[0], "hit10": v[1], "auc": v[2]})
    if len(uses) >= 5 and len(ups) >= 3:      # reverse: uses -> held-out upvote
        for s in [ups[i] for i in rng.permutation(len(ups))[:10]]:
            tg = pix[s]; prof = np.array([pix[x] for _, x in uses if x != s])
            for (neg, m), v in evaluate(tg, prof, allmine, own).items():
                rows.append({"person": p, "task": "upvote_from_uses", "type": "upvote", "profile": "U" if m == "taste" else "-", "neg": neg, "scorer": m, "hit1": v[0], "hit10": v[1], "auc": v[2]})
R = pd.DataFrame(rows)


def boot(df, col, B=2000):
    g = df.groupby("person")[col].mean().to_numpy()
    bs = [g[rng.integers(0, len(g), len(g))].mean() for _ in range(B)]
    return [round(float(g.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(g))]


res = {"products_with_text": len(prods), "people_eligible": int(R.person.nunique()), "rows": len(R), "table": {}}
for key, g in R.groupby(["task", "type", "neg", "scorer", "profile"]):
    res["table"][" | ".join(key)] = {m: boot(g, m) for m in ("hit1", "hit10", "auc")}
for key, g in R[R.task == "uses"].groupby(["neg", "scorer", "profile"]):
    res["table"][" | ".join(("uses", "ALL") + key)] = {m: boot(g, m) for m in ("hit1", "hit10", "auc")}
json.dump(res, open(OUT, "w"), indent=1)
for k, v in res["table"].items(): print(k, v)
