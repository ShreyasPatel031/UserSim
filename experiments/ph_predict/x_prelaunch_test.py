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
Leakage: reply search has no end time, so only engager rows whose own post (engager_post_id, an X snowflake:
ms = (id >> 22) + 1288834974657) is dated before 00:00 PT on the launch day are kept. Reposts carry no post id or
time, so they are dropped (counted in the output).
Coverage: a (handle, launch day) counts only when all its posts are fetched (posts_complete) and every post with any
reposts, quotes or replies has its engagers fetched; a launch is covered if one of its team handles is.
3. Turnout (aimed at the per-launch shock): distinct pre-launch engagers (all X users, not only PH people), engagers per
   post, and posts; within-day Spearman with the launch model's residual (final log votes minus prediction), no fitting.
usage: SIMLAB_DATA=data_v2 python x_prelaunch_test.py <prelaunch_posts.jsonl> <prelaunch_engagers.jsonl> <x_handles_pool.json>"""
import glob, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
from scipy.stats import spearmanr


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
    hp = defaultdict(list)
    for r in posts:
        hp[((r.get("handle") or "").lower(), (r.get("launch_day") or "")[:10])].append(r)
    engaged = lambda r: sum(r.get(c) or 0 for c in ("repost_count", "quote_count", "reply_count")) > 0
    fetched_days = defaultdict(set)
    for (h, ld), v in hp.items():
        if all(r.get("posts_complete", True) for r in v) and all(r.get("engagers_fetched", True) for r in v if engaged(r)):
            fetched_days[h].add(ld)
    if os.environ.get("XGATE"):   # explicit complete (handle, launch day) list from the fetch job's state (flags in the files lag)
        fetched_days = defaultdict(set)
        for h, ld in json.load(open(os.environ["XGATE"])):
            fetched_days[h.lower()].add(ld[:10])
    if os.environ.get("XLOOKUP"):  # drop handles X reports as not found or suspended
        LK = json.load(open(os.environ["XLOOKUP"]))
        dead = {k.lower() for k, v in LK.items() if isinstance(v, dict) and (v.get("status") or ("ok" if v.get("exists", True) else "")) not in ("ok", "exists", "active")}
        x2ph = {k: v for k, v in x2ph.items() if k not in dead}
    fetched = set(fetched_days)
    post_at = {str(r.get("post_id")): (r.get("post_at") or r.get("posted_at") or "")[:10] for r in posts}
    post_ld = {str(r.get("post_id")): (r.get("launch_day") or "")[:10] for r in posts}
    ev = defaultdict(list)   # team handle -> [(date, engager ph person)]
    xu = defaultdict(set)    # (team handle, launch day) -> distinct X engagers, pre-launch
    n_match, n_repost, n_late = 0, 0, 0
    for r in eng:
        h, ld, eid = (r.get("handle") or "").lower(), post_ld.get(str(r.get("post_id")), ""), r.get("engager_post_id")
        if not eid:
            n_repost += 1; continue
        cut = pd.Timestamp(ld).tz_localize("America/Los_Angeles").value // 10**6 if ld else 0
        if ((int(eid) >> 22) + 1288834974657) >= cut:
            n_late += 1; continue
        xu[(h, ld)].add((r.get("user") or "").lower().lstrip("@"))
        u = x2ph.get((r.get("user") or "").lower().lstrip("@"))
        d = (r.get("post_at") or r.get("posted_at") or post_at.get(str(r.get("post_id")), ""))[:10]
        if u and h and d:
            ev[h].append((d, u)); n_match += 1
    day = dict(zip(I.id, I.day))
    Ev = E.assign(item=E.item.astype(str)); Ev = Ev[Ev.item.map(day) == Ev.date]
    votes = Ev.groupby("person").item.apply(set).to_dict(); lineup = I.groupby("day").id.apply(set).to_dict()
    res = {"posts": len(posts), "engager_rows": len(eng), "engager_rows_matched_to_PH": n_match, "complete_handle_days": sum(map(len, fetched_days.values())),
           "engager_rows_dropped": {"repost_no_time": n_repost, "after_launch_start": n_late}}
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
        users = set().union(*[xu.get((h, d), set()) for h in hs]); npost = sum(len(hp[(h, d)]) for h in hs)
        ps = [r for h in hs for r in hp[(h, d)]]; t0 = pd.Timestamp(d).tz_localize("America/Los_Angeles")
        age = [(t0 - pd.Timestamp(r.get("posted_at"))).total_seconds() / 86400 if r.get("posted_at") else 99 for r in ps]
        reach = {}
        for w in (7, 30):   # counts are read at fetch time (after launch), so they include post-launch engagement
            q = [r for r, a in zip(ps, age) if 0 <= a < w]
            for c in ("impression_count", "like_count", "repost_count"):
                reach[f"xr_{c.split('_')[0]}_{w}d"] = np.log1p(sum(r.get(c) or 0 for r in q))
        q48 = [r for r, a in zip(ps, age) if 0 <= a < 2]
        tease = any(any(t in (r.get("text") or "").lower() for t in ("producthunt", "product hunt", "launching", "tomorrow")) for r in q48)
        rows.append({"id": x, "xt_pool": np.log1p(len(tied)), "xt_w": float(sum(tied.values())), "xt_cov": 1.0,
                     "xe_users": np.log1p(len(users)), "xe_per_post": len(users) / max(npost, 1), "xe_posts": np.log1p(npost),
                     **reach, "x48_posts": np.log1p(len(q48)), "x48_tease": float(tease)})
    res["covered_launches"] = len(rows)
    res["person_level"] = {"tied_person_launch_pairs": n, "share_voted": round(hit / n, 3) if n else None,
                           "placebo_share_other_launches_same_day": round(ph_hit / ph_n, 4) if ph_n else None,
                           "lift": round((hit / n) / (ph_hit / ph_n), 1) if n and ph_hit else None}
    if n:
        s = hit / n; se = np.sqrt(s * (1 - s) / n); res["person_level"]["share_ci95"] = [round(max(0, s - 1.96 * se), 3), round(min(1, s + 1.96 * se), 3)]
    # launch level
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    A = C[["id", "day", "logv", "all"]].merge(I[["id", "out_dailyRank"]], on="id").merge(pd.DataFrame(rows), on="id", how="left")
    A["xt_cov"] = A.xt_cov.fillna(0.0)
    X = ["all", "xt_pool", "xt_w", "xt_cov", "xe_users", "xe_per_post", "xe_posts"]
    cov_days = sorted(A[A.xt_cov > 0].day.unique())
    Ac = A[A.xt_cov > 0].assign(resid=lambda f: f.logv - f["all"])
    res["turnout_vs_shock"] = {c: round(float(np.nanmean([spearmanr(g[c], g.resid).correlation for _, g in Ac.groupby("day") if len(g) >= 3 and g[c].nunique() > 1])), 3)
                               if len(Ac) else None for c in [c for c in A if c.startswith(("xe_", "xr_", "x48_"))] + ["xt_pool"]}
    res["turnout_vs_shock"]["covered_days_with_3plus"] = int((Ac.groupby("day").size() >= 3).sum()) if len(Ac) else 0
    if len(rows) < 100 or not cov_days:
        res["launch_level"] = f"not measurable yet ({len(rows)} covered launches)"
    else:
        A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); out = []
        for w in sorted(A[A.day.isin(cov_days)].week.unique()):
            tr, te = A[A.week < w], A[A.week == w].copy()
            if tr.xt_cov.sum() < 30:
                continue
            te["x"] = np.mean([lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=20, random_state=s, verbose=-1)
                               .fit(tr[X], tr.logv).predict(te[X]) for s in range(3)], 0)
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
