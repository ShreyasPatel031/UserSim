"""TARGETS-0: how much room the simulation has on the targets that matter. Builds the truth sets and scores the structural
model on each. No model calls.

  python -m simharness.targets0 --work WORK [--sync gs://.../tmp/targets0]

WORK holds local copies of (all private, from gs://usersim-bakeoff-347838016394/usersim_sim):
  bt/<day>.json              results/structural/backtest/<day>.json (structural scores frozen at 00:05; final rank and votes)
  launches/*.parquet         tables/launches (warehouse: day, makers, daily_rank, weekly_rank, monthly_rank, votes)
  tax/launch_categories.parquet, tax/products.parquet   simharness/taxonomy
  similar_products_all.jsonl raw/ph_alternatives (launch -> product slug, to Nov 1)
  pinfo/*.json               raw/products_info (official API post(slug): post_id, reviews_count, reviews_rating; Nov 11)
  store/events.parquet, store/persons.parquet           raw/population/store_v3 (held upvotes, account join dates)

Parts:
  1. Structural ranks 11-20: which launches make the real daily top 10, by category, held-backer quality (truth side),
     first launch vs relaunch, number of makers. Effect sizes with day-bootstrap 95% intervals.
  2. Weekly and monthly top 10: truth from the warehouse weekly_rank / monthly_rank (PH API weeklyRank / monthlyRank;
     checked against raw/ph_at_launch/<day>/weekly_close). Structural capture from the daily 00:05 scores aggregated
     over the period (only periods whose every day has a frozen structural file are scored).
  3. Sustained outcomes per launch (still online, reviews and rating now, later relaunches) against structural score and
     daily rank: Spearman / AUC with intervals, and the share daily rank leaves unexplained.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr, rankdata
from sklearn.metrics import roc_auc_score

O = lambda d: (pd.Timestamp(str(d)[:10]) - pd.Timestamp("1970-01-01")).days
RNG = np.random.default_rng(0)


def boot_mean(x, B=2000):
    x = np.array([v for v in x if v is not None and not np.isnan(v)], float)
    if len(x) < 2:
        return {"mean": float(x.mean()) if len(x) else None, "lo": None, "hi": None, "n": int(len(x))}
    m = RNG.choice(x, (B, len(x))).mean(1)
    return {"mean": round(float(x.mean()), 4), "lo": round(float(np.percentile(m, 2.5)), 4),
            "hi": round(float(np.percentile(m, 97.5)), 4), "n": int(len(x))}


def boot_clustered(df, stat, cluster="day", B=1000):
    """stat(df) -> float; bootstrap over clusters."""
    groups = [g for _, g in df.groupby(cluster)]
    est = stat(df)
    vals = []
    for _ in range(B):
        pick = RNG.integers(0, len(groups), len(groups))
        s = stat(pd.concat([groups[i] for i in pick]))
        if s is not None and not np.isnan(s):
            vals.append(s)
    return {"est": None if est is None or np.isnan(est) else round(float(est), 4),
            "lo": round(float(np.percentile(vals, 2.5)), 4) if vals else None,
            "hi": round(float(np.percentile(vals, 97.5)), 4) if vals else None, "n": int(len(df)), "clusters": len(groups)}


def auc(y, s):
    y = np.asarray(y, bool); s = np.asarray(s, float)
    ok = ~np.isnan(s)
    y, s = y[ok], s[ok]
    return roc_auc_score(y, s) if 0 < y.sum() < len(y) else np.nan


def sp(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    return spearmanr(a[ok], b[ok]).correlation if ok.sum() > 5 else np.nan


# ------------------------------------------------------------------ loading
def load(W):
    days = {}
    for f in sorted(glob.glob(f"{W}/bt/*.json")):
        j = json.load(open(f))
        by = j["truth"].get("by_id") or {}
        days[j["day"]] = {"model": j.get("structural_model"),
                          "launches": [{"id": str(x["id"]), "srank": int(x["structural_rank"]), "score": x.get("structural_score")}
                                       for x in j["launches"]],
                          "truth": {str(k): (v.get("final_rank"), v.get("votes")) for k, v in by.items()}}
    L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{W}/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
    L["id"] = L.id.astype(str)
    L["d"] = L.day.astype(str).str[:10]
    L["n_makers"] = L.makers.map(lambda m: len(json.loads(m)) if isinstance(m, str) and m.startswith("[") else np.nan)
    cats = pd.read_parquet(f"{W}/tax/launch_categories.parquet")
    cats["item_id"] = cats.item_id.astype(str)
    prods = pd.read_parquet(f"{W}/tax/products.parquet").set_index("slug")
    sim = {}
    for l in open(f"{W}/similar_products_all.jsonl"):
        r = json.loads(l)
        if r.get("product_slug"):
            sim[str(r["launch_id"])] = r["product_slug"]
    pinfo = {}
    for f in glob.glob(f"{W}/pinfo/*.json"):
        try:
            j = json.load(open(f))
        except Exception:  # noqa: BLE001
            continue
        if j.get("http") == 200 and j.get("post_id"):
            pinfo[str(j["post_id"])] = {"reviews_count": j.get("reviews_count"), "reviews_rating": j.get("reviews_rating"), "fetched_at": j.get("fetched_at")}
    return days, L, cats, prods, sim, pinfo


def backer_quality(W, days):
    """Truth-side held-backer quality per (day, launch): held people who upvoted it; their state as of D-1."""
    U = pq.read_table(f"{W}/store/events.parquet", columns=["person_id", "kind", "target_id"], filters=[("kind", "=", "upvote")]).to_pandas()
    U = U.drop_duplicates(["person_id", "target_id"])
    L = pd.concat([pd.read_parquet(f, columns=["id", "day"]) for f in glob.glob(f"{W}/launches/*.parquet")]).drop_duplicates("id", keep="last")
    lday = {str(i): O(d) for i, d in zip(L.id, L.day)}
    U["lday"] = U.target_id.map(lday)
    P = pd.read_parquet(f"{W}/store/persons.parquet", columns=["person_id", "joined"])
    joined = {p: (O(j) if pd.notna(j) else None) for p, j in zip(P.person_id, P.joined)}
    prior = {p: np.sort(g.lday.to_numpy()) for p, g in U.dropna(subset=["lday"]).groupby("person_id")}
    backers = U.groupby("target_id").person_id.apply(list).to_dict()
    out = {}
    for d, v in days.items():
        o = O(d)
        for x in v["launches"]:
            ppl = backers.get(x["id"], [])
            if len(ppl) < 5:
                continue
            ages = np.array([o - joined[p] for p in ppl if joined.get(p) is not None], float)
            pr = np.array([np.searchsorted(prior.get(p, np.zeros(0)), o) for p in ppl], float)
            out[(d, x["id"])] = {"held_backers": len(ppl), "share_age_lt90": float((ages < 90).mean()) if len(ages) else np.nan,
                                 "median_age_days": float(np.median(ages)) if len(ages) else np.nan,
                                 "share_prior_lt5": float((pr < 5).mean()), "median_prior_upvotes": float(np.median(pr))}
    return out


VERSION_RE = re.compile(r"(\b\d+\.\d+\b|\bv\d+\b|\b2\.0\b|\bnext\b|\breloaded\b)", re.I)


# ------------------------------------------------------------------ part 1
def part1(days, L, cats, sim, BQ):
    lmap = dict(zip(L.id, L.d))
    by_prod = {}
    for i, ps in sim.items():
        if i in lmap:
            by_prod.setdefault(ps, []).append(lmap[i])
    cat = dict(zip(cats.item_id, cats.primary))
    nm = dict(zip(L.id, L.n_makers))
    name = dict(zip(L.id, L.name))
    rows = []
    for d, v in days.items():
        for x in v["launches"]:
            if not (11 <= x["srank"] <= 20):
                continue
            rk = v["truth"].get(x["id"], (None, None))[0]
            if rk is None:
                continue
            ps = sim.get(x["id"])
            relaunch = (any(e < d for e in by_prod.get(ps, [])) if ps else np.nan)
            q = BQ.get((d, x["id"]), {})
            rows.append({"day": d, "id": x["id"], "srank": x["srank"], "made": rk <= 10, "category": cat.get(x["id"]),
                         "relaunch_2026": relaunch, "version_name": bool(VERSION_RE.search(str(name.get(x["id"], "")))),
                         "n_makers": nm.get(x["id"], np.nan), **q})
    R = pd.DataFrame(rows)
    out = {"n_launches": len(R), "n_days": R.day.nunique(), "made_top10_rate": round(float(R.made.mean()), 4),
           "made_by_structural_rank": R.groupby("srank").made.mean().round(4).to_dict()}
    out["structural_rank_within_11_20_auc"] = boot_clustered(R, lambda g: auc(g.made, -g.srank))
    # binary features: made rate with minus without
    for f in ("relaunch_2026", "version_name"):
        G = R.dropna(subset=[f])
        out[f] = {"coverage": round(len(G) / len(R), 3), "share_true": round(float(G[f].astype(bool).mean()), 4),
                  "made_rate_true_minus_false": boot_clustered(G, lambda g: g[g[f].astype(bool)].made.mean() - g[~g[f].astype(bool)].made.mean())}
    # continuous: AUC (higher value -> made)
    for f in ("n_makers", "held_backers", "share_age_lt90", "median_age_days", "share_prior_lt5", "median_prior_upvotes"):
        if f not in R:
            continue
        G = R.dropna(subset=[f])
        out[f] = {"coverage": round(len(G) / len(R), 3), "auc_higher_value_made": boot_clustered(G, lambda g: auc(g.made, g[f])),
                  "median_made": float(G[G.made][f].median()) if G.made.any() else None, "median_missed": float(G[~G.made][f].median())}
    # categories: made rate per category with >= 30 launches, vs the rest
    C = R.dropna(subset=["category"])
    cat_rows = []
    for c, g in C.groupby("category"):
        if len(g) >= 30:
            b = boot_clustered(C.assign(_in=C.category == c), lambda h: h[h._in].made.mean() - h[~h._in].made.mean(), B=500)
            cat_rows.append({"category": c, "n": len(g), "made_rate": round(float(g.made.mean()), 4), "minus_rest": b})
    out["category"] = {"coverage": round(len(C) / len(R), 3), "n_categories_30plus": len(cat_rows),
                       "by_category": sorted(cat_rows, key=lambda r: -r["made_rate"])}
    return out, R


# ------------------------------------------------------------------ part 2
def part2(days, L):
    L = L.dropna(subset=["weekly_rank", "monthly_rank"]).copy()
    L["dt"] = pd.to_datetime(L.d)
    L["week"] = L.dt.dt.to_period("W-SUN").astype(str)
    L["month"] = L.dt.dt.to_period("M").astype(str)
    score = {}
    for d, v in days.items():
        for x in v["launches"]:
            if x["score"] is not None:
                score[x["id"]] = (x["score"], x["srank"], d)
    covered = set(days)
    out = {}
    for per, rk in (("week", "weekly_rank"), ("month", "monthly_rank")):
        res, rows = [], []
        for p, g in L.groupby(per):
            want = {str(x) for x in pd.period_range(pd.Period(p).start_time, pd.Period(p).end_time, freq="D")} if per == "week" else \
                   {str(x) for x in pd.period_range(pd.Period(p, "M").start_time, pd.Period(p, "M").end_time, freq="D")}
            have = want & covered
            truth = set(g[g[rk] <= 10].id)
            if len(truth) < 10:
                continue
            S = [(score[i][0], -score[i][1], i) for i in g.id if i in score]
            pred = {i for _, _, i in sorted(S, reverse=True)[:10]}
            pred_rank = {i for _, i in sorted([(score[i][1], i) for i in g.id if i in score])[:10]} if S else set()
            votes = {i for _, i in sorted([(-v_, i) for i, v_ in zip(g.id, g.votes.fillna(0))])[:10]}
            rows.append({"period": p, "days_covered": len(have), "days_in_period": len(want),
                         "capture_structural_score": len(pred & truth) * 10, "capture_by_daily_structural_rank": len(pred_rank & truth) * 10,
                         "capture_real_votes_ceiling": len(votes & truth) * 10, "launches_scored": len(S)})
        R = pd.DataFrame(rows)
        full = R[R.days_covered == R.days_in_period]
        part = R[R.days_covered >= 0.8 * R.days_in_period]
        out[per] = {"periods_with_truth": len(R), "periods_fully_covered": len(full), "periods_80pct_covered": len(part),
                    "fully_covered": {k: boot_mean(full[k]) for k in ("capture_structural_score", "capture_by_daily_structural_rank", "capture_real_votes_ceiling")},
                    "80pct_covered": {k: boot_mean(part[k]) for k in ("capture_structural_score", "capture_by_daily_structural_rank", "capture_real_votes_ceiling")},
                    "rows": R.to_dict("records")}
    return out


# ------------------------------------------------------------------ part 3
def part3(days, L, prods, sim, pinfo):
    lmap = dict(zip(L.id, L.d))
    by_prod = {}
    for i, ps in sim.items():
        if i in lmap:
            by_prod.setdefault(ps, []).append(lmap[i])
    rows = []
    for d, v in days.items():
        for x in v["launches"]:
            rk = v["truth"].get(x["id"], (None, None))[0]
            if x["score"] is None or rk is None:
                continue
            ps = sim.get(x["id"])
            pr = prods.loc[ps] if ps in prods.index else None
            pi = pinfo.get(x["id"], {})
            rows.append({"day": d, "id": x["id"], "score": x["score"], "daily_rank": rk, "age_days": O("2026-11-11") - O(d),
                         "online": (None if pr is None else (not bool(pr["no_longer_online"]))),
                         "prod_reviews": None if pr is None else pr["reviews_count"], "prod_rating": None if pr is None or not pr["rating"] else pr["rating"],
                         "post_reviews": pi.get("reviews_count"), "post_rating": pi.get("reviews_rating") or None,
                         "relaunched_later": (sum(e > d for e in by_prod.get(ps, [])) if ps else None)})
    R = pd.DataFrame(rows)
    out = {"n_launches": len(R), "n_days": R.day.nunique()}

    def pc(g, a, b, c):   # partial Spearman of a with b given c
        ra, rb, rc = (rankdata(g[k]) for k in (a, b, c))
        r = lambda u, v: np.corrcoef(u, v)[0, 1]
        return (r(ra, rb) - r(ra, rc) * r(rb, rc)) / np.sqrt(max(1e-12, (1 - r(ra, rc) ** 2) * (1 - r(rb, rc) ** 2)))
    for f, kind in (("online", "bin"), ("prod_reviews", "num"), ("prod_rating", "num"), ("post_reviews", "num"), ("post_rating", "num"), ("relaunched_later", "num")):
        G = R.dropna(subset=[f]).copy()
        if len(G) < 30:
            out[f] = {"coverage": len(G), "note": "too few"}
            continue
        G[f] = G[f].astype(float)
        G["neg_rank"] = -G.daily_rank
        o = {"coverage_launches": len(G), "coverage_share": round(len(G) / len(R), 3), "mean": round(float(G[f].mean()), 4)}
        if kind == "bin":
            o["auc_structural_score"] = boot_clustered(G, lambda g: auc(g[f] > 0, g.score))
            o["auc_daily_rank"] = boot_clustered(G, lambda g: auc(g[f] > 0, g.neg_rank))
        o["spearman_structural_score"] = boot_clustered(G, lambda g: sp(g.score, g[f]))
        o["spearman_daily_rank"] = boot_clustered(G, lambda g: sp(g.neg_rank, g[f]))
        o["unexplained_by_daily_rank_1_minus_rho2"] = round(1 - (o["spearman_daily_rank"]["est"] or 0) ** 2, 4)
        o["partial_structural_given_daily_rank"] = boot_clustered(G, lambda g: pc(g, "score", f, "neg_rank"))
        o["spearman_daily_rank_given_launch_age"] = boot_clustered(G, lambda g: pc(g, "neg_rank", f, "age_days"))
        out[f] = o
    return out, R


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--sync")
    a = ap.parse_args(argv)
    W = a.work
    days, L, cats, prods, sim, pinfo = load(W)
    BQ = backer_quality(W, days)
    res = {"version": "targets0_v1", "n_backtest_days": len(days), "first_day": min(days), "last_day": max(days),
           "coverage": {"similar_products_launches": len(sim), "products_info_posts": len(pinfo), "warehouse_launches": len(L),
                        "held_backer_quality_launches": len(BQ)}}
    res["part1_ranks_11_20"], R1 = part1(days, L, cats, sim, BQ)
    res["part2_weekly_monthly"] = part2(days, L)
    res["part3_sustained"], R3 = part3(days, L, prods, sim, pinfo)
    os.makedirs(f"{W}/out", exist_ok=True)
    json.dump(res, open(f"{W}/out/targets0.json", "w"), indent=1, default=str)
    R1.to_parquet(f"{W}/out/part1_rows.parquet", index=False)
    R3.to_parquet(f"{W}/out/part3_rows.parquet", index=False)
    if a.sync:
        subprocess.run(["gsutil", "-q", "-m", "cp", f"{W}/out/*", a.sync + "/"], check=False)
    print(json.dumps({k: v for k, v in res.items() if k != "part2_weekly_monthly"}, indent=1, default=str)[:6000])
    for per in ("week", "month"):
        p = res["part2_weekly_monthly"][per]
        print(per, {k: v for k, v in p.items() if k != "rows"})


if __name__ == "__main__":
    main()
