"""Score the maker-placeholder shadow (results/shadow_makerfix/<day>.json) once the day's final ranks exist:
top 3/5/10 of rank_unfixed, rank_makerfix and the live published launch_model forecast vs final daily rank, on the
00:05 line-up. Appends to results/shadow_makerfix_forward.jsonl (one row per day, skips days already scored).
usage: python makerfix_score.py"""
import glob, json, os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))


def main():
    from pipeline import warehouse as W
    fp = os.path.join(HERE, "results", "shadow_makerfix_forward.jsonl")
    done = {json.loads(l)["day"] for l in open(fp)} if os.path.exists(fp) else set()
    for p in sorted(glob.glob(os.path.join(HERE, "results", "shadow_makerfix", "*.json"))):
        S = json.load(open(p)); d = S["day"]
        if d in done:
            continue
        R = W.query(f"SELECT CAST(id AS VARCHAR) id, daily_rank FROM launches WHERE day = '{d}' AND daily_rank IS NOT NULL", do_sync=False)
        if R.empty or pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d") <= d:
            continue
        F = pd.DataFrame(S["forecast"]).merge(R, on="id")
        L = W.query(f"SELECT CAST(launch_id AS VARCHAR) id, predicted_rank FROM forecasts WHERE model = 'launch_model' AND forecast_date = '{d}'", do_sync=False)
        F = F.merge(L, on="id", how="left"); F["predicted_rank"] = F.predicted_rank.fillna(999)
        real = lambda k: set(F.nsmallest(k, "daily_rank").id)
        r = {"day": d, "launches": int(len(F)), "placeholder_launches": S["placeholder_launches"]}
        for nm, c in (("live", "predicted_rank"), ("unfixed", "rank_unfixed"), ("makerfix", "rank_makerfix")):
            for k in (3, 5, 10):
                r[f"{nm}_top{k}"] = len(set(F.nsmallest(k, c).id) & real(k)) / k * 100
        open(fp, "a").write(json.dumps(r) + "\n"); print(json.dumps(r))


if __name__ == "__main__":
    main()
