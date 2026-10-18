"""Third held-out eval: live scrapes (G2, Capterra, TrustRadius, Gartner) of 28 products and their model-named rivals,
scored with the SHIPPED agent-mode rating code (mvp/agent_mode.py). Nothing is fit here: k, the offsets and their
weights were all set on the Capterra/G2 snapshots, so this measures transfer to new sites and new products.

Data: session usersim-9c's live scrape (branch claude/modest-wozniak-p0bt3q, experiments/staged_context/out/live/
live_reviews.csv.gz, out/mixture/competitors.json); pass their directory with --data (default /home/user/live).
For each reviewer of a target product (overall rating known):
  global        mean of every other product in the scrape
  rivals        mean of the named rivals' reviews (agent mode's prior)
  own_all       agent mode: the product's own reviews dated before this person (all sites, most recent 100),
                shrunk to rivals with k=10
  own_same_site the same, using only reviews from this person's site
  *+persona     agent_mode.personalize on top (role / size / time used / industry offsets learned on Capterra)

    python live_bench.py [--data DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from mvp import agent_mode as A  # noqa: E402

OUT = HERE / "results/live_bench"


def live_shape(r: dict) -> dict:
    g = lambda k: None if (r.get(k) is None or (isinstance(r.get(k), float) and np.isnan(r[k]))) else r[k]  # noqa: E731
    return {"source": r["site"], "product": r["query"], "role": g("title"), "size": g("size3"), "industry": g("industry"),
            "time_used": g("time_used"), "rating": g("overall_rating"), "nps": g("recommendation_score"),
            "pros": g("pros"), "cons": g("cons"), "text": g("review_text"), "date": g("date")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/home/user/live")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(Path(a.data) / "live_reviews.csv.gz")
    comps = json.loads((Path(a.data) / "competitors.json").read_text())
    d = d[d.overall_rating.notna()].copy()
    d["date"] = pd.to_datetime(d.date, errors="coerce")
    rows = []
    for target, rivals in comps.items():
        own_all = d[d["query"] == target]
        riv = d[d["query"].isin(rivals)]
        if len(own_all) < 20 or riv.empty:
            continue
        rv = [live_shape(x) for x in riv.to_dict("records")]
        glob = d[d["query"] != target].overall_rating.mean()
        for r in own_all.to_dict("records"):
            if pd.isna(r["date"]):
                continue
            past = own_all[(own_all.date < r["date"]) & (own_all.rid != r["rid"])].sort_values("date", ascending=False)
            persona = {"role": r.get("title") if isinstance(r.get("title"), str) else "",
                       "company_size": r.get("size3") if isinstance(r.get("size3"), str) else None,
                       "industry": r.get("industry") if isinstance(r.get("industry"), str) else None,
                       "time_used": r.get("time_used") if isinstance(r.get("time_used"), str) else None}
            row = {"rid": r["rid"], "product": target, "site": r["site"], "y": r["overall_rating"], "global": glob,
                   "n_past": len(past)}
            for name, own in (("own_all", past), ("own_same_site", past[past.site == r["site"]])):
                rat = A.rating_estimates([live_shape(x) for x in own.to_dict("records")], rv, persona)
                A.personalize(rat, persona)
                o = rat["overall_rating"]
                row["rivals"] = o["rivals_mean"]
                row[name] = o["estimate"]
                row[f"{name}+persona"] = o.get("for_this_persona", o["estimate"])
            rows.append(row)
    X = pd.DataFrame(rows)
    X.to_csv(OUT / "per_person.csv", index=False)
    methods = ["global", "rivals", "own_all", "own_all+persona", "own_same_site", "own_same_site+persona"]
    res = []
    for site, g in list(X.groupby("site")) + [("all", X)]:
        r = {"site": site, "n": len(g), "products": g["product"].nunique()}
        for m in methods:
            r[f"{m}_rmse"] = float(np.sqrt(((g[m] - g.y) ** 2).mean()))
            ws = [z[m].rank().corr(z.y.rank()) for _, z in g.groupby("product") if len(z) >= 10 and z[m].std() > 0 and z.y.std() > 0]
            r[f"{m}_within_sp"] = float(np.mean(ws)) if ws else np.nan
        res.append(r)
    R = pd.DataFrame(res)
    R.to_csv(OUT / "summary.csv", index=False)
    pd.set_option("display.width", 250)
    print(R[["site", "n", "products"] + [f"{m}_rmse" for m in methods]].round(3).to_string(index=False))
    print("\nwithin-product Spearman:")
    print(R[["site"] + [f"{m}_within_sp" for m in methods]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
