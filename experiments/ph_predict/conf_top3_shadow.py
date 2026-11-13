"""Top-3 confidence shadow (orchestrator 21:10Z Nov 13; shadow next to conf_live, NOT for the website until ~30 live days).
Frozen fit results/frozen/top3_confidence_arm2_20261113.json (top3_confidence.py; 184 month-forward backtest days). Score = the published
00:05 order: pred_arm2 from raw/daily/<d>/forecast_<d>.parquet (falls back to pred = clean_nosite when arm 2 is missing; flagged).
Per pick: P(finishes in the official top 3) as "about N in 10". Day tier from expected picks right: sure / normal / open (backtest tercile
cut points), with each tier's measured accuracy. Writes results/web/confidence_top3_shadow/<d>.json + bucket copy, and adds
items["top3_confidence"] + launches[id]["top3_confidence"] to results/web/why/<d>_0005.json (and why_shadow until Nov 20).
usage: python conf_top3_shadow.py <d>   (DRY=1: print only, nothing uploaded)"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
FZ = json.load(open(f"{HERE}/results/frozen/top3_confidence_arm2_20261113.json"))
TIERS = [("open", 0.0, 1.751, 53.8), ("normal", 1.751, 1.916, 62.8), ("sure", 1.916, 9.0, 67.8)]   # expected-right cut points (backtest terciles)
NOTE = "shadow; per-pick probability that the pick finishes top 3, calibrated month-forward on 184 backtest days (May-Oct); not on the website until ~30 live days"


def main(d):
    dry = os.environ.get("DRY") == "1"; tmp = tempfile.mkdtemp()
    loc = f"{HERE}/results/forecast_{d}.parquet"
    if not os.path.exists(loc):
        loc = f"{tmp}/f.parquet"; subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", loc], capture_output=True)
    if not os.path.exists(loc):
        print(json.dumps({"day": d, "status": "no forecast parquet"})); sys.exit(1)
    T = pd.read_parquet(loc); T["id"] = T.id.astype(str)
    base = "pred_arm2" if "pred_arm2" in T and T.pred_arm2.notna().all() else "pred"
    T = T.sort_values([base, "id"], ascending=[False, True]).reset_index(drop=True); s = T[base].values; n = len(T)
    if n < 4:
        print(json.dumps({"day": d, "status": "fewer than 4 launches"})); sys.exit(1)
    c, b0 = FZ["coef"], FZ["intercept"]; picks = []
    for k in range(3):
        f = {"pos2": float(k == 1), "pos3": float(k == 2), "m_k4": s[k] - s[3], "m_34": s[2] - s[3], "m_12": s[0] - s[1], "lnn": np.log(n)}
        p = 1 / (1 + np.exp(-(b0 + sum(c[x] * f[x] for x in c))))
        picks.append({"pick": k + 1, "id": T.id[k], "p_top3": round(float(p), 3), "about_n_in_10": int(round(p * 10))})
    exp = sum(x["p_top3"] for x in picks); tier = next(t for t in TIERS if t[1] <= exp < t[2])
    out = {"day": d, "applies_to": "published 00:05 order" + ("" if base == "pred_arm2" else " (FALLBACK: arm 2 missing, clean_nosite score)"),
           "base": base, "launches": n, "expected_right": round(exp, 2), "tier": tier[0],
           "tier_accuracy_backtest": {t[0]: t[3] for t in TIERS}, "note": NOTE, "picks": picks, "written_at": pd.Timestamp.now(tz="UTC").isoformat()}
    print(json.dumps({k: out[k] for k in ("day", "base", "expected_right", "tier")}), [(x["pick"], x["about_n_in_10"]) for x in picks])
    if dry:
        return
    od = f"{HERE}/results/web/confidence_top3_shadow"; os.makedirs(od, exist_ok=True); p = f"{od}/{d}.json"; json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/confidence_top3_shadow/{d}.json"], check=True)
    w = subprocess.run(["gsutil", "cat", f"{B}/results/web/why/{d}_0005.json"], capture_output=True, text=True)
    if w.returncode:
        print(json.dumps({"day": d, "why": "missing; confidence not added"})); return
    W = json.loads(w.stdout)
    W.setdefault("items", {})["top3_confidence"] = {"label": "How sure are we about each top-3 pick (shadow)", "unit": "probability the pick finishes top 3",
                                                   "note": NOTE, "tier": tier[0], "expected_right": out["expected_right"], "tier_accuracy_backtest": out["tier_accuracy_backtest"], "base": base}
    for x in picks:
        W.setdefault("launches", {}).setdefault(x["id"], {})["top3_confidence"] = {"pick": x["pick"], "p_top3": x["p_top3"], "about_n_in_10": x["about_n_in_10"]}
    lw = f"{tmp}/why.json"; json.dump(W, open(lw, "w"), indent=1)
    for dst in ("why", "why_shadow"):
        if dst == "why_shadow" and d > "2026-11-20":
            continue
        subprocess.run(["gsutil", "-q", "cp", lw, f"{B}/results/web/{dst}/{d}_0005.json"], check=True)
    print(json.dumps({"day": d, "why": "top3_confidence added"}))


if __name__ == "__main__":
    main(sys.argv[1])
