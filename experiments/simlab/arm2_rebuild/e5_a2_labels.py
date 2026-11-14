"""E5 (orchestrator 11:55Z Nov 14): arm-2 training-data tests on the backup rebuild. Same build / old-row rules / columns / fit as
history_retrain.py DECOMP 'both' (TW.prep, TW.fitw, minus ID_COLS, llm_site, ph_month). Test months Apr-Oct 2026, 2026 rows only.
Variants (train rows for test month m):
  base      2025 + 2026 rows with mon < m                      (= 'both')
  dropgap   base minus the 2025 days with a missing rank inside the listed top 10 (holes, GAP_FILE)
  droptrunc base minus the 2025 days listing fewer than 10 ranked launches (short lists)
  lag30     2025 rows + 2026 rows with day < (first day of m) - 30 days (30-day publication lag on labels)
usage: PYTHONPATH=. H25_DATA=.. H25_SRC=.. ARM=2 GAP_FILE=.. python e5_a2_labels.py <out parquet>"""
import json, os, sys, time, glob
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; SEEDS = int(os.environ.get("SEEDS", "5"))
df, _ = HR.build(os.environ["H25_SRC"]); old = df.day < "2026-01-01"
gap = set(json.load(open(os.environ["GAP_FILE"])))
nr = {os.path.basename(f)[:-5]: sum(1 for x in json.load(open(f)) if x.get("dailyRank")) for f in glob.glob(os.environ["H25_SRC"] + "/*.json")}
trunc = {d for d, n in nr.items() if n < 10}
print(json.dumps({"gap_days": len(gap), "gap_rows": int(df[old & df.day.isin(gap)].shape[0]), "trunc_days": len(trunc), "trunc_rows": int(df[old & df.day.isin(trunc)].shape[0])}), flush=True)
P = []
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    te0 = df[(df.mon == m) & ~old]; cut = (pd.Timestamp(m + "-01") - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    base = df[df.mon < m]
    V = {"base": base, "dropgap": base[~(old[base.index] & base.day.isin(gap))], "droptrunc": base[~(old[base.index] & base.day.isin(trunc))],
         "lag30": base[old[base.index] | (base.day < cut)]}
    for nm, tr0 in V.items():
        tr, te, cols = TW.prep(tr0, te0); cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
        for s in range(SEEDS):
            P.append(pd.DataFrame({"id": te.id.values, "variant": nm, "seed": s, "pred": TW.fitw(tr, te, cols, s)}))
    print(json.dumps({"month": m, "seconds": round(time.time() - t0)}), flush=True)
R = pd.concat(P); R.to_parquet(OUT.replace(".parquet", "_seeds.parquet"))
A = R.groupby(["id", "variant"]).pred.mean().unstack().reset_index().merge(df[["id", "day", "dailyRank"]], on="id"); A.to_parquet(OUT)
print(json.dumps({"rows": len(A), "days": int(A.day.nunique())}))
