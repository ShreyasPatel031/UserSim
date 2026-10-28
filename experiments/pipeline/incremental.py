"""Fetch only what is new. Reads the warehouse's fetch_state / launch_state and decides, per person and launch, the
smallest fetch that brings our data up to date, then merges results without duplicating anything.

Rules (cheapest that keeps the data complete):
  new person (first seen, e.g. commented on a launch)  -> upvotes page 1 (includes the profile) + following page 1, once
  known person, active in the last 30 days             -> upvotes page 1 when last fetched > STALE_DAYS ago, or they
                                                          commented since; scroll deeper only if page 1 does not reach
                                                          the newest upvote we already have (stop at the first known one)
  follow lists                                         -> page 1 weekly for active people; the diff dates new follows
  launch comments                                      -> once, the day after launch (final), for launches not fetched
usage: from pipeline import incremental as INC; plan = INC.plan(con, "2026-10-28")"""
import datetime as dt, json
import pandas as pd

STALE_DAYS = 7
FOLLOW_WEEKDAY = 0   # Monday


def days_before(d, n):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=n)).isoformat()


def plan(con, d):
    """-> dict of lists: comments (slugs), new_people, refresh_upvotes, follows."""
    q = lambda s: con.execute(s).df()
    # launches from yesterday (final) without fetched comments
    comments = q(f"""SELECT l.slug FROM launches l LEFT JOIN (SELECT launch_id FROM launch_state WHERE source = 'comments') s
                     ON s.launch_id = l.id WHERE l.day = '{days_before(d, 1)}' AND s.launch_id IS NULL""").slug.tolist()
    active = q(f"""SELECT DISTINCT person FROM events WHERE date >= '{days_before(d, 30)}' AND date < '{d}'""").person
    known = set(q("SELECT person FROM people").person)
    st = q("SELECT person, last_fetched FROM fetch_state WHERE source = 'upvotes_page1'").set_index("person").last_fetched
    lastc = q(f"SELECT person, max(date) AS c FROM comments WHERE date < '{d}' GROUP BY 1").set_index("person").c
    stale = days_before(d, STALE_DAYS)
    refresh = [u for u in active if u in known and (st.get(u, "0") < stale or lastc.get(u, "0") > st.get(u, "0"))]
    follows = list(active) if dt.date.fromisoformat(d).weekday() == FOLLOW_WEEKDAY else []
    return {"comments": comments, "refresh_upvotes": refresh, "follows": follows, "known": known}


def new_people_from_comments(rows, known):
    """Commenters we have never seen: they get the new-person fetch."""
    return sorted({r["username"] for r in rows if r.get("username") and r["username"] not in known and r["username"] != "[REDACTED]"})


def merge_upvotes(con, recs, d):
    """Parsed upvote pages -> new events only (person x launch not already known) + fetch_state rows; and the people
    whose page 1 did not reach their newest known upvote (they need a deeper, stop-at-known scroll)."""
    day = dict(con.execute("SELECT id, day FROM launches").fetchall())
    have = set(map(tuple, con.execute("SELECT person, launch_id FROM events WHERE kind = 'upvote'").fetchall()))
    newest = dict(con.execute("SELECT person, newest_item FROM fetch_state WHERE source IN ('upvotes_page1','upvotes_scroll') AND newest_item IS NOT NULL").fetchall())
    ev, st, deeper = [], [], []
    for r in recs:
        u, ups = r["username"], [str(x) for x in (r.get("upvotes") or [])]
        st.append({"person": u, "source": "upvotes_page1", "last_fetched": d, "status": r.get("status"), "items": len(ups),
                   "newest_item": ups[0] if ups else newest.get(u), "complete": not r.get("has_more", True)})
        for x in ups:
            if (u, x) not in have and x in day:
                ev.append({"person": u, "launch_id": x, "date": day[x], "kind": "upvote", "date_quality": "launch_day"})
        if ups and newest.get(u) and newest[u] not in ups and r.get("has_more"):
            deeper.append(u)
    return pd.DataFrame(ev), pd.DataFrame(st), deeper


def merge_follows(con, recs, d):
    """Following page 1 -> follows rows (observed_on = d). A followee not seen before for that person is a new follow,
    dated to the window since their last snapshot (the only honest date for a follow)."""
    prev = con.execute("SELECT person, followee FROM follows").fetchall()
    have = set(prev)
    rows, st = [], []
    for r in recs:
        u = r["username"]
        for f, _ in (r.get("following") or []):
            rows.append({"person": u, "followee": f, "observed_on": d, "new_since_last": (u, f) not in have})
        st.append({"person": u, "source": "follows", "last_fetched": d, "status": r.get("status"),
                   "items": len(r.get("following") or []), "complete": not r.get("has_more", False)})
    return pd.DataFrame(rows), pd.DataFrame(st)
