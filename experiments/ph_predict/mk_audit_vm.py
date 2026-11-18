"""read-only: hist_maker_n as the backtest build sees it (maker ids from the stored day file) vs as the live 00:05 path sees it
(maker ids from data/today/<d>.json), same earlier-maker history (stored day files, days < d, placeholder ids kept as features.py does)."""
import glob, json, os
import pandas as pd
D = os.path.expanduser("~/w/experiments/ph_predict/data")
ids = lambda r: [str(m.get("id")) for m in (r.get("makers") or []) if isinstance(m, dict)]
PH = lambda m: m in ("0", "", "None")
days = sorted(os.path.basename(f)[:10] for f in glob.glob(f"{D}/days/*.json"))
Mk, rows = {}, []
for d in days:
    S = json.load(open(f"{D}/days/{d}.json"))
    T = {str(r["id"]): r for r in json.load(open(f"{D}/today/{d}.json"))} if os.path.exists(f"{D}/today/{d}.json") and d >= "2026-10-25" else None
    if T is not None:
        for r in S:
            i = str(r["id"]); ms_b = ids(r); t = T.get(i); ms_l = ids(t) if t else None
            rows.append({"day": d, "id": i, "in_0005": t is not None, "n_mk_b": len(ms_b), "n_ph_b": sum(map(PH, ms_b)),
                         "hist_b": sum(Mk.get(m, 0) for m in ms_b),
                         "n_mk_l": len(ms_l) if ms_l is not None else None, "n_ph_l": sum(map(PH, ms_l)) if ms_l is not None else None,
                         "hist_l": sum(Mk.get(m, 0) for m in ms_l) if ms_l is not None else None,
                         "hist_b_noph": sum(Mk.get(m, 0) for m in ms_b if not PH(m)),
                         "hist_l_noph": sum(Mk.get(m, 0) for m in ms_l if not PH(m)) if ms_l is not None else None})
    for r in S:
        for m in set(ids(r)): Mk[m] = Mk.get(m, 0) + 1
pd.DataFrame(rows).to_parquet(os.path.expanduser("~/w/phops_tm/mk_audit.parquet")); print(len(rows), len(days), days[0])
