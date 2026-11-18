"""Score dry-run live P1..P4 files (CF_DRY dir) on days with live comments_ts + 00:05 LM + final ranks, beside LM only
and comment count; and test R0/R1 raw votes + w x z(P4 comment score). usage: python comment_forecast_replay_score.py <dry dir>"""
import json, sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/UserSim/experiments/ph_predict"); sys.path.insert(0, "/home/user/UserSim/experiments")
import early_forecast as EF
from pipeline import warehouse as W
S = sys.argv[1]
R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
z = lambda x: (x - x.mean()) / (x.std() + 1e-9)
def topk(g, col, k): return len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100
rows = []
for d in ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-10"]:
    rk = R[R.day == d].set_index("id").daily_rank
    T = EF.load_snaps(d); R0 = EF.reveal(T); lm = EF.lm_scores(d)
    for p in ("P1", "P2", "P3", "P4"):
        F = pd.DataFrame(json.load(open(f"{S}/{d}_{p}.json"))["forecast"]).set_index("id")
        F["rank"] = rk.reindex(F.index); F = F.dropna(subset=["rank"]).reset_index()
        F["lmo"] = [lm.get(i, -99) for i in F.id]
        F["cnt"] = F.n_c + 1e-6 * F.lmo
        r = {"day": d, "point": p}
        for nm, c in (("LM", "lmo"), ("count", "cnt"), ("comments_ridge", "score")):
            r.update({f"{nm}_{k}": topk(F, c, k) for k in (3, 5, 10)})
        rows.append(r)
    if R0 is not None:
        F4 = pd.DataFrame(json.load(open(f"{S}/{d}_P4.json"))["forecast"]).set_index("id").score
        for name, h in (("R0", 0), ("R1", 1)):
            t = R0 + pd.Timedelta(hours=h)
            A = EF.features(T, t, R0, lm, d).reset_index()
            A["rank"] = A.id.map(rk); A = A.dropna(subset=["rank"])
            A["cs"] = A.id.map(F4).fillna(F4.min())
            A["votes"] = A.lv + 1e-6 * A.lm
            r = {"day": d, "point": name}
            for w in (0, 0.25, 0.5, 1.0):
                A["b"] = z(A.lv) + w * z(A.cs)
                r.update({f"votes+{w}c_{k}": topk(A, "b", k) for k in (3, 5, 10)})
            rows.append(r)
X = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(X.groupby("point").mean(numeric_only=True).round(1).T.to_string())
X.to_json(f"{S}/cf_forward_retro.json", orient="records")
