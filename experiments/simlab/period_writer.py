"""Nightly running weekly / monthly board with stated chances (orchestrator 01:28Z Nov 14). Counts and launch ids only.
For the PT day D just closed: running board = launches dated in D's Mon-Sun week (month) up to and including D, ordered by current
warehouse votes (synced; a running read, not a reconstructed close). Chance of finishing in the final weekly / monthly top 3 / 5 / 10 =
POSITION TABLE from reports/period_prob/frozen_period_prob.json (share of launches at that running position and call point that finished
top k; 2025 + 2026, walk-forward-checked in period_prob.py), shrunk with a Jeffreys prior via its n. Weekly call point = weekday of D
(Mon = 1 .. Sat = 6; Sunday = the close, no chance shown); monthly call point = the largest of 10 / 15 / 20 / 25 <= day of month (none
before day 10). Positions beyond 15 get 0 (none of the table's rows).
    python period_writer.py <D> <scratchpad>  -> tmp/e5/website/probabilities/<D>_weekly.json and <D>_monthly.json
"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
D, SP = sys.argv[1:3]; HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
sys.path.insert(0, os.path.dirname(HERE)); from pipeline import warehouse as W
import period_parts as PP   # staleness guard (orchestrator 12:38Z Nov 14)
FZ = json.load(open(os.path.join(HERE, "reports", "period_prob", "frozen_period_prob.json"))); CAL = json.load(open(os.path.join(HERE, "reports", "period_prob", "period_prob.json")))
L = W.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L["votes"] = pd.to_numeric(L.votes, errors="coerce")
d = pd.Timestamp(D)
for per in ("week", "month"):
    if per == "week": start = d - pd.Timedelta(days=d.weekday()); c = d.weekday() + 1
    else: start = d.replace(day=1); c = max([x for x in (10, 15, 20, 25) if x <= d.day], default=None)
    out = {"day": D, "board": per, "period_start": start.strftime("%Y-%m-%d"), "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "basis": FZ["basis"]}
    if (per == "week" and c >= 7) or c is None:
        out.update({"status": "no chance shown at this point", "call_point": c})
    else:
        g = L[(pd.to_datetime(L.day) >= start) & (pd.to_datetime(L.day) <= d)].dropna(subset=["votes"]).sort_values("votes", ascending=False).reset_index(drop=True)
        rows = []
        for i, r in g.iterrows():
            o = {"id": r.id, "running_position": i + 1, "votes_now": int(r.votes)}
            for k in (3, 5, 10):
                v = FZ["position tables"][f"{per}_top{k}"].get(f"{c}|{i + 1}")
                o[f"p_final_top{k}"] = None if v is None else round(float(v), 3) if i < 15 else 0.0
            rows.append(o)
        for k in (3, 5, 10):   # chances never rise with a worse running position
            m = 1.0
            for o in rows:
                if o[f"p_final_top{k}"] is not None: m = min(m, o[f"p_final_top{k}"]); o[f"p_final_top{k}"] = round(m, 3)
        out.update({"status": "ok", "call_point": c, "method": "position table by (call point, running position), 2025 + 2026 complete periods",
                    "calibration": {f"top{k}": {kk: CAL[f"{per} | all"][f"top{k}"][kk] for kk in ("Brier skill vs base rate [CI]", "Brier skill vs position-only [CI]")} for k in (3, 5, 10)},
                    "note": "running votes are current reads; chances are historical shares for that position and call point", "launches": rows})
    miss = PP.missing_days(per, D, pd.Timestamp.now(tz="UTC")); out["stale_days_missing"] = miss
    if miss:   # a day of the period so far has no read after its close (as Nov 5-7): never publish a silently stale board
        out["status"] = "stale: days missing"; out["stale_note"] = "no launches read with votes after the close of: " + ", ".join(miss)
    p = os.path.join(SP, f"prob_{D}_{per}.json"); json.dump(out, open(p, "w"), indent=1, default=float)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/website/probabilities/{D}_{'weekly' if per == 'week' else 'monthly'}.json"], check=True)
    print(per, out["status"], out.get("call_point"), len(out.get("launches", [])))
