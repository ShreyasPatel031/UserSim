"""How much does the ph_n_makers leak inflate arm 2 (orchestrator 23:34Z Nov 14)? Same trained arm-2 models, two scorings of the test
rows on the nights with 00:05 reads (Oct 25 - Nov 13): (1) stored ph_n_makers and its day rank (as the backtest uses them), (2) the 00:05
values (len(makers) in data/today/<d>.json; day rank recomputed within the day as features.py does: groupby(day).rank(pct=True)).
Launches absent from the 00:05 file keep the stored value (counted). Models: month-forward arm 2 (TW.prep, TW.P0, 5 seeds, cols minus
TW.ID_COLS / llm_site / ph_month) for 2026-10 (train < Oct) and 2026-11 (train < Nov). Pre-registered: paired frozen - stored,
top 3/5/10, day bootstrap 95% (scored by nmakers_frozen_score.py on truth_daily.json).
usage (VM, cwd ~/w/experiments/ph_predict): PYTHONPATH=~/w/phops_tm:~/w/mk:.:~/w/h25 /opt/exp/bin/python3 nmakers_frozen.py <out.parquet> [from to]"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
D0, D1 = (sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ("2026-10-25", "2026-11-13")
TD = os.path.expanduser("~/w/experiments/ph_predict/data/today")
df, _ = HR.build(os.environ.get("H25_SRC", os.path.expanduser("~/w/ph_history/2025")))
df["id"] = df.id.astype(str); df = df.drop_duplicates("id", keep="last").reset_index(drop=True)
n0005 = {}
for d in pd.date_range(D0, D1).strftime("%Y-%m-%d"):
    f = f"{TD}/{d}.json"
    if os.path.exists(f):
        for r in json.load(open(f)):
            mk = r.get("makers") or []; n0005[str(r["id"])] = len(mk) if isinstance(mk, list) else np.nan
out = []
for m in sorted({d[:7] for d in pd.date_range(D0, D1).strftime("%Y-%m-%d")}):
    tem = (df.mon == m) & (df.day >= D0) & (df.day <= D1)
    if not tem.any(): continue
    tr, te, cols = TW.prep(df[df.mon < m], df[tem]); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    te = te.copy(); te["id"] = te.id.astype(str)
    fz = te.copy(); v = fz.id.map(n0005); fz["has_0005"] = v.notna(); fz["ph_n_makers"] = v.fillna(fz.ph_n_makers)
    fz["ph_dayrank_ph_n_makers"] = fz.groupby("day").ph_n_makers.rank(pct=True)
    B = [lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[cols], tr.logv) for s in range(5)]
    out.append(pd.DataFrame({"id": te.id.values, "day": te.day.values, "stored": np.mean([b.predict(te[cols]) for b in B], 0),
                             "frozen": np.mean([b.predict(fz[cols]) for b in B], 0), "n_stored": te.ph_n_makers.values,
                             "n_0005": fz.ph_n_makers.values, "has_0005": fz.has_0005.values}))
    print(json.dumps({"month": m, "test": int(len(te)), "with_0005": int(fz.has_0005.sum()), "n_changed": int((te.ph_n_makers.values != fz.ph_n_makers.values).sum())}), flush=True)
pd.concat(out).to_parquet(sys.argv[1]); print(json.dumps({"done": True}))
