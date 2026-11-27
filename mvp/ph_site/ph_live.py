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
FIELDS = "id name tagline slug featuredAt votesCount commentsCount dailyRank thumbnail{url}"
QUERY = ("query($a:DateTime!,$b:DateTime!,$c:String){ posts(first:20, after:$c, featured:true, postedAfter:$a, "
         "postedBefore:$b, order:NEWEST){ pageInfo{hasNextPage endCursor} edges{node{%s}}}}" % FIELDS)

_lock = threading.Lock()
_mem: dict[str, dict] = {}          # day -> last good snapshot held by this instance
_state = {"last_error": None, "last_error_at": None, "last_ok_at": None, "upstream_calls": 0, "backoff_until": None,
          "backoff_n": 0, "last_partial": None}
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


def _window(day: str, back_days: int = 0) -> tuple[str, str]:
    d = datetime.fromisoformat(day).date()
    a = datetime.combine(d, datetime.min.time(), PT)
    return (a - timedelta(days=back_days)).isoformat(), (a + timedelta(days=1)).isoformat()


def _pt_day(iso: str | None) -> str | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(PT).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


class RateLimited(Upstream):
    def __init__(self, reset_in: int | None):
        super().__init__("rate limited")
        self.reset_in = reset_in


def _query(http, tok_ref: list, a: str, b: str) -> list[dict]:
    """Every page of the window. A partial GraphQL error with data is accepted only for a page that came back whole."""
    import httpx

    nodes, cur, pages, reminted = [], None, 0, False
    while True:
        _state["upstream_calls"] += 1
        try:
            r = http.post(ENDPOINT, json={"query": QUERY, "variables": {"a": a, "b": b, "c": cur}},
                          headers={"Authorization": f"Bearer {tok_ref[0]}", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise Upstream(f"network: {type(exc).__name__}") from None
        if r.status_code == 401 and not reminted and not os.environ.get("PH_TOKEN"):
            _minted.clear()                     # a rejected or expired minted token: mint a new one, once
            tok_ref[0] = _token(http)
            reminted = True
            continue
        try:
            body = r.json()
        except ValueError:
            raise Upstream(f"http {r.status_code}") from None
        errs = [e for e in (body.get("errors") or []) if isinstance(e, dict)] or (
            [{"error": "unknown"}] if body.get("errors") else [])
        for e in errs:
            if e.get("error") == "rate_limit_reached":
                try:
                    reset = int((e.get("details") or {}).get("reset_in"))
                except (TypeError, ValueError):
                    reset = None
                raise RateLimited(reset)
        if r.status_code == 429:
            raise RateLimited(None)
        if r.status_code != 200:
            raise Upstream(f"http {r.status_code}")
        p = (body.get("data") or {}).get("posts")
        if not isinstance(p, dict) or not isinstance(p.get("edges"), list) or not isinstance(p.get("pageInfo"), dict):
            msg = errs[0].get("error") or errs[0].get("message") if errs else "no posts in reply"
            raise Upstream(f"api error: {str(msg)[:60]}")
        if errs:
            _state["last_partial"] = str(errs[0].get("error") or errs[0].get("message") or "partial")[:60]
        nodes += [e["node"] for e in p["edges"] if isinstance(e, dict) and isinstance(e.get("node"), dict)]
        pages += 1
        if not p["pageInfo"].get("hasNextPage"):
            return nodes
        if pages >= 12:
            raise Upstream("too many pages")    # never serve a list we know is cut short
        cur = p["pageInfo"].get("endCursor")


def _rank_gap(nodes: list[dict]) -> bool:
    ranks = sorted(int(n["dailyRank"]) for n in nodes if isinstance(n.get("dailyRank"), int) and n["dailyRank"] > 0)
    return bool(ranks) and ranks[-1] > len(nodes)


def _fetch_upstream(day: str) -> list[dict]:
    """All featured launches of PT day `day`, as raw API nodes. Raises Upstream on any paging or parse failure.
    Complete means every page parsed and the API reported no further page. Rank gaps are normal on Product Hunt
    (a skipped rank after a tie, a launch hidden later), so a gap never makes a list "incomplete"; it only triggers
    one extra read with a 3-day window in case a launch was created before the day, and the larger list wins."""
    import httpx

    def keep(nodes):
        seen, out = set(), []
        for n in nodes:
            k = str(n.get("id"))
            if k in seen or (n.get("featuredAt") and _pt_day(n["featuredAt"]) != day):
                continue
            seen.add(k)
            out.append(n)
        return out

    with httpx.Client(timeout=UPSTREAM_TIMEOUT_S) as http:
        tok = [_token(http)]
        a, b = _window(day)
        out = keep(_query(http, tok, a, b))
        if _rank_gap(out):
            try:
                wide = keep(_query(http, tok, *_window(day, 2)))
                if len(wide) > len(out):
                    out = wide
            except Upstream:
                pass                                   # the first read is complete on its own
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
            "featured_at": str(n.get("featuredAt") or "")[:40] or None,
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
        paths = [f"site/live_board/{snap['day']}.json"]
        if snap["day"] == datetime.now(PT).strftime("%Y-%m-%d"):
            paths.append("site/live_board/latest.json")   # latest.json only ever holds today's board
        for p in paths:
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


def _backoff_active() -> bool:
    now = datetime.now(timezone.utc)
    until = _state.get("backoff_until")
    if not until:
        j = _read_persisted_any("site/live_board/backoff.json")
        until = (j or {}).get("until")
    try:
        return bool(until) and datetime.fromisoformat(until) > now
    except (TypeError, ValueError):
        return False


def _set_backoff(reset_in: int | None) -> None:
    """Honour Product Hunt's reset time; otherwise back off 1, 2, 4 ... 15 minutes. Shared with other instances."""
    n = _state["backoff_n"] = _state.get("backoff_n", 0) + 1
    wait = reset_in + 5 if reset_in else min(60 * 2 ** (n - 1), 900)
    until = (datetime.now(timezone.utc) + timedelta(seconds=wait)).isoformat()
    _state["backoff_until"] = until
    try:
        gcs._bucket().blob(f"{gcs.ROOT}/site/live_board/backoff.json").upload_from_string(
            json.dumps({"until": until, "reason": "rate limited"}), content_type="application/json")
    except Exception:  # noqa: BLE001 - in-memory back-off still applies
        pass


def _read_persisted_any(path: str) -> dict | None:
    try:
        j = gcs.read_json(path, ttl=30)
        return j if isinstance(j, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _refresh(day: str, last: dict | None, fetch, final: bool) -> dict | None:
    if not configured():
        return last
    if _backoff_active():                      # rate limited: serve the last good board until the reset time
        return last
    if not _lock.acquire(blocking=False):      # another thread is fetching: serve what we have
        return last
    try:
        try:
            nodes = fetch(day)
        except RateLimited as exc:
            _note_error("rate limited")
            _set_backoff(exc.reset_in)
            return last
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
        _state["backoff_n"], _state["backoff_until"] = 0, None
        _persist(snap)
        return snap
    finally:
        _lock.release()


# ---------- durable 15-minute record of the day (site/live_board/<day>_ts/<HHMM>.jsonl) ----------

def slot_for(now_pt: datetime) -> str:
    """:00/:15/:30/:45 PT, plus the day-close read at 23:50 PT. (03:45 PT is a regular slot.)"""
    if now_pt.hour == 23 and 50 <= now_pt.minute < 55:
        return "2350"
    return f"{now_pt.hour:02d}{now_pt.minute - now_pt.minute % 15:02d}"


def append_slot(*, fetch=None) -> dict:
    """Write this slot's snapshot once (create-only object: never overwritten, so the record is append-only).
    Called by the scheduler every 15 minutes and at 23:50 PT; repeated calls in the same slot are no-ops."""
    now = datetime.now(PT)
    day, slot = now.strftime("%Y-%m-%d"), slot_for(now)
    path = f"site/live_board/{day}_ts/{slot}.jsonl"
    snap = board(day, fetch=fetch)
    if not snap or snap.get("day") != day or not snap.get("launches"):
        return {"day": day, "slot": slot, "status": "skipped", "reason": "no board for today yet"}
    age = _age_s(snap)
    rows = [{"snapshot_ts": snap["fetched_at"], "slot": slot, "id": r["id"], "slug": r["slug"], "votes": r["votes"],
             "comments": r["comments"], "rank": r["rank"], "featured_at": r.get("featured_at")} for r in snap["launches"]]
    from google.api_core.exceptions import PreconditionFailed
    blob = gcs._bucket().blob(f"{gcs.ROOT}/{path}")
    blob.metadata = {"rows": str(len(rows)), "upstream_age_s": str(int(age or 0))}
    try:
        blob.upload_from_string("\n".join(json.dumps(r) for r in rows) + "\n", content_type="application/x-ndjson",
                                if_generation_match=0)
    except PreconditionFailed:
        return {"day": day, "slot": slot, "status": "exists"}
    _state["last_ts_append_at"] = datetime.now(timezone.utc).isoformat()
    return {"day": day, "slot": slot, "status": "written", "rows": len(rows), "upstream_age_s": int(age or 0),
            "stale": bool(age and age > 5 * 60)}


def ts_health(day: str) -> dict:
    try:
        blobs = list(gcs._bucket().client.list_blobs(gcs.BUCKET, prefix=f"{gcs.ROOT}/site/live_board/{day}_ts/"))
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}
    rows = sum(int((b.metadata or {}).get("rows") or 0) for b in blobs)
    last = max((b.updated for b in blobs if b.updated), default=None)
    return {"slots_today": len(blobs), "rows_today": rows, "last_ts_append_at": last.isoformat() if last else None}


def health() -> dict:
    today = datetime.now(PT).strftime("%Y-%m-%d")
    snap = _mem.get(today) or _read_persisted("site/live_board/latest.json")
    age = _age_s(snap) if snap and snap.get("day") == today else None
    return {"configured": configured(), "age_s": None if age is None else int(age),
            "launches": len((snap or {}).get("launches") or []) if snap and snap.get("day") == today else 0,
            "last_ok_at": _state["last_ok_at"] or (snap or {}).get("fetched_at"),
            "last_error": _state["last_error"], "last_error_at": _state["last_error_at"],
            "backoff_until": _state.get("backoff_until"), "upstream_calls_since_start": _state["upstream_calls"]}
