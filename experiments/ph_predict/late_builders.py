"""Late builders (orchestrator 02:15Z Nov 12): launches that gather their votes after the 04:00 PT reveal.
Data: warehouse vote_snapshots (hourly, the pipeline's recorder; Nov 2-11) + final votes / daily rank (launches);
hidden API rank at the 03:00 PT read (rank_now); 00:05 LM; line-up, weekday; makers and hunter (self-hunted, team size).
  late_share = 1 - votes at the first read at/after 04:00 PT / final votes
  rise       = hidden rank at 03:00 - final daily rank (positive = rose after the reveal)
Questions: does gap = hidden rank at 03:00 - LM rank (LM ranks it higher than the hidden rank) predict late_share / rise?
Correction tested (LODO over days): pred_rank_best2 = rank of [w_api * api_pos + (1 - w_api) * lm_pos - beta * max(0, api_pos - lm_pos)]
with w_api = 0.75 (the best recipe at 03:00) and beta in {0, 0.1, 0.25, 0.5}, plus a weekend switch (w_api 0.5 on Sat/Sun).
(E5's Wayback same-day captures are on another branch; not used here.)
usage: python late_builders.py -> results/late_builders.json + .md"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import lm_scores


def tk(o, t, k):
    return len(set(o[:k]) & set(t[:k])) / k * 100


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, votes, makers, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, votes, rank_now FROM vote_snapshots', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    rows = []
    for d, g in V[V.d < today].groupby("d"):
        f = L[L.day == d].set_index("id")
        if len(f) < 10:
            continue
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        pre = g[g.a <= t0 + pd.Timedelta(hours=3, minutes=10)].sort_values("a").groupby("id").rank_now.last()
        post = g[g.a >= t0 + pd.Timedelta(hours=4)].sort_values("a").groupby("id").votes.first()
        if pre.empty or post.empty:
            continue
        lm = lm_scores(d)
        ids = sorted(f.index)   # ties broken by id, never by final rank
        lm_pos = pd.Series({i: -lm.get(i, -99) for i in ids}).rank(method="first")
        api_pos = pd.Series({i: pre.get(i, 999) for i in ids}).rank(method="first")
        wd = pd.Timestamp(d).dayofweek
        for i in ids:
            mk = json.loads(f.at[i, "makers"]) if isinstance(f.at[i, "makers"], str) and f.at[i, "makers"].startswith("[") else []
            v4 = post.get(i, np.nan); fv = f.at[i, "votes"]
            rows.append({"day": d, "id": i, "final_rank": f.at[i, "daily_rank"], "final_votes": fv, "votes_04": v4,
                         "late_share": 1 - v4 / fv if fv and v4 == v4 else np.nan, "api_pos": api_pos[i], "lm_pos": lm_pos[i],
                         "gap": api_pos[i] - lm_pos[i], "rise": api_pos[i] - f.at[i, "daily_rank"], "weekend": float(wd >= 5), "lineup": len(ids),
                         "n_makers": len(mk), "self_hunted": float(bool(f.at[i, "poster"]) and f.at[i, "poster"] in mk)})
    X = pd.DataFrame(rows)
    days = sorted(X.day.unique())
    out = {"days": days, "launches": int(len(X))}
    Y = X.dropna(subset=["late_share"])
    cor = {c: round(float(spearmanr(Y[c], Y.late_share).correlation), 3) for c in ("gap", "lm_pos", "api_pos", "weekend", "lineup", "n_makers", "self_hunted")}
    cor_rise = {c: round(float(spearmanr(X[c], X.rise).correlation), 3) for c in ("gap", "lm_pos", "weekend", "lineup", "n_makers", "self_hunted")}
    top = X[X.lm_pos <= 5]
    out.update({"late_share_median": round(float(Y.late_share.median()), 3), "spearman_late_share": cor, "spearman_rise": cor_rise,
                "lm_top5_rise_by_gap": top.assign(gbin=pd.cut(top.gap, [-100, 0, 3, 100], labels=["hidden >= LM", "gap 1-3", "gap > 3"])).groupby("gbin", observed=True).rise.agg(["mean", "size"]).round(2).to_dict()})
    # correction, LODO over days
    cands = {}
    for beta in (0.0, 0.1, 0.25, 0.5):
        cands[f"beta_{beta}"] = (beta, False)
    cands["weekend_w0.5"] = (0.0, True)
    sc = {c: {} for c in cands}
    for d, g in X.groupby("day"):
        truth = g.sort_values("final_rank").id.tolist()
        for c, (beta, wk) in cands.items():
            w = 0.5 if (wk and g.weekend.iloc[0]) else 0.75
            s = w * g.api_pos + (1 - w) * g.lm_pos - beta * np.maximum(0, g.api_pos - g.lm_pos)
            o = g.assign(s=s).sort_values(["s", "lm_pos"]).id.tolist()
            sc[c][d] = [tk(o, truth, k) for k in (3, 5, 10)]
    tab = {c: [round(float(x), 1) for x in np.mean(list(v.values()), axis=0)] for c, v in sc.items()}
    lodo, picks = [], []
    for dh in days:
        best = max(cands, key=lambda c: np.mean([np.mean(v) for d_, v in sc[c].items() if d_ != dh]))
        picks.append(best); lodo.append(sc[best][dh])
    out.update({"correction_table": tab, "lodo": [round(float(x), 1) for x in np.mean(lodo, axis=0)], "lodo_picks": picks,
                "per_day": {c: v for c, v in sc.items()}})
    json.dump(out, open(os.path.join(HERE, "results", "late_builders.json"), "w"), indent=1, default=str)
    md = ["# Late builders: votes after the 04:00 PT reveal (hourly reads, " + f"{len(days)} days: {', '.join(days)})", "",
          f"Launches: {len(X)}. Median share of final votes arriving after 04:00 PT: {out['late_share_median']}.", "",
          "Spearman with late_share: " + ", ".join(f"{k} {v:+.2f}" for k, v in cor.items()),
          "Spearman with rise (hidden rank at 03:00 - final rank): " + ", ".join(f"{k} {v:+.2f}" for k, v in cor_rise.items()), "",
          "LM top-5 launches, mean rise by gap (hidden rank - LM rank at 03:00): " + json.dumps(out["lm_top5_rise_by_gap"]), "",
          "Correction of the 03:00 best recipe (0.75 API + 0.25 LM), mean over days, top 3 / 5 / 10:", "", "| candidate | top 3 / 5 / 10 |", "|---|---|"]
    md += [f"| {c} | {' / '.join(str(x) for x in v)} |" for c, v in tab.items()]
    md += ["", f"Leave-one-day-out: {' / '.join(str(x) for x in out['lodo'])} (picks: {', '.join(picks)})."]
    open(os.path.join(HERE, "results", "late_builders.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
