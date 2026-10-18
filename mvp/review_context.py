"""Live Capterra + G2 reviews of the study's own rivals, for the session-feedback step.

Production uses ONLY live scrapes of the rivals named in the study plan (Apify: trakk/capterra-reviews-scraper and
automation-lab/g2-scraper; APIFY_TOKEN, or the token file at ~/.config/apify/token). The FreshCrawl snapshots in
experiments/staged_context are research data covering arbitrary products and are never used here.

From the scraped reviews it builds what tested best in experiments/staged_context (see HANDOFF_review_context.md):
people-like-this-persona rating averages, complaint-topic rates, and the reviews of the most similar people.
Scrapes start in the background when a study starts (prefetch) and are cached per rival in cache/apify/.
When no usable scrape is available the result says why (status/reason) and carries no evidence; nothing is
substituted. Turn off with MVP_REVIEW_CONTEXT=0.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

_EXP = Path(__file__).resolve().parents[1] / "experiments" / "staged_context"
_APIFY_CACHE = _EXP / "cache" / "apify"
_LOCK = threading.Lock()
_IN_FLIGHT: set[str] = set()
G2_ACTOR = "automation-lab~g2-scraper"
CAPTERRA_ACTOR = "trakk~capterra-reviews-scraper"
PER_SITE = 50
# Apify account caps: 16 GB actor memory, 5 concurrent runs. Exceeding either returns HTTP 402 ("Payment Required").
_RUN_SLOTS = threading.BoundedSemaphore(int(os.environ.get("MVP_APIFY_MAX_RUNS", "3")))
_RUN_MEMORY_MB = {"trakk~capterra-reviews-scraper": 2048, "automation-lab~g2-scraper": 256}


def enabled() -> bool:
    return os.environ.get("MVP_REVIEW_CONTEXT", "1").strip().lower() not in {"0", "false", "no", "off"}


def _helpers():
    """role_family / clean / complaint topics are shared with the experiments (pure functions, no data)."""
    if str(_EXP) not in sys.path:
        sys.path.insert(0, str(_EXP))
    import experiment as E  # noqa: PLC0415
    import predictability as PR  # noqa: PLC0415

    return E, PR


def apify_token() -> str | None:
    tok = os.environ.get("APIFY_TOKEN", "").strip()
    if tok:
        return tok
    f = Path.home() / ".config" / "apify" / "token"
    return f.read_text().strip() if f.is_file() else None


def _apify_run(actor: str, payload: dict[str, Any], token: str, wait_s: float = 300.0) -> list[dict[str, Any]]:
    """Start a run, poll it, return its dataset items (sync endpoints are dropped by long-lived proxies).

    Runs are capped (_RUN_SLOTS) and given explicit memory so parallel scrapes stay under the account limits."""
    with _RUN_SLOTS:
        params = {"token": token}
        if actor in _RUN_MEMORY_MB:
            params["memory"] = _RUN_MEMORY_MB[actor]
        run = requests.post(f"https://api.apify.com/v2/acts/{actor}/runs", params=params, json=payload, timeout=60)
        run.raise_for_status()
        data = run.json()["data"]
        deadline = time.monotonic() + wait_s
        while data["status"] in {"READY", "RUNNING"} and time.monotonic() < deadline:
            time.sleep(5)
            data = requests.get(f"https://api.apify.com/v2/actor-runs/{data['id']}", params={"token": token}, timeout=30).json()["data"]
    if data["status"] != "SUCCEEDED":
        raise RuntimeError(f"{actor} run {data['id']} ended {data['status']}")
    items = requests.get(f"https://api.apify.com/v2/datasets/{data['defaultDatasetId']}/items",
                         params={"token": token, "clean": "true"}, timeout=60)
    items.raise_for_status()
    return items.json()


def _text(v: Any) -> str | None:
    """The G2 scraper returns some fields (industry, companySegment) as numeric ids; keep only real text."""
    v = str(v or "").strip()
    return v if v and not v.isdigit() else None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _same_product(found: str | None, wanted: str) -> bool:
    """Capterra's search returns its best match even when it is a different product."""
    f, w = _slug(found or ""), _slug(wanted)
    return bool(f) and (f == w or f.startswith(w + "-") or w.startswith(f + "-"))


def cached_live_reviews(product_name: str) -> dict[str, Any] | None:
    """{reviews, errors} for a rival once its scrape has finished, else None."""
    cache = _APIFY_CACHE / f"{_slug(product_name)}.json"
    return json.loads(cache.read_text()) if cache.is_file() else None


def prefetch(names: list[str]) -> None:
    """Start live scrapes for rivals in the background (one per name); never blocks a study."""
    if not enabled():
        return
    if not apify_token():
        print("[review_context] APIFY_TOKEN missing: no competitor reviews will be scraped", flush=True)
        return
    for n in names:
        if not n or cached_live_reviews(n) is not None:
            continue
        with _LOCK:
            if _slug(n) in _IN_FLIGHT:
                continue
            _IN_FLIGHT.add(_slug(n))

        def run(name=n):
            try:
                live_reviews(name)
            finally:
                with _LOCK:
                    _IN_FLIGHT.discard(_slug(name))
        threading.Thread(target=run, name=f"apify-{_slug(n)}", daemon=True).start()


def live_reviews(product_name: str, *, per_site: int = PER_SITE) -> dict[str, Any]:
    """Recent Capterra + G2 reviews for one rival. Blocking (1-2 min); studies prefetch() and read the cache."""
    token = apify_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN missing")
    cache = _APIFY_CACHE / f"{_slug(product_name)}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    reviews: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        for r in _apify_run(CAPTERRA_ACTOR, {"searchQueries": [product_name], "maxProductsPerQuery": 1,
                                             "maxReviewsPerProduct": per_site, "maxItems": per_site,
                                             "includeProductAggregate": False}, token):
            reviews.append({"source": "capterra", "product": r.get("productName") or "",
                            "role": r.get("reviewerJobTitle"), "size": r.get("reviewerCompanySize"),
                            "industry": r.get("reviewerIndustry"), "time_used": r.get("timeUsedProduct"),
                            "rating": r.get("overallRating"), "ease": r.get("easeOfUseRating"),
                            "nps": r.get("likelihoodToRecommend"), "pros": r.get("pros"), "cons": r.get("cons")})
    except (requests.RequestException, KeyError, ValueError, RuntimeError) as exc:
        errors.append(_redact(f"capterra: {exc!r}", token))
    try:
        for r in _apify_run(G2_ACTOR, {"mode": "product_reviews", "productUrls": [_slug(product_name)], "maxReviews": per_site}, token):
            # G2 scraper fields (checked Oct 2026): no job title; companySegment/industry are numeric ids; loveTheme/
            # hateTheme are one-word tags, not text; easeOfUse is 1-7; switchedFromOtherProduct is yes/no. The full
            # review lives in reviewText, so that is the evidence; there is no separate dislikes text to count.
            reviews.append({"source": "g2", "product": r.get("productName") or "", "role": None,
                            "size": _text(r.get("companySegment")), "industry": _text(r.get("industry")),
                            "rating": r.get("starRating"), "ease_1_7": r.get("easeOfUse"), "nps": r.get("nps"),
                            "text": r.get("reviewText"), "pros": None, "cons": None,
                            "love_theme": r.get("loveTheme"), "hate_theme": r.get("hateTheme"),
                            "switched": r.get("switchedFromOtherProduct"), "switched_reason": r.get("switchedReason")})
    except (requests.RequestException, KeyError, ValueError, RuntimeError) as exc:
        errors.append(_redact(f"g2: {exc!r}", token))
    failed = list(errors)  # fetch failures (credit, network): not cached, so the next study retries
    wrong = sorted({x["product"] for x in reviews if not _same_product(x["product"], product_name)})
    if wrong:
        errors.append(f"dropped reviews of other products returned by search: {wrong}")
    out = {"product": product_name, "reviews": [x for x in reviews if _same_product(x["product"], product_name)],
           "errors": errors}
    if not failed:
        _APIFY_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out))
    return out


def _redact(msg: str, token: str) -> str:
    """Apify errors echo the request URL, which carries the token."""
    return re.sub(r"token=[^&\s')\"]+", "token=<redacted>", msg.replace(token, "<redacted>"))[:300]


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def review_context(site_url: str, persona: dict[str, Any], *, rivals: list[str] | None = None) -> dict[str, Any]:
    """{status, reason, text, sources}. text is "" unless at least one rival's live scrape returned matching reviews."""
    if not enabled():
        return {"status": "disabled", "reason": "MVP_REVIEW_CONTEXT=0", "text": "", "sources": []}
    rivals = [r for r in (rivals or []) if r]
    if not rivals:
        return {"status": "no_rivals", "reason": "the study plan names no competitors", "text": "", "sources": []}
    prefetch(rivals)
    got = {r: cached_live_reviews(r) for r in rivals}
    pending = [r for r, v in got.items() if v is None]
    reviews = [x for v in got.values() if v for x in v["reviews"]]
    errors = [e for v in got.values() if v for e in v["errors"]]
    if not reviews:
        why = (f"scrapes still running for {pending}" if pending else "no matching reviews") + (f"; errors: {errors}" if errors else "")
        return {"status": "unavailable", "reason": why, "text": "", "sources": []}
    E, PR = _helpers()
    role = E.role_family(" ".join(str(persona.get(k) or "") for k in ("role", "bio", "name")))
    same = [x for x in reviews if E.role_family(str(x.get("role") or "")) == role]

    def avg(rows, key):
        v = [n for n in (_num(x.get(key)) for x in rows) if n]  # 0 means "not rated" in the Capterra scrape
        return (sum(v) / len(v), len(v)) if v else (None, 0)
    lines = []
    for key, label in (("rating", "overall (1-5)"), ("ease", "ease of use (Capterra, 1-5)"),
                       ("ease_1_7", "ease of use (G2, 1-7)"), ("nps", "likelihood to recommend (0-10)")):
        a, n = avg(reviews, key)
        b, m = avg(same, key)
        if a is not None:
            lines.append(f"- {label}: all reviewers {a:.2f} (n={n})" + (f"; reviewers in this persona's role family '{role}' {b:.2f} (n={m})" if b is not None else ""))
    cons = [str(x.get("cons") or "").lower() for x in reviews if x.get("cons")]
    topics = [f"- {k.replace('complaint_', '')}: {sum(bool(re.search(p, c)) for c in cons) / len(cons):.0%} of complaints"
              for k, p in PR.TOPICS.items()] if cons else []
    sim = (same + [x for x in reviews if x not in same])[:8]
    revs = [f"[{x['product']} | {x['source']}] role: {x.get('role') or '-'}; size: {x.get('size') or '-'}; rating: {x.get('rating') or '-'}\n"
            + (f"Review: {E.clean(x.get('text'))[:700]}" if x.get("text") else
               f"Liked: {E.clean(x.get('pros'))[:400]}\nDisliked: {E.clean(x.get('cons'))[:400]}") for x in sim]
    used = sorted({x["product"] for x in reviews})
    text = (f"## Ratings from live Capterra/G2 reviews of the rivals ({', '.join(used)}; {len(reviews)} reviews)\n" + "\n".join(lines)
            + ("\n\n## Complaint topics in those reviews\n" + "\n".join(topics) if topics else "")
            + "\n\n## Reviews by the most similar people\n" + "\n\n".join(revs))
    return {"status": "ok", "reason": f"pending: {pending}" if pending else "", "text": text,
            "sources": sorted({x["source"] for x in reviews}), "rivals_used": used, "errors": errors}
