"""Hourly vote snapshots of today's launches, for a launch-day forecast (how votes in the first hours predict the final
daily rank). Official Product Hunt API (the same query as collect_ph.py), every featured launch of the current Pacific
day: votes, comments and Product Hunt's current daily rank, with the time of the snapshot. Writes the warehouse table
vote_snapshots (one row per launch per snapshot) and a raw copy in ph_predict/data/vote_snapshots/<day>.jsonl.
Never an input to the pre-launch forecast.
usage: PH_TOKEN=... python -m pipeline.hourly            (one snapshot now)
       PH_TOKEN=... python -m pipeline.hourly --until HH:MM   (a snapshot at the top of every hour until HH:MM UTC)"""
import datetime as dt, json, os, sys, time
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.join(os.path.dirname(HERE), "ph_predict")
sys.path.insert(0, PH)


from zoneinfo import ZoneInfo
PT = ZoneInfo("America/Los_Angeles")   # Product Hunt's day starts at 00:00 Pacific (07:00 UTC in PDT, 08:00 in PST)


def pacific_day(now):
    return now.astimezone(PT).date()


def snapshot():
    import collect_ph as C
    from . import warehouse as W
    now = dt.datetime.now(dt.timezone.utc); d = pacific_day(now)
    start = dt.datetime.combine(d, dt.time(0), PT); end = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT)
    a, b = start.isoformat(), end.isoformat()
    nodes, cur, seen = [], None, set()
    while True:
        p, rem = C.gql({"a": a, "b": b, "c": cur})
        for e in p["edges"]:
            n = e["node"]
            if str(n["id"]) not in seen:   # the list can shift while paging: keep each launch once
                seen.add(str(n["id"])); nodes.append(n)
        if not p["pageInfo"]["hasNextPage"]:
            break
        cur = p["pageInfo"]["endCursor"]
    at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    launch = start
    rows = [{"day": str(d), "at": at, "hours_since_start": round((now - launch).total_seconds() / 3600, 2), "launch_id": str(n["id"]),
             "name": n["name"], "votes": n.get("votesCount"), "comments": n.get("commentsCount"), "rank_now": n.get("dailyRank")} for n in nodes]
    os.makedirs(f"{PH}/data/vote_snapshots", exist_ok=True)
    with open(f"{PH}/data/vote_snapshots/{d}.jsonl", "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    W.write("vote_snapshots", pd.DataFrame(rows))
    print(at, d, len(rows), "launches; API points left", rem, flush=True)


def main(argv):
    if "--until" not in argv:
        snapshot(); return
    hh, mm = map(int, argv[argv.index("--until") + 1].split(":"))
    now = dt.datetime.now(dt.timezone.utc)   # UTC: the machine must be off before the 07:05 UTC scheduled start
    stop = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if stop <= now:
        stop += dt.timedelta(days=1)
    while True:
        try:
            snapshot()
        except Exception as e:  # noqa: BLE001 - one failed snapshot never stops the next ones
            print("snapshot failed", str(e)[:200], flush=True)
        nxt = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        if nxt >= stop:
            return
        time.sleep(max(0, (nxt - dt.datetime.now(dt.timezone.utc)).total_seconds()))


if __name__ == "__main__":
    main(sys.argv[1:])
