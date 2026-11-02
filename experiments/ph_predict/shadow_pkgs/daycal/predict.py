"""Day-calibrated weekly forecast (shadow_daycal). Run from this folder: python3 predict.py <day> -> JSON lines
{"launch_id", "score"}; score = log expected votes. The launch model's prediction shifted by a day factor (weekday,
line-up size, the line-up's predicted total, 7-day trailing real and predicted totals ending 2 days before); the
daily order is the launch model's. Inputs: ../../../results/forecast_<day>.parquet (today and the trailing days),
lm_days.json (backtest days' predicted totals), real daily vote totals from the warehouse (pipeline.warehouse)."""
import json, os, sys, datetime as dt
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EXP = os.path.dirname(PH)


def main(day):
    meta = json.load(open(os.path.join(HERE, "meta.json")))
    F = pd.read_parquet(os.path.join(PH, "results", f"forecast_{day}.parquet")); F["id"] = F.id.astype(str)
    mu0 = np.expm1(F.pred.astype(float)).clip(lower=0.5)
    lm = json.load(open(os.path.join(HERE, "lm_days.json")))
    trail = [(dt.date.fromisoformat(day) - dt.timedelta(days=k)).isoformat() for k in range(2, 9)]
    for t in trail:
        f = os.path.join(PH, "results", f"forecast_{t}.parquet")
        if os.path.exists(f):
            lm[t] = float(np.expm1(pd.read_parquet(f).pred.astype(float)).clip(lower=0.5).sum())
    sys.path.insert(0, EXP)
    from pipeline import warehouse as W
    real = dict(W.query(f"SELECT day::VARCHAR, sum(votes) FROM launches WHERE day::VARCHAR IN ({','.join(repr(t) for t in trail)}) "
                        "AND votes IS NOT NULL GROUP BY 1").values.tolist())
    tr_real = [real[t] for t in trail if t in real]; tr_lm = [lm[t] for t in trail if t in lm]
    X = pd.DataFrame({"day_wd": dt.date.fromisoformat(day).weekday(), "day_n": len(F), "day_lm_sum": float(mu0.sum()),
                      "trail_real7": np.mean(tr_real) if len(tr_real) >= 3 else np.nan,
                      "trail_lm7": np.mean(tr_lm) if len(tr_lm) >= 3 else np.nan}, index=F.index)[meta["features"]]
    raw = np.mean([lgb.Booster(model_file=os.path.join(HERE, f)).predict(X, raw_score=True) for f in meta["models"]], axis=0)
    for i, s in zip(F.id, raw + np.log(mu0)):
        print(json.dumps({"launch_id": str(i), "score": float(s)}))
    print(f"daycal: {len(F)} launches, trailing days real {len(tr_real)}/7, predicted {len(tr_lm)}/7, day factor {float(np.exp(raw[0])):.3f}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
