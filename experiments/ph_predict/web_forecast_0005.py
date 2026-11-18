"""00:05 forecast order as small JSON for the website (no parquet needed on Vercel; website agent Nov 11).
From the warehouse forecasts table (model launch_model), the first published run of each day (Nov 1 was run twice),
duplicate launch ids dropped (best rank kept). Writes results/web/forecast_0005/<day>.json and uploads it to
gs://.../results/web/forecast_0005/<day>.json: {"day", "written_at", "run_updated_at", "forecast": [{"id", "predicted_rank"}]}.
Run after 01:00 PT (never 00:05-01:00 PT); the local warehouse must be synced (pool_size.py in the check does that).
usage: python web_forecast_0005.py [day ...]   (no args: every day from 2026-10-25 not yet written, plus today)"""
import json, os, subprocess, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
OUT = os.path.join(HERE, "results", "web", "forecast_0005")


def main(days):
    from pipeline import warehouse as W
    F = W.query("SELECT forecast_date d, CAST(launch_id AS VARCHAR) id, predicted_rank pr, updated_at u FROM forecasts WHERE model = 'launch_model' AND launch_id IS NOT NULL", do_sync=False)
    os.makedirs(OUT, exist_ok=True)
    today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    todo = days or [d for d in sorted(F.d.unique()) if d >= "2026-10-25" and (d == today or not os.path.exists(f"{OUT}/{d}.json"))]
    for d in todo:
        g = F[F.d == d]
        if g.empty:
            print(json.dumps({"day": d, "status": "no 00:05 forecast in the warehouse"})); continue
        g = g[g.u == g.u.min()].sort_values("pr").drop_duplicates("id")
        g["rank"] = range(1, len(g) + 1)
        res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "run_updated_at": g.u.iloc[0],
               "forecast": [{"id": i, "predicted_rank": int(r)} for i, r in zip(g.id, g["rank"])]}
        p = f"{OUT}/{d}.json"; json.dump(res, open(p, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/forecast_0005/{d}.json"], check=True)
        import heartbeat; heartbeat.beat("forecast_0005", d, pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC"), "ok")
        print(json.dumps({"day": d, "launches": len(g)}))


if __name__ == "__main__":
    main(sys.argv[1:])
