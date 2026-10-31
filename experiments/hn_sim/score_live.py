"""Score the live hourly forecasts (forecast_daily/<day>/<HHMM>.json, from forecast_daily.py on hn-sim-1) against the
real daily list once it has settled (the listwatch read made 48 h or more after the day ended; if none yet, the latest
read). Prints top-30 / top-10 found per forecast hour, per day.

    python score_live.py
"""
import json
import os

import pandas as pd

import store as S

b = S._bucket()
F, L = [], []
for x in b.list_blobs(prefix="usersim_sim/hn_jobs/cache/forecast_daily/"):
    f = json.loads(x.download_as_text())
    F.append({"day": f["day"], "hour": f["made_at"][11:13], "top": [r["post_id"] for r in f["top"]]})
for x in b.list_blobs(prefix="usersim_sim/hn_jobs/cache/listwatch/"):
    L.append(pd.read_json(x.download_as_text(), lines=True, dtype={"day": str}))
L = pd.concat(L) if L else pd.DataFrame(columns=["read_at", "day", "rank", "post_id"])
rows = []
for f in F:
    g = L[L.day == f["day"]]
    if g.empty:
        continue
    end = pd.Timestamp(f["day"], tz="UTC").timestamp() + 86400
    settled = g[g.read_at >= end + 48 * 3600]
    g = (settled if len(settled) else g)
    g = g[g.read_at == g.read_at.max()]
    real30, real10 = set(g[g["rank"] <= 30].post_id), set(g[g["rank"] <= 10].post_id)
    rows.append({"day": f["day"], "hour": f["hour"], "settled": bool(len(settled)),
                 "top30_found": len(real30 & set(f["top"][:30])) / 30, "top10_found": len(real10 & set(f["top"][:10])) / 10})
R = pd.DataFrame(rows)
print(R.groupby(["day", "hour", "settled"])[["top30_found", "top10_found"]].mean().round(2).to_string() if len(R) else "no forecasts yet")
