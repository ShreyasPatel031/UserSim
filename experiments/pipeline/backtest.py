"""Twice-weekly backward monthly test (Mondays and Thursdays, after the daily run): retrain on everything before each
test month and score the last two months, 5 seeds, with the three numbers we report:
  simulation only  (=sc)                     what the user simulation alone predicts
  launch only      (-cm-rec-hn-web-dom-fol-seg)       launch facts, no person data
  both             (-cm-rec-hn-web-dom-fol-seg+sc)    launch facts + simulation
  current          (-cm-rec-hn-web-dom)               the live daily forecast's inputs (model.LIVE_SOURCES)
Only "simulation only" is claimed as the simulation's accuracy. Weekly and monthly lists count only once they have ended.
Writes the backtests table (run_file monthly_<date>) and the machine time to spend.
usage: python -m pipeline.backtest [YYYY-MM-DD] [--force]"""
import datetime as dt, os, subprocess, sys, time
import pandas as pd
from . import warehouse as W

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); PH = os.path.join(EXP, "ph_predict")
DAYS = (0, 3)                        # Monday, Thursday
VARIANTS = {"=sc": "simulation only", "-cm-rec-hn-web-dom-fol-seg": "launch only", "-cm-rec-hn-web-dom-fol-seg+sc": "both",
            "-cm-rec-hn-web-dom": "current"}   # current = the live forecast's inputs (model.LIVE_SOURCES)
USD_PER_HOUR = float(os.environ.get("VM_USD_PER_HOUR", "0.134"))   # e2-standard-4 on demand, us-central1


def months(d):
    first = dt.date.fromisoformat(d).replace(day=1)
    prev = (first - dt.timedelta(days=1)).replace(day=1)
    return [prev.strftime("%Y-%m"), first.strftime("%Y-%m")]


def main(argv):
    d = next((a for a in argv if a[:2] == "20"), dt.date.today().isoformat())
    if dt.date.fromisoformat(d).weekday() not in DAYS and "--force" not in argv:
        print("not a backtest day"); return
    ms, out, t0 = months(d), f"{PH}/results/monthly_{d}.csv", time.time()
    subprocess.run(["python3", "robust_src.py", *VARIANTS], cwd=PH, check=True,
                   env={**os.environ, "MONTHS": ",".join(ms), "OUT": out})
    secs = time.time() - t0
    R = pd.read_csv(out.replace(".csv", "_lists.csv"), dtype={"key": str})
    today = dt.date.fromisoformat(d)
    final = lambda lst, key: (lst.startswith("day") or (lst.startswith("week") and key < today.strftime("%G-W%V"))
                              or (lst.startswith("mon") and key < today.strftime("%Y-%m")))   # only lists that have ended
    R = R[[final(l, k) for l, k in zip(R.list, R.key)]]
    P = R.groupby(["list", "variant"]).recall.mean().unstack().mul(100).round(1)
    n = R.groupby("list").key.nunique()
    rows = [{"run_file": f"monthly_{d}", "run_on": d, "variant": VARIANTS[v], "list": lst, "recall": float(P.loc[lst, v]),
             "seeds": 5, "months": ",".join(ms), "lists": int(n[lst])} for v in VARIANTS for lst in P.index if v in P.columns]
    W.write("backtests", pd.DataFrame(rows))
    W.write("spend", pd.DataFrame([{"step": "backtest_monthly", "provider": "gcp_vm", "usd": round(secs / 3600 * USD_PER_HOUR, 4),
                                    "note": f"{secs / 60:.0f} min machine time", "logged_on": d}]))
    W.write("pipeline_runs", pd.DataFrame([{"run_date": d, "step": "backtest", "status": "ok", "items": len(rows), "bytes": 0,
                                            "usd": round(secs / 3600 * USD_PER_HOUR, 4), "seconds": round(secs, 1)}]))
    print(P[[v for v in VARIANTS if v in P.columns]].to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
