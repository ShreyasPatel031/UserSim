"""Live PH leaderboard forecast: read the day's forecast files, attach product facts and (once known) actual ranks.

Sources (read only):
  raw/daily/<day>/today_0005.json            line-up at 00:05 PT (product fields only are kept)
  raw/daily/<day>/forecast_<day>.parquet     00:05 PT launch-model forecast (pred = predicted log votes)
  results/early_forecast/<day>_P1..P4.json   pre-reveal: comment ridge (pred_rank), PH API rank (pred_rank_api), blend
  results/early_forecast/<day>_R0..R4.json   after the vote reveal (~04:00 PT)
  raw/ph_at_launch/<day>/api_detail/*.jsonl  hourly official-API detail: name/tagline/topics, votes, dailyRank
  raw/ph_at_launch/<day>/live/posts_ts.jsonl fallback for end-of-day ranks
Only product fields (id, name, tagline, slug, topics) and counts leave this module: maker/hunter/user fields are dropped.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mvp.ph_site import gcs

PT = ZoneInfo("America/Los_Angeles")

# Forecast points in time order. "sees" is what the forecast could see when it was made.
POINTS = [
    ("0005", "pre-launch", "Line-up, product pages, maker/hunter/team track record. No votes, no comments."),
    ("P1", "pre-reveal 1", "00:05 inputs + launch-day comments + PH's own ordering so far. Vote counts still hidden."),
    ("P2", "pre-reveal 2", "00:05 inputs + launch-day comments + PH's own ordering so far. Vote counts still hidden."),
    ("P3", "pre-reveal 3", "00:05 inputs + launch-day comments + PH's own ordering so far. Vote counts still hidden."),
    ("P4", "pre-reveal 4", "00:05 inputs + launch-day comments + PH's own ordering so far. Vote counts still hidden."),
    ("R0", "votes revealed", "First vote counts after PH reveals them (~04:00 PT) + the 00:05 forecast."),
    ("R1", "reveal + 1 h", "Vote counts and vote speed up to 1 h after the reveal + the 00:05 forecast."),
    ("R2", "reveal + 2 h", "Vote counts and vote speed up to 2 h after the reveal + the 00:05 forecast."),
    ("R4", "reveal + 4 h", "Vote counts and vote speed up to 4 h after the reveal + the 00:05 forecast."),
]
POINT_KEYS = [p[0] for p in POINTS]


def today_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d")


def _topics(v) -> list[str]:
    """topics arrive as dict edges/nodes, a list, or a stringified python dict (api_detail)."""
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v)
        except Exception:  # noqa: BLE001
            try:
                v = json.loads(v)
            except Exception:  # noqa: BLE001
                return []
    out = []
    if isinstance(v, dict):
        items = v.get("edges") or v.get("nodes") or []
        for it in items:
            n = it.get("node", it) if isinstance(it, dict) else {}
            if isinstance(n, dict) and n.get("name"):
                out.append(str(n["name"]))
    elif isinstance(v, list):
        out = [str(x) for x in v if isinstance(x, str)]
    return out[:4]


def _clean_text(s) -> str:
    return " ".join(str(s or "").split())[:200]


def _product(r: dict) -> dict:
    # Whitelist: product facts only. Never makers / user / hunter / website redirect.
    return {"id": str(r.get("id")), "name": _clean_text(r.get("name")), "tagline": _clean_text(r.get("tagline")),
            "slug": _clean_text(r.get("slug")), "topics": _topics(r.get("topics"))}


def available_days(limit: int = 30) -> list[str]:
    days = set()
    for name, _ in gcs.list_names("raw/daily/", ttl=300):
        parts = name.split("/")
        if len(parts) >= 4 and parts[3].startswith("forecast_") and parts[3].endswith(".parquet"):
            days.add(parts[2])
    for name, _ in gcs.list_names("results/early_forecast/", ttl=120):
        f = name.rsplit("/", 1)[-1]
        if f[:10].count("-") == 2:
            days.add(f[:10])
    return sorted(days, reverse=True)[:limit]


def _api_detail(day: str) -> tuple[list[dict], str | None]:
    names = sorted(n for n, _ in gcs.list_names(f"raw/ph_at_launch/{day}/api_detail/", ttl=300) if n.endswith(".jsonl"))
    if not names:
        return [], None
    rows = gcs.read_jsonl(names[-1], ttl=300)
    at = max((r.get("snapshot_at") or "" for r in rows), default="") or None
    return rows, at


def _posts_ts_final(day: str) -> tuple[dict, str | None]:
    rows = gcs.read_jsonl(f"raw/ph_at_launch/{day}/live/posts_ts.jsonl", ttl=600)
    last: dict[str, dict] = {}
    for r in rows:
        if r.get("fetch_status") != 200 or str(r.get("day", day)) != day:
            continue
        lid = str(r.get("launch_id"))
        if lid not in last or str(r.get("snapshot_ts")) >= str(last[lid].get("snapshot_ts")):
            last[lid] = r
    if not last:
        return {}, None
    at = max(str(r.get("snapshot_ts")) for r in last.values())
    votes = {k: float(r.get("votes_at_fetch") or 0) for k, r in last.items()}
    order = sorted(votes, key=lambda k: -votes[k])
    ranks = {}
    for i, k in enumerate(order, 1):
        dr = last[k].get("daily_rank_at_fetch")
        ranks[k] = {"rank": int(dr) if str(dr or "").isdigit() else i, "votes": int(votes[k])}
    return ranks, at


def _is_final(day: str, at_iso: str | None) -> bool:
    if not at_iso:
        return False
    at = datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(day).replace(tzinfo=PT) + timedelta(hours=22, minutes=55)
    return at >= end


def actuals(day: str) -> dict:
    """{'final': bool, 'as_of': iso, 'revealed': bool, 'ranks': {id: {rank, votes}}}"""
    def go():
        rows, at = _api_detail(day)
        ranks = {}
        for r in rows:
            try:
                ranks[str(r["id"])] = {"rank": int(r.get("dailyRank") or 0) or None, "votes": int(r.get("votesCount") or 0)}
            except (ValueError, TypeError):
                continue
        src = "api_detail"
        if not _is_final(day, at):
            pr, pat = _posts_ts_final(day)
            if pr and (_is_final(day, pat) or not ranks):
                ranks, at, src = pr, pat, "posts_ts"
        revealed = any(v.get("votes") for v in ranks.values())
        return {"final": _is_final(day, at), "as_of": at, "revealed": revealed, "ranks": ranks, "source": src}
    return gcs._cached("actuals:" + day, 300, go)


def _lineup(day: str) -> dict[str, dict]:
    prods: dict[str, dict] = {}
    t = gcs.read_json(f"raw/daily/{day}/today_0005.json", ttl=600) or []
    for r in t if isinstance(t, list) else []:
        p = _product(r)
        prods[p["id"]] = p
    rows, _ = _api_detail(day)
    for r in rows:
        p = _product(r)
        if p["id"] not in prods:
            prods[p["id"]] = p
        elif not prods[p["id"]]["topics"]:
            prods[p["id"]]["topics"] = p["topics"]
    return prods


def _forecast_0005(day: str):
    df = gcs.read_parquet(f"raw/daily/{day}/forecast_{day}.parquet", ttl=600)
    if df is None or not len(df):
        return None
    df = df.sort_values("pred", ascending=False)
    upd = dict(gcs.list_names(f"raw/daily/{day}/", ttl=300)).get(f"raw/daily/{day}/forecast_{day}.parquet", "")
    return {"ranks": {str(i): n for n, i in enumerate(df["id"].astype(str), 1)}, "made_at": upd,
            "data_up_to": datetime.fromisoformat(day).replace(hour=0, minute=5, tzinfo=PT).isoformat(),
            "method": "launch model (deployed 00:05 PT)"}


def _forecast_file(day: str, key: str):
    j = gcs.read_json(f"results/early_forecast/{day}_{key}.json", ttl=120)
    if not j or not j.get("forecast"):
        return None
    f = j["forecast"]
    if key.startswith("P"):
        # Pre-reveal files carry three orderings; the blend is the headline, the others are kept for the record.
        field = "pred_rank_blend" if any("pred_rank_blend" in r for r in f) else "pred_rank"
    else:
        field = "pred_rank"
    ranks = {str(r["id"]): int(r[field]) for r in f if r.get(field) is not None}
    if not ranks:
        return None
    alt = {}
    for af in ("pred_rank", "pred_rank_api"):
        if af != field and any(af in r for r in f):
            alt[af] = {str(r["id"]): int(r[af]) for r in f if r.get(af) is not None}
    return {"ranks": ranks, "made_at": j.get("written_at", ""), "data_up_to": j.get("data_up_to", ""),
            "method": j.get("method") or field, "rank_field": field, "alt": alt}


def forecasts(day: str) -> dict[str, dict]:
    def go():
        out = {}
        f = _forecast_0005(day)
        if f:
            out["0005"] = f
        for k in POINT_KEYS[1:]:
            f = _forecast_file(day, k)
            if f:
                out[k] = f
        return out
    return gcs._cached("fc:" + day, 120, go)


def _pt_label(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PT).strftime("%H:%M PT")
    except ValueError:
        return ""


def hits(pred: dict[str, int], act: dict[str, dict], k: int) -> int | None:
    actual_top = [i for i, v in sorted(act.items(), key=lambda kv: kv[1]["rank"] or 999) if v.get("rank")][:k]
    if len(actual_top) < k:
        return None
    pred_top = [i for i, _ in sorted(pred.items(), key=lambda kv: kv[1])][:k]
    return len(set(pred_top) & set(actual_top))


def day_view(day: str) -> dict:
    prods = _lineup(day)
    fc = forecasts(day)
    act = actuals(day)
    points = []
    for key, label, sees in POINTS:
        if key not in fc:
            continue
        f = fc[key]
        made = _pt_label(f.get("data_up_to")) or _pt_label(f.get("made_at"))
        score = None
        if act["final"]:
            score = {str(k): hits(f["ranks"], act["ranks"], k) for k in (3, 5, 10)}
        points.append({"key": key, "label": label, "time_pt": made, "made_at": f.get("made_at"),
                       "data_up_to": f.get("data_up_to"), "sees": sees, "method": f.get("method"),
                       "ranks": f["ranks"], "score": score})
    # Only expose live votes after the reveal; before it they are hidden on PH too.
    ranks = act["ranks"] if act["revealed"] else {}
    launches = []
    for pid, p in prods.items():
        a = ranks.get(pid, {})
        launches.append({**p, "actual_rank": a.get("rank") if act["final"] else None,
                         "current_rank": a.get("rank") if act["revealed"] else None,
                         "votes": a.get("votes") if act["revealed"] else None})
    return {"day": day, "today": today_pt(), "lineup_size": len(launches), "launches": launches, "points": points,
            "status": {"final": act["final"], "revealed": act["revealed"], "as_of_pt": _pt_label(act["as_of"] or ""),
                       "as_of": act["as_of"]}}


def track_record(max_days: int = 30) -> dict:
    """Top 3/5/10 hit rate per forecast point over every day that has a final result. Computed from files only."""
    def go():
        per = {k: {"days": [], "h3": 0, "h5": 0, "h10": 0} for k in POINT_KEYS}
        for day in available_days(max_days):
            act = actuals(day)
            if not act["final"]:
                continue
            for k, f in forecasts(day).items():
                h = [hits(f["ranks"], act["ranks"], kk) for kk in (3, 5, 10)]
                if None in h:
                    continue
                per[k]["days"].append(day)
                per[k]["h3"] += h[0]; per[k]["h5"] += h[1]; per[k]["h10"] += h[2]
        rows = []
        for key, label, sees in POINTS:
            r = per[key]
            n = len(r["days"])
            rows.append({"key": key, "label": label, "sees": sees, "n_days": n, "days": sorted(r["days"]),
                         "top3": round(100 * r["h3"] / (3 * n)) if n else None,
                         "top5": round(100 * r["h5"] / (5 * n)) if n else None,
                         "top10": round(100 * r["h10"] / (10 * n)) if n else None})
        return {"rows": rows, "computed_at": datetime.now(timezone.utc).isoformat(),
                "how": "Share of the day's actual top 3 / 5 / 10 that the forecast put in its own top 3 / 5 / 10, "
                       "pooled over every day with a final result and that forecast file."}
    return gcs._cached("track", 600, go)


def weekly() -> dict | None:
    names = sorted(n for n, _ in gcs.list_names("results/weekly_live/", ttl=300) if n.endswith(".json"))
    if not names:
        return None
    j = gcs.read_json(names[-1], ttl=300) or {}
    keep = []
    lookup: dict[str, dict] = {}
    for d in j.get("days_covered", []):
        lookup.update(_lineup(d))
    for r in (j.get("forecast") or [])[:10]:
        p = lookup.get(str(r.get("id")), {"name": "", "tagline": "", "topics": [], "slug": ""})
        keep.append({"id": str(r.get("id")), "pred_rank": r.get("pred_rank"), "est_votes": r.get("est"), "day": r.get("day"),
                     "name": p.get("name"), "tagline": p.get("tagline"), "slug": p.get("slug"), "topics": p.get("topics", [])})
    return {"week_monday": j.get("week_monday"), "as_of_day": j.get("day"), "point": j.get("point"),
            "written_at": j.get("written_at"), "top": keep}
