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


def handle_of(d):
    for k in ("handle", "username"):
        if isinstance(d.get(k), str):
            return d[k].lstrip("@").lower()
    m = HANDLE.search(str(d.get("profile") or ""))
    return m.group(1).lower() if m else None


def load_full(path, ids, upload_time=None, source=None):
    d = json.load(open(path))
    user = handle_of(d)
    pid = ids(user)
    f = _ts((d.get("run") or {}).get("finished_utc") or d.get("fetched_at"))
    f_quality = "estimated" if (d.get("run") or {}).get("finished_utc_estimated") else "file"
    if pd.isna(f):
        f, f_quality = _ts(upload_time), "upload_time_upper_bound"
    source = source or "people_live:" + path.split("people_live/")[-1].split("/")[0]
    hdr = d.get("header") or {}
    tabs, ev = [], []
    for t in TABS:
        v = d.get(t)
        if v is None:
            tabs.append(dict(person_id=pid, tab=t, header=hdr.get(t), count=None, complete=False, stopped_early=None,
                             fetched_at=f, fetched_quality=f_quality, source=source))
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
                         fetched_at=ft, fetched_quality=fq, source=source))
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
                typ = (it.get("type") or "").lower()
                kind = "comment" if "comment" in typ else ("launched" if "launch" in typ else ("hunted" if "hunt" in typ else "discussion"))
                ts = _ts(it.get("datetime"))
                cid = it.get("comment_id") or (COMMENT.search(url).group(1) if COMMENT.search(url) else None)
                ev.append({**base, "kind": kind, "ts_lo": ts, "ts_hi": ts, "ts_quality": "exact" if pd.notna(ts) else "none",
                           "extra": json.dumps({"comment_id": cid})})
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
