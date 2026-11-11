"""Daily north-star scoreboard for the website's track record (orchestrator 23:45Z Nov 11). One row per (day, point,
method) with top 3/5/10 overlap vs the final daily rank (k-overlap / k x 100, the forecast's own line-up), and a summary
of running means per (point, method, source). Rebuilt from scratch each run, so it is always consistent.

Points / sources:
  0005 published   warehouse forecasts model=launch_model (the deployed 00:05 forecast), live, Oct 25 on
  0005 makerfix    results/shadow_makerfix/<day>.json rank_makerfix (shadow, live from Nov 11); rank_unfixed beside it
  P1..P4           results/early_forecast/<day>_P*.json: pred_rank (ridge), pred_rank_api, pred_rank_blend (live from Nov 12);
                   replay rows (CF_DRY files, source=replay) for Nov 2-10 if present in results/early_forecast_replay_P/
  R0..R4           results/early_forecast/<day>_R*.json (raw votes), live; written_at after the point time -> source=late
Final ranks: warehouse launches.daily_rank, only days before today (PT). Days are PT dates.
usage: python scoreboard.py -> results/web/scoreboard.json (+ gs://.../results/web/scoreboard.json)"""
import glob, json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
POINT_T = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def ov(pred_ids, real_ids, k):
    return len(set(pred_ids[:k]) & set(real_ids[:k])) / k * 100


def main():
    from pipeline import warehouse as W
    today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    R = W.query(f"SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-25' AND day < '{today}'", do_sync=False)
    real = {d: g.sort_values("daily_rank") for d, g in R.groupby("day")}
    rows = []

    def add(day, point, method, source, ranked_ids, written_at=None):
        g = real.get(day)
        if g is None:
            return
        ids = list(dict.fromkeys(ranked_ids))   # the forecast's order; launches it did not rank can never be hit
        if len(set(ids) & set(g.id)) < 10:
            return
        sub = g.id.tolist()   # the day's full final ranking (the number-of-record convention)
        rows.append({"day": day, "point": point, "method": method, "source": source, "n": len(ids), "written_at": written_at,
                     **{f"top{k}": round(ov(ids, sub, k), 1) for k in (3, 5, 10)}})

    F = W.query("SELECT forecast_date d, CAST(launch_id AS VARCHAR) id, predicted_rank pr, updated_at u FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    for d, g in F.groupby("d"):
        g = g[g.u == g.u.min()]   # the first (published) run of the day; Nov 1 was run twice
        add(d, "0005", "published", "live", g.sort_values("pr").id.tolist(), g.u.iloc[0])
    for p in sorted(glob.glob(os.path.join(HERE, "results", "shadow_makerfix", "*.json"))):
        S = json.load(open(p)); f = pd.DataFrame(S["forecast"])
        add(S["day"], "0005", "makerfix_shadow", "live", f.sort_values("rank_makerfix").id.tolist(), S["written_at"])
        add(S["day"], "0005", "unfixed_replay", "live", f.sort_values("rank_unfixed").id.tolist(), S["written_at"])
    for src, pat in (("live", os.path.join(HERE, "results", "early_forecast", "*.json")), ("replay", os.path.join(HERE, "results", "early_forecast_replay_P", "*.json"))):
        for p in sorted(glob.glob(pat)):
            E = json.load(open(p)); f = pd.DataFrame(E.get("forecast", []))
            if f.empty:
                continue
            pt, d = E["point"], E["day"]
            s = src
            if src == "live":
                due = pd.Timestamp(E["data_up_to"]) if E.get("data_up_to") else None
                if due is not None and pd.Timestamp(E["written_at"]) > due + pd.Timedelta(minutes=90):
                    s = "late"
            if pt.startswith("P"):
                for m, c in (("comment_ridge", "pred_rank"), ("api_rank", "pred_rank_api"), ("blend", "pred_rank_blend")):
                    if c in f:
                        add(d, pt, m, s, f.sort_values(c).id.astype(str).tolist(), E["written_at"])
            else:
                add(d, pt, "raw_votes", s, f.sort_values("pred_rank").id.astype(str).tolist(), E["written_at"])
    X = pd.DataFrame(rows).sort_values(["day", "point", "method"])
    summ = []
    for (pt, m, s), g in X.groupby(["point", "method", "source"]):
        summ.append({"point": pt, "method": m, "source": s, "days": int(len(g)), "first_day": g.day.min(), "last_day": g.day.max(),
                     **{f"mean_top{k}": round(float(g[f"top{k}"].mean()), 1) for k in (3, 5, 10)}})
    actual = {d: g.head(10).id.tolist() for d, g in real.items()}
    out = {"built_at": pd.Timestamp.now(tz="UTC").isoformat(),
           "definition": "topK = share of the forecast's top K that finished in the day's final daily top K (all ranked launches of the day), x100; days are PT dates",
           "sources": {"live": "written before or at its point time", "late": "written >90 min after its data cut (honest data, not a live call)", "replay": "re-run afterwards with only data up to the point time"},
           "summary": summ, "rows": X.to_dict("records"), "actual_top10": actual}
    os.makedirs(os.path.join(HERE, "results", "web"), exist_ok=True)
    p = os.path.join(HERE, "results", "web", "scoreboard.json"); json.dump(out, open(p, "w"), indent=1, default=str)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/scoreboard.json"], check=True)
    north_star(X)
    print(json.dumps(summ, indent=0))


# backtest number beside each live line (source files in results/; update here when a backtest is re-run)
BACKTEST = {
    ("0005", "published"): ("63.0 / 69.3 / 75.0", "honest out-of-fold LM, 207 days Mar-Oct (honest.json)"),
    ("0005", "makerfix_shadow"): ("60.2 / 68.6 / 75.7", "placeholders as missing, 245 days (maker_resolve.md; current features 59.9 / 67.7 / 75.4)"),
    ("P1", "comment_ridge"): ("66.2 / 70.2 / 75.8", "live-compatible ridge, 207 days month-forward (comment_forecast.md)"),
    ("P2", "comment_ridge"): ("67.8 / 71.2 / 76.1", "same"), ("P3", "comment_ridge"): ("69.1 / 71.4 / 76.1", "same"),
    ("P4", "comment_ridge"): ("68.0 / 73.1 / 77.0", "same"),
    ("R0", "raw_votes"): ("72 / 77 / 88", "6-day replay (early_forecast_replay.json); 85 / 93 / 92 first hour after reveal on 9 days"),
    ("R1", "raw_votes"): ("see replay", "6-day replay"), ("R2", "raw_votes"): ("83 / 90 / 93", "6-day replay"),
    ("R4", "raw_votes"): ("94 / 90 / 95", "6-day replay; 93 / 95 / 93 at 08:00-12:00 PT on 29 days"),
    ("week", "dayend_votes"): ("57.5 / 71.5 / 77.8", "end-of-week call without dated votes, 40 weeks (weekly_forecast.md); 100 / 80 / 90 with day-end votes on 1 week"),
    ("month", "monthlyRank"): ("75 / 75 / 80", "dated reads, 4 months (E5 monthly_northstar); 42 / 50 / 52 from daily rank"),
}
ORDER = [("0005", "published"), ("0005", "makerfix_shadow"), ("0005", "unfixed_replay")] + \
        [(p, m) for p in ("P1", "P2", "P3", "P4") for m in ("comment_ridge", "api_rank", "blend")] + \
        [(p, "raw_votes") for p in ("R0", "R1", "R2", "R4")] + [("week", "dayend_votes"), ("month", "monthlyRank"), ("month", "votes")]


def _boot(v, rng, n=2000):
    v = np.asarray(v, float)
    if len(v) < 5:
        return None
    b = np.array([v[rng.integers(0, len(v), len(v))].mean() for _ in range(n)])
    return np.percentile(b, [2.5, 97.5])


def north_star(X):
    """results/NORTH_STAR.md: one table, every forecast time, live record (with 95% day-bootstrap intervals when n >= 5)
    beside the backtest. Weekly / monthly lines from their forward files."""
    rng = np.random.default_rng(0)
    rows = {}
    for (pt, m, src), g in X.groupby(["point", "method", "source"]):
        rows.setdefault((pt, m), {})[src] = g
    for kind, fp, cols in (("week", "weekly_forecast_forward.jsonl", {"dayend_votes": "week_top"}),
                           ("month", "monthly_forecast_forward.jsonl", {"monthlyRank": "monthlyRank_month_top", "votes": "votes_month_top"})):
        f = os.path.join(HERE, "results", fp)
        if os.path.exists(f):
            W_ = pd.DataFrame([json.loads(l) for l in open(f)])
            if kind == "week":
                W_ = W_[(W_.point == "dayend") & (pd.to_datetime(W_.day).dt.dayofweek == 6)]   # the Sunday end-of-week call
            else:
                W_ = W_.sort_values("day").groupby("month").tail(1)   # the month-end call
            for m, pre in cols.items():
                if len(W_):
                    rows.setdefault((kind, m), {})["live"] = W_.rename(columns={f"{pre}{k}": f"top{k}" for k in (3, 5, 10)})
    L = ["# North star: Product Hunt forecast accuracy", "",
         f"Regenerated by scoreboard.py at {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%MZ')}. topK = share of the forecast's top K "
         "that finished in the final top K (daily rank for 00:05 / P / R; weekly and monthly rank for the period lines). "
         "Days are PT. 95% intervals are day bootstraps, shown when at least 5 days are scored. "
         "Sources: live = written in time; late = honest data cut written afterwards; replay = re-run afterwards.", "",
         "| forecast | when | live: days | live top 3 / 5 / 10 [95% CI] | other rows (source: days, top 3/5/10) | backtest top 3 / 5 / 10 | backtest basis |",
         "|---|---|---|---|---|---|---|"]
    WHEN = {"0005": "00:05 PT", "P1": "01:00 PT", "P2": "02:00 PT", "P3": "03:00 PT", "P4": "04:00 PT", "R0": "reveal ~04:00 PT",
            "R1": "reveal +1 h", "R2": "reveal +2 h", "R4": "reveal +4 h", "week": "Sunday 23:59 PT", "month": "month end"}
    for key in ORDER:
        d = rows.get(key, {}); live = d.get("live")
        if live is not None and len(live):
            mean = [live[f"top{k}"].mean() for k in (3, 5, 10)]
            ci = [_boot(live[f"top{k}"], rng) for k in (3, 5, 10)]
            cell = " / ".join(f"{m_:.1f}" + (f" [{c[0]:.0f}, {c[1]:.0f}]" if c is not None else "") for m_, c in zip(mean, ci))
            nd = len(live)
        else:
            cell, nd = "-", 0
        other = "; ".join(f"{s_}: {len(g)}, " + " / ".join(f"{g[f'top{k}'].mean():.0f}" for k in (3, 5, 10)) for s_, g in d.items() if s_ != "live") or "-"
        bt = BACKTEST.get(key, ("-", "-"))
        L.append(f"| {key[0]} {key[1]} | {WHEN.get(key[0], '')} | {nd} | {cell} | {other} | {bt[0]} | {bt[1]} |")
    L += ["", "Notes: the 00:05 published line is the number of record (first published run per day; duplicate rows removed). "
          "P-point API rank and blend have no months-long backtest (the API's pre-reveal rank is only held from Nov 4). "
          "Weekly / monthly lines start scoring after their first full period (week of Nov 9-15; November)."]
    p = os.path.join(HERE, "results", "NORTH_STAR.md"); open(p, "w").write("\n".join(L) + "\n")
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/NORTH_STAR.md"], check=True)
    print("\n".join(L))


if __name__ == "__main__":
    main()
