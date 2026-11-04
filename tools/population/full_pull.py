"""Load Grok Bot / Data Feeder full all-tab pulls (people_live/{vm,boxbrowser}/**.json) into store tables.
tabs table: one row per (person, tab): header (count shown on PH), count (items captured), complete, stopped_early, fetched_at.
events: upvote (list order kept; launch id when the pull has post_id, else product slug), comment (exact datetime, comment_id),
launched / hunted (exact or day), review (exact), follows edges (follower -> person, person -> followee), collection/stack items.
fetched_at: the file's own time (run.finished_utc / fetched_at), else the GCS upload time passed in (upper bound, flagged).
"""
import json, os, re
from datetime import datetime
import pandas as pd

TABS = ["about", "forums", "activity", "upvotes", "hunted", "collections", "stacks", "reviews", "followers", "following"]
HANDLE = re.compile(r"producthunt\.com/@([A-Za-z0-9_\.\-]+)")
PRODUCT = re.compile(r"/products/([^/?#]+)")
LAUNCH = re.compile(r"/launches/([^/?#]+)|[?&]launch=([^&#]+)")
COMMENT = re.compile(r"[?&]comment=(\d+)")


def _ts(s):
    if not s or not isinstance(s, str):
        return pd.NaT
    t = pd.to_datetime(s, utc=True, errors="coerce")
    if pd.isna(t):  # "November 3rd, 2026"
        try:
            t = pd.Timestamp(datetime.strptime(re.sub(r"(\d)(st|nd|rd|th)", r"\1", s), "%B %d, %Y"), tz="UTC")
        except ValueError:
            return pd.NaT
    return t


def handle_of(d, path=None):
    for k in ("handle", "username"):
        if isinstance(d.get(k), str):
            return d[k].lstrip("@").lower()
    m = HANDLE.search(str(d.get("profile") or ""))
    return m.group(1).lower() if m else None


def load_full(path, ids, upload_time=None, source=None, filled=None):
    """filled: {"<handle>|<comment_id>": {"created_at", "method", "post_id"}} times recovered from API comments (F1 fix)."""
    filled = filled or {}
    d = json.load(open(path))
    if not isinstance(d, dict) or not any(t in d for t in ("upvotes", "header")):
        return pd.DataFrame(), pd.DataFrame()   # heartbeat / status files
    user = handle_of(d)
    pid = ids(user)
    f = _ts((d.get("run") or {}).get("finished_utc") or d.get("fetched_at"))
    f_quality = "estimated" if (d.get("run") or {}).get("finished_utc_estimated") else "file"
    if pd.isna(f):
        f, f_quality = _ts(upload_time), "upload_time_upper_bound"
    source = source or "people_live:" + path.split("people_live/")[-1].split("/")[0]
    # light pull (48 h coverage plan): profile header + upvotes list only. Recognised by mode/method or by shape.
    others = [t for t in TABS if t not in ("upvotes", "about") and isinstance(d.get(t), dict)]
    light = "light" in str(d.get("mode") or d.get("method") or "").lower() or "/light/" in path or not others
    pull_type = "light" if light else "full"
    if "pgql" in str(d.get("method") or "").lower() or "/vm_pgql/" in path:
        light, pull_type = False, "pgql"   # fast GraphQL pull: real lists, but collection items / product pages / threads need deep
        source = "people_live:vm_pgql"
    if str(d.get("method") or "").startswith("one long-lived"):
        source += ":reused_browser"
    hdr = d.get("header") or {}
    tabs, ev = [], []
    for t in (["upvotes"] if light else TABS):
        v = d.get(t)
        if v is None:
            tabs.append(dict(person_id=pid, tab=t, header=hdr.get(t), count=None, complete=False, stopped_early=None,
                             fetched_at=f, fetched_quality=f_quality, source=source, pull_type=pull_type,
                             complete_not_visible=False, capped_large=False, signed_out_cap=False))
            continue
        items = v.get("items") or []
        ft = _ts(v.get("fetched_at")) if v.get("fetched_at") else f   # per-tab fetch time when the pull records it
        fq = "estimated" if v.get("fetched_at_estimated") else (f_quality if not v.get("fetched_at") else "file")
        n = v.get("count", len(items)) if t != "about" else 1
        h = v.get("header", hdr.get(t))
        note = (v.get("note") or "").lower()
        # stopped early: an explicit partial note, or fewer than 98% of the displayed count (reviews' header counts rating-only
        # reviews that are never listed, so it is not compared). Boilerplate notes ("manual saw 20") don't count.
        explicit = bool(re.search(r"partial|stops after|first \d+ loaded|of ~|lazy-load continued", note))
        short = h is not None and t != "reviews" and n < 0.98 * h
        stopped = explicit or short
        tabs.append(dict(person_id=pid, tab=t, header=h, count=n, complete=not stopped, stopped_early=stopped,
                         fetched_at=ft, fetched_quality=fq, source=source, pull_type=pull_type,
                         complete_not_visible=bool(v.get("complete_not_visible")) and not v.get("capped_large"),
                         capped_large=bool(v.get("capped_large") or v.get("status") == "capped_large"),
                         signed_out_cap=bool(t == "upvotes" and (v.get("upvotes_capped") or (v.get("complete_not_visible") and 190 <= n <= 210)))))
        for i, it in enumerate(items, 1):
            url = it.get("url") or ""
            prod = PRODUCT.search(url)
            lm = LAUNCH.search(url)
            target = str(it.get("post_id") or (f"launch:{lm.group(1) or lm.group(2)}" if lm else None)
                         or (f"product:{prod.group(1)}" if prod else url))
            base = dict(person_id=pid, platform="producthunt", target_id=target, first_seen_at=ft, fetched_at=ft, source=source)
            if t == "upvotes":
                ev.append({**base, "kind": "upvote", "ts_lo": pd.NaT, "ts_hi": ft, "ts_quality": "snapshot",
                           "extra": json.dumps({"position": i, "of": n})})
            elif t == "activity":
                typ = (it.get("type") or it.get("raw_type") or "").lower()
                kind = "comment" if "comment" in typ else ("launched" if "launch" in typ else ("hunted" if "hunt" in typ else "discussion"))
                ts = _ts(it.get("datetime"))
                cid = it.get("comment_id") or (COMMENT.search(url).group(1) if COMMENT.search(url) else None)
                if kind == "comment" and not it.get("post_id"):
                    # the feed's own url is the product (?comment=); the launch commented on is in on_launch_url / on_url
                    for k in ("on_launch_url", "on_url", "launch_url"):
                        m2 = LAUNCH.search(it.get(k) or "")
                        if m2:
                            base["target_id"] = f"launch:{m2.group(1) or m2.group(2)}"; break
                q = "exact" if pd.notna(ts) else "none"
                lo, hi = ts, ts
                fill = filled.get(f"{user}|{cid}") if kind == "comment" else None
                if fill:  # F1: time recovered from API comments by comment id; the API's post id is the launch
                    lo = hi = _ts(fill["created_at"]); q = "exact"
                    if fill.get("post_id"):
                        base["target_id"] = str(fill["post_id"])
                elif kind == "comment" and (it.get("comment_time_unknown") or pd.isna(ts)):
                    lo, hi, q = pd.NaT, ft, "unknown"   # F1: only a launch stamp existed; time unknown, before fetch
                elif kind == "comment" and pd.notna(ts) and ts.tz_convert("America/Los_Angeles").strftime("%H:%M:%S") == "00:01:00" \
                        and it.get("datetime_source") not in ("comment.createdAt (thread capture)", "api_match"):
                    # Nov 4 check: comments stamped 00:01:00 PT carry the LAUNCH time, not the comment's (16/16 matched to
                    # API createdAt were 0.5-200 h later; all other times matched to the second). Keep a window only.
                    q, hi = "bounded", ft
                ev.append({**base, "kind": kind, "ts_lo": lo, "ts_hi": hi, "ts_quality": q,
                           "extra": json.dumps({"comment_id": cid, "time_source": (fill or {}).get("method") or it.get("datetime_source")})})
            elif t == "reviews":
                ts = _ts(it.get("date"))
                ev.append({**base, "kind": "review", "ts_lo": ts, "ts_hi": ts, "ts_quality": "exact" if pd.notna(ts) else "none",
                           "extra": None})
            elif t in ("followers", "following"):
                other = (it.get("handle") or "").lstrip("@").lower() or (HANDLE.search(url).group(1).lower() if HANDLE.search(url) else None)
                if not other:
                    continue
                a, b = (ids(other), pid) if t == "followers" else (pid, ids(other))
                ev.append({**base, "person_id": a, "target_id": b, "kind": "follows", "ts_lo": pd.NaT, "ts_hi": ft,
                           "ts_quality": "snapshot", "extra": None})
            elif t in ("collections", "stacks"):
                for sub in (it.get("items") or [it] if t == "stacks" else it.get("items") or []):
                    pm = PRODUCT.search(sub.get("url") or "")
                    ev.append({**base, "kind": t[:-1], "target_id": f"product:{pm.group(1)}" if pm else sub.get("url"),
                               "ts_lo": pd.NaT, "ts_hi": ft, "ts_quality": "snapshot",
                               "extra": json.dumps({"list": it.get("name")}) if t == "collections" else None})
    tabs = pd.DataFrame(tabs)
    ev = pd.DataFrame(ev)
    if len(ev):
        ev = ev.drop_duplicates(["person_id", "kind", "target_id", "ts_lo"])
    return tabs, ev
