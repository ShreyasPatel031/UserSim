#!/usr/bin/env python3
"""Live-feed freshness audit and downtime ledger (population agent, Nov 13; detection only, changes no feed).

Feeds and their maximum allowed gap (orchestrator 20:54Z Nov 13, for Shreyas):
  live_capture_heartbeat   mailbox/from_grokbot/ph_live_capture.status.md "updated:" (and from_cursor/ when it takes over)  20 min
  posts_ts                 raw/ph_at_launch/<PT day>/live/posts_ts.jsonl snapshot_ts series                                20 min
  comments_ts              raw/ph_at_launch/<PT day>/api_comments/<tag>PT.jsonl reads, 00:00-02:00 PT 20 min, then         60 min
  day_close_read           a snapshots/<day+1>T2345..2359PT read of day D, present by 00:05 PT                           once/day
  first_comment_read       an api_comments read at 00:07 PT (00:00-00:15 PT window) present by 00:20 PT                  once/day
  fleet_status             mailbox/from_cursor/status.json "utc"; VMs alive vs 20 expected; dead slots                     20 min
Modes:
  check   now: prints breaches as JSON lines and appends open/closed gaps to the local ledger (W/downtime_ledger.jsonl)
  backfill DAY_FROM DAY_TO: every gap over the limits, per feed, from the files; prints per-day totals
Counts and times only. Usage: freshness_audit.py W check | W backfill 2026-11-01 2026-11-13
"""
import datetime as dt
import json
import re
import subprocess
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

G = "gs://usersim-bakeoff-347838016394/usersim_sim"
PT = ZoneInfo("America/Los_Angeles")
UTC = dt.timezone.utc
sh = lambda *a: subprocess.run(a, capture_output=True, text=True).stdout


def ts(s):
    s = str(s).replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(s)
    except Exception:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def tag_ts(tag):  # 20261112T0130PT -> aware datetime
    m = re.match(r"(\d{8})T(\d{4})PT", tag)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=PT)


def gaps(times, limit_fn, feed, day):
    out = []
    times = sorted(set(times))
    for a, b in zip(times, times[1:]):
        lim = limit_fn(a)
        mins = (b - a).total_seconds() / 60
        if mins > lim:
            out.append({"feed": feed, "day_pt": day, "gap_start": a.astimezone(UTC).isoformat(), "gap_end": b.astimezone(UTC).isoformat(),
                        "minutes": round(mins, 1), "limit_min": lim, "cause": None})
    return out


def comment_limit(t):
    p = t.astimezone(PT)
    return 20 if p.hour < 2 else 60


def day_series(day):
    """(posts snapshot times, comment read times, snapshot tags) for one PT day."""
    base = f"{G}/raw/ph_at_launch/{day}"
    posts = []
    raw = sh("gsutil", "cat", f"{base}/live/posts_ts.jsonl")
    for l in raw.splitlines():
        try:
            d = json.loads(l)
        except Exception:
            continue
        t = ts(d.get("snapshot_ts") or d.get("fetched_at"))
        if t:
            posts.append(t)
    cm = [tag_ts(u.rsplit("/", 1)[-1]) for u in sh("gsutil", "ls", f"{base}/api_comments/").split()]
    snaps = [u.rsplit("/", 1)[-1] for u in sh("gsutil", "ls", f"{base}/snapshots/").split()]
    return posts, [t for t in cm if t], snaps


def backfill(d0, d1):
    """capture times are pooled across every launch-day folder (a launch day's captures run for days after it), then gaps
    are measured inside each PT day: from 00:00 PT (or the first capture ever) to 24:00 PT (or now)."""
    D0, D1 = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    posts, cms, snaps = set(), set(), set()
    day = D0 - dt.timedelta(days=2)
    while day <= D1:
        p_, c_, s_ = day_series(day.isoformat())
        posts |= set(p_); cms |= set(c_); snaps |= set(s_)
        day += dt.timedelta(days=1)
    first_ever = min(posts) if posts else None
    rows, per_day = [], defaultdict(lambda: defaultdict(float))
    no_close, no_first = [], []
    day = D0
    while day <= D1:
        d = day.isoformat()
        start = dt.datetime.combine(day, dt.time(0, 0), PT)
        end = min(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), PT), dt.datetime.now(UTC))
        if first_ever and first_ever > start:
            start = max(start, first_ever)
        if end <= start:
            day += dt.timedelta(days=1)
            continue
        for feed, series, lim in (("posts_ts", posts, lambda t: 20), ("comments_ts", cms, comment_limit)):
            inday = [t for t in series if start <= t <= end]
            g = gaps([start] + inday + [end], lim, feed, d)
            rows += g
            for r in g:
                per_day[d][feed] += r["minutes"]
        close_tags = {f"{(day + dt.timedelta(days=1)).strftime('%Y%m%d')}T00{m:02d}PT" for m in range(0, 6)} | \
            {f"{day.strftime('%Y%m%d')}T23{m:02d}PT" for m in range(45, 60)}
        if not any(any(s.startswith(t) for t in close_tags) for s in snaps):
            no_close.append(d)
        if not any(t.astimezone(PT).date() == day and t.astimezone(PT).hour == 0 and t.astimezone(PT).minute <= 15 for t in cms):
            no_first.append(d)
        day += dt.timedelta(days=1)
    return rows, per_day, no_close, no_first


def check():
    now = dt.datetime.now(UTC)
    out = []
    st = sh("gsutil", "cat", f"{G}/mailbox/from_grokbot/ph_live_capture.status.md")
    m = re.search(r"updated:\s*(\S+)", st)
    hb = ts(m.group(1)) if m else None
    if not hb or (now - hb).total_seconds() / 60 > 20:
        out.append({"feed": "live_capture_heartbeat", "last_good": hb.isoformat() if hb else None,
                    "gap_min": round((now - hb).total_seconds() / 60, 1) if hb else None, "limit_min": 20})
    day = now.astimezone(PT).date().isoformat()
    posts, cms, _ = day_series(day)
    for feed, series, lim in (("posts_ts", posts, 20), ("comments_ts", cms, comment_limit(now))):
        last = max(series) if series else None
        if not last or (now - last).total_seconds() / 60 > lim:
            out.append({"feed": feed, "day_pt": day, "last_good": last.isoformat() if last else None,
                        "gap_min": round((now - last).total_seconds() / 60, 1) if last else None, "limit_min": lim})
    try:
        fs = json.loads(sh("gsutil", "cat", f"{G}/mailbox/from_cursor/status.json"))
        fu = ts(fs.get("utc"))
        slots = fs.get("slots_summary") or []
        dead = [s.get("slot") for s in slots if s.get("state") == "dead"]
        alive = sum(1 for s in slots if s.get("state") != "dead")
        if not fu or (now - fu).total_seconds() / 60 > 20 or alive < 20 or dead:
            out.append({"feed": "fleet_status", "last_good": fu.isoformat() if fu else None,
                        "gap_min": round((now - fu).total_seconds() / 60, 1) if fu else None, "limit_min": 20,
                        "vms_alive": alive, "vms_expected": 20, "dead_slots": dead})
    except Exception:
        out.append({"feed": "fleet_status", "last_good": None, "note": "status.json unreadable"})
    return out


def main():
    W, mode = sys.argv[1], sys.argv[2]
    if mode == "check":
        br = check()
        for b in br:
            print(json.dumps(b))
        with open(f"{W}/downtime_ledger_checks.jsonl", "a") as f:
            for b in br:
                f.write(json.dumps({"checked_utc": dt.datetime.now(UTC).isoformat(), **b}) + "\n")
        print(f"FRESHNESS breaches={len(br)}")
    else:
        rows, per_day, no_close, no_first = backfill(sys.argv[3], sys.argv[4])
        with open(f"{W}/downtime_ledger.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        print(f"LEDGER gaps={len(rows)}")
        for d in sorted(per_day):
            print(d, {k: round(v) for k, v in per_day[d].items()})
        print("no_day_close_read:", no_close)
        print("no_first_comment_read_0007PT:", no_first)


if __name__ == "__main__":
    main()
