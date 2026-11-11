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
        "gemini_calls_per_run": 2, "embedding_calls_per_run": 2, "max_output_tokens_per_run": 6000}
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


def _interest_people(tok: str) -> dict:
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


async def step_people(tok: str) -> dict:
    """Interest-segment match (13.6k profiles, category level) + E5's similar-tools scorer (5,096 people, AUC 0.69)."""
    from mvp.ph_site import person_e5

    a = verify(tok)["a"]
    out = _interest_people(tok)
    out["interest_top"] = out.pop("top_people")
    try:
        B = person_e5.bundle()
        text = f"{a.get('name')}. {a.get('tagline')}. {a.get('summary') or ''} {(a.get('page_excerpt') or '')[:700]}"
        q = await person_e5.embed(text)
        sm = person_e5.summarize(B, person_e5.score_text(B, q))
        out["similar"] = {**{k: sm[k] for k in ("people_scored", "likely_count", "likely_share", "segments", "tiers")},
                          "typical_share": 0.01,
                          "method": ("Similar-tools match: each person's own tool stack, reviews and collections are "
                                     "compared with this page (Gemini embeddings + a learned scorer). Person-level "
                                     "accuracy: ranks a person's real tools above look-alike non-uses 69% of the time. "
                                     "By design about 1% of people match a typical product.")}
        out["top_people"] = [{"label": f"User {chr(65 + i)}", **p} for i, p in enumerate(sm["people"])]
    except Exception as exc:  # noqa: BLE001 - fall back to the interest index alone
        print(f"[try] similar-tools scorer unavailable: {exc!r}", flush=True)
        out["similar"] = None
        out["top_people"] = [{"label": p["label"], "roles": [p["role"]], "tier": p["activity"], "strength": "interest match",
                              "likely": True} for p in out["interest_top"]]
    return out


def _types_from_people(p: dict, topics: list[str]) -> list[str]:
    out = []
    for r in p["top_people"][:4]:
        out.append(f"{r['label']}: {' / '.join(r['roles'])}, {r['tier']}, interested in {', '.join(topics[:2]) or 'this category'}")
    # Contrast types so it isn't only fans.
    out.append("User E: heavy PH voter who comments often and sees dozens of similar launches a week")
    out.append("User F: maker from an unrelated category, browsing the day's launches")
    return out


async def step_reactions(tok: str) -> dict:
    from capability.gemini_config import extract_json, gemini_chat

    a = verify(tok)["a"]
    p = await step_people(tok)
    types = _types_from_people(p, a.get("topics") or [])
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

def _band_score(lb: dict, name: str, tagline: str, description: str, topics: list[str]) -> float:
    """PH ops' product-only ridge (results/web/launch_band.json `recipe`): TF-IDF + topic flags + lengths -> ln(1+votes)."""
    import re as _re
    text = (f"{name}. {tagline}. {description} " + " ".join(topics)).lower()
    toks = _re.findall(r"\b[a-z0-9]+\b", text)
    counts: dict[str, int] = {}
    for t in toks + [a + " " + b for a, b in zip(toks, toks[1:])]:
        if t in lb["vocab"]:
            counts[t] = counts.get(t, 0) + 1
    x = {t: (1 + math.log(c)) * lb["vocab"][t][0] for t, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in x.values())) or 1.0
    score = lb["intercept"] + sum(lb["vocab"][t][1] * v / norm for t, v in x.items())
    dense = [1.0 if t in topics else 0.0 for t in lb["topics_order"]]
    dense += [math.log1p(len(description)), math.log1p(len(tagline)), float(len(topics))]
    for v, m, sd, c in zip(dense, lb["dense_mean"], lb["dense_sd"], lb["dense_coef"]):
        score += c * (v - m) / (sd or 1.0)
    return score


def step_launch(tok: str) -> dict:
    a = verify(tok)["a"]
    lb = gcs.read_json("results/web/launch_band.json", ttl=3600)
    if not lb:
        raise RuntimeError("launch band missing")
    desc = (a.get("summary") or "") + " " + (a.get("page_excerpt") or "")[:600]
    score = _band_score(lb, a.get("name") or "", a.get("tagline") or "", desc, a.get("topics") or [])
    pct = sum(1 for c in lb["score_percentile_cuts"] if c < score)
    b = lb["bands"][min(9, pct // 10)]
    rk, vt = b["daily_rank_p10_p50_p90"], b["votes_p10_p50_p90"]
    acc = lb["heldout_accuracy"]
    return {"percentile": pct, "decile": b["decile"],
            "rank_band": {"likely": [int(rk[0]), int(rk[2])], "median": int(rk[1])},
            "votes_band": {"likely": [int(vt[0]), int(vt[2])], "median": int(vt[1])},
            "share_top3": b["share_top3"], "share_top10": b["share_top10"], "similar_launches": b["n"],
            "accuracy": {"days": acc["days"], "top3": acc["top3"], "top5": acc["top5"], "top10": acc["top10"],
                         "spearman": acc["within_day_spearman"],
                         "full_model": {k: acc["reference_full_launch_model_honest"][k] for k in ("top3", "top5", "top10")}},
            "assumed": {"hunter": "population median (unknown)", "maker history": "population median (unknown)",
                        "team ties / audience": "population median (unknown)", "launch day": "a typical day's line-up"},
            "method": (f"Percentile band from the page alone: a text model trained on {lb['trained_on']['launches']:,} "
                       f"featured launches ({lb['trained_on']['days'][0]} to {lb['trained_on']['days'][1]}) scores "
                       f"this page above {pct}% of them. The ranges are where launches in that tenth actually finished "
                       "(10th to 90th percentile)."),
            "honesty": _honesty(acc)}


def _honesty(acc: dict) -> str:
    rec = ""
    try:
        from mvp.ph_site import live
        row = next(r for r in live.track_record()["rows"] if r["key"] == "0005" and r.get("source", "live") == "live")
        if row["n_days"]:
            rec = (f" Our deployed 00:05 PT launch model, which also knows the hunter, makers and team history, "
                   f"scores {row['top3']:.0f} / {row['top5']:.0f} / {row['top10']:.0f} live over {row['n_days']} days.")
    except Exception:  # noqa: BLE001
        pass
    return (f"Pre-launch rank prediction is weak, and weaker still from a page alone. Tested month-forward on "
            f"{acc['days']} days, this page-only model put {acc['top3']:.0f}% / {acc['top5']:.0f}% / "
            f"{acc['top10']:.0f}% of the real top 3 / 5 / 10 in its own top 3 / 5 / 10." + rec +
            " Who hunts it and who shows up on the day decide most of the result.")
