"""Pre-launch X ties (raw/x/prelaunch_posts.jsonl + prelaunch_engagers.jsonl, Data Feeder; partial batches welcome):
the makers' and hunters' X posts from day -30 to -1 before their launch, and who reposted, quoted or replied to them.
Engagers are matched to Product Hunt people through raw/x_handles_pool.json ({ph_username: x_handle}) and the store's
profile `twitter` field. A person is X-tied to a launch if they engaged with a post by any of its team's handles in the
30 days before the launch day (dated by post_at; only engagement rows on posts dated before the day count).
1. Person level: of the X-tied pool people, the share who voted on (upvoted or commented) the launch on its day, vs the
   same people's rate on the day's other launches (placebo), with a 95% interval. Covered launches only (a team
   handle with fetched posts).
2. Launch level, pre-launch: per launch, distinct X-tied pool people (log), all distinct engagers (log),
   recency-weighted engagement (30-day half-life), and a covered flag. LightGBM on final log votes from the launch
   model's prediction plus these, trained on every earlier day, tested week by week (the X data exists only around
   the covered launches, so a monthly roll has nothing to train on). Daily top 3/5/10 vs the launch model, paired
   over days, on all days and on covered launches only (days with at least 3 covered launches, ranked among them).
usage: SIMLAB_DATA=data_v2 python x_prelaunch_test.py <prelaunch_posts.jsonl> <prelaunch_engagers.jsonl> <x_handles_pool.json>"""
import glob, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def topk(T, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.out_dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.out_dailyRank <= k).sum() == k})


def boot(a, b, rng):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    if not len(d):
        return None
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main(posts_p, eng_p, pool_p):
    posts, eng, pool = jl(posts_p), jl(eng_p), json.load(open(pool_p))
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    x2ph = {str(v).lower().lstrip("@"): k for k, v in pool.items() if v}
    x2ph.update({str(t).lower().lstrip("@"): p for p, t in zip(P.person, P.twitter) if isinstance(t, str) and t and t != "None"})
    team = defaultdict(set)
    for f in glob.glob("data/days/*.json"):
        for p in json.load(open(f)):
            hs = {(m.get("twitterUsername") or "").lower() for m in (p.get("makers") or []) if isinstance(m, dict)} | {((p.get("user") or {}).get("twitterUsername") or "").lower()}
            team[str(p["id"])] = hs - {""}
    # coverage is per (handle, launch day): each handle's posts cover the 30 days before its assigned launch only
    fetched_days = defaultdict(set)
    for r in posts:
        fetched_days[(r.get("handle") or "").lower()].add((r.get("launch_day") or "")[:10])
    fetched = set(fetched_days)
    post_at = {str(r.get("post_id")): (r.get("post_at") or r.get("posted_at") or "")[:10] for r in posts}
    ev = defaultdict(list)   # team handle -> [(date, engager ph person)]
    n_match = 0
    for r in eng:
        u = x2ph.get((r.get("user") or "").lower().lstrip("@")); h = (r.get("handle") or "").lower()
        d = (r.get("post_at") or r.get("posted_at") or post_at.get(str(r.get("post_id")), ""))[:10]
        if u and h and d:
            ev[h].append((d, u)); n_match += 1
    day = dict(zip(I.id, I.day))
    Ev = E.assign(item=E.item.astype(str)); Ev = Ev[Ev.item.map(day) == Ev.date]
    votes = Ev.groupby("person").item.apply(set).to_dict(); lineup = I.groupby("day").id.apply(set).to_dict()
    res = {"posts": len(posts), "engager_rows": len(eng), "engager_rows_matched_to_PH": n_match, "handles_with_posts": len(fetched)}
    rows, hit, n, ph_hit, ph_n = [], 0, 0, 0, 0
    for x, d in day.items():
        hs = {h for h in team.get(x, set()) & fetched if d in fetched_days[h]}
        if not hs:
            continue
        lo = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); tied = defaultdict(float); allu = set()
        for h in hs:
            for dd, u in ev.get(h, []):
                if lo <= dd < d:
                    tied[u] += 0.5 ** ((pd.Timestamp(d) - pd.Timestamp(dd)).days / 30); allu.add(u)
        for u in tied:
            v = votes.get(u, set()); hit += x in v; n += 1
            o = lineup.get(d, set()) - {x}; ph_hit += len(v & o); ph_n += len(o)
        rows.append({"id": x, "xt_pool": np.log1p(len(tied)), "xt_w": float(sum(tied.values())), "xt_cov": 1.0})
    res["covered_launches"] = len(rows)
    res["person_level"] = {"tied_person_launch_pairs": n, "share_voted": round(hit / n, 3) if n else None,
                           "placebo_share_other_launches_same_day": round(ph_hit / ph_n, 4) if ph_n else None,
                           "lift": round((hit / n) / (ph_hit / ph_n), 1) if n and ph_hit else None}
    if n:
        s = hit / n; se = np.sqrt(s * (1 - s) / n); res["person_level"]["share_ci95"] = [round(max(0, s - 1.96 * se), 3), round(min(1, s + 1.96 * se), 3)]
    # launch level
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    A = C[["id", "day", "logv", "all"]].merge(I[["id", "out_dailyRank"]], on="id").merge(pd.DataFrame(rows, columns=["id", "xt_pool", "xt_w", "xt_cov"]), on="id", how="left")
    A["xt_cov"] = A.xt_cov.fillna(0.0)
    cov_days = sorted(A[A.xt_cov > 0].day.unique())
    if len(rows) < 50 or not cov_days:
        res["launch_level"] = f"not measurable yet ({len(rows)} covered launches)"
    else:
        A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); out = []
        for w in sorted(A[A.day.isin(cov_days)].week.unique()):
            tr, te = A[A.week < w], A[A.week == w].copy()
            if tr.xt_cov.sum() < 30:
                continue
            te["x"] = np.mean([lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=20, random_state=s, verbose=-1)
                               .fit(tr[["all", "xt_pool", "xt_w", "xt_cov"]], tr.logv).predict(te[["all", "xt_pool", "xt_w", "xt_cov"]]) for s in range(3)], 0)
            out.append(te)
        if not out:
            res["launch_level"] = "not measurable yet (too few covered launches in earlier weeks to train on)"
        else:
            T = pd.concat(out); rng = np.random.default_rng(0); L = {}
            Tc = T[T.xt_cov > 0]; Tc = Tc[Tc.groupby("day").id.transform("size") >= 3]
            for name, U in (("all days", T), ("covered launches only", Tc)):
                L[name] = {f"top{k}": {"launch model": round(100 * float(topk(U, "all", k).mean()), 1) if len(topk(U, "all", k)) else None,
                                      "with X ties": round(100 * float(topk(U, "x", k).mean()), 1) if len(topk(U, "x", k)) else None,
                                      "delta": boot(topk(U, "all", k), topk(U, "x", k), rng)} for k in (3, 5, 10)}
            res["launch_level"] = L
    json.dump(res, open("results/x_prelaunch_test.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
