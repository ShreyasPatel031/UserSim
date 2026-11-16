"""Forecast-side drivers from the deployed arm-2 model itself (orchestrator 12:50Z Nov 14; SHADOW only, not on the website).

Runs the pinned ~/w/arm2_live/h25_live.predict(<d>) exactly as the 00:05 forecast does (same 5 seeds, same training rows), with LightGBM's
predict wrapped so the 5 fitted boosters and today's input frame are captured; then tree-SHAP (pred_contrib) averaged over the seeds.
Checks: sum of contributions == the seed-mean prediction (and == the published pred_arm2 in the 00:05 parquet, when present).
Groups = E5's map over all 40 inputs (claude/person-model-v2 b6450b3a, experiments/simlab/arm2_explain.py grp()). Drivers of a launch =
groups ranked by WITHIN-DAY-CENTRED contribution (contribution minus the day mean; only differences move ranks).
Concentration = top group's share of the positive centred contribution; > 0.6 is flagged (backtest: such picks right 54% vs 64%, overlapping
intervals: a caution, not a rule).
Writes results/shadow_arm2_shap/<d>.json and gs://.../results/shadow_arm2_shap/<d>.json. Launch ids and numbers only; no names or people.
usage (VM, cwd ~/w/experiments/ph_predict, PYTHONPATH unset): python3 arm2_shap.py <d>   (DRY=1: local file only)"""
import datetime as dt
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
LABEL = "from the forecast model itself; removing the top driver changes the pick 45% of the time (214 backtest days)"
CAUTION = "picks where one group carries more than 60% of the positive contribution were right 54% vs 64% (214 backtest days; intervals overlap)"


def grp(c):   # E5's map (b6450b3a arm2_explain.py), verbatim
    if c.startswith("hist_") or "hunter" in c: return "hunter record"
    if c == "llm_pitch": return "pitch"
    if c == "llm_brand": return "brand"
    if c.startswith("topic_") or c == "ph_n_topics": return "topic"
    if c.startswith("comp_"): return "competition"
    if "media" in c or c == "ph_has_video": return "media"
    if "makers" in c: return "team size"
    if c.startswith("promo_") or c == "x_company_has_x": return "promotion"
    if c in ("txt_ridge", "ph_desc_len", "ph_tagline_len", "ph_name_len"): return "text"
    return "day/lineup"


def main(d):
    sys.path.insert(0, os.path.expanduser("~/w/arm2_live"))
    import h25_live
    import lightgbm as lgb
    SEEN = []

    class Rec(lgb.LGBMRegressor):
        def predict(self, X, *a, **k):
            if not a and not k:
                SEEN.append((self, X))
            return super().predict(X, *a, **k)

    class Shim:
        pass
    shim = Shim(); shim.__dict__.update({k: getattr(lgb, k) for k in dir(lgb) if not k.startswith("__")}); shim.LGBMRegressor = Rec
    real = h25_live.lgb; h25_live.lgb = shim
    try:
        PA, info = h25_live.predict(d)
    finally:
        h25_live.lgb = real
    if len(SEEN) != 5:
        raise RuntimeError(f"expected 5 fitted boosters, captured {len(SEEN)}")
    X = SEEN[0][1]; cols = list(X.columns)
    C = np.mean([m.predict(Xs, pred_contrib=True) for m, Xs in SEEN], axis=0)
    pred = np.mean([m.predict(Xs, raw_score=False, num_iteration=None) for m, Xs in SEEN], axis=0)
    ids = PA.id.astype(str).values
    chk_sum = float(np.abs(C.sum(1) - pred).max()); chk_pub = None
    fp = f"/tmp/arm2_shap_fc_{d}.parquet"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", fp], capture_output=True).returncode == 0:
        F = pd.read_parquet(fp); os.remove(fp)
        if "pred_arm2" in F and F.pred_arm2.notna().all():
            pub = F.assign(id=F.id.astype(str)).set_index("id").pred_arm2.reindex(ids).values
            chk_pub = float(np.nanmax(np.abs(pub - PA.pred_arm2.values)))
    S = pd.DataFrame(C[:, :-1], columns=cols, index=ids)
    G = S.T.groupby([grp(c) for c in cols]).sum().T                       # group contribution per launch
    Cc = G - G.mean()                                                       # within-day centred
    rank = pd.Series(PA.pred_arm2.values, index=ids).rank(ascending=False, method="first").astype(int)
    L = {}
    for i in ids:
        r = Cc.loc[i].sort_values(key=lambda s: -s.abs())
        pos = Cc.loc[i][Cc.loc[i] > 0]
        top_pos = Cc.loc[i].sort_values(ascending=False)
        conc = float(top_pos.iloc[0] / pos.sum()) if len(pos) and pos.sum() > 0 else None
        L[i] = {"rank_arm2": int(rank[i]), "score": round(float(PA.set_index(PA.id.astype(str)).pred_arm2[i]), 4),
                "groups_centred": {g: round(float(v), 4) for g, v in r.items()},
                "top_groups": [g for g in top_pos.index[:3] if top_pos[g] > 0],
                "concentration": round(conc, 3) if conc is not None else None, "concentrated": bool(conc is not None and conc > 0.6)}
    out = {"day": d, "kind": "arm2_shap_shadow", "status": "shadow only, not on the website", "label": LABEL, "caution": CAUTION,
           "unit": "points (log-vote scale), contribution minus the day mean", "groups": sorted(set(grp(c) for c in cols)), "inputs": len(cols),
           "group_map": {c: grp(c) for c in cols}, "group_map_source": "E5 claude/person-model-v2 b6450b3a arm2_explain.py",
           "model": "arm 2 (pinned ~/w/arm2_live/h25_live.py, 5 seeds, refit as at 00:05)", "fit_info": info,
           "checks": {"max |sum(shap) - seed-mean pred|": round(chk_sum, 8), "max |refit - published pred_arm2|": None if chk_pub is None else round(chk_pub, 8)},
           "written_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "launches": L}
    os.makedirs(os.path.join(HERE, "results", "shadow_arm2_shap"), exist_ok=True)
    p = os.path.join(HERE, "results", "shadow_arm2_shap", f"{d}.json"); json.dump(out, open(p, "w"), indent=1)
    if os.environ.get("DRY") != "1":
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/shadow_arm2_shap/{d}.json"], check=True)
    print(json.dumps({"day": d, "launches": len(L), "checks": out["checks"], "concentrated": sum(v["concentrated"] for v in L.values()), "file": p}))


if __name__ == "__main__":
    main(sys.argv[1])
