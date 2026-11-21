"""Pool forward_says_<day>.json (PREREG addendum 3): panel vs plain-prompt arm, paired per launch, day bootstrap.
    python says_pooled.py <out json> <day> [<day> ...]"""
import json, os, sys
import numpy as np, pandas as pd
OUT, DAYS = sys.argv[1], sys.argv[2:]; HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); rng = np.random.default_rng(0)
R = pd.DataFrame([{**r, "day": d} for d in DAYS for r in json.load(open(f"{HERE}/reports/forward_sim/forward_says_{d}.json"))["per_launch"] if r.get("scored")])
for m in ("recall", "precision", "complaint_recall"): R[f"d_{m}"] = R[m] - R.get(f"plain_{m}")
def boot(c):
    x = R.dropna(subset=[c]); d = sorted(x.day.unique()); bs = [pd.concat([x[x.day == z] for z in rng.choice(d, len(d))])[c].mean() for _ in range(4000)]
    return [round(100 * float(x[c].mean()), 1), round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1), int(len(x)), len(d)]
out = {"prereg": "PREREG.md addendum 3", "days": DAYS, "panel": {m: boot(m) for m in ("recall", "recall_w", "precision", "complaint_recall")},
       "plain prompt": {m: boot("plain_" + m) for m in ("recall", "recall_w", "precision", "complaint_recall")},
       "panel minus plain (paired)": {m: boot("d_" + m) for m in ("recall", "precision", "complaint_recall")}, "note": "[mean %, day-bootstrap 2.5%, 97.5%, launches, days]"}
b = out["panel"]; out["north_star"] = {"broad themes recall>=70 & precision>=50": f"recall {b['recall'][0]} (lower {b['recall'][1]}), precision {b['precision'][0]} (lower {b['precision'][1]})",
       "specific issues above plain prompt, interval clear": out["panel minus plain (paired)"]["complaint_recall"][1] > 0}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out, indent=1))
