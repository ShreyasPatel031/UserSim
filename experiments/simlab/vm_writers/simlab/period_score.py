"""Score the running weekly / monthly boards (period_writer.py) against the final period rank (orchestrator 12:38Z Nov 14).
Truth: weekly_rank / monthly_rank <= k from the FIRST launches part written after the period's close (Mon ~00:16 PT reread for weeks;
the first reread after the month's last day), rows of that part only; never a later vote order. For each day D of the period up to
the day before the close: the board is the live file tmp/e5/website/probabilities/<D>_weekly|monthly.json when one exists (flag
"live"), else rebuilt from the parts held at the writer's run time D+1 09:20 UTC (flag "replay"; never pooled with live).
Per board: top 3/5/10 hits vs truth, the ceiling (truth top-k launches already held on the board), read times, and "stale: days missing"
when a day of the period so far had no read after its close by the run time. Headline: Saturday's board (week) / the last board
before the close (month). Appends to tmp/e5/website/period_track_record.json (one entry per period and flag).
    python period_score.py week|month <any day in the period> <scratchpad> [--replay]"""
import json, os, subprocess, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse as W
import period_parts as PP
per, D0, SP = sys.argv[1:4]; REPLAY = "--replay" in sys.argv; B = "gs://usersim-bakeoff-347838016394/usersim_sim"
W.sync(); s, e = PP.period(per, D0); T, tts, tpart = PP.truth(per, D0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
res = {"board": per, "period": [s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")], "written_at": pd.Timestamp.now(tz="UTC").isoformat()}
if T is None:
    res["status"] = "no truth read yet (no launches part with votes after the close)"; print(json.dumps(res)); sys.exit(0)
tr = {k: set(T[T["rank"] <= k].id) for k in (3, 5, 10)}
res.update({"truth": {"part": tpart, "read_at_utc": tts.isoformat(), "read_at_pt": tts.tz_convert("America/Los_Angeles").strftime("%Y-%m-%d %H:%M PT"), "launches": int(len(T))}, "days": []})
for D in pd.date_range(s, e - pd.Timedelta(days=1)):
    d = D.strftime("%Y-%m-%d"); run = pd.Timestamp(d, tz="UTC") + pd.Timedelta(days=1, hours=9, minutes=20)
    live = None if REPLAY else gcat(f"{B}/tmp/e5/website/probabilities/{d}_{'weekly' if per == 'week' else 'monthly'}.json")
    lines = {}
    if live:
        j = json.loads(live); flag = "live"; rd = j.get("written_at"); stale = j.get("stale_days_missing", [])
        lines[j.get("board_line", "votes_only")] = [r["id"] for r in j.get("launches", [])]
        if j.get("shadow_votes_only"): lines["votes_only"] = [r["id"] for r in j["shadow_votes_only"]]   # both lines scored (orchestrator 13:06Z)
    else:
        order, upd = PP.board(per, d, run); flag = "replay"; rd = upd; stale = PP.missing_days(per, d, run); lines["votes_only"] = order
    for line, order in lines.items():
        row = {"day": d, "board_day": (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d") + " 00:05 (votes through " + d + " + predicted line-up)" if line == "with_entrants" else d + " close (votes only)", "flag": flag, "line": line, "board_size": len(order), "board_read_latest_updated_at": str(rd), "status": "stale: days missing" if stale else "ok", "days_missing": stale}
        for k in (3, 5, 10):
            row[f"top{k}"] = len(set(order[:k]) & tr[k]); row[f"ceiling_top{k}"] = len(tr[k] & set(order)) if order else 0
        res["days"].append(row)
hdd = [r for r in res["days"] if pd.Timestamp(r["day"]).weekday() == 5] if per == "week" else [r for r in res["days"] if r["day"] == res["days"][-1]["day"]] if res["days"] else []
res["headlines"] = hdd; pref = [r for r in hdd if r["line"] == "with_entrants"] or hdd
res["headline"] = pref[0] if pref else None
out = os.path.join(SP, f"period_score_{per}_{s:%Y%m%d}{'_replay' if REPLAY else ''}.json"); json.dump(res, open(out, "w"), indent=1, default=str)
subprocess.run(["gsutil", "-q", "cp", out, f"{B}/tmp/e5/website/period_scores/{os.path.basename(out)}"], check=True)
# track record: one entry per (board, period, flag); replace an earlier entry for the same key
TRp = os.path.join(SP, "period_track_record.json"); raw = gcat(f"{B}/tmp/e5/website/period_track_record.json")
TR = json.loads(raw) if raw else {"note": "weekly / monthly board scores; flags live / replay never pooled; truth = first read after the close, that part only", "entries": []}
h = res["headline"]
for h in res["headlines"]:
    key = (per, res["period"][0], h["flag"], h["line"]); TR["entries"] = [x for x in TR["entries"] if (x["board"], x["period_start"], x["flag"], x.get("line", "votes_only")) != key]
    TR["entries"].append({"board": per, "period_start": res["period"][0], "flag": h["flag"], "line": h["line"], "headline_day": h["day"], "status": h["status"],
                          "hits top3/5/10": [h["top3"], h["top5"], h["top10"]], "ceiling top3/5/10": [h["ceiling_top3"], h["ceiling_top5"], h["ceiling_top10"]],
                          "board_read": h["board_read_latest_updated_at"], "truth_read_pt": res["truth"]["read_at_pt"], "truth_part": tpart})
if res["headlines"]:
    TR["entries"].sort(key=lambda x: (x["board"], x["period_start"], x["flag"], x.get("line", ""))); TR["updated_at"] = res["written_at"]
    json.dump(TR, open(TRp, "w"), indent=1); subprocess.run(["gsutil", "-q", "cp", TRp, f"{B}/tmp/e5/website/period_track_record.json"], check=True)
print(json.dumps({"headline": res["headline"], "days": [[r["day"], r["flag"], r.get("line"), r["status"], r["top3"], r["top5"], r["top10"], r["ceiling_top3"], r["ceiling_top5"], r["ceiling_top10"]] for r in res["days"]], "truth": res["truth"]}))
