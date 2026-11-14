"""Arm 2 + the fields picked by rawfield_sweep.py (drv.slug_suffix_n, slug:len; values from the stored raw record, knowable at 00:05 per
the sweep's check). PRE-REGISTERED: same rows, months and 5 seeds as arm 2 (month-forward, TW.prep, TW.P0); paired (plus - arm 2) top 3/5/10,
day bootstrap 95%. Order: 2025 first (YEAR=2025), then 2026 once (YEAR=2026). Scored by drop_nmakers_score.py-style code in rawfield_arm2_score.py.
usage (VM): PYTHONPATH=~/w/phops_tm:~/w/mk:.:~/w/h25 /opt/exp/bin/python3 rawfield_arm2.py <rawfields.parquet> <out.parquet> <YEAR>"""
import json, os, sys, time
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
ADD = {"drv.slug_suffix_n": "rf_slug_suffix_n", "slug:len": "rf_slug_len"}
RF = pd.read_parquet(sys.argv[1]); RF = RF[RF.kind == "stored"].drop_duplicates("id", keep="last")[["id"] + list(ADD)].rename(columns=ADD)
YEAR = sys.argv[3]; t0 = time.time()
df, _ = HR.build(os.environ.get("H25_SRC", os.path.expanduser("~/w/ph_history/2025")))
df["id"] = df.id.astype(str); df = df.drop_duplicates("id", keep="last").reset_index(drop=True); df = df.merge(RF, on="id", how="left")
old = (df.day < "2026-01-01").values
months = [("2026", m, (df.mon < m).values, (df.mon == m).values & ~old) for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]] if YEAR == "2026" else \
         [("2025", m, (df.mon < m).values & old, (df.mon == m).values & old) for m in [f"2025-{k:02d}" for k in range(3, 13)]]
P = []
for yr, m, trm, tem in months:
    if tem.sum() == 0 or trm.sum() == 0: continue
    tr, te, cols = TW.prep(df[trm], df[tem]); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month") and c not in ADD.values()]
    for c in ADD.values():
        tr[c] = df.loc[tr.index, c].values if c not in tr else tr[c]; te[c] = df.loc[te.index, c].values if c not in te else te[c]
    cp = cols + list(ADD.values())
    fit = lambda cc: np.mean([lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], 0)
    P.append(pd.DataFrame({"id": te.id.astype(str).values, "day": te.day.values, "year": yr, "dailyRank": pd.to_numeric(te.dailyRank, errors="coerce").values,
                           "arm2": fit(cols), "plus": fit(cp)}))
    print(json.dumps({"month": m, "test": int(len(te)), "inputs": len(cols), "added_coverage_test": round(float(te[list(ADD.values())].notna().all(axis=1).mean()), 3),
                      "seconds": round(time.time() - t0)}), flush=True)
pd.concat(P).to_parquet(sys.argv[2]); print(json.dumps({"done": True}))
