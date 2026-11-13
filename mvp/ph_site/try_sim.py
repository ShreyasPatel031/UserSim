"""Try-a-product-URL simulation, split into short stateless steps so each fits a serverless request and the page can
show progress:  page (fetch + Gemini read)  ->  people (no LLM)  |  reactions (Gemini)  |  launch (no LLM).

The page step stores the analysis server-side (site/try_runs/<day>/<run id>.json) and returns a signed run id; later
steps accept only that id and each LLM step can be spent once, so tokens cannot be replayed or forged into extra calls. Caps (stated on the page):
  per IP: 3 runs / hour, 10 / day;  everyone: 150 runs / day;  per run: 2 Gemini calls (flash-lite page read and
  2.5-flash reactions, output capped at 1.5k + 3k tokens) and 2 embedding calls. Each LLM step can run once per run (enforced server-side by run id).
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
        "gemini_calls_per_run": 5, "gemini_calls_max_per_run": 8, "embedding_calls_per_run": 5, "max_output_tokens_per_run": 8800}
MODEL = os.environ.get("TRY_GEMINI_MODEL", "gemini-2.5-flash-lite")
TOKEN_TTL_S = 900


# ---------- signing / limits ----------

class NotConfigured(RuntimeError):
    pass


class BadToken(PermissionError):
    pass


def _on_server() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))


def _local_limits() -> bool:
    # In-memory limits are for local runs only; never honoured on the deployed site.
    return os.environ.get("TRY_LOCAL_LIMITS") == "1" and not _on_server()


def _key() -> bytes:
    """HMAC key for run tokens. Fails closed: no key, no runs (never a constant or a derived fallback)."""
    k = os.environ.get("TRY_SIGNING_KEY", "")
    if len(k) < 32:
        raise NotConfigured("The simulator is not configured on this server yet (TRY_SIGNING_KEY).")
    return k.encode()


def sign(obj: dict) -> str:
    raw = json.dumps({**obj, "exp": int(time.time()) + TOKEN_TTL_S}, separators=(",", ":")).encode()
    mac = hmac.new(_key(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode() + "." + base64.urlsafe_b64encode(mac).decode()


def verify(tok: str) -> dict:
    key = _key()
    try:
        a, b = str(tok).split(".")
        raw = base64.urlsafe_b64decode(a)
        if not hmac.compare_digest(base64.urlsafe_b64decode(b), hmac.new(key, raw, hashlib.sha256).digest()):
            raise ValueError
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise BadToken("Invalid or expired run token; start again.") from exc
    if not isinstance(obj, dict) or obj.get("exp", 0) < time.time():
        raise BadToken("This run expired; start again.")
    return obj


def _ip_hash(ip: str) -> str:
    return hmac.new(_key(), ("ip:" + ip).encode(), hashlib.sha256).hexdigest()[:16]   # IPs never stored in clear


_mem: dict[str, list[float]] = {}
_runs_mem: dict[str, dict] = {}
STEP_USES = {"people": 1, "reactions": 1, "asks": 1, "launch": 3}   # LLM/embedding steps once per run; launch is free (no LLM)


def take_slot(ip: str) -> dict:
    """Count one run; raise PermissionError when a cap is hit. GCS counter (shared by all instances)."""
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

    if _local_limits():
        cur = upd({"total": len(_mem.get("_all", [])), "ips": {h: _mem.get(h, [])}})
        _mem[h] = cur["ips"][h]
        _mem.setdefault("_all", []).append(now)
        return {"used_today": cur["total"]}
    cur = gcs.write_json_cas(f"site/try_usage/{day}.json", upd)
    return {"used_today": cur["total"]}


def refund_slot(ip: str) -> None:
    """Undo the last take_slot for this visitor (the run failed before spending anything)."""
    day = datetime.now(PT).strftime("%Y-%m-%d")
    h = _ip_hash(ip)

    def upd(cur):
        ts = cur.get("ips", {}).get(h, [])
        if ts:
            cur["ips"][h] = ts[:-1]
            cur["total"] = max(0, int(cur.get("total", 0)) - 1)
        return cur

    if _local_limits():
        if _mem.get(h):
            _mem[h] = _mem[h][:-1]
        if _mem.get("_all"):
            _mem["_all"] = _mem["_all"][:-1]
        return
    gcs.write_json_cas(f"site/try_usage/{day}.json", upd)


def _run_path(day: str, jti: str) -> str:
    return f"site/try_runs/{day}/{jti}.json"


def new_run(analysis: dict) -> str:
    """Store the run's analysis (incl. page excerpt) server-side; the client only gets a signed run id."""
    import secrets as _secrets
    jti = _secrets.token_urlsafe(16)
    day = datetime.now(PT).strftime("%Y-%m-%d")
    rec = {"a": analysis, "uses": {}, "created": time.time()}
    if _local_limits():
        _runs_mem[jti] = rec
    else:
        gcs.write_json_cas(_run_path(day, jti), lambda cur: rec)
    return sign({"jti": jti, "d": day})


def use_run(tok: str, step: str) -> dict:
    """Verify the token and spend one use of `step` for this run (at most STEP_USES[step]). Returns the analysis."""
    t = verify(tok)
    jti, day = str(t.get("jti", "")), str(t.get("d", ""))
    if not jti or not day:
        raise BadToken("Invalid run token; start again.")
    cap = STEP_USES.get(step, 0)

    def upd(cur):
        if not cur or "a" not in cur:
            raise PermissionError("This run expired; start again.")
        n = int(cur.get("uses", {}).get(step, 0))
        if n >= cap:
            raise PermissionError("This step already ran for this simulation; start a new one.")
        cur.setdefault("uses", {})[step] = n + 1
        return cur

    if _local_limits():
        rec = upd(_runs_mem.get(jti))
    else:
        rec = gcs.write_json_cas(_run_path(day, jti), upd)
    return rec["a"]


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


async def _analyze(page: dict, ip: str, source: str, fetch=None, fallback=None) -> dict:
    """Shared by page reads and pasted descriptions: (optional fetch) -> Gemini read -> stored run."""
    from capability.gemini_config import extract_json, gemini_chat

    usage = take_slot(ip)
    stage = "fetch"
    try:
        if fetch is not None:
            page = await fetch()
        if len((page["text"] or "").strip()) < 80:
            raise ValueError("That page has almost no readable text (it may need JavaScript or a login).")
        vocab = index()["meta"]["vocab"]
        prompt = READ_PROMPT.format(url=page["url"] or "(description pasted by the visitor)", title=page["title"],
                                    desc=page["description"], text=page["text"][:9000],
                                    pricing=page["pricing_text"][:2500], vocab=", ".join(vocab))
        stage = "gemini"
        raw = await gemini_chat([{"role": "user", "content": prompt}], model=MODEL, temperature=0.0, max_retries=3,
                                max_output_tokens=1500)
        stage = "judged"
        a = extract_json(raw)
        if a.get("problem") and fallback is not None:
            # e.g. a docs or code page: judge the site's home page once instead (one extra read, same slot)
            alt = await fallback()
            if alt is not None and len((alt["text"] or "").strip()) >= 80:
                page = alt
                prompt = READ_PROMPT.format(url=page["url"], title=page["title"], desc=page["description"],
                                            text=page["text"][:9000], pricing=page["pricing_text"][:2500],
                                            vocab=", ".join(vocab))
                raw = await gemini_chat([{"role": "user", "content": prompt}], model=MODEL, temperature=0.0,
                                        max_retries=3, max_output_tokens=1500)
                a = extract_json(raw)
        if a.get("problem"):
            raise ValueError("Couldn't judge this page: " + str(a["problem"])[:200])
        a["topics"] = [t for t in (a.get("topics") or []) if t in vocab][:4] or ["Productivity"]
        a = {k: a.get(k) for k in ("name", "tagline", "summary", "topics", "audience", "pricing", "strengths", "doubts", "clarity")}
        a["url"] = page["url"]
        a["source"] = source
        if source == "pasted":
            # Keep the visitor's own words: this is the input the launch band and reactions were measured on.
            a["name"] = page["title"] or a.get("name")
            a["tagline"] = page["description"] or a.get("tagline")
            a["ph_description"] = page["text"][:1200]
            a["page_excerpt"] = (page["description"] + "\n" + page["text"])[:2500]
        else:
            a["page_excerpt"] = (page["description"] + "\n" + page["text"])[:2500]
        stage = "store"
        tok = new_run(a)
    except Exception:
        # Give the run back when nothing was spent (fetch failed) or when our own storage failed. A page that reached
        # Gemini keeps its slot, so failing pages can't be used to buy unlimited model calls.
        if stage in ("fetch", "store"):
            try:
                refund_slot(ip)
            except Exception:  # noqa: BLE001
                pass
        raise
    return {"analysis": {k: v for k, v in a.items() if k not in ("page_excerpt", "ph_description")}, "token": tok,
            "caps": CAPS, "used_today": usage["used_today"]}


async def step_page(url: str, ip: str) -> dict:
    from urllib.parse import urlsplit
    from mvp.ph_site import safe_fetch

    norm = await safe_fetch.check_url(url)        # validate before spending a slot
    parts = urlsplit(norm)
    root = f"{parts.scheme}://{parts.netloc}/"

    async def fetch():
        # A deep link (docs, a code page, a JS-only route) often fails where the site's home page works:
        # retry the root once before giving up (E5: recovers about 1 in 4 failures).
        try:
            page = await safe_fetch.fetch_product(norm)
            if len((page["text"] or "").strip()) >= 80 or norm.rstrip("/") == root.rstrip("/"):
                return page
        except safe_fetch.FetchError:
            if norm.rstrip("/") == root.rstrip("/"):
                raise
        return await safe_fetch.fetch_product(root)

    async def root_page():
        if norm.rstrip("/") == root.rstrip("/"):
            return None
        try:
            return await safe_fetch.fetch_product(root)
        except safe_fetch.FetchError:
            return None

    return await _analyze({}, ip, "page", fetch=fetch, fallback=root_page)


async def step_text(name: str, tagline: str, description: str, ip: str) -> dict:
    """Fallback when a page can't be fetched: the visitor pastes a PH-style name, tagline and description."""
    name, tagline, description = (" ".join(str(x or "").split()) for x in (name, tagline, description))
    if not (1 <= len(name) <= 80):
        raise ValueError("Give the product's name (up to 80 characters).")
    if not (1 <= len(tagline) <= 140):
        raise ValueError("Give a one-line tagline (up to 140 characters).")
    if not (80 <= len(description) <= 2000):
        raise ValueError("Give a description of 80 to 2,000 characters, like a Product Hunt launch description.")
    page = {"url": "", "title": name, "description": tagline, "text": description, "pricing_text": ""}
    return await _analyze(page, ip, "pasted")


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


def _interest_people(a: dict) -> dict:
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
            "note": (f"Based on {n:,} public Product Hunt profiles. These are types of members whose past Product Hunt "
                     "activity centres on this category: they show who the product resembles, not who will vote for it "
                     "or use it. On launch day, votes come mostly from the most active members. " +
                     " Segments shown only where 20 or more people back them.")}


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

    a = use_run(tok, "people")
    out = _interest_people(a)
    out.pop("top_people", None)   # per-person interest rows are not shown (no k-anonymity floor); segments are
    try:
        B = person_e5.bundle()
        text = (f"{a.get('name')}. {a.get('tagline')}. {a['ph_description'][:1100]}" if a.get("ph_description") else
                f"{a.get('name')}. {a.get('tagline')}. {a.get('summary') or ''} {(a.get('page_excerpt') or '')[:700]}")
        q = await person_e5.embed(text)
        sm = person_e5.summarize(B, person_e5.score_text(B, q))
        from mvp.ph_site.live import claims
        c = claims()["similar_tools_auc"]
        out["similar"] = {**{k: sm[k] for k in ("people_scored", "likely_count", "likely_share", "segments", "tiers")},
                          "typical_share": c["values"]["typical_likely_share"],
                          "method": ("Similar-tools match: each person's own tool stack, reviews and collections are "
                                     "compared with this page (Gemini embeddings + a learned scorer). Fixed offline "
                                     f"figure ({c['label']}, {c['date']}): it ranks a person's real tools above look-alike "
                                     f"non-uses {c['values']['auc']:.0%} of the time. By design about "
                                     f"{c['values']['typical_likely_share']:.0%} of people match a typical product.")}
        out["top_people"] = [{"label": f"User {chr(65 + i)}", **p} for i, p in enumerate(sm["people"])]
        v = claims()["matches_vs_voting"]
        out["voting_note"] = (f"Matches are people whose tools and interests resemble this product. Fixed offline figure "
                              f"({v['label']}, {v['date']}): they were no more likely to upvote than members with similar "
                              f"activity ({v['values']['top_match_upvote_rate']:.2%} vs "
                              f"{v['values']['activity_matched_rate']:.2%}), so this shows who it resonates with, not "
                              "who will vote.")
    except Exception as exc:  # noqa: BLE001 - fall back to the interest segments alone
        print(f"[try] similar-tools scorer unavailable: {exc!r}", flush=True)
        out["similar"] = None
        out["top_people"] = []
    return out


def _reactions_note(grounded: bool = True, source: str | None = None) -> str:
    from mvp.ph_site.live import claims
    cl = claims()
    c, ps = cl["reactions_eval"], cl.get("person_sim")
    v = c["values"]
    person = ""
    if ps:
        pv = ps["values"]
        person = (f" Voiced as types of Product Hunt members, not as specific real people: in a test on {ps['label']}, giving "
                  f"the simulation a member's own past comments raised the chance of making the same point from "
                  f"{pv['same_point_generic']:.0%} to {pv['same_point_own_history']:.0%}, and a judge could not tell it "
                  f"from a generic member ({pv['forced_choice_own']:.0%} vs {pv['forced_choice_generic']:.0%}, chance "
                  f"{pv['chance']:.0%}).")
    ground = (" Grounded in themes from similar past launches." if grounded else
              " Similar past launches were unavailable for this run, so these were not grounded; the figures below "
              "were measured with grounding.")
    page = source == "page"
    m = v["page" if page else "desc"]
    if page:
        acc = (f"These reactions are at the level of topics only. From a web page alone, about "
               f"{m['point_precision']:.0%} make the same specific point a real user made, fewer than a generic list of "
               f"typical launch comments ({m['generic_point_precision']:.0%}, {m['launches']} launches). Counting the same "
               f"topic, about {m['topic_recall']:.0%} of real users' topics are covered. Paste your launch description "
               f"for closer results.")
    else:
        acc = (f"From a launch description, about {m['point_precision']:.0%} of simulated reactions make the same specific "
               f"point a real user made, only a little above a generic list of typical launch comments "
               f"({m['generic_point_precision']:.0%}); most are on the right topic but not the same point. Counting the "
               f"same topic, about {m['topic_recall']:.0%} of real users' topics are covered.")
    return (f"Simulated, not real comments.{person}{ground} Fixed offline figure ({c['label']}, {c['date']}): {acc}"
            + ("" if page else " " + _vs_humans()) + _rerun_note())


def _rerun_note() -> str:
    from mvp.ph_site.live import claims
    r = claims().get("try_stability")
    if not r:
        return ""
    return (f" Simulated comments vary between runs: rerunning the same page repeated about "
            f"{r['values']['reaction_agreement']:.0%} of the points ({r['label']}).")


def _vs_humans() -> str:
    from mvp.ph_site.live import claims
    h = claims().get("reactions_vs_humans")
    if not h:
        return ""
    return (f"Counting the same topic, on {h['values']['launches']} new launches they covered real users' topics at "
            "least as well as a second group of real commenters on the same launch did.")


def _types_from_people(p: dict, topics: list[str]) -> list[str]:
    """4 voices from the similar-tools scorer's closest descriptions (each shared by 20+ people) + 2 contrast voices."""
    out = []
    for r in p["top_people"][:4]:
        out.append(f"Type {chr(65 + len(out))}: {' / '.join(r['roles'])}, {r['tier']}, interested in "
                   f"{', '.join(topics[:2]) or 'this category'}")
    while len(out) < 4:
        out.append(f"Type {chr(65 + len(out))}: regular PH voter interested in {', '.join(topics[:2]) or 'this category'}")
    out.append("Type E: heavy PH voter who comments often and sees dozens of similar launches a week")
    out.append("Type F: maker from an unrelated category, browsing the day's launches")
    return out


def _member_types(p: dict, topics: list[str]) -> list[str]:
    """Reaction voices from aggregate interest segments (never from an individual row)."""
    out = []
    segs = (p.get("segments") or [])[:4]
    for i, sg in enumerate(segs):
        role = "often makers themselves" if sg.get("maker_share", 0) >= 0.5 else "mostly voters"
        out.append(f"Type {chr(65 + i)}: member of the '{sg['name']}' crowd ({role}), interested in "
                   f"{', '.join(sg['top_topics'][:2])}")
    while len(out) < 4:
        out.append(f"Type {chr(65 + len(out))}: regular PH voter interested in {', '.join(topics[:2]) or 'this category'}")
    # Contrast voices so it isn't only fans.
    out.append("Type E: heavy PH voter who comments often and sees dozens of similar launches a week")
    out.append("Type F: maker from an unrelated category, browsing the day's launches")
    return out


_RET: dict = {}
REACT_MODEL = os.environ.get("TRY_REACT_MODEL", "gemini-2.5-flash")


def _retrieval() -> dict:
    """E5's reactions retrieval bundle: paraphrased comment themes of 3,371 past launches (no verbatim comments, no
    usernames) with gemini-embedding-001 256-d vectors (site/reactions_retrieval_v1.*)."""
    if not _RET:
        import io
        raw = gcs.read_bytes("site/reactions_retrieval_v1.npz", ttl=86400)
        meta = gcs.read_json("site/reactions_retrieval_v1.json", ttl=86400)
        if raw is None or not meta:
            raise RuntimeError("reactions retrieval bundle missing")
        _RET.update(emb=np.load(io.BytesIO(raw))["emb"].astype(np.float32), rows=meta)
    return _RET


def _slug_stem(name: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _grounding(q: np.ndarray, name: str, k: int = 10, max_lines: int = 60) -> list[str]:
    R = _retrieval()
    sims = R["emb"] @ q
    own = _slug_stem(name)
    lines = []
    for j in np.argsort(-sims):
        row = R["rows"][int(j)]
        stem = str(row.get("slug_stem") or "")
        if own and (stem == own or stem.startswith(own + "-") or own.startswith(stem + "-")):
            continue
        lines.extend(str(t) for t in (row.get("themes") or [])[:6])
        k -= 1
        if k == 0 or len(lines) >= max_lines:
            break
    return lines[:max_lines]


async def step_reactions(tok: str) -> dict:
    """E5's measured best variant (reactions_v2 BEST): gemini-2.5-flash at 0.3, grounded in themes from the 10 most
    similar past launches, member types from the similar-tools scorer (+2 contrast voices)."""
    from capability.gemini_config import extract_json, gemini_chat
    from mvp.ph_site import person_e5

    a = use_run(tok, "reactions")
    desc = (a.get("ph_description") or ((a.get("summary") or "") + " " + (a.get("page_excerpt") or "")))[:800]
    q = await person_e5.embed(f"{a.get('name')}. {a.get('tagline')}. {desc}")
    try:
        B = person_e5.bundle()
        sm = person_e5.summarize(B, person_e5.score_text(B, q))
        people = {"top_people": [{"label": f"User {chr(65 + i)}", **pp} for i, pp in enumerate(sm["people"])]}
        types = _types_from_people(people, a.get("topics") or [])
    except Exception as exc:  # noqa: BLE001
        print(f"[try] member types fallback: {exc!r}", flush=True)
        types = _member_types(_interest_people(a), a.get("topics") or [])
    prompt = REACT_PROMPT.format(name=a.get("name"), tagline=a.get("tagline"), summary=a.get("summary"),
                                 pricing=a.get("pricing"), strengths="; ".join(a.get("strengths") or []),
                                 doubts="; ".join(a.get("doubts") or []), excerpt=(a.get("page_excerpt") or "")[:2500],
                                 types="\n".join(types))
    grounded = False
    try:
        lines = _grounding(q, a.get("name") or "")
        if lines:
            prompt += ("\n\nFor grounding: users of similar past Product Hunt products raised these points (other "
                       "products, not this one; reuse only what plausibly applies here):\n" +
                       "\n".join(f"- {l}" for l in lines))
            grounded = True
    except Exception as exc:  # noqa: BLE001 - ungrounded is still a valid (weaker) answer
        print(f"[try] grounding unavailable: {exc!r}", flush=True)
    raw = await gemini_chat([{"role": "user", "content": prompt}], model=REACT_MODEL, temperature=0.3, max_retries=3,
                            max_output_tokens=3000)
    j = extract_json(raw)
    reacts = []
    for r in (j.get("reactions") or [])[:6]:
        reacts.append({k: r.get(k) for k in ("type", "comment", "sentiment", "why")})   # no unvalidated vote meters
    return {"reactions": reacts, "types": types, "headline": j.get("headline_takeaway", ""), "grounded": grounded,
            "note": _reactions_note(grounded, a.get("source"))}


# ---------- step 3b: most likely question / concern (E5 RANKED recipe) ----------

ASK_MODEL = os.environ.get("TRY_ASK_MODEL", "gemini-2.5-flash")
_ASK_GEN = {
    "concerns": ("List the 6 criticisms most likely from real users: first the complaints users of this product CATEGORY "
                 "almost always raise (2-3), then the ones SPECIFIC to this product (the rest). Write them as they would "
                 "appear in launch-day comments (objections, questions to the maker, feature requests). Do not invent "
                 "features.\nProduct: {name} - {tagline}\nDescription: {desc}\n"
                 "Return JSON {{\"items\": [\"<one specific sentence>\", ...]}}"),
    "questions": ("A new product is launching on Product Hunt today.\nProduct: {name} - {tagline}\nDescription: {desc}\n"
                  "List the 6 questions users are most likely to ask the makers in the launch comments in the first hours, "
                  "most likely first.\nBe specific to this product; do not invent features. "
                  "Return JSON {{\"items\": [\"...\", ...]}}"),
}
_ASK_LIKE = ("A new product is launching on Product Hunt.\nProduct: {name} - {tagline}\nDescription: {desc}\n"
             "Below are candidate {what} users might raise in the launch comments.\nRate how likely real users are to "
             "raise each one for THIS product, 1 (unlikely) to 5 (very likely).\n"
             "Return JSON {{\"ratings\": [1-5 per candidate, in order]}}\n{c}")


def _ask_res():
    import re as _re
    return {"concerns": _re.compile(r"^\s*(objection|question|feature request|feature_request)\s*:\s*", _re.I),
            "questions": _re.compile(r"^\s*question\s*:\s*", _re.I)}


def _pct_rank(v: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(v, kind="mergesort"), kind="mergesort").astype(float)
    # average ranks for ties, as pandas rank(pct=True)
    out = np.empty(len(v))
    for x in np.unique(v):
        m = v == x
        out[m] = order[m].mean()
    return (out + 1) / len(v)


def _rank_order(gen: list[str], nth: list[tuple[str, int]], NX: np.ndarray, X: np.ndarray, ratings, top: int = 5) -> list[int]:
    """E5's RANKED score for candidates = generated + retrieved: neighbour frequency + cross-source agreement + Gemini
    likelihood, each as a percentile rank. Returns candidate indices, best first, near-duplicates (cosine >= 0.90) dropped."""
    if not len(X):
        return []
    own = np.array([j for _, j in nth])
    g = np.array(["GEN"] * len(gen) + ["RETR"] * (len(X) - len(gen)))
    S_ = X @ X.T
    a = np.array([len(set(own[(NX @ X[i]) >= 0.80])) if len(nth) else 0 for i in range(len(X))], float)
    b = np.array([((S_[i] >= 0.80) & (g != g[i])).sum() for i in range(len(X))], float)
    c = np.array(ratings if isinstance(ratings, list) and len(ratings) == len(X) else [3] * len(X), float)
    sc = (_pct_rank(a) + _pct_rank(b) + _pct_rank(c)) / 3
    out, used = [], np.zeros(len(X), bool)
    for i in np.argsort(-sc, kind="stable"):
        if used[i]:
            continue
        out.append(int(i))
        used |= S_[i] >= 0.90
        if len(out) == top:
            break
    return out


def _rank_pick(gen, nth, NX, X, ratings) -> int | None:
    o = _rank_order(gen, nth, NX, X, ratings, top=1)
    return o[0] if o else None


# E5's retrieval-condensed concerns ("b20", RECIPE_b20_concerns.md): real points from the 20 most similar earlier
# launches, condensed by one gemini-2.5-flash call. Below these nearest-neighbour similarities (the bottom third of the
# 170 test launches) the recipe does not apply.
B20_MIN_SIM = {"pasted": 0.898, "page": 0.886}
COMMON_CONCERNS = ["Pricing is unclear or too high.", "How is this different from existing alternatives?",
                   "Concerns about data privacy and security."]
_B20_PROMPT = ("A new product is launching on Product Hunt today.\nProduct: {name} - {tagline}\n{text}\n"
               "Real users raised these points in the launch comments of the 20 most similar EARLIER launches (one line "
               "per point, launch number first):\n{points}\n"
               "Using these real points as evidence of what this audience asks about, write the 3 concerns, objections or "
               "feature requests most likely to be raised about THIS product,\nmost likely first, each reworded for this "
               "product. Return JSON {{\"items\": [\"...\", \"...\", \"...\"]}}")


def _b20_neighbours(R: dict, q: np.ndarray, name: str, k: int = 20) -> tuple[list[int], float]:
    """The k most similar earlier launches, never the same product's earlier launches (stems compared without a trailing
    -N); also the cosine of the nearest one kept."""
    import re as _re
    base = lambda st: _re.sub(r"-\d+$", "", st or "")
    own = base(_slug_stem(name))
    sims = R["emb"] @ q
    nb = []
    for j in np.argsort(-sims):
        if own and base(str(R["rows"][int(j)].get("slug_stem") or "")) == own:
            continue
        nb.append(int(j))
        if len(nb) == k:
            break
    return nb, (float(sims[nb[0]]) if nb else 0.0)


def _b20_points(R: dict, nb: list[int]) -> str:
    rex = _ask_res()["concerns"]
    lines = []
    for i, j in enumerate(nb, 1):
        pts = [rex.sub("", t) for t in (R["rows"][j].get("themes") or []) if rex.match(t)][:4]
        lines.extend(f"[{i}] {t}" for t in pts)
    return "\n".join(lines)[:6000]


async def step_asks(tok: str) -> dict:
    """The single most likely question (E5's RANKED recipe) and the 3 most likely concerns (E5's retrieval-condensed
    recipe "b20"), each with the figures E5 measured on the strict same-specific-point standard. Page reads use the
    raw page excerpt. Where few similar past launches exist, concerns fall back (pasted: RANKED; page: a common list)
    and carry no accuracy figure."""
    import asyncio

    from capability.gemini_config import extract_json, gemini_chat
    from mvp.ph_site import person_e5

    a = use_run(tok, "asks")
    pasted = bool(a.get("ph_description"))
    name, tagline = a.get("name") or "", a.get("tagline") or ""
    desc = a["ph_description"] if pasted else (a.get("page_excerpt") or a.get("summary") or "")
    res = _ask_res()

    async def cj(prompt, temp, tok_):
        try:
            return extract_json(await gemini_chat([{"role": "user", "content": prompt}], model=ASK_MODEL,
                                                  temperature=temp, max_retries=3, max_output_tokens=tok_)) or {}
        except Exception as exc:  # noqa: BLE001
            print(f"[try] asks call failed: {exc!r}", flush=True)
            return {}

    q = await person_e5.embed(f"{name}. {tagline}. {desc[:800]}")
    R = _retrieval()
    own_stem = _slug_stem(name)
    nb = []
    for j in np.argsort(-(R["emb"] @ q)):
        stem = str(R["rows"][int(j)].get("slug_stem") or "")
        if own_stem and (stem == own_stem or stem.startswith(own_stem + "-") or own_stem.startswith(stem + "-")):
            continue
        nb.append(int(j))
        if len(nb) == 25:
            break

    async def ranked(kinds: list[str]) -> dict:
        """kind -> items, most likely first (E5 RANKED)."""
        gens = await asyncio.gather(*[cj(_ASK_GEN[k].format(name=name, tagline=tagline,
                                                             desc=desc[:1500 if k == "concerns" else 1200]), 0.3, 800)
                                      for k in kinds])
        gens = {k: [str(x) for x in (g.get("items") or [])][:6] for k, g in zip(kinds, gens)}
        nth = {k: [(res[k].sub("", t), j) for j in nb for t in (R["rows"][j].get("themes") or []) if res[k].match(t)]
               for k in kinds}
        texts = list(dict.fromkeys(t for k in kinds for t, _ in nth[k]))[:200]
        keep = set(texts)
        nth = {k: [(t, j) for t, j in nth[k] if t in keep] for k in kinds}
        E = await person_e5.embed_many(texts) if texts else np.zeros((0, 256), np.float32)
        pos = {t: i for i, t in enumerate(texts)}
        cands = {}
        for k in kinds:
            NX = E[[pos[t] for t, _ in nth[k]]] if nth[k] else np.zeros((0, 256), np.float32)
            retr = []
            if len(NX):
                own = np.array([j for _, j in nth[k]])
                SS = NX @ NX.T
                cnt = np.array([len(set(own[SS[i] >= 0.80])) for i in range(len(NX))])
                used = np.zeros(len(NX), bool)
                for i in np.argsort(-cnt, kind="stable"):
                    if used[i]:
                        continue
                    retr.append(nth[k][i][0])
                    used |= SS[i] >= 0.80
                    if len(retr) == 8:
                        break
            cands[k] = (list(dict.fromkeys(gens[k] + retr)), NX, len(dict.fromkeys(gens[k])))
        allc = list(dict.fromkeys(t for k in kinds for t in cands[k][0]))
        CE = await person_e5.embed_many(allc) if allc else np.zeros((0, 256), np.float32)
        cpos = {t: i for i, t in enumerate(allc)}
        what = {"concerns": "concerns (objections, doubting questions, feature requests)",
                "questions": "questions to the makers"}
        num = lambda l: "\n".join(f"{i + 1}. {str(t)[:300]}" for i, t in enumerate(l))
        likes = await asyncio.gather(*[cj(_ASK_LIKE.format(name=name, tagline=tagline, desc=desc[:1200], what=what[k],
                                                           c=num(cands[k][0])), 0.0, 300) for k in kinds])
        out = {}
        for k, lk in zip(kinds, likes):
            items, NX, n_gen = cands[k]
            order = _rank_order(items[:n_gen], nth[k], NX, CE[[cpos[t] for t in items]], lk.get("ratings"))
            out[k] = [items[i] for i in order]
        return out

    async def b20() -> list[str]:
        pts = _b20_points(R, nb20)
        if not pts:
            return []
        j = await cj(_B20_PROMPT.format(name=name, tagline=tagline, text=desc[:1500], points=pts), 0.0, 600)
        return [str(x) for x in (j.get("items") or []) if str(x).strip()][:3]

    nb20, s1 = _b20_neighbours(R, q, name)
    thin = s1 < B20_MIN_SIM["pasted" if pasted else "page"]
    if thin and pasted:
        r = await ranked(["questions", "concerns"])
        concerns, basis = r.get("concerns", [])[:3], "earlier_method"
    elif thin:
        r = await ranked(["questions"])
        concerns, basis = list(COMMON_CONCERNS), "common"
    else:
        r, concerns = await asyncio.gather(ranked(["questions"]), b20())
        basis = "retrieval"
        if not concerns:                       # the condensing call failed: the recipe's fallback
            if pasted:
                concerns, basis = (await ranked(["concerns"])).get("concerns", [])[:3], "earlier_method"
            else:
                concerns, basis = list(COMMON_CONCERNS), "common"
    question = (r.get("questions") or [None])[0]
    if not question and not concerns:
        raise RuntimeError("no question or concern could be produced")
    return {"question": question, "concerns": concerns, "concerns_basis": basis,
            "source": "pasted" if pasted else "page",
            "note": _asks_note(pasted, len(desc.split()) if pasted else None, basis)}


def _asks_note(pasted: bool, words: int | None = None, basis: str = "retrieval") -> str:
    from mvp.ph_site.live import claims
    cl = claims()
    t, b = cl.get("top_items"), cl.get("concerns_b20")
    if not t or not b:
        return "Simulated, not real comments."
    v, bv = t["values"], b["values"]
    src = "pasted launch description" if pasted else "web page"
    s = (f"Simulated, not real comments. Fixed offline figures. Question ({t['label']}, {t['date']}): from a {src}, the "
         f"most likely question made the same specific point as a real user's question about "
         f"{v['q_desc' if pasted else 'q_page']} times, against {v['q_generic']} for a generic question.")
    if basis == "retrieval":
        s += (f" Concerns are based on what real users raised on similar earlier launches ({b['label']}, {b['date']}): "
              f"about {bv['desc' if pasted else 'page']} of these concerns matched a point real commenters raised on "
              f"comparable launches, against about {bv['generic']} for a common list.")
        fw = b.get("forward") or {}
        if pasted and fw.get("desc_n"):
            s += (f" A forward check on {fw['desc_n']} new launches ({fw['window']}) gave {fw['desc_p3']:.0%}; a small "
                  f"sample.")
        elif not pasted and not fw.get("page_n"):
            s += " The page-read figure is from a backtest only; it has not yet been checked on new launches."
    elif basis == "earlier_method":
        s += (" Few similar past launches were found for this product, so the concerns come from our earlier method and "
              "carry no accuracy figure.")
    else:
        s += " Few similar past launches were found for this product; showing common concerns, with no accuracy figure."
    if pasted and words is not None and words < 40:
        s += (f" Your description has {words} words: on past launches with descriptions under 40 words, the top question "
              f"did no better than a generic one (40 to 100 words did clearly better).")
    if not pasted and basis == "retrieval":
        s += " A pasted launch description gives closer concerns."
    return s


# ---------- step 4: launch (no LLM) ----------

import re as _re_mod
_PH_PHRASES = _re_mod.compile(r"(#\s*\d+\s*)?product of the (day|week|month)|#\s*1 product|product\s*hunt|upvotes?",
                              _re_mod.I)


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
    a = use_run(tok, "launch")
    lb_ph = gcs.read_json("results/web/launch_band.json", ttl=3600)
    if not lb_ph:
        raise ValueError("The launch placement model is unavailable right now; the other sections still work.")
    lb = lb_ph
    if a.get("ph_description"):
        desc = a["ph_description"]            # pasted launch text: the PH-description band (validated on that input)
    else:
        # Page reads: E5's page-trained band (site/launch_band_page_v1.json, out of sample on 130 fresh page reads),
        # input = summary + page excerpt with Product Hunt outcome phrases removed; fallback to the PH band.
        page_lb = gcs.read_json("site/launch_band_page_v1.json", ttl=3600)
        excerpt = _PH_PHRASES.sub(" ", (a.get("page_excerpt") or "")[:1500])
        if page_lb:
            lb, desc = page_lb, (a.get("summary") or "") + " " + excerpt
        else:
            desc = a.get("summary") or ""
    score = _band_score(lb, a.get("name") or "", a.get("tagline") or "", desc, a.get("topics") or [])
    pct = sum(1 for c in lb["score_percentile_cuts"] if c < score)
    b = lb["bands"][min(9, pct // 10)]
    rk, vt = b["daily_rank_p10_p50_p90"], b["votes_p10_p50_p90"]
    acc = lb_ph["heldout_accuracy"]   # top-3/5/10 table: measured on PH descriptions (labelled as such)
    card = None
    if lb is not lb_ph:
        # E5's validated card for the page band (same score and cuts): percentile of the day's line-up, share of the
        # day's votes and P(top 10% of the day), out of sample on 856 page reads.
        cv = gcs.read_json("site/launch_band_card_v2.json", ttl=3600)
        if cv and cv.get("cuts_identical_to_v1"):
            d = cv["deciles"][min(9, pct // 10)]
            val = cv.get("validation_out_of_sample_856") or {}
            card = {"pct_of_day": d["pct_of_day_p10_p50_p90"], "rank_typical": d["rank_band_typical_day"],
                    "typical_n": cv.get("typical_day_size_last_8_weeks"), "share_votes": d["share_of_day_votes_p15_p50_p85"],
                    "p_top10pct": d["p_top10pct_of_day"], "p_top3_by_size": d["p_top3_by_day_size"],
                    "p_top10_by_size": d["p_top10_by_day_size"],
                    "validation": {"launches": 856, "band": val.get("pct_of_day_band_coverage"),
                                   "band_by_size": val.get("by_day_size"), "fresh": val.get("fresh_130"),
                                   "share": val.get("share_of_day_votes_p15_p85"),
                                   "top10pct": val.get("p_top10pct_pred_vs_actual")}}
    return {"percentile": pct, "decile": b["decile"],
            "rank_band": {"likely": [int(rk[0]), int(rk[2])], "median": int(rk[1])},
            "votes_band": {"likely": [int(vt[0]), int(vt[2])], "median": int(vt[1])},
            "share_top3": b["share_top3"], "share_top10": b["share_top10"], "similar_launches": b["n"],
            "accuracy": {"days": acc["days"], "top3": acc["top3"], "top5": acc["top5"], "top10": acc["top10"],
                         "spearman": acc["within_day_spearman"],
                         "full_model": _full_model_ref(acc)},
            "assumed": {"hunter": "population median (unknown)", "maker history": "population median (unknown)",
                        "team ties / audience": "population median (unknown)", "launch day": "a typical day's line-up"},
            "method": (f"Percentile band from the page alone: a text model trained on {lb['trained_on']['launches']:,} "
                       f"featured launches ({lb['trained_on']['days'][0]} to {lb['trained_on']['days'][1]}) scores "
                       f"this page above {pct}% of them. The ranges are where launches in that tenth actually finished "
                       "(10th to 90th percentile)."),
            "honesty": _honesty(acc, a.get("source")), "coverage": None,  # one coverage figure per band: input note (pasted) / card (page)
            "input_note": _input_note(a.get("source")),
            "card": card, "source": a.get("source")}


def _input_note(source: str | None) -> str | None:
    """Which band scored this run and how that band was validated."""
    from mvp.ph_site.live import claims
    cl = claims()
    if source == "pasted":
        v = cl["try_e2e"]["values"]
        return (f"Scored from the description you pasted with a model trained on Product Hunt launch descriptions. "
                f"Tested only on launches it had not seen: rank correlation {v['spearman_ph_856']:.2f} on "
                f"{v['ph_forward_n']} Sep–Nov launches ({v['spearman_ph']:.2f} on the {v['ph_recent_n']} most recent); "
                f"the real rank fell inside the band about 3 times in 4 ({v['coverage_ph_n']} launches).")
    pb = cl.get("page_band")
    if not pb:
        return "Scored from a read of your web page; the accuracy figures were measured on Product Hunt descriptions."
    v = pb["values"]
    return (f"Scored from your web page alone with a model trained on product web pages: on {v['n']} held-out "
            f"launches its rank correlation was {v['spearman']:.2f} ({pb['date']}). A pasted launch description scored "
            f"somewhat higher on the same launches ({cl['try_e2e']['values']['spearman_ph_856']:.2f} vs "
            f"{v['spearman']:.2f}). The top-3 table below was "
            "measured on Product Hunt descriptions.")

def _full_model_ref(acc: dict) -> dict:
    """Corrected 00:05 launch-model backtest (claims.json; the 63/69/75 in older launch_band.json was leak-inflated)."""
    try:
        from mvp.ph_site.live import claims
        v = claims()["launch_model_backtest"]["values"]
        return {**{k: v[k] for k in ("top3", "top5", "top10")}, "days": v["days"]}
    except Exception:  # noqa: BLE001 - never fall back to the leak-inflated reference in launch_band.json
        return None


def _coverage() -> dict | None:
    try:
        from mvp.ph_site.live import claims
        c = claims()["rank_band_coverage"]
        return {"share": c["values"]["coverage"], "launches": c["values"]["launches"], "label": c["label"], "date": c["date"]}
    except Exception:  # noqa: BLE001
        return None


def _r(x) -> int:
    return int(float(x) + 0.5)   # round half up, matching the /ph page


def _honesty(acc: dict, source: str | None = None) -> str:
    rec = ""
    try:
        from mvp.ph_site import live
        row = next(r for r in live.track_record()["rows"] if r["key"] == "0005" and r.get("source", "live") == "live")
        if row["n_days"]:
            rec = (f" Our deployed 00:05 PT launch model, which also knows the hunter, makers and team history, "
                   f"scores {_r(row['top3'])} / {_r(row['top5'])} / {_r(row['top10'])} live over {row['n_days']} days.")
    except Exception:  # noqa: BLE001
        pass
    return (f"Pre-launch rank prediction is weak, and weaker still from a page alone. Tested month-forward on "
            f"{acc['days']} days using Product Hunt launch descriptions, the description-only model put "
            f"{acc['top3']:.0f}% / {acc['top5']:.0f}% / {acc['top10']:.0f}% of the real top 3 / 5 / 10 in its own "
            f"top 3 / 5 / 10{'' if source == 'pasted' else '; a read of your web page is a weaker input than that'}." + rec +
            " Who hunts it and who shows up on the day decide most of the result.")
