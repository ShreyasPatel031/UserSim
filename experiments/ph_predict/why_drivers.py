"""Forecast-side drivers into the why files (orchestrator 19:10Z Nov 13). Adds the readable v2 per-input points (the explanation model) to
results/web/why/<d>_0005.json (and the why_shadow copy until Nov 20), next to E5's people-side items. Runs after the READABLE SHADOW file and
the P030 file exist. Reads both from the bucket; aggregates only (launch ids, points), no people.
Adds: items["forecast_drivers"] (label + unit + accuracy note) and per launch launches[id]["forecast_drivers"] =
{rank_explanation_model, score, base_value, points: {input label: points, sorted by |points|}, top_inputs: 3 labels}.
Also notes the th_n_pre status for the day (from P030: first comment read time, or missing). usage: python why_drivers.py <d>"""
import json, subprocess, sys
import pandas as pd
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
ACC = "explanation model, 58.9 / 69.2 / 74.5 on 214 backtest days; shares 2 of 3 top picks with the forecast on 97.7% of days"
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
                                                     "note": ACC, "model": R.get("model"), "inputs": lab, "th_n_pre": th, "base_value": R.get("base_value")}
    n = 0
    for f in R["forecast"]:
        i = str(f["id"]); pts = sorted(((lab.get(k, k), v) for k, v in f["points"].items()), key=lambda x: -abs(x[1]))
        W.setdefault("launches", {}).setdefault(i, {})["forecast_drivers"] = {"rank_explanation_model": int(f["rank_readable_v2"]), "score": round(float(f["pred_readable_v2"]), 4),
                                                                             "points": dict(pts), "top_inputs": [k for k, _ in pts[:3]]}; n += 1
    W["forecast_drivers_written_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    import os, tempfile; loc = os.path.join(tempfile.gettempdir(), f"why_drivers_{d}.json")
    json.dump(W, open(loc, "w"), indent=1)
    for dst in ("why", "why_shadow"):
        if dst == "why_shadow" and d > "2026-11-20": continue
        subprocess.run(["gsutil", "-q", "cp", loc, f"{B}/results/web/{dst}/{d}_0005.json"], check=True)
    print(json.dumps({"day": d, "launches_with_drivers": n, "th_n_pre": th}))


if __name__ == "__main__":
    main(sys.argv[1])
