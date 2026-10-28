"""Small JSON files for the pipeline dashboard (https://claude.ai/artifact/MVKkd6uG95hsGpmopJ9jKL), from the warehouse.
Each file is one dataset of the dashboard; a daily scheduled session uploads them after the pipeline runs.
  runs.json       one row per pipeline step per day (status, items, MB, $, seconds)
  collected.json  rows added to the warehouse per day and table (the one-time initial load is left out)
  totals.json     rows in each table now
  spend.json      $ per day and provider from the daily steps and backtests
  scores.json     yesterday's forecast vs the final daily ranks (share of the real top k we had in our top k)
  forecast.json   the latest daily forecast (top 10)
  backtests.json  the twice-weekly backward monthly test, one row per run, list and variant
usage: python -m pipeline.dash_export [out_dir]"""
import json, os, sys
from . import warehouse as W

COLLECTED = {   # table -> label, and which rows count
    "events": ("upvotes", "kind = 'upvote'"), "comments": ("comments", "TRUE"), "people": ("new people", "TRUE"),
    "follows": ("follow rows", "TRUE"), "persona_ratings": ("persona ratings", "TRUE"), "launches": ("launch updates", "TRUE"),
}


def rows(con, sql):
    df = con.execute(sql).df()
    return json.loads(df.to_json(orient="records", date_format="iso"))


def export(out):
    con = W.connect()
    os.makedirs(out, exist_ok=True)
    have = set(con.execute("SELECT table_name FROM information_schema.tables").df().table_name)
    raw = lambda t: f"read_parquet('{W.LOCAL}/{t}/*.parquet', union_by_name=true, filename=true)"
    data = {}
    data["runs"] = rows(con, """SELECT run_date, step, status, items, round(bytes / 1e6, 1) AS mb, round(usd, 4) AS usd, seconds
                                FROM pipeline_runs ORDER BY run_date, step""") if "pipeline_runs" in have else []
    data["collected"] = [r for t, (label, cond) in COLLECTED.items() if t in have for r in rows(con, f"""
        SELECT substr(updated_at, 1, 10) AS day, '{label}' AS what, count(*) AS n FROM {raw(t)}
        WHERE filename NOT LIKE '%initial-%' AND {cond} GROUP BY 1 ORDER BY 1""")]
    data["totals"] = [{"table": t, "rows": int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])} for t in sorted(have)]
    data["spend"] = rows(con, """SELECT substr(updated_at, 1, 10) AS day, provider, round(sum(usd), 4) AS usd FROM spend
                                 WHERE step LIKE 'daily_%' OR step LIKE 'backtest%' GROUP BY 1, 2 ORDER BY 1, 2""")
    data["scores"] = rows(con, "SELECT day, model, k, hit, round(100 * recall, 1) AS recall FROM daily_scores ORDER BY day, k") \
        if "daily_scores" in have else []
    data["forecast"] = rows(con, """SELECT forecast_date, predicted_rank, name FROM forecasts
                                    WHERE forecast_date = (SELECT max(forecast_date) FROM forecasts) AND predicted_rank <= 10
                                    ORDER BY predicted_rank""")
    data["backtests"] = rows(con, """SELECT run_on, run_file, variant, list, recall FROM backtests
                                     WHERE run_file LIKE 'monthly_%' ORDER BY run_on, list, variant""")
    for k, v in data.items():
        json.dump(v, open(f"{out}/{k}.json", "w"))
        print(f"{k:10s} {len(v):>5} rows")
    return data


if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "/tmp/usersim_dash")
