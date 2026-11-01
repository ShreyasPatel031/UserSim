"""Product Hunt's own "Similar Products" (raw/ph_alternatives, read by Grok Bot's team) against the same answer key as
comp_validate.py / comp_gemini.py: Product Hunt Alternatives picked by reviewers (ph_alts.json), restricted as there to
alternatives we have text for (alt_products.json). For every answer-key product that has a Similar Products list
(matched on product_slug), score the list's first 5: share of the real alternatives in it, and whether at least one is.
A similar product counts as a hit when its slug is a real alternative's slug, or its name matches (as comp_gemini.match).
Caveat printed with the result: if Product Hunt builds Similar Products from reviewers' alternatives, this test is
partly circular; the share of list entries that are anyone's reviewed alternative is reported to gauge that.
usage: python comp_validate_ph.py similar_products.jsonl ph_alts.json alt_products.json -> results/comp_validate_ph.json"""
import json, sys
import numpy as np
from comp_gemini import match


def main(sim_file, alts_file, prod_file):
    A, P = json.load(open(alts_file)), json.load(open(prod_file))
    S = {}
    for l in open(sim_file):
        r = json.loads(l)
        if r.get("similar_products") and r["product_slug"] not in S:
            S[r["product_slug"]] = r["similar_products"]
    any_alt = {a for v in A.values() for a in v}
    rows, inkey = [], []
    for k, alts in A.items():
        real = {a for a in alts if a in P and a != k}
        if not real or k not in S:
            continue
        top = S[k][:5]
        hit = {a for a in real if any(s["slug"] == a or match(s["name"], P[a]["name"]) for s in top)}
        rows.append((len(hit) / len(real), float(bool(hit))))
        inkey += [s["slug"] in any_alt for s in top]
    res = {"products_tested": len(rows), "lists_available": len(S),
           "similar_products": {"share_of_alternatives_in_5": round(100 * float(np.mean([r[0] for r in rows])), 1) if rows else None,
                                "at_least_one_in_5": round(100 * float(np.mean([r[1] for r in rows])), 1) if rows else None},
           "share_of_list_entries_that_are_some_reviewed_alternative": round(100 * float(np.mean(inkey)), 1) if inkey else None}
    if rows:   # 95% bootstrap intervals over products
        rng = np.random.default_rng(0); R = np.array(rows)
        B = np.array([R[rng.integers(0, len(R), len(R))].mean(0) for _ in range(5000)])
        res["similar_products"]["ci95_share"] = [round(100 * x, 1) for x in np.percentile(B[:, 0], [2.5, 97.5])]
        res["similar_products"]["ci95_at_least_one"] = [round(100 * x, 1) for x in np.percentile(B[:, 1], [2.5, 97.5])]
    json.dump(res, open("results/comp_validate_ph.json", "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
