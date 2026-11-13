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
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mvp.ph_site import gcs

PT = ZoneInfo("America/Los_Angeles")

# Forecast points in time order. "sees" is what the forecast could see when it was made.
POINTS = [
    ("0005", "pre-launch", "Line-up, product pages, maker/hunter/team track record. No votes, no comments."),
    ("P1", "pre-reveal 1", "Product Hunt's own (hidden-vote) order so far + the 00:05 forecast. No comments; vote counts still hidden."),
    ("P2", "pre-reveal 2", "Product Hunt's own (hidden-vote) order so far + the 00:05 forecast. No comments; vote counts still hidden."),
    ("P3", "pre-reveal 3", "Product Hunt's own (hidden-vote) order so far + the 00:05 forecast. No comments; vote counts still hidden."),
    ("P4", "pre-reveal 4", "Product Hunt's own (hidden-vote) order so far + the 00:05 forecast. No comments; vote counts still hidden."),
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


THUMB_HOSTS = ("ph-files.imgix.net",)


def _thumb(v) -> str | None:
    """Product thumbnail from PH's image CDN only (Post.thumbnail.url in the official API). Never a person avatar."""
    if isinstance(v, dict):
        v = v.get("url")
    if not isinstance(v, str):
        return None
    m = re.match(r"^https://(ph-files\.imgix\.net)/[A-Za-z0-9._\-/]+$", v.split("?")[0])
    if not m or m.group(1) not in THUMB_HOSTS:
        return None
    return v.split("?")[0] + "?auto=format&fit=crop&w=112&h=112"


def _product(r: dict) -> dict:
    # Whitelist: product facts only. Never makers / user / hunter / website redirect.
    return {"id": str(r.get("id")), "name": _clean_text(r.get("name")), "tagline": _clean_text(r.get("tagline")),
            "slug": _clean_text(r.get("slug")), "topics": _topics(r.get("topics")),
            "thumb": _thumb(r.get("thumbnail") or r.get("thumbnail_url"))}


def _icons(day: str) -> dict[str, str]:
    """Optional per-day {launch_id: thumbnail url} written by the data feeder from the official API."""
    j = gcs.read_json(f"results/web/icons/{day}.json", ttl=600) or {}
    return {str(k): t for k, v in j.items() if (t := _thumb(v))} if isinstance(j, dict) else {}


def available_days(limit: int = 30) -> list[str]:
    days = set()
    for name, _ in gcs.list_names("raw/daily/", ttl=300):
        parts = name.split("/")
        if len(parts) >= 4 and parts[3].startswith("forecast_") and parts[3].endswith(".parquet"):
            days.add(parts[2])
    for name, _ in gcs.list_names("results/web/forecast_0005/", ttl=300):
        f = name.rsplit("/", 1)[-1]
        if f.endswith(".json") and f[:10].count("-") == 2:
            days.add(f[:10])
    for name, _ in gcs.list_names("results/early_forecast/", ttl=120):
        f = name.rsplit("/", 1)[-1]
        if f[:10].count("-") == 2:
            days.add(f[:10])
    return sorted(days, reverse=True)[:limit]


def _api_detail(day: str) -> tuple[list[dict], str | None]:
    names = sorted(n for n, _ in gcs.list_names(f"raw/ph_at_launch/{day}/api_detail/", ttl=300) if n.endswith(".jsonl"))
    if not names:
        return [], None
    rows = [r for r in gcs.read_jsonl(names[-1], ttl=300) if _launch_day(r, day) == day]
    at = max((r.get("snapshot_at") or "" for r in rows), default="") or None
    return rows, at


def _launch_day(r: dict, default: str) -> str:
    """Launch day = PT date of featured_at (raw files tag launches featured at exactly 00:00 PT to the previous day)."""
    fa = r.get("featured_at") or r.get("featuredAt")
    if fa:
        try:
            return datetime.fromisoformat(str(fa).replace("Z", "+00:00")).astimezone(PT).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return str(r.get("day") or default)


def _final_after(day: str) -> datetime:
    """PH's daily rank is votes at midnight PT; it is only stable from 03:00 PT the next day."""
    return datetime.fromisoformat(day).replace(tzinfo=PT) + timedelta(days=1, hours=3)


def _pt_day(iso: str) -> str | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(PT).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _monthly_reread(day: str) -> tuple[dict, str | None]:
    """Official dailyRank from the 23:50 PT official-API re-read, using only rows read at or after 03:00 PT the next
    day. The launch day is the PT date of featuredAt (a launch featured at 00:00 PT belongs to that new day)."""
    cut = _final_after(day)
    months = sorted({day[:7], (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m")})
    names = sorted(n for m in months for n, _ in gcs.list_names(f"raw/ph_at_launch/monthly_reread/{m}/", ttl=600)
                   if n.endswith(".jsonl"))
    for n in reversed(names):
        rows = gcs.read_jsonl(n, ttl=600)
        ranks, at = {}, None
        for r in rows:
            if r.get("_header") or not r.get("dailyRank"):
                continue
            launch_day = _pt_day(r.get("featuredAt")) or str(r.get("launch_day_PT"))
            if launch_day != day:
                continue
            try:
                fetched = datetime.fromisoformat(str(r.get("fetched_at")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if fetched < cut:
                continue
            try:
                ranks[str(r["id"])] = {"rank": int(r["dailyRank"]), "votes": int(r.get("votesCount") or 0)}
            except (ValueError, TypeError):
                continue
            at = max(at or "", str(r.get("fetched_at") or ""))
        if ranks:
            return ranks, at
    return {}, None


def _scoreboard_top10(day: str) -> dict:
    sb = gcs.read_json("results/web/scoreboard.json", ttl=600) or {}
    ids = (sb.get("actual_top10") or {}).get(day) or []
    return {str(i): {"rank": n, "votes": None} for n, i in enumerate(ids, 1)}


def actuals(day: str) -> dict:
    """{'final', 'as_of', 'revealed', 'ranks': {id: {rank, votes}}, 'source'}.
    Final only from the official daily rank read at or after 03:00 PT the next day (monthly re-read), or from the
    warehouse's final ranks (lineup file / scoreboard top 10) for older days. Same-day reads are 'current', never final."""
    def go():
        now = datetime.now(PT)
        if now >= _final_after(day):
            mr, mat = _monthly_reread(day)
            if mr:
                return {"final": True, "as_of": mat, "revealed": True, "ranks": mr, "source": "official daily rank"}
            lu = gcs.read_json(f"results/web/lineup/{day}.json", ttl=3600) or {}
            top = {str(r["id"]): {"rank": int(r["daily_rank"]), "votes": r.get("votes")}
                   for r in (lu.get("launches") or []) if isinstance(r, dict) and r.get("daily_rank")}
            src = "warehouse final ranks"
            if not top:
                top, src = _scoreboard_top10(day), "scoreboard final top 10"
            if top:
                return {"final": True, "as_of": _final_after(day).isoformat(), "revealed": True, "ranks": top,
                        "source": src}
        rows, at = _api_detail(day)
        ranks = {}
        for r in rows:
            try:
                ranks[str(r["id"])] = {"rank": int(r.get("dailyRank") or 0) or None, "votes": int(r.get("votesCount") or 0)}
            except (ValueError, TypeError):
                continue
        revealed = any(v.get("votes") for v in ranks.values())
        return {"final": False, "as_of": at, "revealed": revealed, "ranks": ranks, "source": "same-day read (not final)"}
    return gcs._cached("actuals:" + day, 300, go)


def _lineup(day: str) -> dict[str, dict]:
    prods: dict[str, dict] = {}
    t = (gcs.read_json(f"raw/daily/{day}/today_0005.json", ttl=600)
         or gcs.read_json(f"raw/daily/{day}/{day}.json", ttl=600) or [])
    for r in t if isinstance(t, list) else []:
        p = _product(r)
        prods[p["id"]] = p
    lu = gcs.read_json(f"results/web/lineup/{day}.json", ttl=3600) or {}
    for r in lu.get("launches") or [] if isinstance(lu, dict) else []:
        p = _product(r)
        prods.setdefault(p["id"], p)
    rows, _ = _api_detail(day)
    for r in rows:
        p = _product(r)
        if p["id"] not in prods:
            prods[p["id"]] = p
        else:
            prods[p["id"]]["topics"] = prods[p["id"]]["topics"] or p["topics"]
            prods[p["id"]]["thumb"] = prods[p["id"]]["thumb"] or p["thumb"]
    for pid, url in _icons(day).items():
        if pid in prods and not prods[pid]["thumb"]:
            prods[pid]["thumb"] = url
    return prods


def _forecast_0005(day: str):
    """00:05 PT launch-model order. Prefer the JSON export (results/web/forecast_0005/<day>.json: [{id, predicted_rank}]
    or {id: rank}); the parquet is read only where pyarrow happens to be installed (it is not in the Vercel bundle)."""
    ids, made = None, ""
    j = gcs.read_json(f"results/web/forecast_0005/{day}.json", ttl=600)
    if isinstance(j, dict) and isinstance(j.get("forecast"), list):
        made = j.get("run_updated_at") or j.get("written_at", "")   # when the forecast itself was produced
        j = j["forecast"]
    if isinstance(j, list) and j:
        rows = [(str(r.get("id")), int(r.get("predicted_rank") or r.get("pred_rank") or 0)) for r in j if isinstance(r, dict)]
        ids = [i for i, _ in sorted(rows, key=lambda t: t[1]) if i]
    elif isinstance(j, dict) and j:
        ids = [str(k) for k, _ in sorted(j.items(), key=lambda kv: int(kv[1]))]
    if not ids:
        try:
            df = gcs.read_parquet_cols(f"raw/daily/{day}/forecast_{day}.parquet", ["id", "pred"], ttl=600)
        except ImportError:
            df = None
        if not df or not df["id"]:
            return _forecast_0005_md(day)
        ids = [str(i) for i, _ in sorted(zip(df["id"], df["pred"]), key=lambda t: -(t[1] if t[1] is not None else -1e9))]
        made = dict(gcs.list_names(f"raw/daily/{day}/", ttl=300)).get(f"raw/daily/{day}/forecast_{day}.parquet", "")
    return {"ranks": {i: n for n, i in enumerate(ids, 1)}, "made_at": made,
            "data_up_to": datetime.fromisoformat(day).replace(hour=0, minute=5, tzinfo=PT).isoformat(),
            "method": "launch model (deployed 00:05 PT)"}


def _forecast_0005_md(day: str):
    """Fallback without pyarrow (the Vercel bundle): the same 00:05 run also writes raw/daily/<day>/forecast_<day>.md, a
    table of predicted rank and product name; names are mapped to ids through that night's line-up file."""
    import re as _re
    raw = gcs.read_bytes(f"raw/daily/{day}/forecast_{day}.md", ttl=600)
    t = gcs.read_json(f"raw/daily/{day}/today_0005.json", ttl=600) or gcs.read_json(f"raw/daily/{day}/{day}.json", ttl=600)
    if not raw or not isinstance(t, list):
        return None
    by_name: dict[str, list[str]] = {}
    for r in t:
        p = _product(r)
        by_name.setdefault((p.get("name") or "").strip().lower(), []).append(p["id"])
    ranked = []
    for line in raw.decode("utf-8", "replace").splitlines():
        m = _re.match(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|", line)
        if not m:
            continue
        cand = by_name.get(m.group(2).strip().lower()) or []
        if len(cand) == 1:
            ranked.append((int(m.group(1)), cand[0]))
    if len(ranked) < max(3, len(t) // 2):        # too few names matched: do not show a partial order as the forecast
        return None
    ids = [i for _, i in sorted(ranked)]
    made = dict(gcs.list_names(f"raw/daily/{day}/", ttl=300)).get(f"raw/daily/{day}/forecast_{day}.md", "")
    return {"ranks": {i: n for n, i in enumerate(ids, 1)}, "made_at": made,
            "data_up_to": datetime.fromisoformat(day).replace(hour=0, minute=5, tzinfo=PT).isoformat(),
            "method": "launch model (deployed 00:05 PT)"}


def _forecast_file(day: str, key: str):
    j = gcs.read_json(f"results/early_forecast/{day}_{key}.json", ttl=120)
    if not j or not j.get("forecast"):
        return None
    f = j["forecast"]
    # Pre-reveal files carry three orderings. The comment ridge leads (backtested on 207 days); PH's API rank and the
    # blend rest on a few replay days, so they are kept as experimental alternatives (PH ops, Nov 11).
    field = "pred_rank_best" if key.startswith("P") and any("pred_rank_best" in r for r in f) else "pred_rank"
    ranks = {str(r["id"]): int(r[field]) for r in f if r.get(field) is not None}
    # Expected day-end votes (PH ops growth model, from Nov 12; null when unknown).
    exp = {str(r["id"]): round(float(r["exp_final_votes"])) for r in f
           if isinstance(r.get("exp_final_votes"), (int, float))}
    if not ranks:
        return None
    alt = {}
    for af in ("pred_rank", "pred_rank_blend", "pred_rank_api"):
        if af != field and any(af in r for r in f):
            alt[af] = {str(r["id"]): int(r[af]) for r in f if r.get(af) is not None}
    method = ("best blend (comments, PH's hidden order, 00:05 model)" if field == "pred_rank_best"
              else "comment ridge" if key.startswith("P") else (j.get("method") or field))
    agree = None
    if key.startswith("P"):
        # Do PH's hidden API order and the 00:05 model roughly agree on this pick? (|positions| <= 2, PH ops' rule)
        api = {str(r["id"]): r.get("pred_rank_api") for r in f}
        lm = sorted(((str(r["id"]), r.get("lm")) for r in f if isinstance(r.get("lm"), (int, float))), key=lambda t: -t[1])
        lm_pos = {i: n for n, (i, _) in enumerate(lm, 1)}
        agree = {i: abs(int(api[i]) - lm_pos[i]) <= 2 for i in ranks if api.get(i) and i in lm_pos}
    return {"ranks": ranks, "made_at": j.get("written_at", ""), "data_up_to": j.get("data_up_to", ""),
            "method": method, "rank_field": field, "alt": alt, "exp_votes": exp or None, "agree": agree}


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


def _written_label(day: str, iso: str | None) -> str:
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(PT)
    except ValueError:
        return ""
    return t.strftime("%H:%M PT") if t.strftime("%Y-%m-%d") == day else t.strftime("%b %d, %H:%M PT")


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


def current_board(day: str) -> dict:
    """PH's own leaderboard from the latest 15-min snapshot (official API light loop). Votes only once PH shows them."""
    rows = gcs.read_tail_jsonl(f"raw/ph_at_launch/{day}/live/posts_ts.jsonl", ttl=120)
    rows = [r for r in rows if r.get("fetch_status") == 200 and r.get("snapshot_ts") and _launch_day(r, day) == day]
    if not rows:
        return {"as_of": None, "as_of_pt": "", "ranks": {}, "votes_hidden": True}
    last = max(r["snapshot_ts"] for r in rows)
    snap = [r for r in rows if r["snapshot_ts"] == last]
    hidden = sum(bool(r.get("hide_votes_count")) for r in snap) > len(snap) / 2
    ranks = {}
    for i, r in enumerate(sorted(snap, key=lambda r: (int(r.get("daily_rank_at_fetch") or 999), -(r.get("votes_at_fetch") or 0))), 1):
        dr = r.get("daily_rank_at_fetch")
        ranks[str(r["launch_id"])] = {"rank": int(dr) if dr else i,
                                      "votes": None if hidden or r.get("votes_at_fetch") is None else int(r["votes_at_fetch"]),
                                      "comments": int(r.get("comments_count_at_fetch") or 0)}
    return {"as_of": last, "as_of_pt": _pt_label(last), "ranks": ranks, "votes_hidden": hidden}


def claims() -> dict:
    """Fixed offline figures with source and date (mvp/ph_site/claims.json)."""
    from pathlib import Path
    return json.loads((Path(__file__).with_name("claims.json")).read_text())


_BRAND = re.compile(r"\bby\s+[A-Z]")
_VERSION = re.compile(r"\b\d+(\.\d+)+\b|\bv\d+\b")


def _top3_confidence(ranks: dict[str, int], prods: dict[str, dict]) -> dict[str, dict]:
    """Live per-pick record of the deployed 00:05 model (scoreboard: how often our #k finished in the final top 3)."""
    sb = gcs.read_json("results/web/scoreboard.json", ttl=600) or {}
    row = next((r for r in sb.get("summary") or [] if r.get("point") == "0005" and r.get("method") == "published"
                and r.get("source") == "live"), None)
    if not row:
        return {}
    bt = None
    b = claims().get("launch_model_backtest")
    if b and "p1_top3" in b["values"]:
        bt = {"label": b.get("pick_label") or b["label"], "p1": b["values"]["p1_top3"], "exact1": b["values"]["exact1"],
              "date": b["date"]}
    out = {}
    for pid, r in ranks.items():
        cnt = row.get(f"p{r}_top3_count") if r <= 3 else None
        if cnt:
            out[pid] = {"count": cnt, "what": "top 3", "basis": f"live 00:05 calls, {row.get('first_day')} to {row.get('last_day')}",
                        "backtest": bt}
    return out


def _prereveal_confidence(key: str, f: dict) -> dict | None:
    """PH ops' replay of the pre-reveal picks (results/web/prereveal_confidence.json): how often pick k finished in the
    top 3 (picks 1-3) or top 5 (picks 4-5), as counts, plus whether the hidden API order and the 00:05 model agree."""
    pc = gcs.read_json("results/web/prereveal_confidence.json", ttl=3600)
    if not pc or key not in (pc.get("by_point") or {}) or pc.get("applies_to", "pred_rank_best") != "pred_rank_best":
        return None
    bp, out = pc["by_point"][key], {}
    ag = pc.get("by_agreement") or {}
    for pid, r in f["ranks"].items():
        if r > 5:
            continue
        cell = (bp.get(f"pick{r}") or {}).get("in_top3" if r <= 3 else "in_top5")
        if not cell:
            continue
        a = (f.get("agree") or {}).get(pid)
        arate = ((ag.get("agree" if a else "disagree") or {}).get("picks1_3_in_top3" if r <= 3 else "picks1_5_in_top5")
                 if a is not None else None)
        out[pid] = {"hits": cell["hits"], "n": cell["n"], "what": "top 3" if r <= 3 else "top 5", "agree": a,
                    "agree_rate": arate["rate"] if arate else None,
                    "basis": f"{'in-sample ' if pc.get('in_sample') else ''}replay, {pc.get('n_days')} days",
                    "note": pc.get("note", "")}
    return out or None


def _difficulty(day: str) -> dict | None:
    """Day label from results/web/confidence/<day>.json (conf_v2: clear_leader / open_field). It is validated for the
    clean shadow model only, so it is returned only if the file says it applies to the published ranking and is
    stable; with today's files (applies_to "clean shadow model") it is never shown next to the published picks."""
    j = gcs.read_json(f"results/web/confidence/{day}.json", ttl=600)
    if not isinstance(j, dict) or not j.get("label") or j.get("stable") is not True:
        return None
    if str(j.get("applies_to") or "").strip().lower() not in ("published", "published 00:05 ranking", "deployed"):
        return None
    vr = j.get("validated_rates") or {}
    out = {"label": j["label"], "text": j.get("text") or "", "days": vr.get("days"), "p1_top3": vr.get("p1_top3"),
           "p1_count": vr.get("p1_count"), "source": j.get("source") or ""}
    fc = gcs.read_json("results/web/confidence_scoreboard.json", ttl=600) or {}
    fwd = ((fc.get("by_label") or {}).get(j["label"])) if isinstance(fc, dict) else None
    if isinstance(fwd, dict) and fwd.get("days"):
        out["forward"] = {"days": fwd["days"], "p1_top3_count": fwd.get("p1_top3_count")}
    return out


WHY_MIN_GROUP = 20


def _why_prefix() -> str:
    # The published path. A local-only override lets the shadow files be previewed; it is ignored on the deployed site.
    import os
    o = os.environ.get("PH_WHY_PREFIX")
    return o if o and not (os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV")) else "results/web/why"


def _why_num(v):
    return round(float(v), 4) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def why(day: str, point: str, ids: set[str]) -> dict | None:
    """Per-launch explanation items written by the model owners (results/web/why/<day>_<point>.json): aggregates only.
    Re-checked here before anything is served: only launches in the day's line-up, only numbers (or one level of named
    numeric shares), and no item that rests on fewer than 20 people."""
    j = gcs.read_json(f"{_why_prefix()}/{day}_{point}.json", ttl=300)
    if not isinstance(j, dict) or not isinstance(j.get("launches"), dict) or not isinstance(j.get("items"), dict):
        return None
    floor = max(WHY_MIN_GROUP, int(j.get("min_group") or 0))
    notes = {str(k): str(v)[:500] for k, v in (j.get("notes") or {}).items()}
    items = {str(k): {"label": str(v.get("label") or k)[:120], "unit": str(v.get("unit") or "")[:40],
                      "note": notes.get(str(v.get("note")), "")}
             for k, v in j["items"].items() if isinstance(v, dict)}
    out = {}
    for pid, row in j["launches"].items():
        if str(pid) not in ids or not isinstance(row, dict):
            continue
        keep = {}
        for k, it in row.items():
            if k not in items or not isinstance(it, dict):
                continue
            n = it.get("n_people")
            if isinstance(n, (int, float)) and n < floor:
                continue                                     # never show a group under the floor
            val = it.get("value")
            if isinstance(val, dict):
                v = {str(a)[:40]: {str(b)[:20]: _why_num(x) for b, x in d.items() if _why_num(x) is not None}
                     for a, d in val.items() if isinstance(d, dict)}
            else:
                v = _why_num(val)
            if v is None or v == {}:
                continue
            cov = {str(a)[:40]: (int(b) if float(b).is_integer() else round(float(b), 3))
                   for a, b in (it.get("coverage") or {}).items()
                   if isinstance(b, (int, float)) and not isinstance(b, bool)} if isinstance(it.get("coverage"), dict) else {}
            keep[k] = {"value": v, "n_people": int(n) if isinstance(n, (int, float)) else None, "coverage": cov}
        if keep:
            out[str(pid)] = keep
    if not out:
        return None
    used = {k for r in out.values() for k in r}
    return {"as_of": str(j.get("as_of") or ""), "as_of_pt": _pt_label(str(j.get("as_of") or "")), "shadow": bool(j.get("shadow")),
            "items": {k: v for k, v in items.items() if k in used}, "launches": out}


# Nominal data cut of each point (PT, hours after midnight); a point counts as "not made" once its cut is 90 min past.
NOMINAL_CUT_H = {"0005": 0.08, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "R0": 4, "R1": 5, "R2": 6, "R4": 8}
BOARD_STALE_MIN = 35


def _capture_gaps(day: str) -> list[dict]:
    """Gaps of more than 30 min in the 15-min Product Hunt capture (raw/ph_at_launch/<day>/snapshots/<day>T<HHMM>PT_*)."""
    import re as _re
    ts = sorted({m.group(1) for n, _ in gcs.list_names(f"raw/ph_at_launch/{day}/snapshots/", ttl=120)
                 for m in [_re.search(r"T(\d{4})PT", n.rsplit("/", 1)[-1])] if m})
    mins = [int(t[:2]) * 60 + int(t[2:]) for t in ts]
    return [{"from_pt": f"{a // 60:02d}:{a % 60:02d} PT", "to_pt": f"{b // 60:02d}:{b % 60:02d} PT", "minutes": b - a}
            for a, b in zip(mins, mins[1:]) if b - a > 30]


def _freshness(day: str, fc: dict, board: dict, final: bool) -> dict:
    """What is missing or not updated, so the page can say so instead of breaking or looking current."""
    now = datetime.now(PT)
    is_today = day == now.strftime("%Y-%m-%d")
    midnight = datetime.fromisoformat(day).replace(tzinfo=PT)
    past = now - midnight
    missing = [k for k, h in NOMINAL_CUT_H.items() if k not in fc and (not is_today or past.total_seconds() > (h * 60 + 90) * 60)]
    out = {"missing_points": missing, "missing_labels": [dict((k, l) for k, l, _ in POINTS).get(k, k) for k in missing],
           "capture_gaps": [], "board_stale": False, "board_stale_label": ""}
    try:
        out["capture_gaps"] = _capture_gaps(day)
    except Exception as exc:  # noqa: BLE001 - a listing failure must not take the page down
        print(f"[ph] capture gap check failed: {exc!r}", flush=True)
    if is_today and not final:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(board.get("as_of")).replace("Z", "+00:00"))).total_seconds() / 60
        except (ValueError, TypeError):
            age = None
        if age is None or age > BOARD_STALE_MIN:
            out["board_stale"] = True
            out["board_stale_label"] = (f"not updated since {board.get('as_of_pt')}" if board.get("as_of_pt")
                                        else "no live reading yet today")
            # an open gap: the capture stopped and has not resumed
            if board.get("as_of_pt") and age is not None:
                out["capture_gaps"].append({"from_pt": board["as_of_pt"], "to_pt": None, "minutes": int(age)})
    return out


def day_view(day: str) -> dict:
    prods = _lineup(day)
    fc = forecasts(day)
    act = actuals(day)
    points = []
    for key, label, sees in POINTS:
        if key not in fc:
            continue
        f = fc[key]
        # 'Made' is when the file was actually written (not its data cut); show the date if written on a later day.
        made = _written_label(day, f.get("made_at")) or _pt_label(f.get("data_up_to"))
        cut = _pt_label(f.get("data_up_to"))
        score = None
        if act["final"]:
            score = {str(k): hits(f["ranks"], act["ranks"], k) for k in (3, 5, 10)}
        conf = _top3_confidence(f["ranks"], prods) if key == "0005" else (
            _prereveal_confidence(key, f) if key.startswith("P") and f.get("rank_field") == "pred_rank_best" else None)
        exp_err = None
        if f.get("exp_votes"):
            g = claims().get("exp_votes_error", {}).get("values", {})
            exp_err = g.get(key)
        late = False
        try:
            late = (datetime.fromisoformat(str(f.get("made_at")).replace("Z", "+00:00"))
                    - datetime.fromisoformat(str(f.get("data_up_to")).replace("Z", "+00:00"))).total_seconds() > (
                        30 if key == "0005" else 90) * 60
        except (ValueError, TypeError):
            pass
        points.append({"key": key, "label": label, "time_pt": made, "data_cut_pt": cut, "late": late, "top3_conf": conf,
                       "exp_votes": f.get("exp_votes"), "exp_err": exp_err, "made_at": f.get("made_at"),
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
    board = current_board(day) if not act["final"] else {"as_of": act["as_of"], "as_of_pt": _pt_label(act["as_of"] or ""),
                                                          "ranks": act["ranks"], "votes_hidden": False}
    for x in launches:
        b = board["ranks"].get(x["id"], {})
        x["board_rank"] = b.get("rank")
        x["board_votes"] = b.get("votes")
    difficulty = _difficulty(day)
    on_time = [p for p in points if not p.get("late")]
    lead = (on_time or points)[-1]["key"] if points else None
    lk = gcs.read_json(f"results/web/lock/{day}.json", ttl=120) if not act["final"] else None
    lock = None
    if isinstance(lk, dict) and lk.get("label_top3"):
        lock = {k: lk.get(k) for k in ("point", "read_at", "label_top3", "label_top5", "label_top10", "top3_locked",
                                       "top5_locked", "top2_locked", "top10_locked", "top3_first_locked_at", "rule")}
        lock["read_pt"] = _pt_label(lk.get("read_at") or "")
        lock.pop("rule", None)   # internal text; the page states the tested reliability instead
        # Interim (orchestrator / E5 audit, Nov 13): no sourced reliability-by-hour figure yet.
        lock["reliability"] = "checked against final ranks each day; no tested reliability figure is shown yet"
    fresh = _freshness(day, fc, board, act["final"])
    ids = set(prods)
    whys = {}
    for pt in [p["key"] for p in points] + (["after"] if act["final"] else []):
        try:
            w = why(day, pt, ids)
        except Exception as exc:  # noqa: BLE001 - explanations are optional; never take the page down
            print(f"[ph] why {pt} unavailable: {exc!r}", flush=True)
            w = None
        if w:
            whys[pt] = w
    return {"day": day, "today": today_pt(), "lineup_size": len(launches), "launches": launches, "points": points,
            "freshness": fresh, "why": whys,
            "lead_point": lead, "difficulty": difficulty, "board": {**{k: board[k] for k in ("as_of", "as_of_pt", "votes_hidden")}, "lock": lock},
            "status": {"final": act["final"], "revealed": act["revealed"], "as_of_pt": _written_label(day, act["as_of"]),
                       "as_of": act["as_of"]}}


SB_LABEL = {"0005": "00:05 PT launch model", "P1": "pre-reveal +1 h", "P2": "pre-reveal +2 h", "P3": "pre-reveal +3 h",
            "P4": "pre-reveal +4 h", "P0": "pre-reveal 00:45", "R0": "votes revealed", "R1": "reveal + 1 h", "R2": "reveal + 2 h", "R4": "reveal + 4 h"}
SB_METHOD = {"published": "", "comment_ridge": "comments", "api_rank": "PH order", "blend": "blend",
             "best": "best (shown)", "depth": "depth", "raw_votes": "votes"}


def track_record(max_days: int = 30) -> dict:
    """Prefer the PH agent's daily scoreboard (results/web/scoreboard.json); fall back to scoring the files here."""
    sb = gcs.read_json("results/web/scoreboard.json", ttl=600)
    if sb and sb.get("summary"):
        order = {k: i for i, k in enumerate(POINT_KEYS)}
        src_rank = {"live": 0, "late": 1, "replay": 2, "replay_in_sample": 3}
        rows = []
        for r in sb["summary"]:
            if r.get("source") == "shadow" or r.get("method") in ("makerfix_shadow", "unfixed_replay"):
                continue
            if str(r.get("point", "")).startswith("P") and r.get("method") not in ("best",):
                continue   # only the pre-reveal ranking the page shows
            m = SB_METHOD.get(r.get("method"), r.get("method", ""))
            rows.append({"key": r["point"], "label": SB_LABEL.get(r["point"], r["point"]) + (f" · {m}" if m else ""),
                         "source": r.get("source"), "n_days": r.get("days", 0),
                         "days_range": [r.get("first_day"), r.get("last_day")],
                         "top3": r.get("mean_top3"), "top5": r.get("mean_top5"), "top10": r.get("mean_top10"),
                         "experimental": "experimental" in m,
                         "picks": {k: r.get(f"{k}_count") for k in ("p1_top3", "p2_top3", "p3_top3", "exact1")
                                   if r.get(f"{k}_count")} or None,
                         # 95% day-bootstrap intervals, if the scoreboard carries them (NORTH_STAR shows them at 5+ days)
                         "ci": {k: r[c] for k in ("top3", "top5", "top10")
                                for c in (f"ci_{k}", f"ci95_{k}", f"{k}_ci") if c in r} or None})
        rows.sort(key=lambda r: (src_rank.get(r["source"], 9), order.get(r["key"], 99), r["experimental"], r["label"]))
        return {"rows": rows, "computed_at": sb.get("built_at"), "source": "results/web/scoreboard.json",
                "how": (sb.get("definition") or "") + ". Live = written in time; late = honest data cut but written "
                       "after the fact; replay = re-run afterwards on data up to the point time."}
    # No scoreboard -> no track record: the local fallback cannot tell live calls from late runs.
    return {"rows": [], "computed_at": None, "source": None, "unavailable": True,
            "how": "The track record is unavailable right now."}


def weekly() -> dict | None:
    ptr = gcs.read_json("results/web/weekly_latest.json", ttl=300) or {}
    pts = ptr.get("points") or {}
    # The reveal + 4 h call if it is the newest day, else the end-of-day standings (never the 03:45 estimate).
    # Preferred: Product Hunt's own running weekly rank (official, after the nightly ranks step). Otherwise our call
    # at reveal + 4 h if it is the newest day, else the end-of-day standings (never the 03:45 estimate).
    pick = pts.get("running") if isinstance(pts.get("running"), dict) and pts["running"].get("file") else None
    pick = pick or max((v for k, v in pts.items() if k in ("R4", "dayend") and isinstance(v, dict) and v.get("file")),
                       key=lambda v: (v.get("day") or "", v.get("written_at") or ""), default=None)
    if pick:
        names = [pick["file"]]
    else:
        names = sorted(n for n, _ in gcs.list_names("results/weekly_live/", ttl=300)
                       if n.endswith(".json") and not n.endswith("_est.json"))
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
    if j.get("point") == "running":
        for x in keep:
            x["est_votes"] = None          # running files carry -rank, not votes
    out = {"week_monday": j.get("week_monday"), "as_of_day": j.get("day"), "point": j.get("point"),
           "ratio": j.get("ratio"), "written_at": j.get("written_at"), "top": keep}
    try:
        out["month"] = monthly()
    except Exception as exc:  # noqa: BLE001 - the week still shows
        print(f"[ph] monthly unavailable: {exc!r}", flush=True)
        out["month"] = None
    return out


def monthly() -> dict | None:
    """Product Hunt's own running monthly rank (results/monthly_live/<month>_<day>_running.json), top 10."""
    names = sorted(n for n, _ in gcs.list_names("results/monthly_live/", ttl=300) if n.endswith("_running.json"))
    if not names:
        return None
    j = gcs.read_json(names[-1], ttl=300) or {}
    ids = [str(i) for i in (j.get("forecast_monthlyRank") or [])[:10]]
    day, month = str(j.get("day") or ""), str(j.get("month") or "")
    if not ids or not day.startswith(month):
        return None
    lookup: dict[str, dict] = {}
    d = datetime.fromisoformat(month + "-01")
    while d.strftime("%Y-%m-%d") <= day:
        lookup.update(_lineup(d.strftime("%Y-%m-%d")))
        d += timedelta(days=1)
    slugs: dict[str, str] = {}
    if any(i not in lookup for i in ids):
        # Launches missing from the nightly line-up files: take the product slug from the official monthly re-read.
        rr = sorted(n for n, _ in gcs.list_names(f"raw/ph_at_launch/monthly_reread/{month}/", ttl=600) if n.endswith(".jsonl"))
        for r in (gcs.read_jsonl(rr[-1], ttl=600) if rr else []):
            if str(r.get("id")) in ids and r.get("slug"):
                slugs[str(r["id"])] = str(r["slug"])
    pretty = lambda sl: " ".join(w.capitalize() for w in re.sub(r"-\d+$", "", sl).split("-")) if sl else None
    top = [{"id": i, "rank": n, "name": lookup.get(i, {}).get("name") or pretty(slugs.get(i)),
            "slug": lookup.get(i, {}).get("slug") or slugs.get(i)} for n, i in enumerate(ids, 1)]
    return {"month": month, "as_of_day": day, "written_at": j.get("written_at"), "top": top}
