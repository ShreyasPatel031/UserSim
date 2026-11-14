#!/usr/bin/env python3
"""Live-feed freshness audit and downtime ledger (population agent, Nov 13; detection only, changes no feed).

Feeds and their maximum allowed gap (orchestrator 20:54Z Nov 13, for Shreyas):
  live_capture_heartbeat   mailbox/from_grokbot/ph_live_capture.status.md "updated:" (and from_cursor/ when it takes over)  20 min
  posts_ts                 raw/ph_at_launch/<PT day>/live/posts_ts.jsonl snapshot_ts series                                20 min
  comments_ts              raw/ph_at_launch/<PT day>/api_comments/<tag>PT.jsonl reads, 00:00-02:00 PT 20 min, then         60 min
  day_close_read           a snapshots/<day+1>T2345..2359PT read of day D, present by 00:05 PT                           once/day
  first_comment_read       an api_comments read at 00:07 PT (00:00-00:15 PT window) present by 00:20 PT                  once/day
  fleet_status             mailbox/from_cursor/status.json "utc"; VMs alive vs 20 expected; dead slots                     20 min
  vote_snapshots_daily_export  bucket raw/vote_snapshots/<PT day>.jsonl (daily export): previous PT day present by 08:00Z  daily
  vote_snapshots_hourly    tables/vote_snapshots/<YYYYMMDDTHHMMSS>-<hex>.parquet, one part per hourly load: newest
                           upload time and that part's max(at) and row count                                              75 min
  live_capture_heartbeat also reads mailbox/from_cursor/ph_live_capture.status.md (Cursor loop) and takes the newer
Modes:
  check   now: prints breaches as JSON lines and appends open/closed gaps to the local ledger (W/downtime_ledger.jsonl)
  backfill DAY_FROM DAY_TO: every gap over the limits, per feed, from the files; prints per-day totals
  run    standalone (cron, no LLM, no session): check, then per breach a ledger row in GCS, an ALERT file in GCS and a
         Grok Bot webhook call (tools/grokbot_post.sh, if its credentials file exists); re-alerts a feed at most every
         30 min while its breach lasts; writes a "closed" row when a feed recovers. Run note: docs/population/freshness_audit_RUN.md
Counts and times only. Usage: freshness_audit.py W check | W run | W backfill 2026-11-01 2026-11-13 | W first_comment D0 D1
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
    hbs = []
    for who in ("from_grokbot", "from_cursor"):
        m = re.search(r"updated:\s*(\S+)", sh("gsutil", "cat", f"{G}/mailbox/{who}/ph_live_capture.status.md"))
        if m and ts(m.group(1)):
            hbs.append(ts(m.group(1)))
    hb = max(hbs) if hbs else None
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
    # bucket raw/vote_snapshots is a once-a-day export (orchestrator 21:45Z): the previous PT day's file must exist by 08:00Z
    vs = sh("gcloud", "storage", "objects", "list", f"{G}/raw/vote_snapshots/*.jsonl", "--format=value(name)")
    days = sorted(l.rsplit("/", 1)[-1][:-6] for l in vs.splitlines() if l.endswith(".jsonl"))
    prev = (now.astimezone(PT).date() - dt.timedelta(days=1)).isoformat()
    due = dt.datetime.combine(dt.date.fromisoformat(prev) + dt.timedelta(days=1), dt.time(8, 0), UTC)
    if now >= due and prev not in days:
        out.append({"feed": "vote_snapshots_daily_export", "missing_day": prev, "due_utc": due.isoformat(),
                    "newest_day": days[-1] if days else None, "late_min": round((now - due).total_seconds() / 60, 1)})
    # once-a-day reads (live check): day-close read of yesterday by 00:05 PT, first comment read of today by 00:20 PT;
    # reported until 12:00 PT, after which the backfill ledger carries them
    pn = now.astimezone(PT)
    if pn.hour < 12:
        today, yday = pn.date(), pn.date() - dt.timedelta(days=1)
        if (pn.hour, pn.minute) >= (0, 5):
            snaps = set()
            for d_ in (yday, today):
                snaps |= set(day_series(d_.isoformat())[2])
            tags = {f"{yday.strftime('%Y%m%d')}T23{m:02d}PT" for m in range(45, 60)} | \
                {f"{today.strftime('%Y%m%d')}T00{m:02d}PT" for m in range(0, 6)}
            if not any(any(x.startswith(t) for t in tags) for x in snaps):
                out.append({"feed": "day_close_read", "day_pt": yday.isoformat(), "due_pt": "00:05", "note": "no 23:45-00:05 PT snapshot"})
        if (pn.hour, pn.minute) >= (0, 20):
            pool = set(cms) | set(day_series(yday.isoformat())[1])  # a launch day's reads can sit in the previous day's folder
            cm0 = [t for t in pool if t.astimezone(PT).date() == today and t.astimezone(PT).hour == 0 and t.astimezone(PT).minute <= 15]
            if not cm0:
                out.append({"feed": "first_comment_read", "day_pt": today.isoformat(), "due_pt": "00:20", "note": "no 00:00-00:15 PT comment read"})
    # hourly warehouse load (PH ops 22:35Z): one parquet part per load; VM is off 23:00-00:05 PT (~65-70 min, under 75)
    parts = [l.split("\t") for l in sh("gcloud", "storage", "objects", "list", f"{G}/tables/vote_snapshots/*.parquet",
                                        "--format=value(name,creation_time)").splitlines() if "\t" in l]
    if parts:
        name, ct = max(parts, key=lambda r: r[1])
        up = ts(ct.replace("+0000", "+00:00"))
        if not up or (now - up).total_seconds() / 60 > 75:
            row = {"feed": "vote_snapshots_hourly", "last_load": up.isoformat() if up else None,
                   "gap_min": round((now - up).total_seconds() / 60, 1) if up else None, "limit_min": 75}
            try:
                import io
                import pandas as pd
                df = pd.read_parquet(io.BytesIO(subprocess.run(["gsutil", "cat", f"gs://{G.split('//')[1].split('/')[0]}/{name}"],
                                                               capture_output=True).stdout))
                row.update({"last_part_rows": len(df), "last_part_max_at": str(df["at"].max())})
            except Exception:
                pass
            out.append(row)
    else:
        out.append({"feed": "vote_snapshots_hourly", "last_load": None, "note": "no parts"})
    return out


def first_comment_reads(d0, d1):
    """per PT day: time of the first api_comments read after 00:00 PT (pooled across launch-day folders)."""
    D0, D1 = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    cms = set()
    day = D0 - dt.timedelta(days=2)
    while day <= D1:
        cms |= set(day_series(day.isoformat())[1])
        day += dt.timedelta(days=1)
    out = {}
    day = D0
    while day <= D1:
        f = sorted(t for t in cms if t.astimezone(PT).date() == day)
        out[day.isoformat()] = f[0].astimezone(PT).strftime("%H:%M PT") if f else None
        day += dt.timedelta(days=1)
    return out


REALERT_MIN = 30


def put(text, url):
    subprocess.run(["gsutil", "-q", "cp", "-", url], input=text, text=True, check=False)


def run(W):
    """one cron tick: check, write GCS rows, ALERT file and webhook per breach (re-alert every 30 min), close recovered."""
    import os
    now = dt.datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    state_f = os.path.join(W, "freshness_state.json")
    try:
        state = json.load(open(state_f))
    except Exception:
        state = {}  # feed -> {"open_since": iso, "last_alert": iso}
    try:
        br = check()
    except Exception as e:  # the audit itself failing is a breach too
        br = [{"feed": "freshness_audit_itself", "note": f"check failed: {type(e).__name__}"}]
    rows, due = [], []
    now_feeds = {b["feed"] for b in br}
    for b in br:
        st = state.setdefault(b["feed"], {"open_since": now.isoformat(), "last_alert": None})
        la = ts(st["last_alert"]) if st.get("last_alert") else None
        alert = la is None or (now - la).total_seconds() / 60 >= REALERT_MIN - 3  # 3 min slack: ticks drift, so a 30-min tick still re-alerts
        if alert:
            st["last_alert"] = now.isoformat()
            due.append(b)
        rows.append({"checked_utc": now.isoformat(), "status": "open", "open_since": st["open_since"], "alerted": alert, **b})
    for f in [f for f in state if f not in now_feeds]:
        rows.append({"checked_utc": now.isoformat(), "status": "closed", "feed": f, "open_since": state[f]["open_since"],
                     "minutes_open": round((now - ts(state[f]["open_since"])).total_seconds() / 60, 1)})
        del state[f]
    if rows:  # one object per tick: no read-modify-write race between runners
        put("".join(json.dumps(r) + "\n" for r in rows), f"{G}/raw/_audit/checks/{stamp}.jsonl")
    if due:
        lines = [f"# FRESHNESS ALERT {stamp}", "", f"{len(br)} feed(s) over their limit (detection only; no feed was changed).", ""]
        for b in br:
            lines.append("- " + ", ".join(f"{k}={v}" for k, v in b.items()))
        text = "\n".join(lines) + "\n"
        put(text, f"{G}/raw/_audit/ALERT_{stamp}.md")
        here = os.path.dirname(os.path.abspath(__file__))
        post = os.path.join(here, "..", "grokbot_post.sh")
        env = os.environ.get("GROKBOT_WEBHOOK_ENV", "/root/.usersim/grokbot_webhook.env")
        if os.path.exists(env) and os.path.exists(post):
            summary = "; ".join(f"{b['feed']} gap {b.get('gap_min')} min (limit {b.get('limit_min')})" for b in due)
            r = subprocess.run([post, "freshness-audit", "live feed down", summary], capture_output=True, text=True)
            print(f"WEBHOOK rc={r.returncode} {r.stdout.strip()[:120]}")
        else:
            print("WEBHOOK skipped (no credentials file)")
    json.dump(state, open(state_f, "w"))
    print(f"FRESHNESS_RUN {stamp} breaches={len(br)} alerted={len(due)} closed={sum(1 for r in rows if r['status'] == 'closed')}")
    return 1 if br else 0


def main():
    W, mode = sys.argv[1], sys.argv[2]
    if mode == "run":
        sys.exit(run(W))
    if mode == "check":
        br = check()
        for b in br:
            print(json.dumps(b))
        with open(f"{W}/downtime_ledger_checks.jsonl", "a") as f:
            for b in br:
                f.write(json.dumps({"checked_utc": dt.datetime.now(UTC).isoformat(), **b}) + "\n")
        print(f"FRESHNESS breaches={len(br)}")
    elif mode == "first_comment":
        for d, t in first_comment_reads(sys.argv[3], sys.argv[4]).items():
            print(d, t)
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
