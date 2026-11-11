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
    print(json.dumps(summ, indent=0))


if __name__ == "__main__":
    main()
