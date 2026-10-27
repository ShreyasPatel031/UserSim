"""Path to 90% top-3 hit: where the current best person model misses, and how far each kind of signal could take it.

Current best = trees on popularity + relationships + simple taste + persona ratings (v1-v4), trained on Sep active
person-days, scored on Oct. For every Oct person-day whose real picks are all outside our top 3, each real pick is put in
the first bucket that applies:
  A popular      the launch finished in the day's top 5
  B connected    a detectable tie to the team before the day: follows (undated), backed before, co-commented on the
                 same launches, the team commented on the person's launches
  C taste        ranked in the person's top 5 by any taste signal (topic, meaning, persona v1-v4)
  D unexplained  none of the above
Oracle curves: top-3 hit if every pick in the listed buckets were ranked into the top 3 (an upper bound per signal).
Run with FOLLOWS=0 to drop the undated follow lists everywhere.
usage: python -m simlab.path90  -> simlab/reports/path_to_90_data.json + printed tables"""
import json, os
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
from . import store, choice
from .persona import CACHE

FOLLOWS = os.environ.get("FOLLOWS", "1") == "1"
HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    R = {}
    for l in open(path):
        r = json.loads(l); R[r["person"] + "|" + r["day"]] = r["ratings"]
    return R


def main():
    P, I, E = store.load()
    D = choice.rows()
    files = {"p1": "taste_ratings.jsonl", "p2": "taste_v2_ratings.jsonl", "p3": "taste_v3_ratings.jsonl", "p4": "taste_best4_full.jsonl"}
    for k, f in files.items():
        R = load(f"{CACHE}/{f}")
        D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = D.dropna(subset=list(files))
    if not FOLLOWS:
        D["follow"] = 0.0
    # extra relationship signals, dated before the day
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()}
    day = dict(zip(I.id, I.day))
    ev = E[E.kind == "comment"]
    on = defaultdict(set)
    for u, it, dt in zip(ev.person, ev.item, ev.date):
        on[it].add((u, dt))
    by_person = ev.groupby("person").apply(lambda g: list(zip(g.item, g.date)), include_groups=False).to_dict()
    built = defaultdict(list)
    for it, t in team.items():
        for m in t:
            built[m].append(it)
    cache = {}

    def ties(u, d, it):
        key = (u, d, it)
        if key in cache:
            return cache[key]
        t = team[it]
        co = any(m in {x for x, dt2 in on[i2] if dt2 < d} for i2, dt in by_person.get(u, []) if dt < d for m in t)
        sup = any(x in t and dt < d for i2 in built.get(u, []) for x, dt in on[i2])
        cache[key] = co or sup
        return cache[key]

    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"].copy()
    cols = ["pop", "follow", "backed", "topic", "meaning", "p1", "p2", "p3", "p4"]
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1).fit(tr[cols], tr.y)
    te["p"] = m.predict_proba(te[cols])[:, 1]
    te["r"] = te.groupby("g").p.rank(ascending=False, method="first")
    rk = dict(zip(I.id, I.out_dailyRank))
    te["final_rank"] = te.id.map(rk)
    for c in ("topic", "meaning", "p1", "p2", "p3", "p4"):
        te[f"{c}_r"] = te.groupby("g")[c].rank(ascending=False, method="first")
    hit = te[te.r <= 3].groupby("g").y.any()
    picks = te[te.y == 1].copy()
    picks["hit_day"] = picks.g.map(hit).fillna(False)

    def bucket(r):
        if r.final_rank <= 5:
            return "A popular"
        u, d = r.g.split("|")
        if r.follow > 0 or r.backed > 0 or ties(u, d, r.id):
            return "B connected"
        if min(r[f"{c}_r"] for c in ("topic", "meaning", "p1", "p2", "p3", "p4")) <= 5:
            return "C taste"
        return "D unexplained"
    miss = picks[~picks.hit_day].copy()
    miss["bucket"] = miss.apply(bucket, axis=1)
    n_days = te.g.nunique(); cur = hit.reindex(te.g.unique(), fill_value=False).mean()
    day_buckets = miss.groupby("g").bucket.apply(set)
    order = ["A popular", "B connected", "C taste", "D unexplained"]
    curve, got = [("current model", cur)], set(hit[hit].index)
    for i, b in enumerate(order[:3]):
        got |= {g for g, s in day_buckets.items() if s & set(order[: i + 1])}
        curve.append((f"+ perfect {b}", len(got) / n_days))
    # best single bucket per missed day (closest-to-fixable first)
    first = day_buckets.apply(lambda s: next(b for b in order if b in s))
    out = {"follows_used": FOLLOWS, "test_person_days": int(n_days), "current_top3_hit": float(cur),
           "missed_days": int(len(day_buckets)), "missed_day_best_bucket": first.value_counts(normalize=True).round(3).to_dict(),
           "missed_picks_bucket": miss.bucket.value_counts(normalize=True).round(3).to_dict(),
           "oracle_curve": [(a, round(float(b), 3)) for a, b in curve]}
    os.makedirs(f"{HERE}/reports", exist_ok=True)
    json.dump(out, open(f"{HERE}/reports/path_to_90_data{'' if FOLLOWS else '_nofollows'}.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
