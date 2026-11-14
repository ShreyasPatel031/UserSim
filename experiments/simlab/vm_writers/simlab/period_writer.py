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
d = pd.Timestamp(D); NXT = (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
# PREDICTED ENTRANTS (orchestrator 13:06Z Nov 14, rule 5; PH ops b1e4f767 reproduced in entrants_repro.py: all days +2.5 / +5.2 / +7.3
# top 3/5/10, always-insert not worse than Mon-Wed only): this file is written ~01:20 PT on D+1, after D+1's 00:05 forecast exists, so the
# board = days <= D by votes + D+1's line-up at calibrated arm-2 predicted final votes when D+1 is in the same period. Calibration
# log1p(votes) = a + b * pred fit AS OF: arm-2 walk-forward preds (assets a2x/X.parquet 'both') x warehouse votes, months < D+1's month.
def entrants():
    fc = subprocess.run(["gsutil", "cat", f"{B}/raw/daily/{NXT}/forecast_{NXT}.parquet"], capture_output=True).stdout
    if not fc: return None, "no 00:05 forecast for " + NXT
    import io; F = pd.read_parquet(io.BytesIO(fc)); F["id"] = F.id.astype(str)
    col = "pred_arm2" if "pred_arm2" in F and F.pred_arm2.notna().all() else "pred"
    X = pd.read_parquet(os.path.join(SP, "a2x", "X.parquet"))[["id", "day", "both"]]; X["id"] = X.id.astype(str)
    X = X.merge(L[["id", "votes"]], on="id").dropna(subset=["votes"]); X = X[X.day.str[:7] < NXT[:7]]
    a, b = (0.0, 1.0) if X.empty else tuple(np.polyfit(X.both, np.log1p(X.votes), 1)[::-1])
    F["pv"] = np.expm1(a + b * F[col]); return F, {"source": f"raw/daily/{NXT}/forecast_{NXT}.parquet {col}" + ("" if col == "pred_arm2" else " (arm 2 missing: clean_nosite)"),
                                                    "calibration log1p(votes) = a + b*pred": [round(float(a), 3), round(float(b), 3)], "calibration rows (months < " + NXT[:7] + ")": int(len(X))}
ENT, ENT_INFO = entrants()
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
        for o in rows: o["source"] = "votes"
        same = pd.Timestamp(NXT) <= (start + pd.Timedelta(days=6) if per == "week" else start + pd.offsets.MonthEnd(0))
        ins = per == "week" and same and ENT is not None
        if ins:   # with_entrants = the weekly board; votes rows keep their votes-only chance; predicted rows carry none (table not fit for them)
            pr = [{"id": r.id, "votes_now": None, "predicted_final_votes": round(float(r.pv), 1), "source": "predicted", **{f"p_final_top{k}": None for k in (3, 5, 10)}} for r in ENT.itertuples()]
            board = sorted(rows + pr, key=lambda o: -(o["votes_now"] if o["source"] == "votes" else o["predicted_final_votes"]))
            for i, o in enumerate(board): o["board_position"] = i + 1
            out.update({"board_line": "with_entrants", "entrants": {"day": NXT, "n": len(pr), **ENT_INFO}, "shadow_votes_only": [dict(o) for o in rows],
                        "board_day": {"launches (with_entrants)": f"{NXT} 00:05 PT board: votes through {D} + {NXT} line-up predicted",
                                      "shadow_votes_only": f"{D} close board: votes through {D}"}})
        else:
            board = rows; out.update({"board_day": {"launches (votes_only)": f"{D} close board: votes through {D}"}, "board_line": "votes_only", "entrants": {"day": NXT, "inserted": False, "reason": ("next day not in this period" if not same else ENT_INFO if ENT is None else "monthly: shadow only")}})
        rows = board
        out.update({"status": "ok", "call_point": c, "method": "position table by (call point, running position), 2025 + 2026 complete periods",
                    "calibration": {f"top{k}": {kk: CAL[f"{per} | all"][f"top{k}"][kk] for kk in ("Brier skill vs base rate [CI]", "Brier skill vs position-only [CI]")} for k in (3, 5, 10)},
                    "note": "running votes are current reads; chances are historical shares for that position and call point", "launches": rows})
    if per == "month" and d.day <= 7 and ENT is not None and pd.Timestamp(NXT).month == d.month:   # monthly days 1-7: entrants as a SHADOW line only
        g2 = L[(pd.to_datetime(L.day) >= start) & (pd.to_datetime(L.day) <= d)].dropna(subset=["votes"])
        sb = [{"id": r.id, "value": float(r.votes), "source": "votes"} for r in g2.itertuples()] + [{"id": r.id, "value": round(float(r.pv), 1), "source": "predicted"} for r in ENT.itertuples()]
        out["shadow_with_entrants"] = [{"id": o["id"], "board_position": i + 1, "source": o["source"]} for i, o in enumerate(sorted(sb, key=lambda o: -o["value"]))]
    miss = PP.missing_days(per, D, pd.Timestamp.now(tz="UTC")); out["stale_days_missing"] = miss
    if miss:   # a day of the period so far has no read after its close (as Nov 5-7): never publish a silently stale board
        out["status"] = "stale: days missing"; out["stale_note"] = "no launches read with votes after the close of: " + ", ".join(miss)
    p = os.path.join(SP, f"prob_{D}_{per}.json"); json.dump(out, open(p, "w"), indent=1, default=float)
    if os.environ.get("DRY") != "1": subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/website/probabilities/{D}_{'weekly' if per == 'week' else 'monthly'}.json"], check=True)
    print(per, out["status"], out.get("call_point"), len(out.get("launches", [])))
