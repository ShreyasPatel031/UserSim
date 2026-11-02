"""Launch-day forecast from real intraday votes: Wayback captures of the Product Hunt homepage, Jul-Oct 2026
(raw/ph_homepage_archive/parsed.jsonl, Data Feeder). A homepage capture at hour h after 00:00 PT of day d shows d's
featured posts with their votes at that moment.
1. Verification: archived daily leaderboard pages (near-final) and launchDayScore of past days vs our stored final
   votes and daily ranks (data/days).
2. Backtest: for every (day, capture) of the homepage on that day, rank the day's launches by
     prior        the pre-launch launch model (ctrl.py, out of sample)
     votes        log votes at capture (launches not on the page: 0)
     blend        mean of the within-day percentile ranks of prior and votes (no fitted weight)
   and score against the final daily rank: top 3 / 5 / 10, by bucket of hours since 00:00 PT. The latest capture per
   day and bucket is used. Intervals: bootstrap over days.
usage: python wayback_launchday.py <parsed.jsonl> -> results/wayback_launchday.json"""
import glob, json, sys
import numpy as np, pandas as pd

BUCKETS = [(0, 2), (2, 4), (4, 8), (8, 12), (12, 24)]


def main(path):
    W = pd.read_json(path, lines=True, dtype={"post_id": str, "capture_ts": str})
    W = W[W.day.astype(str).str.len() == 10]
    final = {}
    for f in glob.glob("data/days/*.json"):
        for p in json.load(open(f)):
            final[str(p["id"])] = (f[-15:-5], p.get("votesCount"), p.get("dailyRank"))
    res = {}
    # 1. verification
    L = W[W.capture_kind == "lb"].sort_values("capture_ts").drop_duplicates("post_id", keep="last")
    L = L[L.post_id.isin(final)]
    fv = L.post_id.map(lambda x: final[x][1]); fr = L.post_id.map(lambda x: final[x][2])
    ratio = (L.votes / fv).replace([np.inf], np.nan)
    rank_l = L.groupby("day").votes.rank(ascending=False, method="first")
    res["verify_leaderboard_pages"] = {"posts": int(len(L)), "days": int(L.day.nunique()), "median_votes_page_over_ours": round(float(ratio.median()), 3),
                                       "share_within_5pct": round(float(((ratio - 1).abs() <= 0.05).mean()), 3),
                                       "top3_agreement_page_vs_our_rank": round(float(np.mean([len(set(g.nsmallest(3, "rk").post_id) & set(g[g.fr <= 3].post_id)) / 3
                                                                                              for _, g in L.assign(rk=rank_l, fr=fr).groupby("day") if (g.fr <= 3).sum() == 3])), 3)}
    H = W[(W.capture_kind == "home")].copy()
    ts = pd.to_datetime(H.capture_ts, format="%Y%m%d%H%M%S", utc=True)
    start = pd.to_datetime(H.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")
    H["h"] = (ts - start).dt.total_seconds() / 3600
    past = H[(H.h >= 24) & H.launchDayScore.notna() & H.post_id.isin(final)].drop_duplicates("post_id")
    lr = past.launchDayScore / past.post_id.map(lambda x: final[x][1])
    res["verify_launchDayScore_past_days"] = {"posts": int(len(past)), "median_ratio_to_our_final": round(float(lr.median()), 3),
                                              "share_within_5pct": round(float(((lr - 1).abs() <= 0.05).mean()), 3)}
    # 2. backtest
    H = H[(H.h >= 0) & (H.h < 24) & H.votes.notna()]
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
    C = C[C.day >= "2026-07-01"][["id", "day", "dailyRank", "all"]].drop_duplicates("id")
    rng = np.random.default_rng(0); out = {}
    for lo, hi in BUCKETS:
        Hb = H[(H.h >= lo) & (H.h < hi)]
        if Hb.empty:
            continue
        last = Hb.groupby("day").capture_ts.max()
        Hb = Hb[Hb.capture_ts.values == Hb.day.map(last).values].drop_duplicates(["day", "post_id"])
        per = {k: {m: {} for m in ("prior", "votes", "blend")} for k in (3, 5, 10)}
        seen_share = []
        for d, g in C[C.day.isin(Hb.day.unique())].groupby("day"):
            v = dict(zip(Hb[Hb.day == d].post_id, Hb[Hb.day == d].votes))
            g = g.assign(votes=np.log1p(g.id.map(v).fillna(0)))
            seen_share.append(g.id.isin(v).mean())
            g["blend"] = g["all"].rank(pct=True) + g.votes.rank(pct=True); g["prior"] = g["all"]
            for k in (3, 5, 10):
                real = set(g[g.dailyRank <= k].id)
                if len(real) == k:
                    for m in ("prior", "votes", "blend"):
                        per[k][m][d] = len(set(g.nlargest(k, m).id) & real) / k
        b = {"days": len(per[3]["prior"]), "share_of_lineup_on_page": round(float(np.mean(seen_share)), 3) if seen_share else None,
             "median_hour": round(float(Hb.h.median()), 1)}
        for k in (3, 5, 10):
            days = sorted(per[k]["prior"])
            for m in ("prior", "votes", "blend"):
                b[f"{m} top{k}"] = round(100 * float(np.mean([per[k][m][d] for d in days])), 1) if days else None
            if days:
                dd = np.array([per[k]["blend"][d] - per[k]["prior"][d] for d in days]); bs = [dd[rng.integers(0, len(dd), len(dd))].mean() for _ in range(5000)]
                b[f"blend - prior top{k}"] = [round(100 * float(dd.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])]]
        out[f"{lo}-{hi}h"] = b
    res["backtest_by_hour"] = out
    json.dump(res, open("results/wayback_launchday.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
