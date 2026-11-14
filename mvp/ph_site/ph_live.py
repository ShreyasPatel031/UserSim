"""Live Product Hunt leaderboard, fetched by the site itself from Product Hunt's official API (GraphQL v2).

It depends on no agent session, data feeder, fleet or VM: one server-side call per ~60 s at most, shared by every
visitor and instance through a durable last-good snapshot in GCS. On any upstream error or rate limit the last good
snapshot is served with its age; the page never goes blank.

  token     PH_TOKEN (developer token), else a client-credentials token minted from PH_CLIENT_ID + PH_CLIENT_SECRET
            (the names mvp/discovery.py and the PH ops collectors already use). Server-side only.
  persisted site/live_board/latest.json (newest snapshot, any day) and site/live_board/<day>.json (last snapshot of
            that PT day; marked final once re-read after the day closed).
  query     the PH ops collector's own query shape (experiments/ph_predict/collect_ph.py): featured posts created in
            the PT day's window, kept only when featuredAt falls on that PT day, ordered by dailyRank.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mvp.ph_site import gcs

PT = ZoneInfo("America/Los_Angeles")
ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
TOKEN_URL = "https://api.producthunt.com/v2/oauth/token"
MIN_INTERVAL_S = 60          # at most one upstream refresh per minute, across all instances
UPSTREAM_TIMEOUT_S = 8
REVEAL_HOUR_PT = 4           # Product Hunt hides vote counts until about 04:00 PT
FIELDS = ("id name tagline slug featuredAt votesCount commentsCount dailyRank "
          "thumbnail{url} topics(first:3){edges{node{name}}}")
QUERY = ("query($a:DateTime!,$b:DateTime!,$c:String){ posts(first:20, after:$c, featured:true, postedAfter:$a, "
         "postedBefore:$b, order:NEWEST){ pageInfo{hasNextPage endCursor} edges{node{%s}}}}" % FIELDS)

_lock = threading.Lock()
_mem: dict[str, dict] = {}          # day -> last good snapshot held by this instance
_state = {"last_error": None, "last_error_at": None, "last_ok_at": None, "upstream_calls": 0}
_minted: dict[str, str] = {}


class Upstream(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("PH_TOKEN") or (os.environ.get("PH_CLIENT_ID") and os.environ.get("PH_CLIENT_SECRET")))


def _token(http) -> str:
    t = os.environ.get("PH_TOKEN", "").strip()
    if t:
        return t
    cid, sec = os.environ.get("PH_CLIENT_ID", "").strip(), os.environ.get("PH_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        raise Upstream("not configured")
    if cid not in _minted:
        r = http.post(TOKEN_URL, json={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"},
                      timeout=UPSTREAM_TIMEOUT_S)
        if r.status_code != 200:
            raise Upstream(f"token http {r.status_code}")
        _minted[cid] = r.json()["access_token"]
    return _minted[cid]


def _window(day: str) -> tuple[str, str]:
    d = datetime.fromisoformat(day).date()
    a = datetime.combine(d, datetime.min.time(), PT)
    return a.isoformat(), (a + timedelta(days=1)).isoformat()


def _pt_day(iso: str | None) -> str | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(PT).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _fetch_upstream(day: str) -> list[dict]:
    """All featured launches of PT day `day`, as raw API nodes. Raises Upstream on any failure."""
    import httpx

    a, b = _window(day)
    nodes, cur, pages = [], None, 0
    with httpx.Client(timeout=UPSTREAM_TIMEOUT_S) as http:
        tok = _token(http)
        while True:
            _state["upstream_calls"] += 1
            try:
                r = http.post(ENDPOINT, json={"query": QUERY, "variables": {"a": a, "b": b, "c": cur}},
                              headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
            except httpx.HTTPError as exc:
                raise Upstream(f"network: {type(exc).__name__}") from None
            try:
                body = r.json()
            except ValueError:
                raise Upstream(f"http {r.status_code}") from None
            errs = body.get("errors") or []
            if errs:
                e = errs[0] if isinstance(errs[0], dict) else {}
                raise Upstream("rate limited" if e.get("error") == "rate_limit_reached" else f"api error: {str(e.get('error') or e.get('message') or 'unknown')[:60]}")
            if r.status_code != 200:
                raise Upstream(f"http {r.status_code}")
            p = (body.get("data") or {}).get("posts") or {}
            nodes += [e["node"] for e in p.get("edges") or [] if isinstance(e, dict) and e.get("node")]
            pages += 1
            info = p.get("pageInfo") or {}
            if not info.get("hasNextPage") or pages >= 8:
                break
            cur = info.get("endCursor")
    seen, out = set(), []
    for n in nodes:
        k = str(n.get("id"))
        if k in seen or (n.get("featuredAt") and _pt_day(n["featuredAt"]) != day):
            continue
        seen.add(k)
        out.append(n)
    return out


def _snapshot(day: str, nodes: list[dict], final: bool) -> dict:
    """Product fields only (no makers, hunters or users)."""
    now = datetime.now(timezone.utc)
    hidden = (not final and day == datetime.now(PT).strftime("%Y-%m-%d") and datetime.now(PT).hour < REVEAL_HOUR_PT)
    rows = []
    for n in nodes:
        thumb = ((n.get("thumbnail") or {}).get("url") or "")
        rows.append({
            "id": str(n.get("id")), "name": str(n.get("name") or "")[:120], "tagline": str(n.get("tagline") or "")[:200],
            "slug": str(n.get("slug") or "")[:120],
            "thumb": thumb if thumb.startswith("https://ph-files.imgix.net/") else None,
            "topics": [str(e["node"]["name"])[:40] for e in ((n.get("topics") or {}).get("edges") or [])
                       if isinstance(e, dict) and (e.get("node") or {}).get("name")][:3],
            "rank": int(n["dailyRank"]) if isinstance(n.get("dailyRank"), int) and n["dailyRank"] > 0 else None,
            "votes": None if hidden else (int(n["votesCount"]) if isinstance(n.get("votesCount"), int) else None),
            "comments": int(n["commentsCount"]) if isinstance(n.get("commentsCount"), int) else None,
        })
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -(r["votes"] or 0)))
    for i, r in enumerate(rows, 1):            # fill missing ranks after the ranked ones, in API order
        r["rank"] = r["rank"] or i
    return {"day": day, "fetched_at": now.isoformat(), "votes_hidden": hidden, "final": final,
            "source": "Product Hunt API", "launches": rows}


def _read_persisted(path: str) -> dict | None:
    try:
        j = gcs.read_json(path, ttl=0)
        return j if isinstance(j, dict) and isinstance(j.get("launches"), list) else None
    except Exception:  # noqa: BLE001
        return None


def _persist(snap: dict) -> None:
    try:
        b = gcs._bucket()
        data = json.dumps(snap)
        for p in ("site/live_board/latest.json", f"site/live_board/{snap['day']}.json"):
            b.blob(f"{gcs.ROOT}/{p}").upload_from_string(data, content_type="application/json")
    except Exception as exc:  # noqa: BLE001 - persistence is best effort; memory still serves this instance
        print(f"[ph_live] persist failed: {type(exc).__name__}", flush=True)


def _age_s(snap: dict | None) -> float | None:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(snap["fetched_at"])).total_seconds()
    except (TypeError, KeyError, ValueError):
        return None


def _note_error(msg: str) -> None:
    _state["last_error"], _state["last_error_at"] = msg, datetime.now(timezone.utc).isoformat()
    print(f"[ph_live] upstream: {msg}", flush=True)


def board(day: str, *, fetch=None) -> dict | None:
    """The leaderboard for PT day `day`: today's is refreshed at most once a minute; a past day is its last saved
    snapshot, re-read once from the API after the day closes (03:00 PT next day) to get the final ranks.
    Returns None only when nothing has ever been saved for that day and the API is unavailable."""
    fetch = fetch or _fetch_upstream
    today = datetime.now(PT).strftime("%Y-%m-%d")
    mem = _mem.get(day)
    if day == today:
        if mem and (_age_s(mem) or 1e9) < MIN_INTERVAL_S:
            return mem
        saved = _read_persisted("site/live_board/latest.json")
        if saved and saved.get("day") == day and (_age_s(saved) or 1e9) < MIN_INTERVAL_S:
            _mem[day] = saved                      # another instance refreshed it within the minute
            return saved
        last = max((s for s in (mem, saved if saved and saved.get("day") == day else None) if s),
                   key=lambda s: s.get("fetched_at", ""), default=None)
        return _refresh(day, last, fetch, final=False)
    # past day
    snap = mem or _read_persisted(f"site/live_board/{day}.json")
    closed = datetime.now(PT) >= datetime.fromisoformat(day).replace(tzinfo=PT) + timedelta(days=1, hours=3)
    if closed and not (snap and snap.get("final")) and configured():
        snap = _refresh(day, snap, fetch, final=True)
    if snap:
        _mem[day] = snap
    return snap


def _refresh(day: str, last: dict | None, fetch, final: bool) -> dict | None:
    if not configured():
        return last
    if not _lock.acquire(blocking=False):      # another thread is fetching: serve what we have
        return last
    try:
        try:
            nodes = fetch(day)
        except Upstream as exc:
            _note_error(str(exc))
            return last
        except Exception as exc:  # noqa: BLE001 - never let the upstream take the page down
            _note_error(f"unexpected: {type(exc).__name__}")
            return last
        if not nodes and last and last.get("launches"):
            _note_error("empty response")          # keep the last good board rather than blanking it
            return last
        snap = _snapshot(day, nodes, final)
        _mem[day] = snap
        _state["last_ok_at"] = snap["fetched_at"]
        _persist(snap)
        return snap
    finally:
        _lock.release()


def health() -> dict:
    today = datetime.now(PT).strftime("%Y-%m-%d")
    snap = _mem.get(today) or _read_persisted("site/live_board/latest.json")
    age = _age_s(snap) if snap and snap.get("day") == today else None
    return {"configured": configured(), "age_s": None if age is None else int(age),
            "launches": len((snap or {}).get("launches") or []) if snap and snap.get("day") == today else 0,
            "last_ok_at": _state["last_ok_at"] or (snap or {}).get("fetched_at"),
            "last_error": _state["last_error"], "last_error_at": _state["last_error_at"]}
