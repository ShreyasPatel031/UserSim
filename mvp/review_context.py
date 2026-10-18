"""Capterra + G2 reviews of similar competitors, for the session-feedback step.

Built from the FreshCrawl Capterra and G2 snapshots (experiments/staged_context; downloaded on first use) and, when
the product's category is not covered there, live Apify scrapes of the named rivals (APIFY_TOKEN, or the token file
at ~/.config/apify/token). Tested in experiments/staged_context/router_eval.py and g2_merge.py: with this package an
agent's predicted ratings, pros, cons and overall experience were closer to real reviewers on held-out products,
and data from one review site helped predict reviewers on the other.

Turn off with MVP_REVIEW_CONTEXT=0.
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
_MEMO: dict[tuple, dict[str, Any]] = {}
_IN_FLIGHT: set[str] = set()
G2_ACTOR = "automation-lab~g2-scraper"
CAPTERRA_ACTOR = "trakk~capterra-reviews-scraper"


def enabled() -> bool:
    return os.environ.get("MVP_REVIEW_CONTEXT", "1").strip().lower() not in {"0", "false", "no", "off"}


def _modules():
    if str(_EXP) not in sys.path:
        sys.path.insert(0, str(_EXP))
    import corpus as C  # noqa: PLC0415
    import experiment as E  # noqa: PLC0415
    import ux_mcp as U  # noqa: PLC0415

    # Study-time calls (page classification) keep their own spend log and call cache, in the gitignored cache
    # folder, so they neither count against the experiments' budget nor land in the committed experiment logs.
    E.OUT = E.CACHE / "mvp_runtime"
    E.CALLS = E.OUT / "calls"
    return C, E, U


def apify_token() -> str | None:
    tok = os.environ.get("APIFY_TOKEN", "").strip()
    if tok:
        return tok
    f = Path.home() / ".config" / "apify" / "token"
    return f.read_text().strip() if f.is_file() else None


def _apify_run(actor: str, payload: dict[str, Any], token: str, wait_s: float = 150.0) -> list[dict[str, Any]]:
    """Start a run, poll it, return its dataset items (sync endpoints are dropped by long-lived proxies)."""
    run = requests.post(f"https://api.apify.com/v2/acts/{actor}/runs", params={"token": token}, json=payload, timeout=60)
    run.raise_for_status()
    data = run.json()["data"]
    deadline = time.monotonic() + wait_s
    while data["status"] in {"READY", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(5)
        data = requests.get(f"https://api.apify.com/v2/actor-runs/{data['id']}", params={"token": token}, timeout=30).json()["data"]
    if data["status"] != "SUCCEEDED":
        return []
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


def cached_live_reviews(product_name: str) -> list[dict[str, Any]] | None:
    cache = _APIFY_CACHE / f"{_slug(product_name)}.json"
    return json.loads(cache.read_text()) if cache.is_file() else None


def prefetch(names: list[str]) -> None:
    """Start live scrapes for rivals in the background (one at a time per name); never blocks a study."""
    if not enabled() or not apify_token():
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


def live_reviews(product_name: str, *, per_site: int = 20) -> list[dict[str, Any]]:
    """Recent Capterra + G2 reviews for one rival, normalised to {source, product, role, size, rating, pros, cons}.

    Blocking (a run takes 1-2 minutes); studies call prefetch() and read cached_live_reviews() instead."""
    token = apify_token()
    if not token or not product_name:
        return []
    slug = _slug(product_name)
    cache = _APIFY_CACHE / f"{slug}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    out: list[dict[str, Any]] = []
    try:
        for r in _apify_run(CAPTERRA_ACTOR, {"searchQueries": [product_name], "maxProductsPerQuery": 1,
                                             "maxReviewsPerProduct": per_site, "maxItems": per_site,
                                             "includeProductAggregate": False}, token):
            out.append({"source": "capterra-live", "product": r.get("productName") or product_name,
                        "role": r.get("reviewerJobTitle"), "size": r.get("reviewerCompanySize"),
                        "time_used": r.get("timeUsedProduct"), "rating": r.get("overallRating"),
                        "ease": r.get("easeOfUseRating"), "nps": r.get("likelihoodToRecommend"),
                        "pros": r.get("pros"), "cons": r.get("cons")})
    except (requests.RequestException, KeyError, ValueError):
        pass
    try:
        for r in _apify_run(G2_ACTOR, {"mode": "product_reviews", "productUrls": [slug], "maxReviews": per_site}, token):
            # G2 scraper fields: no job title; loveTheme/hateTheme carry likes/dislikes, reviewText the full body
            out.append({"source": "g2-live", "product": r.get("productName") or product_name, "role": _text(r.get("industry")),
                        "size": _text(r.get("companySegment")), "rating": r.get("starRating"), "ease": r.get("easeOfUse"),
                        "nps": r.get("nps"), "pros": r.get("loveTheme") or r.get("reviewText"), "cons": r.get("hateTheme"),
                        "switched_from": r.get("switchedFromOtherProduct"), "switched_reason": r.get("switchedReason")})
    except (requests.RequestException, KeyError, ValueError):
        pass
    out = [x for x in out if _same_product(x.get("product"), product_name)]
    _APIFY_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))  # an empty list records "searched, nothing matching" so it is not re-run
    return out


def _persona_role(persona: dict[str, Any]) -> str:
    return " ".join(str(persona.get(k) or "") for k in ("role", "bio", "name"))


def review_context(site_url: str, persona: dict[str, Any], *, rivals: list[str] | None = None) -> dict[str, Any]:
    """{text, category, sources}. Empty text when disabled or nothing relevant is found."""
    if not enabled():
        return {"text": "", "category": None, "sources": []}
    C, E, U = _modules()
    role = E.role_family(_persona_role(persona))
    key = (site_url, role, tuple(rivals or ()))
    with _LOCK:
        if key in _MEMO:
            return _MEMO[key]
    cl = U.classify(site_url)
    names = set(C.corpus()["product"].unique())
    own = cl.get("product_name") or ""
    exclude = next((n for n in names if own and n.lower() == own.lower()), None)
    person = {"role_family": role, "size3": None, "size_fine": None, "time_used": None, "industry": None}
    parts, sources = [], []
    if cl.get("category"):
        pkg = C.sections(person, cl["category"], {"capterra", "g2"}, exclude, U.mask_for(own) if own else None)
        parts += list(pkg["sections"].values())
        sources += ["capterra", "g2"]
    covered = {n.lower() for n in names}
    missing = [r for r in (rivals or []) if r and r.lower() not in covered]
    prefetch(missing[:2])
    live = [x for r in missing[:2] for x in (cached_live_reviews(r) or [])]
    if live:
        fam = [x for x in live if E.role_family(str(x.get("role") or "")) == role] or live
        rows = []
        for x in fam[:8]:
            rows.append(f"[{x['product']} | {x['source']}] role: {x.get('role') or '-'}; size: {x.get('size') or '-'}; "
                        f"rating: {x.get('rating') or '-'}\nLiked: {E.clean(x.get('pros'))[:400]}\nDisliked: {E.clean(x.get('cons'))[:400]}")
        parts.append("## Recent reviews of named rivals (live Capterra/G2 scrape)\n" + "\n\n".join(rows))
        sources.append("apify-live")
    out = {"text": "\n\n".join(parts), "category": cl.get("category"), "sources": sources}
    pending = [r for r in missing[:2] if cached_live_reviews(r) is None]
    if not pending:  # memoise only once every live scrape it wanted has landed
        with _LOCK:
            _MEMO[key] = out
    return out
