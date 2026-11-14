"""Forecast-side drivers into the why files (orchestrator 19:10Z Nov 13). Adds the readable v2 per-input points (the explanation model) to
results/web/why/<d>_0005.json (and the why_shadow copy until Nov 20), next to E5's people-side items. Runs after the READABLE SHADOW file and
the P030 file exist. Reads both from the bucket; aggregates only (launch ids, points), no people.
Adds: items["forecast_drivers"] (label + unit + accuracy note) and per launch launches[id]["forecast_drivers"] =
{rank_explanation_model, score, base_value, points: {input label: points, sorted by |points|}, top_inputs: 3 labels}.
Also notes the th_n_pre status for the day (from P030: first comment read time, or missing). usage: python why_drivers.py <d>
SHADOW (orchestrator 12:50Z Nov 14): when results/shadow_arm2_shap/<d>.json exists (arm2_shap.py, SHAP groups from the deployed arm-2
boosters), the why_shadow copy ONLY also gets items["forecast_drivers_shap"] and per launch "forecast_drivers_shap" (first line: the model's
own groups; second line: the readable stump points, already in forecast_drivers). The live why/ copy is unchanged."""
import json, os, subprocess, sys
import pandas as pd
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
ACC = "explanation model, 58.9 / 69.2 / 74.5 on 214 backtest days; shares 2 of 3 top picks with the forecast on 97.7% of days"
# LABEL SOURCE (orchestrator 20:51Z Nov 14; UNDEPLOYED switch, off by default so the routine's live label does not change until the next build
# turns it on): WHY_LABEL_FROM_TABLE=1 takes the explanation-model figure from results/web/north_star_table.json (model readable_v2).
def second_label():   # the SHAP block's second line: the same table figure as acc_label (orchestrator 22:13Z)
    if os.environ.get("WHY_LABEL_FROM_TABLE", "1") != "1": return SECOND
    a_ = acc_label()
    return ("separate readable model, " + a_.split("), ", 1)[1].split(";", 1)[0] + "; typical effect of each input" if "), " in a_ else SECOND)
def acc_label():
    if os.environ.get("WHY_LABEL_FROM_TABLE", "1") != "1": return ACC   # live-code 2: ON by default
    try:
        T = json.loads(subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/north_star_table.json"], capture_output=True, text=True, timeout=60).stdout)
        r = next(x for x in T["rows"] if x["model"] == "readable_v2" and x.get("top10") is not None)
        return (f"explanation model (readable v2, no th_n_pre), {r['top3']} / {r['top5']} / {r['top10']} on {r['n_days']} backtest days ({r['rule']}); "
                f"label source: table {T.get('computed_at', '?')[:16]}")
    except Exception:   # the model producing the drivers is readable v2 alone (readable_shadow.py's own accuracy_backtest field)
        return "explanation model (readable v2, no th_n_pre), 54.4 / 66.8 / 74.5 on 214 backtest days; label source: build constant"
SECOND = "separate readable model, 58.9 / 69.2 / 74.5; typical effect of each input"
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True)


def main(d):
    w = gcat(f"{B}/results/web/why/{d}_0005.json"); r = gcat(f"{B}/results/shadow_readable/{d}.json")
    if w.returncode or r.returncode:
        print(json.dumps({"day": d, "status": "missing", "why": w.returncode == 0, "readable": r.returncode == 0})); sys.exit(1)
    W, R = json.loads(w.stdout), json.loads(r.stdout); lab = R["labels"]
    p = gcat(f"{B}/results/early_forecast/{d}_P030.json"); th = "P030 not written yet"
    if p.returncode == 0:
        P = json.loads(p.stdout); th = P.get("th_n_pre_source") or ("th_n_pre missing (first comment read not landed by 00:30 PT)" if P.get("th_missing") or P.get("comments_missing") else "unknown")
    W.setdefault("items", {})["forecast_drivers"] = {"label": "Why the forecast ranks it here (explanation model)", "unit": "points (log-vote scale)",
                                                     "note": acc_label(), "model": R.get("model"), "inputs": lab, "th_n_pre": th, "base_value": R.get("base_value")}
    n = 0
    for f in R["forecast"]:
        i = str(f["id"]); pts = sorted(((lab.get(k, k), v) for k, v in f["points"].items()), key=lambda x: -abs(x[1]))
        W.setdefault("launches", {}).setdefault(i, {})["forecast_drivers"] = {"rank_explanation_model": int(f["rank_readable_v2"]), "score": round(float(f["pred_readable_v2"]), 4),
                                                                             "points": dict(pts), "top_inputs": [k for k, _ in pts[:3]]}; n += 1
    W["forecast_drivers_written_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    import copy, os, tempfile; loc = os.path.join(tempfile.gettempdir(), f"why_drivers_{d}.json")
    json.dump(W, open(loc, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", loc, f"{B}/results/web/why/{d}_0005.json"], check=True)
    # shadow copy: + SHAP groups from arm 2 itself (first line) and the stump points as the second line
    W2 = copy.deepcopy(W); sh = gcat(f"{B}/results/shadow_arm2_shap/{d}.json"); n_sh = 0
    if sh.returncode == 0:
        SH = json.loads(sh.stdout)
        try:
            pm_ = json.loads(gcat(f"{B}/results/web/predictions/{d}_0005.json").stdout).get("model") or ""
        except Exception:
            pm_ = ""
        shap_lab = ("Why the arm 2 shadow ranks it here (arm 2 shadow, not the published model: arm 3 was published)" if pm_.startswith("arm3")
                    else "Why the forecast ranks it here")
        W2["items"]["forecast_drivers_shap"] = {"label": shap_lab, "note": SH["label"], "caution": SH["caution"],
                                                "unit": SH["unit"], "groups": SH["groups"], "second_line": second_label(), "status": SH["status"]}
        for i, v in SH["launches"].items():
            W2.setdefault("launches", {}).setdefault(i, {})["forecast_drivers_shap"] = v; n_sh += 1
    loc2 = loc.replace(".json", "_shadow.json"); json.dump(W2, open(loc2, "w"), indent=1)
    if d <= "2026-11-20" or n_sh:
        subprocess.run(["gsutil", "-q", "cp", loc2, f"{B}/results/web/why_shadow/{d}_0005.json"], check=True)
    print(json.dumps({"day": d, "launches_with_drivers": n, "launches_with_shap_shadow": n_sh, "th_n_pre": th}))


if __name__ == "__main__":
    main(sys.argv[1])
