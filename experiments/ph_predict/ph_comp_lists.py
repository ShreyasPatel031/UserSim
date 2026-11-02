"""Competitor lists from Product Hunt's own "Similar Products" (raw/ph_alternatives/similar_products_all.jsonl, read by
Grok Bot's team on Nov 1), mapped to launches we have, safe to use at launch time.
For launch x with similar products s1..s5 (page order):
  - each similar product's launches in our data come from the same file (launch_id -> product_slug);
  - competitor launches = the most recent launch of each similar product at least 2 days before x (final votes known);
  - safe = no similar product first appears in our data on or after x's day. The lists were read on Nov 1, so a product
    that launched after x could be on x's list only through hindsight. Products never launched in our data (established
    products such as Zapier) are taken as older than x; that assumption is reported in the counts.
Output data/ph_comp_lists.json {launch_id: {"ids": [most recent launch per similar product, >= 2 days before],
"all_ids": [every earlier launch of the similar products, for "used a competitor"], "pos": [their list position],
"safe": bool, "listed": n, "in_data": m}}.
usage: python ph_comp_lists.py <similar_products_all.jsonl>"""
import glob, json, sys
from datetime import date

D = "data"


def main(path):
    day = {}
    for f in glob.glob(f"{D}/days/*.json"):
        for p in json.load(open(f)):
            day[str(p["id"])] = f[-15:-5]
    R = [json.loads(l) for l in open(path) if l.strip()]
    prod = {}   # product_slug -> [(day, launch_id)]
    for r in R:
        i = str(r.get("launch_id")); d = day.get(i) or r.get("launch_day")
        if r.get("product_slug") and d:
            prod.setdefault(r["product_slug"], []).append((d, i))
    for v in prod.values():
        v.sort()
    od = lambda d: date.fromisoformat(d).toordinal()
    out, n_safe, n_any = {}, 0, 0
    for r in R:
        x = str(r.get("launch_id")); dx = day.get(x)
        if not dx or not r.get("similar_products"):
            continue
        sims = [s["slug"] for s in r["similar_products"] if s.get("slug") and s["slug"] != r.get("product_slug")]
        ids, all_ids, pos, safe, in_data = [], [], [], True, 0
        for s in sims:
            L = prod.get(s)
            if not L:
                continue
            in_data += 1
            if L[0][0] >= dx:
                safe = False
            before = [i for d, i in L if od(d) <= od(dx) - 2]
            if before:
                ids.append(before[-1])
            for d, i in L:
                if d < dx:
                    all_ids.append(i); pos.append(sims.index(s) + 1)
        out[x] = {"ids": ids, "all_ids": all_ids, "pos": pos, "safe": safe, "listed": len(sims), "in_data": in_data}
        n_safe += safe; n_any += bool(ids)
    json.dump(out, open(f"{D}/ph_comp_lists.json", "w"))
    S = [v for v in out.values() if v["safe"]]
    print(json.dumps({"launches_with_list": len(out), "safe": n_safe, "safe_with_competitor_launches": sum(bool(v["ids"]) for v in S),
                      "mean_competitor_launches_when_safe": round(sum(len(v["ids"]) for v in S) / max(len(S), 1), 2),
                      "share_listed_products_in_data": round(sum(v["in_data"] for v in out.values()) / max(sum(v["listed"] for v in out.values()), 1), 3)}))


if __name__ == "__main__":
    main(sys.argv[1])
