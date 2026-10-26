"""seg_: the kinds of people (segments2 labels) among the sampled people who follow a launch's poster/builders,
or backed the team before. Counts (log) per role / seniority / company type / tech level / buyer type, plus US share.
Output: data/seg_features.json"""
import glob, gzip, json, os
from collections import Counter, defaultdict
import numpy as np

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FIELDS = {"role": ["founder_exec", "engineer", "marketing_growth", "investor", "designer", "product", "creator"],
          "seniority": ["founder_c_level", "senior_lead"],
          "company_type": ["own_startup", "big_tech", "enterprise", "agency_consulting"],
          "tech_level": ["builds_software", "non_technical"],
          "buyer_type": ["enterprise_buyer", "team_lead_buyer", "developer_adopter", "individual_prosumer"]}


def main():
    seg = {}
    for l in open(f"{D}/segments2.jsonl"):
        r = json.loads(l)
        if r.get("labels"):
            seg[r["username"]] = r["labels"]
    fans = defaultdict(set)
    for l in gzip.open(f"{D}/ph_following.jsonl.gz", "rt"):
        r = json.loads(l)
        for u, _ in r.get("following") or []:
            fans[u].add(r["username"])
    out = {}
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        for p in json.load(open(fn)):
            team = ({m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")}) - {None}
            F = [seg[u] for u in set().union(*[fans.get(m, set()) for m in team]) if u in seg] if team else []
            row = {"seg_n": float(np.log1p(len(F)))}
            for f, vals in FIELDS.items():
                c = Counter(x.get(f) for x in F)
                for v in vals:
                    row[f"seg_{f}_{v}"] = float(np.log1p(c[v]))
                    row[f"seg_{f}_{v}_share"] = c[v] / len(F) if F else np.nan
            us = sum("united states" in str(x.get("country", "")).lower() for x in F)
            row["seg_us_share"] = us / len(F) if F else np.nan
            out[p["id"]] = row
    json.dump(out, open(f"{D}/seg_features.json", "w"))
    print(len(out))


if __name__ == "__main__":
    main()
