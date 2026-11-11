"""Error analysis of the launch model's top-k misses (user, Nov 11): toward 90% daily top-3/5/10.
Sets
  live    warehouse forecasts (launch_model and the shadows, made at 00:05 PT) on days with final ranks, Oct 25 - Nov 9
  bt      honest backtest predictions (e5h/honest_preds.parquet, 'honest' column), Oct 1 - 24: more misses to characterise
Per day: top-3/5/10 overlap with the real top k (ranked line-up only). Misses:
  FN  real top-k, predicted rank > k        FP  predicted top-k, real rank > k
Profiles of FN vs hits (standardised mean difference within day) on the LM cache features (00:05 inputs) and
llm_* scores: what the misses have in common. Ceiling checks: rank of the k-th / (k+1)-th predicted score gap
(near-ties) and the share of misses whose predicted rank is k+1..k+3 (near misses vs far misses).
Intraday: on days with 15-min snapshots (raw/ph_at_launch/<d>/live, Nov 3+), top-k by cumulative votes at t = 1..12 h
after the day's first featuring vs the 00:05 forecast: how many hours of live votes reach 90%.
usage: python miss_analysis.py -> results/miss_analysis.json (counts and launch ids only, no usernames)"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
S_ = "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad"


def topk(pred_rank, real_rank, k):
    return len(set(pred_rank.nsmallest(k).index) & set(real_rank.nsmallest(k).index)) / k * 100


def main():
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank, votes, poster, makers, topics FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-01'", do_sync=False)
    L = L.set_index("id")
    F = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date AS day, model, predicted_rank FROM forecasts WHERE forecast_date BETWEEN '2026-10-25' AND '2026-11-09'", do_sync=False)
    H = pd.read_parquet(f"{S_}/e5h/honest_preds.parquet"); H["id"] = H.id.astype(str); H = H[(H.day >= "2026-10-01") & (H.day <= "2026-10-24")]
    H["pr"] = H.groupby("day").honest.rank(ascending=False, method="first")
    P = pd.concat([F.rename(columns={"predicted_rank": "pr"})[["id", "day", "model", "pr"]],
                   H.assign(model="honest_backtest")[["id", "day", "model", "pr"]]])
    P = P[P.id.isin(L.index)]; P["real"] = P.id.map(L.daily_rank); P["votes"] = P.id.map(L.votes)
    res = {"per_model": {}, "per_day": []}
    rows = []
    for (m, d), g in P.groupby(["model", "day"]):
        g = g.set_index("id"); n_lineup = int((L.day == d).sum())
        g["pr"] = g.pr.rank(method="first")   # re-rank within the ranked line-up
        row = {"model": m, "day": d, "n": len(g), "lineup": n_lineup, "coverage": round(len(g) / max(1, n_lineup), 2)}
        for k in (3, 5, 10):
            row[f"top{k}"] = topk(g.pr, g.real, k) if len(g) > k else np.nan
        rows.append(row)
    R = pd.DataFrame(rows)
    for m, g in R.groupby("model"):
        res["per_model"][m] = {"days": int(len(g)), **{f"top{k}": round(float(g[f"top{k}"].mean()), 1) for k in (3, 5, 10)},
                               "mean_lineup": round(float(g.n.mean()), 1)}
    # paired comparison on common days
    common = set.intersection(*[set(R[R.model == m].day) for m in ("launch_model", "simulation", "shadow_daycal", "shadow_honest_a2")])
    res["common_live_days"] = sorted(common)
    res["per_model_common"] = {m: {f"top{k}": round(float(R[(R.model == m) & R.day.isin(common)][f"top{k}"].mean()), 1) for k in (3, 5, 10)}
                               for m in ("launch_model", "simulation", "shadow_daycal", "shadow_honest_a2")}
    # misses of the launch model (live) + honest backtest
    df = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); df["id"] = df.id.astype(str); df = df.set_index("id")
    feats = [c for c in df.columns if df[c].dtype.kind in "fi" and not c.startswith(("ctx_", "ph_dayrank", "x_dayrank", "hist_dayrank")) and c not in ("votes", "real", "pr", "dailyRank", "weeklyRank", "monthlyRank", "logv", "rank", "daily_rank")]
    M = P[P.model.isin(["launch_model", "honest_backtest"])].copy()
    M["pr"] = M.groupby(["model", "day"]).pr.rank(method="first")
    miss = {}
    for k in (3, 10):
        M[f"fn{k}"] = (M.real <= k) & (M.pr > k); M[f"hit{k}"] = (M.real <= k) & (M.pr <= k); M[f"fp{k}"] = (M.real > k) & (M.pr <= k)
        fn = M[M[f"fn{k}"]]
        miss[f"top{k}"] = {"real_topk": int((M.real <= k).sum()), "fn": int(len(fn)),
                           "fn_pred_rank_hist": {"k+1..k+3": int(((fn.pr > k) & (fn.pr <= k + 3)).sum()), "k+4..2k": int(((fn.pr > k + 3) & (fn.pr <= 2 * k)).sum()), ">2k": int((fn.pr > 2 * k).sum())},
                           "fp_real_rank_median": float(M[M[f"fp{k}"]].real.median())}
        # SMD within day: FN vs hits on 00:05 features
        Z = M[(M.real <= k)].join(df[feats], on="id")
        smd = {}
        for c in feats:
            x = Z[c].astype(float)
            if x.notna().sum() < 30 or x.nunique() < 3:
                continue
            z = (x - Z.groupby(["model", "day"])[c].transform("mean")) / (x.std() + 1e-9)
            a, b = z[Z[f"fn{k}"]], z[Z[f"hit{k}"]]
            if a.notna().sum() >= 5 and b.notna().sum() >= 5:
                smd[c] = round(float(a.mean() - b.mean()), 2)
        miss[f"top{k}"]["fn_minus_hit_smd_top"] = dict(sorted(smd.items(), key=lambda kv: -abs(kv[1]))[:15])
    cold = lambda Z: (Z.hist_hunter_n.fillna(0) == 0) & (Z.hist_maker_n.fillna(0) == 0)
    noaud = lambda Z: Z.sc_aud_follow.isna() | (Z.sc_aud_follow.fillna(0) == 0)
    for k in (3, 10):
        Z = M[M.real <= k].join(df[["hist_hunter_n", "hist_maker_n", "sc_aud_follow", "llm_brand", "promo_posts"]], on="id")
        for nm, f in (("no_team_history", cold), ("no_known_audience", noaud)):
            miss[f"top{k}"][nm] = {"fn_share": round(float(f(Z[Z[f"fn{k}"]]).mean()), 3), "hit_share": round(float(f(Z[Z[f"hit{k}"]]).mean()), 3),
                                   "recall_when_true": round(float(Z[f(Z)][f"hit{k}"].mean()), 3), "recall_when_false": round(float(Z[~f(Z)][f"hit{k}"].mean()), 3),
                                   "n_true": int(f(Z).sum())}
    res["misses"] = miss
    # how much each top-10 FN was underrated: votes share vs predicted
    fn10 = M[M.fn10].copy(); fn10["topics"] = fn10.id.map(L.topics)
    res["fn10_examples_live"] = fn10[fn10.model == "launch_model"].sort_values(["day", "real"])[["day", "id", "real", "pr", "votes"]].astype({"real": int, "pr": int}).to_dict("records")
    # intraday: top-k by cumulative votes at t hours after first featuring
    intr = []
    for f in sorted(glob.glob(f"{S_}/cascade/posts_*.jsonl")):
        d = os.path.basename(f)[6:16]
        if d not in set(L.day):
            continue
        rr = []
        for l in open(f):
            x = json.loads(l)
            if x.get("fetch_status") == 200 and x.get("votes_at_fetch") is not None:
                rr.append((str(x["launch_id"]), x["snapshot_ts"], x["votes_at_fetch"], x.get("featured_at")))
        T = pd.DataFrame(rr, columns=["id", "ts", "v", "feat"])
        T = T[T.id.isin(L[L.day == d].index)]
        if T.id.nunique() < 10:
            continue
        T["ts"] = pd.to_datetime(T.ts, utc=True); t0 = pd.Timestamp(d + "T08:00:00Z")   # 00:00 PT (featuring at ~00:01 PT)
        if T.ts.min() > t0 + pd.Timedelta(minutes=20):   # capture started late: votes before the first snapshot unknown
            continue
        real = L[L.day == d].daily_rank
        lmf = F[(F.model == "launch_model") & (F.day == d)].set_index("id").predicted_rank
        row = {"day": d, "launches_tracked": int(T.id.nunique()), "lineup": int(len(real))}
        for h in (1, 2, 3, 4, 5, 6, 8, 12):
            S = T[T.ts <= t0 + pd.Timedelta(hours=h)].sort_values("ts").groupby("id").v.last()
            S = S.reindex(real.index).fillna(0)
            pr = (-S).rank(method="first")
            for k in (3, 5, 10):
                row[f"t{h}h_top{k}"] = topk(pr, real, k)
        if len(lmf):
            lp = lmf.reindex(real.index).fillna(999).rank(method="first")
            for k in (3, 5, 10):
                row[f"lm_top{k}"] = topk(lp, real, k)
        intr.append(row)
    I = pd.DataFrame(intr)
    res["intraday"] = {"days": I.day.tolist(), "lm_0005": {f"top{k}": round(float(I[f"lm_top{k}"].mean()), 1) for k in (3, 5, 10) if f"lm_top{k}" in I},
                       **{f"t{h}h": {f"top{k}": round(float(I[f"t{h}h_top{k}"].mean()), 1) for k in (3, 5, 10)} for h in (1, 2, 3, 4, 5, 6, 8, 12)}}
    res["per_day"] = R.round(1).to_dict("records")
    json.dump(res, open(os.path.join(HERE, "results", "miss_analysis.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k not in ("per_day", "fn10_examples_live")}, indent=1, default=float))


if __name__ == "__main__":
    main()
