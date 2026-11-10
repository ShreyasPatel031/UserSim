"""Score the live hourly forecasts (forecast_daily/<day>/<HHMM>.json, from forecast_daily.py on hn-sim-1) against the
real daily list once it has settled (the listwatch read made 48 h or more after the day ended; if none yet, the latest
read). Prints top-30 / top-10 found per forecast hour, per day.

    python score_live.py
"""
import io
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
    L.append(pd.read_json(io.StringIO(x.download_as_text()), lines=True, dtype={"day": str}, convert_dates=False))
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


# ---- live per-post odds (odds_live.py recent): predicted vs realized P(top 30), by decile -------------------------
def odds_calibration():
    """Each hourly odds_live/<day>/<HHMM>.json: every post's P(top 30) at the age it had reached. Realized = the post is
    in a settled daily top 30 (a listwatch read 48 h+ after that list's day ended). Only posts whose possible list days
    (from the earliest posting day through 3 days later; re-ups land later) have all settled count. Reports by decile, Brier, AUC; saves odds_calibration.csv."""
    import numpy as np
    from sklearn.metrics import brier_score_loss, roc_auc_score
    rows = []
    for x in b.list_blobs(prefix="usersim_sim/hn_jobs/cache/odds_live/"):
        for r in json.loads(x.download_as_text()):
            rows.append(r)
    if not rows:
        print("odds: no live forecasts yet")
        return
    O = pd.DataFrame(rows)
    settled = {}
    for d, g in L.groupby("day"):
        end = pd.Timestamp(d, tz="UTC").timestamp() + 86400
        s = g[g.read_at >= end + 48 * 3600]
        if len(s):
            s = s[s.read_at == s.read_at.max()]
            settled[d] = set(s[s["rank"] <= 30].post_id)
    first = pd.to_datetime(O.made_at - 3 * 3600, unit="s", utc=True)          # posts scored are up to 3 h old
    O["days"] = [[(t + pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, 4)] for t in first]
    O = O[[all(d in settled for d in ds) for ds in O.days]]
    if O.empty:
        print(f"odds: {len(rows)} live forecasts, none settled yet (settled list days: {sorted(settled)})")
        return
    O["y"] = [int(any(pid in settled[d] for d in ds)) for pid, ds in zip(O.post_id, O.days)]
    O = O.sort_values("made_at").drop_duplicates(["post_id", "age"], keep="first")
    out = []
    for age, g in O.groupby("age"):
        if len(g) < 10:                                            # too few posts for deciles (e.g. a rare age label)
            print(f"odds {age}: {len(g)} posts, skipped (fewer than 10)")
            continue
        g = g.assign(decile=pd.qcut(g.p_top30.rank(method="first"), 10, labels=False))
        t = g.groupby("decile").agg(posts=("y", "size"), predicted=("p_top30", "mean"), realized=("y", "mean")).reset_index()
        t.insert(0, "age", age)
        out.append(t)
        auc = roc_auc_score(g.y, g.p_top30) if g.y.nunique() == 2 else float("nan")
        print(f"odds {age}: {len(g)} posts, {g.y.sum()} made a top 30; Brier {brier_score_loss(g.y, g.p_top30):.4f}; AUC {auc:.3f}")
    T = pd.concat(out)
    print(T.round(3).to_string(index=False))
    T.to_csv(os.path.join(S.LOCAL, "odds_calibration_live.csv"), index=False)


odds_calibration()
