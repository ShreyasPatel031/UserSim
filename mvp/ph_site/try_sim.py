"""Try-a-product-URL simulation, split into short stateless steps so each fits a serverless request and the page can
show progress:  page (fetch + Gemini read)  ->  people (no LLM)  |  reactions (Gemini)  |  launch (no LLM).

The page step returns a signed token holding the product analysis; later steps accept only that token, so they cost
nothing extra to abuse and cannot be pointed at arbitrary input. Caps (stated on the page):
  per IP: 3 runs / hour, 10 / day;  everyone: 150 runs / day;  per run: 2 Gemini calls (flash-lite), ~6k output tokens.
Person data comes only from site/person_index_v1 (no identifiers). Labels "User A".. are assigned per response.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from mvp.ph_site import gcs

PT = ZoneInfo("America/Los_Angeles")
CAPS = {"per_ip_hour": int(os.environ.get("TRY_PER_IP_HOUR", "3")),
        "per_ip_day": int(os.environ.get("TRY_PER_IP_DAY", "10")),
        "global_day": int(os.environ.get("TRY_GLOBAL_DAY", "150")),
        "gemini_calls_per_run": 2, "max_output_tokens_per_run": 6000}
MODEL = os.environ.get("TRY_GEMINI_MODEL", "gemini-2.5-flash-lite")
TOKEN_TTL_S = 900


# ---------- signing / limits ----------

def _key() -> bytes:
    k = os.environ.get("TRY_SIGNING_KEY")
    if k:
        return k.encode()
    # Derive from the service credentials present on the server (never sent anywhere).
    seed = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64") or os.environ.get("VERTEX_ADC_JSON")
            or os.environ.get("GOOGLE_ADC_JSON") or "atelier-dev-only")
    return hashlib.sha256(("try-sign:" + seed).encode()).digest()


def sign(obj: dict) -> str:
    raw = json.dumps({**obj, "exp": int(time.time()) + TOKEN_TTL_S}, separators=(",", ":")).encode()
    mac = hmac.new(_key(), raw, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(raw).decode() + "." + base64.urlsafe_b64encode(mac).decode()


def verify(tok: str) -> dict:
    try:
        a, b = tok.split(".")
        raw = base64.urlsafe_b64decode(a)
        if not hmac.compare_digest(base64.urlsafe_b64decode(b), hmac.new(_key(), raw, hashlib.sha256).digest()[:16]):
            raise ValueError
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise PermissionError("Invalid or expired run token; start again.") from exc
    if obj.get("exp", 0) < time.time():
        raise PermissionError("This run expired; start again.")
    return obj


def _ip_hash(ip: str) -> str:
    return hashlib.sha256(_key() + ip.encode()).hexdigest()[:16]   # IPs are never stored in clear


_mem: dict[str, list[float]] = {}


def take_slot(ip: str) -> dict:
    """Count one run; raise PermissionError when a cap is hit. GCS counter (shared by all instances) + local fallback."""
    day = datetime.now(PT).strftime("%Y-%m-%d")
    h = _ip_hash(ip)
    now = time.time()

    def upd(cur):
        cur.setdefault("total", 0)
        cur.setdefault("ips", {})
        ts = [t for t in cur["ips"].get(h, []) if now - t < 86400]
        if cur["total"] >= CAPS["global_day"]:
            raise PermissionError(f"Today's limit of {CAPS['global_day']} simulations for everyone is used up. Try tomorrow.")
        if len(ts) >= CAPS["per_ip_day"]:
            raise PermissionError(f"Limit of {CAPS['per_ip_day']} simulations per day reached.")
        if sum(1 for t in ts if now - t < 3600) >= CAPS["per_ip_hour"]:
            raise PermissionError(f"Limit of {CAPS['per_ip_hour']} simulations per hour reached. Try again later.")
        cur["ips"][h] = ts + [now]
        cur["total"] += 1
        return cur

    if os.environ.get("TRY_LOCAL_LIMITS") == "1":
        cur = upd({"total": len(_mem.get("_all", [])), "ips": {h: _mem.get(h, [])}})
        _mem[h] = cur["ips"][h]
        _mem.setdefault("_all", []).append(now)
        return {"used_today": cur["total"]}
    cur = gcs.write_json_cas(f"site/try_usage/{day}.json", upd)
    return {"used_today": cur["total"]}


# ---------- person index ----------

_IDX: dict = {}


def index() -> dict:
    if not _IDX:
        import io
        raw = gcs.read_bytes("site/person_index_v1.npz", ttl=86400)
        meta = gcs.read_json("site/person_index_v1.json", ttl=86400)
        if raw is None or meta is None:
            raise RuntimeError("person index missing")
        z = np.load(io.BytesIO(raw))
        X = z["X"].astype(np.float32)
        _IDX.update(meta=meta, X=X, Xn=X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9), act=z["act"],
                    cmt=z["cmt"], maker=z["maker"], seg=z["seg"])
    return _IDX


# ---------- step 1: page ----------

READ_PROMPT = """You read a product's own web page and describe it for a Product Hunt launch simulation.
Use ONLY the page content below. If the page is empty, a login wall, or not a product, say so in "problem".

URL: {url}
TITLE: {title}
META DESCRIPTION: {desc}
PAGE TEXT:
{text}
PRICING PAGE (may be empty):
{pricing}

Allowed Product Hunt topics (choose 1-4, most specific first, exact spelling): {vocab}

Return JSON:
{{"problem": "" or short reason the page can't be judged,
 "name": "product name", "tagline": "<= 60 chars, Product Hunt style",
 "summary": "2 sentences: what it does and for whom",
 "topics": ["..."],
 "audience": "who it is for, 1 short phrase",
 "pricing": "free | freemium | paid | unknown",
 "strengths": ["up to 3 things a PH visitor would like, from the page"],
 "doubts": ["up to 3 things a PH visitor would question, from the page"],
 "clarity": 1-5 (how quickly a visitor understands what it does)}}"""


async def step_page(url: str, ip: str) -> dict:
    from capability.gemini_config import extract_json, gemini_chat
    from mvp.ph_site import safe_fetch

    norm = await safe_fetch.check_url(url)        # validate before spending a slot
    usage = take_slot(ip)
    page = await safe_fetch.fetch_product(norm)
    if len((page["text"] or "").strip()) < 80:
        raise ValueError("That page has almost no readable text (it may need JavaScript or a login). Try the product's main marketing page.")
    vocab = index()["meta"]["vocab"]
    prompt = READ_PROMPT.format(url=page["url"], title=page["title"], desc=page["description"],
                                text=page["text"][:9000], pricing=page["pricing_text"][:2500], vocab=", ".join(vocab))
    raw = await gemini_chat([{"role": "user", "content": prompt}], model=MODEL, temperature=0.2, max_retries=3)
    a = extract_json(raw)
    if a.get("problem"):
        raise ValueError("Couldn't judge this page: " + str(a["problem"])[:200])
    a["topics"] = [t for t in (a.get("topics") or []) if t in vocab][:4] or ["Productivity"]
    a = {k: a.get(k) for k in ("name", "tagline", "summary", "topics", "audience", "pricing", "strengths", "doubts", "clarity")}
    a["url"] = page["url"]
    a["page_excerpt"] = (page["description"] + "\n" + page["text"])[:2500]
    return {"analysis": {k: v for k, v in a.items() if k != "page_excerpt"}, "token": sign({"a": a}),
            "caps": CAPS, "used_today": usage["used_today"]}


# ---------- step 2: people (no LLM) ----------

def _qvec(topics: list[str], vocab: list[str]) -> np.ndarray:
    q = np.zeros(len(vocab), np.float32)
    for i, t in enumerate(topics):
        if t in vocab:
            q[vocab.index(t)] += 1.0 / (1 + 0.5 * i)    # first topic weighs most
    return q / (np.linalg.norm(q) + 1e-9)


def _describe(meta: dict, x: np.ndarray, act: int, cmt: int, maker: bool, seg: int) -> dict:
    vocab = meta["vocab"]
    top = [vocab[i] for i in np.argsort(-x)[:3] if x[i] > 0.05]
    s = meta["segments"][int(seg)]
    role = "maker (has launched or hunted on PH)" if maker else "voter / user"
    return {"role": role, "activity": meta["act_bands"][int(act)], "comments": meta["cmt_bands"][int(cmt)],
            "interests": top, "segment": s["name"],
            "upvoted_like": f"Mostly upvotes {', '.join(top[:2]) or 'a mix of categories'} launches"}


def step_people(tok: str) -> dict:
    a = verify(tok)["a"]
    I = index()
    meta = I["meta"]
    q = _qvec(a["topics"], meta["vocab"])
    s = I["Xn"] @ q
    # Small activity prior so a person with one matching upvote doesn't outrank a regular in that category.
    score = s * (0.85 + 0.05 * I["act"])
    n = len(score)
    thr = float(np.quantile(score, 0.9))
    likely = score >= max(thr, 1e-6)
    # Closest matches, but at most one per (segment, maker, activity band), so the list shows distinct kinds of people.
    top, seen = [], set()
    for j in np.argsort(-score)[:3000]:
        key = (int(I["seg"][j]), bool(I["maker"][j]), int(I["act"][j]))
        if key in seen:
            continue
        seen.add(key)
        top.append(j)
        if len(top) == 8:
            break
    people = []
    for k, j in enumerate(top):
        d = _describe(meta, I["X"][j], I["act"][j], I["cmt"][j], bool(I["maker"][j]), I["seg"][j])
        people.append({"label": f"User {chr(65 + k)}", "match": round(float(s[j]), 2), **d})
    segs = []
    base = likely.mean()
    for sg in meta["segments"]:
        m = I["seg"] == sg["id"]
        nl = int((likely & m).sum())
        if nl < 20:
            continue
        share = nl / m.sum()
        segs.append({"name": sg["name"], "top_topics": sg["top_topics"], "size": int(m.sum()), "likely": nl,
                     "share": round(float(share), 3), "lift": round(float(share / (base + 1e-9)), 2),
                     "maker_share": sg["maker_share"]})
    segs.sort(key=lambda r: -r["lift"])
    tiers = []
    for b, name in enumerate(meta["act_bands"]):
        m = I["act"] == b
        if (likely & m).sum() >= 20:
            tiers.append({"tier": name, "share": round(float((likely & m).sum() / m.sum()), 3)})
    makers = I["maker"]
    return {"people_scored": int(n), "likely_count": int(likely.sum()), "likely_share": round(float(likely.mean()), 3),
            "top_people": people, "segments": segs[:5], "tiers": tiers,
            "maker_share_of_likely": round(float(makers[likely].mean()), 3) if likely.any() else None,
            "method": ("Category-interest match: each person's share of past upvotes/comments/launches per PH topic "
                       "vs this product's topics. People are real complete PH profiles with every identifier removed; "
                       "descriptors are category-level and banded."),
            "note": f"Based on {n:,} public Product Hunt profiles; matching is approximate (who it resonates with, "
                    "not who will use it). Segments shown only where 20 or more people back them."}


# ---------- step 3: reactions (Gemini) ----------

REACT_PROMPT = """Simulate Product Hunt launch-day reactions to a product from distinct kinds of PH members.
Product (from its own page): {name} - {tagline}
Summary: {summary}
Pricing: {pricing}. Page strengths: {strengths}. Page doubts: {doubts}.
Page excerpt:
{excerpt}

Write one reaction for each member type below. Each is a TYPE of person drawn from real PH activity patterns (not a
real individual). Stay grounded in the page: do not invent features. Mix enthusiasm and skepticism realistically; most
PH comments are short, specific, and some are questions to the maker. Never use real names or @handles.

Member types:
{types}

Return JSON: {{"reactions": [{{"type": "<copy the type label>", "comment": "1-3 sentences as they'd write on PH",
"sentiment": "positive|mixed|skeptical", "would_upvote": 0-100, "would_try": 0-100, "why": "one short reason"}}],
"headline_takeaway": "one sentence: what PH visitors are most likely to say overall"}}"""


def _types_from_people(p: dict) -> list[str]:
    out = []
    for r in p["top_people"][:4]:
        out.append(f"{r['label']}: {r['role']}, {r['activity']}, {r['comments']}, interests: {', '.join(r['interests'])}")
    # Plus contrast types so it isn't only fans.
    out.append("User E: voter / user, very heavy (400+), comments often, interests: Artificial Intelligence, Productivity "
               "(sees dozens of similar launches a week)")
    out.append("User F: maker (has launched or hunted on PH), regular (20-99), comments sometimes, interests outside this "
               "product's category")
    return out


async def step_reactions(tok: str) -> dict:
    from capability.gemini_config import extract_json, gemini_chat

    a = verify(tok)["a"]
    p = step_people(tok)
    types = _types_from_people(p)
    prompt = REACT_PROMPT.format(name=a.get("name"), tagline=a.get("tagline"), summary=a.get("summary"),
                                 pricing=a.get("pricing"), strengths="; ".join(a.get("strengths") or []),
                                 doubts="; ".join(a.get("doubts") or []), excerpt=(a.get("page_excerpt") or "")[:2500],
                                 types="\n".join(types))
    raw = await gemini_chat([{"role": "user", "content": prompt}], model=MODEL, temperature=0.7, max_retries=3)
    j = extract_json(raw)
    reacts = []
    for r in (j.get("reactions") or [])[:6]:
        reacts.append({k: r.get(k) for k in ("type", "comment", "sentiment", "would_upvote", "would_try", "why")})
    return {"reactions": reacts, "types": types, "headline": j.get("headline_takeaway", ""),
            "note": "Simulated by Gemini from the page text, voiced as member types built from real PH activity patterns. "
                    "Not real comments."}


# ---------- step 4: launch (no LLM) ----------

def step_launch(tok: str) -> dict:
    a = verify(tok)["a"]
    meta = index()["meta"]
    tr = meta["topic_rank"]
    ws, pct, votes = [], [], []
    for i, t in enumerate(a.get("topics") or []):
        st = tr.get(t)
        if st:
            w = 1.0 / (1 + i)
            ws.append(w); pct.append(np.array(st["pct"])); votes.append(np.array(st["votes"]))
    if not ws:
        st = tr["_all"]; ws, pct, votes = [1.0], [np.array(st["pct"])], [np.array(st["votes"])]
    w = np.array(ws) / sum(ws)
    P = (w[:, None] * np.stack(pct)).sum(0)      # quantiles 10/25/50/75/90 of rank as share of line-up
    V = (w[:, None] * np.stack(votes)).sum(0)
    L = meta["lineup_recent60"]["median"]
    r = lambda x: max(1, int(math.ceil(x * L)))
    return {"lineup_typical": int(L),
            "rank_band": {"likely": [r(P[1]), r(P[3])], "wide": [r(P[0]), r(P[4])], "median": r(P[2])},
            "votes_band": {"likely": [int(V[1]), int(V[3])], "wide": [int(V[0]), int(V[4])], "median": int(V[2])},
            "assumed": {"hunter": "population median (unknown)", "maker history": "population median (unknown)",
                        "team ties / audience": "population median (unknown)", "launch day": "a typical day"},
            "method": (f"Where featured launches in the same PH topics finished on {meta['days']} launch days "
                       f"({meta['day_range'][0]} to {meta['day_range'][1]}), with everything we can't know about your "
                       "launch (hunter, maker history, team ties, audience) at the population median. On a typical "
                       f"day of {int(L)} featured launches."),
            "honesty": _honesty()}


def _honesty() -> str:
    rec = ""
    try:
        from mvp.ph_site import live
        row = next(r for r in live.track_record()["rows"] if r["key"] == "0005")
        if row["n_days"]:
            rec = (f" Scored live so far ({row['n_days']} days), it puts {row['top3']}% of the real top 3 and "
                   f"{row['top10']}% of the real top 10 in its own top 3 / top 10.")
    except Exception:  # noqa: BLE001
        pass
    return ("Pre-launch rank prediction is weak. Our deployed 00:05 PT launch model knows the hunter, makers and team "
            "history and still misses often." + rec + " From a page alone, the band below is close to the base rate: "
            "who hunts it and who shows up on the day decide most of the result.")
