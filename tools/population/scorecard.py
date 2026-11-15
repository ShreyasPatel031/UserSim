#!/usr/bin/env python3
"""Daily collection scorecard and dashboard dataset (population agent; taken over from the data babysitter Nov 15).

Writes, from files already in the bucket (counts only, no handles):
  raw/_babysitter/<UTC date>/scorecard.md   DATA_SPEC rows: current vs ideal, owner, gap (Nov 4 babysitter template)
  raw/_babysitter/dashboard/latest.json     the datasets tools/coverage_dashboard.py builds (tabs, tiers, recency,
                                            need_missing, freshness, coverage, fleet, summary) in one file
Inputs: HAVE_INDEX (local have_index.jsonl from have_index.py), NEED (need_list.jsonl), the newest vote_coverage ledger
row, the newest freshness check rows, the launch-reread ledger, the fleet status.json and the site health endpoint.
Usage: scorecard.py HAVE_INDEX NEED_LIST OUT_DIR
"""
import collections
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

G = "gs://usersim-bakeoff-347838016394/usersim_sim"
sh = lambda *a: subprocess.run(a, capture_output=True, text=True).stdout


def newest(prefix):
    ls = [l for l in sh("gsutil", "ls", prefix).split() if l.endswith((".json", ".jsonl"))]
    return sorted(ls)[-1] if ls else None


def main():
    have, need, out = sys.argv[1:4]
    now = dt.datetime.now(dt.timezone.utc)
    day = now.strftime("%Y-%m-%d")
    tiers, comp, kinds = collections.Counter(), collections.Counter(), collections.Counter()
    tab_items, tab_needed = collections.Counter(), collections.Counter()
    for l in open(have):
        r = json.loads(l)
        t = r.get("tier") or "other"
        tiers[t] += 1
        if r.get("complete"):
            comp[t] += 1
            kinds[r.get("complete_kind") or "whole"] += 1
        for x in r.get("tabs_with_items") or []:
            tab_items[x] += 1
        for x in r.get("tabs_needed") or []:
            tab_needed[x] += 1
    total = sum(tiers.values())
    need_n = sum(1 for _ in open(need))
    vc = newest(f"{G}/raw/_audit/vote_coverage/")
    vc = json.loads(sh("gsutil", "cat", vc).splitlines()[0]) if vc else {}
    chk = newest(f"{G}/raw/_audit/checks/")
    chk = [json.loads(l) for l in sh("gsutil", "cat", chk).splitlines()] if chk else []
    fleet = json.loads(sh("gsutil", "cat", f"{G}/mailbox/from_cursor/status.json") or "{}")
    try:
        health = json.loads(urllib.request.urlopen("https://usersim.vercel.app/api/ph/health", timeout=20).read())
    except Exception:
        health = {}
    lb = (health.get("checks") or {}).get("live_board") or {}
    lr = (health.get("checks") or {}).get("live_record") or {}
    alive = sum(1 for s in fleet.get("slots_summary") or [] if s.get("state") != "dead")
    wk = next((v for k, v in vc.items() if k.endswith("2026-11-14") and k.startswith("2026-11-08")), {}) or \
        next((v for k, v in vc.items() if ".." in k and k.startswith("2026-11-0")), {})
    octw = vc.get("2026-10-01..2026-10-24", {})
    open_feeds = [c for c in chk if c.get("status") == "open"]
    data = {
        "generated_utc": now.isoformat(), "pt_day": (now - dt.timedelta(hours=8)).strftime("%Y-%m-%d"),
        "summary": {"people": total, "complete": sum(comp.values()), "complete_kinds": dict(kinds), "need_list": need_n},
        "tiers": [{"tier": t, "people": n, "all_tabs_pulled": comp[t], "pct_full": round(100 * comp[t] / max(n, 1), 2)} for t, n in tiers.most_common()],
        "tabs": [{"tab": t, "people_with_items": tab_items[t], "people_needing": tab_needed[t],
                  "share_pct": round(100 * tab_items[t] / max(total, 1), 1)} for t in sorted(set(tab_items) | set(tab_needed))],
        "need_missing": [{"tab": t, "people_missing": n} for t, n in tab_needed.most_common()],
        "vote_coverage": {k: {kk: v.get(kk) for kk in ("share_all", "share_top3", "share_all_without_seeded", "share_top3_without_seeded",
                                                         "share_all_without_flagged", "share_top3_without_flagged", "launches_over_100pct_by_variant")}
                          for k, v in vc.items() if ".." in k},
        "freshness_open": [{k: c.get(k) for k in ("feed", "open_since", "gap_min", "vms_alive", "slots_today")} for c in open_feeds],
        "fleet": {"status_utc": fleet.get("utc"), "vms_alive": alive},
        "site": {"live_board_configured": lb.get("configured"), "live_board_age_s": lb.get("age_s"), "snapshot_slots_today": lr.get("slots_today")},
    }
    os.makedirs(out, exist_ok=True)
    json.dump(data, open(f"{out}/latest.json", "w"), indent=1)
    pct = lambda x: f"{100 * x:.1f}%" if isinstance(x, (int, float)) else "n/a"
    md = f"""# Collection scorecard, {day} ({now.strftime('%H:%M')} UTC)

Counts only; usernames stay in GCS. Written by the population agent (took over from the data babysitter on Nov 15).
Copy: raw/_babysitter/{day}/scorecard.md; dataset: raw/_babysitter/dashboard/latest.json.

## Headline
- People held: {total:,}; complete (whole-person rule): {sum(comp.values()):,} ({', '.join(f'{k} {v:,}' for k, v in kinds.items())}); still needing a pull: {need_n:,}.
- Vote coverage (capped, complete people; all / top-3): Oct 1-24 {pct(octw.get('share_all'))} / {pct(octw.get('share_top3'))}; last week {pct(wk.get('share_all'))} / {pct(wk.get('share_top3'))}.
  Without seeded people: Oct {pct(octw.get('share_all_without_seeded'))} / {pct(octw.get('share_top3_without_seeded'))}; without E5-flagged: Oct {pct(octw.get('share_all_without_flagged'))} / {pct(octw.get('share_top3_without_flagged'))}.
- Feeds over their limit now: {', '.join(c.get('feed') for c in open_feeds) or 'none'}.

## Person coverage
| tier | people | complete | % |
|---|---|---|---|
""" + "".join(f"| {t} | {n:,} | {comp[t]:,} | {100 * comp[t] / max(n, 1):.1f}% |\n" for t, n in tiers.most_common()) + f"""
Tabs still needed (people): {', '.join(f'{t} {n:,}' for t, n in tab_needed.most_common())}.

## DATA_SPEC rows: current vs ideal (Product Hunt; HN rows are owned by the HN agent and not scored here)
| Row | Ideal | Current ({day}) | Gap / owner |
|---|---|---|---|
| Vote total per launch over the day | every launch every 15 min | 15-min API capture (Data Feeder); 25 h 50 min outage Nov 13 19:00Z - Nov 14 20:50Z; day-close Nov 13 and first comment read Nov 14 missed | ledger raw/_audit/; capture owner Data Feeder / Cursor |
| Exposure (board position) | homepage + leaderboard every 15 min | public leaderboard live (configured {lb.get('configured')}, age {lb.get('age_s')} s); site 15-min snapshot job slots today {lr.get('slots_today')} | site job not triggered since ~20:18Z Nov 14; owner website agent |
| Who votes, when (pool) | every held person's new upvotes within 1 h of the launch day | daily vote coverage above; upvote_refresh job not yet writing (median days since last Upvotes read in the coverage row) | upvote_refresh owner Cursor fleet |
| Who votes (outside the pool) | n/a on PH | pool growth via fleet; {need_n:,} on the need list | orchestrator |
| Daily month reread of launches (warehouse) | 31-day part by 01:30 PT D+1 | ledger raw/_audit/launch_reread_ledger.jsonl; missing D=Nov 4-6, late D=Oct 27/29/31 | pipeline VM owner |
| Person records, whole-person | every held person complete | {sum(comp.values()):,} of {total:,} | fleet completion queue raw/_cursor/completion_queue_*.txt |

## Fleet
- status.json {fleet.get('utc')}: {alive} VMs alive of 20.

## Open
""" + "".join(f"- {c.get('feed')}: open since {c.get('open_since')}\n" for c in open_feeds)
    open(f"{out}/scorecard.md", "w").write(md)
    print(f"SCORECARD people={total} complete={sum(comp.values())} open_feeds={len(open_feeds)}")


if __name__ == "__main__":
    main()
