"""read-only diagnosis: null rates of arm-2 inputs in the live 00:05 build (as h25_live builds it) vs the stored rows, Nov 12-14."""
import json, os, sys, glob
import numpy as np, pandas as pd
sys.path.insert(0, os.path.expanduser("~/w/arm2_live")); os.chdir(os.path.expanduser("~/w/experiments/ph_predict")); sys.path.insert(0, ".")
import features as F, model as M, run as RN, history_retrain as HR
COLS = json.load(open(os.path.expanduser("~/w/phops_tm/cols.json")))["2026-10"]
root = os.path.expanduser("~/w/h25/data"); real = F.D; F.D = root
try:
    df = RN.load_llm(F.build(include_today=True))
finally:
    F.D = real
df["id"] = df.id.astype(str)
out = {"features_md5_note": "deployed features.py", "n_today_files": len(glob.glob(f"{real}/today/*.json"))}
for d in ["2026-11-12", "2026-11-13", "2026-11-14"]:
    te = df[df.is_today & (df.day == d)]; st = df[(~df.is_today) & (df.day == d)]
    tr_hist = df[(~df.is_today) & (df.day < d)]
    out[d] = {"today_rows": len(te), "stored_rows": len(st),
              "null_today": {c: round(float(te[c].isna().mean()), 3) for c in COLS if c in te and te[c].isna().mean() > 0},
              "null_stored": {c: round(float(st[c].isna().mean()), 3) for c in COLS if c in st and st[c].isna().mean() > 0},
              "missing_cols": [c for c in COLS if c not in df]}
# hunter rel diagnosis on Nov 14 today rows
te = df[df.is_today & (df.day == "2026-11-14")]
bad = te[te.hist_hunter_rel.isna() & (te.hist_hunter_n > 0)]
rows = []
for _, r in bad.head(8).iterrows():
    H = df[(df.hunter_id == r.hunter_id) & (df.day < "2026-11-14")]
    rows.append({"hist_n": int(r.hist_hunter_n), "earlier_rows": len(H), "earlier_votes_nan": int(H.votes.isna().sum()), "earlier_is_today": int(H.is_today.sum()),
                 "earlier_nan_days": sorted(H[H.votes.isna()].day.unique().tolist())[:6]})
out["hunter_rel_nan_examples"] = rows
out["llm_today_nonnull"] = {d: {c: int(df[df.is_today & (df.day == d)][c].notna().sum()) for c in ("llm_pitch", "llm_brand")} for d in ["2026-11-12", "2026-11-13", "2026-11-14"]}
print(json.dumps(out, indent=1, default=str))
