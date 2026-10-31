"""Are the competitors we pick the real ones? Answer key: Product Hunt's own Alternatives, picked by real users in their
reviews (1,059 product -> alternative pairs over 372 products; profile_tabs). Each product's name, tagline,
description and topics come from the official API (alt_products.json). Same text and model as embed.py (bge-small;
"name. tagline. description[:600]").
For every product with at least one alternative we have text for, rank all other products in a catalogue by
  meaning    cosine of the embeddings (what cmp_features.py / comp_test use for launches)
  topics     number of shared Product Hunt topics (ties broken at random)
  random
in two catalogues: the 619 reviewed / alternative products only, and those plus all 6,694 launches in data/days
(distractors, as in real use). Scores: share of real alternatives in the top 5 / 10 / 50, and how often at least one
real alternative is in the top 5.
usage: python comp_validate.py alt_products.json ph_alts.json -> results/comp_validate.json"""
import glob, json, sys
import numpy as np


def main(prod_file, alts_file):
    from sentence_transformers import SentenceTransformer
    P = json.load(open(prod_file)); A = json.load(open(alts_file))
    launches = {}
    for f in glob.glob("data/days/*.json"):
        for p in json.load(open(f)):
            launches["L" + str(p["id"])] = {"name": p["name"], "tagline": p.get("tagline") or "", "description": (p.get("description") or "")[:600],
                                            "topics": [e["node"]["name"] for e in (p.get("topics") or {}).get("edges", [])]}
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    txt = lambda v: f"{v['name']}. {v.get('tagline') or ''}. {(v.get('description') or '')[:600]}"
    keys = list(P); keysL = list(launches)
    EP = m.encode([txt(P[k]) for k in keys], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
    EL = m.encode([txt(launches[k]) for k in keysL], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
    names = {k: P[k]["name"].lower() for k in keys}
    rng = np.random.default_rng(0); res = {}
    for cat in ("reviewed products only", "plus all launches"):
        ck = keys + (keysL if cat == "plus all launches" else [])
        E = EP if cat == "reviewed products only" else np.vstack([EP, EL])
        topics = [set(P[k]["topics"]) if k in P else set(launches[k]["topics"]) for k in ck]
        cname = [names.get(k) or launches[k]["name"].lower() for k in ck]
        rows = {"meaning": [], "topics": [], "random": []}
        for i, k in enumerate(keys):
            real = {a for a in A.get(k, {}) if a in P and a != k}
            if not real:
                continue
            realnames = {names[a] for a in real}
            sims = E @ EP[i]; sims[i] = -9
            for j, nm in enumerate(cname):   # drop the product itself if it also appears as a launch
                if nm == names[k] and j != i:
                    sims[j] = -9
            tscore = np.array([len(topics[i] & t) for t in topics], float) + rng.random(len(ck)) * 0.5; tscore[i] = -9
            for method, score in (("meaning", sims), ("topics", tscore), ("random", rng.random(len(ck)))):
                order = np.argsort(-score)
                ranked = [cname[j] for j in order[:50]]
                hit = lambda n: len(realnames & set(ranked[:n])) / len(realnames)
                rows[method].append((hit(5), hit(10), hit(50), float(bool(realnames & set(ranked[:5])))))
        res[cat] = {"products_tested": len(rows["meaning"]), "catalogue": len(ck),
                    **{m_: dict(zip(("share_of_alternatives_in_top5", "in_top10", "in_top50", "at_least_one_in_top5"),
                                    [round(100 * float(np.mean([r[c] for r in v])), 1) for c in range(4)])) for m_, v in rows.items()}}
    json.dump(res, open("results/comp_validate.json", "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
