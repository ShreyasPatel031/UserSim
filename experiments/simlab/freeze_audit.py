"""Freeze audit (orchestrator Nov 25 06:14Z): every simulation line for PT launch day D must freeze before 03:30 PT with predicted_at stamped.
Lines: Stage B v1 (rerank_frozen.json), Stage B v2 (rerank_frozen_v2pick.json), person-built panel + no-block shadow (explain say blocks),
PU-1 (product_use/outputs.json, from 2026-11-26).  python freeze_audit.py D  ->  prints one line per sim line, writes results/calibration/D/freeze_audit.json
"""
import json, subprocess, sys
import pandas as pd
D = sys.argv[1]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; DL = pd.Timestamp(f"{D} 03:30", tz="America/Los_Angeles").tz_convert("UTC")
gj = lambda p: json.loads(subprocess.run(["gsutil", "cat", p], capture_output=True).stdout or b"null")
def chk(name, t):
    ts = pd.Timestamp(t) if t else None
    return {"line": name, "predicted_at": t, "on_time": bool(ts is not None and ts < DL), "missing": t is None}
R = []
for name, f in (("stageb_v1", "rerank_frozen.json"), ("stageb_v2", "rerank_frozen_v2pick.json")):
    x = gj(f"{B}/results/calibration/{D}/{f}") or {}; R.append(chk(name, x.get("predicted_at") or x.get("frozen_at")))
E = (gj(f"{B}/results/web/explain/{D}.json") or {}).get("launches") or {}
for name, k in (("person_panel", "person_built_panel"), ("person_panel_noblock", "person_built_panel_noblock")):
    ts = sorted({(v.get("say") or {}).get(k, {}).get("predicted_at") for v in E.values()} - {None}); R.append(chk(name, ts[-1] if ts else None))
for name, f in (("backer_stack_v2", "backer_pred_stack_v2"), ("backer_stack_1b", "backer_pred_stack")):   # PREREG 14/15b (STACK-v2 published from Nov 28)
    if D >= ("2026-11-28" if name == "backer_stack_v2" else "2026-11-27"):
        x = gj(f"{B}/tmp/e5/private/{f}/{D}_meta.json") or {}; R.append(chk(name, x.get("predicted_at")))
if D >= "2026-11-26":
    x = gj(f"{B}/results/calibration/{D}/product_use/outputs.json") or {}; R.append(chk("product_use", x.get("predicted_at") or x.get("frozen_at")))
out = {"day": D, "deadline_utc": DL.isoformat(), "checked_at": pd.Timestamp.now(tz="UTC").isoformat(), "lines": R, "all_on_time": all(r["on_time"] for r in R)}
p = f"/tmp/freeze_audit_{D}.json"; json.dump(out, open(p, "w"), indent=1); subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/calibration/{D}/freeze_audit.json"])
for r in R: print(("OK  " if r["on_time"] else "MISS") + f" {r['line']:22s} {r['predicted_at']}")
print("ALL_ON_TIME" if out["all_on_time"] else "SOME_MISSED")
