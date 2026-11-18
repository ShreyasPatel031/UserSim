"""ph_n_makers leak test (orchestrator 23:28Z Nov 14). Arm 2 retrained with ph_n_makers and ph_dayrank_ph_n_makers DROPPED vs arm 2,
same seeds, same months, same rows. PRE-REGISTERED decision (orchestrator's rule): primary = 2026 top 5 paired difference (drop - arm 2),
184 days on truth_daily.json, day bootstrap 95%; if the interval's lower end is not below 0 by more than noise (i.e. the interval
includes 0 or is above it), the drop goes into the next bundle; if the whole interval is below 0, report the loss and keep a
00:05-frozen version as a forward test from Oct 25. 2025 (Mar-Dec, trained on 2025 months < m only) reported alongside.
Arms: month-forward like history_retrain DECOMP=1 ARM=2 / arm2_explain.py (TW.prep, TW.P0, 5 seeds, cols minus TW.ID_COLS, llm_site, ph_month).
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=~/w/phops_tm:~/w/mk:.:~/w/h25 /opt/exp/bin/python3 drop_nmakers.py <out.parquet>"""
import json, os, sys, time
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
DROP = ["ph_n_makers", "ph_dayrank_ph_n_makers"]
t0 = time.time()
df, _ = HR.build(os.environ.get("H25_SRC", os.path.expanduser("~/w/ph_history/2025"))); old = (df.day < "2026-01-01").values
months = [("2026", m, (df.mon < m).values, (df.mon == m).values & ~old) for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]] + \
         [("2025", m, (df.mon < m).values & old, (df.mon == m).values & old) for m in [f"2025-{k:02d}" for k in range(3, 13)]]
P = []
for yr, m, trm, tem in months:
    if tem.sum() == 0 or trm.sum() == 0: continue
    tr, te, cols = TW.prep(df[trm], df[tem]); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    assert all(c in cols for c in DROP), f"{m}: drop columns not in the arm-2 input list"
    cd = [c for c in cols if c not in DROP]
    fit = lambda cc: np.mean([lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], 0)
    P.append(pd.DataFrame({"id": te.id.astype(str).values, "day": te.day.values, "year": yr, "dailyRank": pd.to_numeric(te.dailyRank, errors="coerce").values,
                           "arm2": fit(cols), "drop": fit(cd)}))
    print(json.dumps({"month": m, "test": int(len(te)), "inputs": len(cols), "inputs_drop": len(cd), "seconds": round(time.time() - t0)}), flush=True)
pd.concat(P).to_parquet(sys.argv[1]); print(json.dumps({"done": True, "seconds": round(time.time() - t0)}))
