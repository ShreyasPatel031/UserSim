"""Can Gemini pick a product's competitors better than meaning similarity? Same answer key and products as
comp_validate.py (Product Hunt Alternatives chosen by reviewers; 281 products with text). Two ways:
  rerank   Gemini sees the product and its 50 nearest candidates by meaning (catalogue = reviewed products + all
           launches) and picks the 5 most direct competitors
  name     Gemini names the 5 main competitors from its own knowledge (no list); names matched to the real
           alternatives' names (case-insensitive, either contains the other)
Scores as comp_validate.py: share of real alternatives in the 5, and how often at least one is.
usage: python comp_gemini.py alt_products.json ph_alts.json -> results/comp_gemini.json"""
import glob, json, re, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import llm


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def match(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a))


def main(prod_file, alts_file):
    from sentence_transformers import SentenceTransformer
    P = json.load(open(prod_file)); A = json.load(open(alts_file))
    L = []
    for f in glob.glob("data/days/*.json"):
        for p in json.load(open(f)):
            L.append({"name": p["name"], "tagline": p.get("tagline") or "", "description": (p.get("description") or "")[:600]})
    keys = list(P); cat = [P[k] for k in keys] + L
    txt = lambda v: f"{v['name']}. {v.get('tagline') or ''}. {(v.get('description') or '')[:600]}"
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    E = m.encode([txt(v) for v in cat], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
    tests = [(i, k) for i, k in enumerate(keys) if {a for a in A.get(k, {}) if a in P and a != k}]

    def one(t):
        i, k = t
        real = [P[a]["name"] for a in A[k] if a in P and a != k]
        s = E @ E[i]; s[i] = -9
        cands, seen = [], {norm(P[k]["name"])}
        for j in np.argsort(-s):
            n = cat[j]["name"]
            if norm(n) not in seen:
                seen.add(norm(n)); cands.append(cat[j])
            if len(cands) == 50:
                break
        me = f"{P[k]['name']}: {P[k].get('tagline') or ''}. {(P[k].get('description') or '')[:400]}"
        lst = "\n".join(f"{n + 1}. {c['name']}: {c['tagline']}" for n, c in enumerate(cands))
        r1 = llm.call(f"Product: {me}\n\nCandidates:\n{lst}\n\nWhich 5 candidates are this product's most direct competitors (a user would "
                      'choose one instead of the other)? Reply with JSON only: {"picks": [five candidate numbers]}', max_tokens=100)
        mm = re.search(r'"picks"\s*:\s*\[([^\]]*)\]', r1 or "")
        rerank = [cands[int(x) - 1]["name"] for x in re.findall(r"\d+", mm.group(1)) if 1 <= int(x) <= len(cands)][:5] if mm else []
        r2 = llm.call(f"Product: {me}\n\nName this product's 5 main competitors (products a user would choose instead). "
                      'Reply with JSON only: {"competitors": ["name", ...]}', max_tokens=150)
        mm = re.search(r'"competitors"\s*:\s*\[([^\]]*)\]', r2 or "")
        named = re.findall(r'"([^"]+)"', mm.group(1))[:5] if mm else []
        meaning = [c["name"] for c in cands[:5]]
        out = {}
        for meth, picks in (("meaning", meaning), ("rerank", rerank), ("name", named)):
            hits = [r for r in real if any(match(r, p) for p in picks)]
            out[meth] = (len(hits) / len(real), float(bool(hits)))
        return out
    with ThreadPoolExecutor(12) as ex:
        R = list(ex.map(one, tests))
    res = {"products_tested": len(R), "usd": round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 3)}
    for meth in ("meaning", "rerank", "name"):
        res[meth] = {"share_of_alternatives_in_5": round(100 * float(np.mean([r[meth][0] for r in R])), 1),
                     "at_least_one_in_5": round(100 * float(np.mean([r[meth][1] for r in R])), 1)}
    json.dump(res, open("results/comp_gemini.json", "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
