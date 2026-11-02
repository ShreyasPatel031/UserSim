"""Competitor outcomes as a demand prior over the honest day-calibrated control (Grok Bot, for the orchestrator and Shreyas,
Nov 2). Hypothesis: how a launch's real competitors (PH Similar Products, raw/ph_alternatives/similar_products_all.jsonl)
did on Product Hunt before this launch's day predicts its own launch-day demand.
Competitors of launch i = its similar products; a competitor's earlier launches are the launches in our data whose product
slug (from the same file, or the launch slug) is that product and whose day is before i's day. Dated outcomes only:
  cmp_rank_best    best final daily rank among those earlier launches (fixed when their day closed)
  cmp_votes_max, cmp_votes_med   final votes (log1p), only from launches at least 7 days before i's day (votes settle
                   within days; later-read counts on very recent launches would leak)
  cmp_days_since   days since the most recent competitor launch
  cmp_n            number of competitor launches before the day; cmp_recent30: one in the last 30 days (crowding)
Not used: the products' ratings / review counts (read now). Launches without an earlier-launched competitor get NaN.
Control and offset exactly as simlab/e1_honest.py (honest launch model + day terms), same split (May–Oct), 5 seeds.
Decision rule fixed before the run: daily top 3 vs the control with a 95% interval above 0.
usage: SIMLAB_DATA=data_v2 python -m simlab.cmp_outcomes <similar_products_all.jsonl> <honest_preds.parquet> -> reports/cmp_outcomes.json"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from . import vote_model2 as V, e1_honest as EH

HERE = os.path.dirname(os.path.abspath(__file__))
CMP = ["cmp_rank_best", "cmp_votes_max", "cmp_votes_med", "cmp_days_since", "cmp_n", "cmp_recent30"]


def competitor_features(sim_path):
    from . import store
    _, I, _ = store.load(); I = I.assign(id=I.id.astype(str))
    rows = [json.loads(l) for l in open(sim_path) if l.strip()]
    prod_of = {str(r["launch_id"]): r.get("product_slug") for r in rows}
    launches_of = defaultdict(list)   # product slug -> [(day, dailyRank, votes)]
    for r in I.itertuples():
        for p in {prod_of.get(r.id), r.slug} - {None, ""}:
            launches_of[p].append((r.day, r.out_dailyRank, r.out_votes))
    out = []
    for r in rows:
        d = r["launch_day"][:10]; me = r.get("product_slug")
        past = [(dd, rk, v) for s in (r.get("similar_products") or []) if s.get("slug") and s["slug"] != me
                for dd, rk, v in launches_of.get(s["slug"], []) if dd < d]
        f = {"id": str(r["launch_id"]), "cmp_has_list": bool(r.get("similar_products"))}
        if past:
            dt = pd.Timestamp(d)
            ranks = [rk for _, rk, _ in past if pd.notna(rk)]
            settled = [np.log1p(v) for dd, _, v in past if pd.notna(v) and (dt - pd.Timestamp(dd)).days >= 7]
            since = min((dt - pd.Timestamp(dd)).days for dd, _, _ in past)
            f.update(cmp_rank_best=min(ranks) if ranks else np.nan, cmp_votes_max=max(settled) if settled else np.nan,
                     cmp_votes_med=float(np.median(settled)) if settled else np.nan, cmp_days_since=since, cmp_n=len(past),
                     cmp_recent30=float(since <= 30))
        out.append(f)
    return pd.DataFrame(out)


def main(sim_path, honest_path):
    D, promo, hist, page = EH.load(honest_path)
    Fc = competitor_features(sim_path)
    D = D.merge(Fc, on="id", how="left")
    for c in CMP:
        if c not in D:
            D[c] = np.nan
    D["cmp_has_earlier"] = D.cmp_n.notna()
    variants = {"control": V.DAY, "+ competitor outcomes": CMP + V.DAY}
    months = sorted(D.mon.unique()); parts = []
    for m in months[1:]:
        tr, te = D[D.mon < m], D[D.mon == m].copy()
        c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
        for name, feats in variants.items():
            te[f"mu_{name}"] = np.mean([EH.fit_seed(tr, te, feats, set(), s) for s in range(5)], 0)
        parts.append(te); print("month", m, flush=True)
    T = pd.concat(parts); rng = np.random.default_rng(0)
    cov = {"with_similar_list": round(float(T.cmp_has_list.fillna(False).mean()), 3), "with_earlier_competitor_launch": round(float(T.cmp_has_earlier.mean()), 3),
           "by_month_earlier_competitor": {m: round(float(g.cmp_has_earlier.mean()), 3) for m, g in T.groupby("mon")}}
    name = "+ competitor outcomes"
    r = {"scores": V.boards(T, f"mu_{name}", rng),
         "vs_control": {k.replace("_vs_lm", ""): v for k, v in V.boards(T, f"mu_{name}", rng, base="mu_control").items() if k.endswith("_vs_lm")}}
    mon = {}
    for m, g in T.groupby("mon"):
        a, b = V.boards(g, f"mu_{name}", rng), V.boards(g, "mu_control", rng)
        mon[m] = {f"{w}_top{k}": [a[f"{w}_top{k}"], b[f"{w}_top{k}"]] for w in ("daily", "weekly") for k in (3, 5, 10)}
    r["by_month"] = mon
    r["months_better_tied_worse"] = {key: [sum(v[key][0] > v[key][1] for v in mon.values()), sum(v[key][0] == v[key][1] for v in mon.values()),
                                           sum(v[key][0] < v[key][1] for v in mon.values())] for key in ("daily_top3", "daily_top5", "daily_top10")}
    r["passes_rule"] = bool(r["vs_control"]["daily_top3"][1][0] > 0)
    res = {"launches": len(T), "days": int(T.day.nunique()), "weeks": int(T.week.nunique()), "months_tested": sorted(T.mon.unique()), "coverage": cov,
           "decision_rule": "daily top 3 vs the day-calibrated control, 95% interval above 0",
           "honest launch model alone": V.boards(T, "mu_lm", rng),
           "control": V.boards(T, "mu_control", rng), "variant": r}
    json.dump(res, open(os.path.join(HERE, "reports", "cmp_outcomes.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in res.items() if k != "variant"}, indent=1, default=str)); print(json.dumps(r["vs_control"])); print(r["months_better_tied_worse"], r["passes_rule"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
