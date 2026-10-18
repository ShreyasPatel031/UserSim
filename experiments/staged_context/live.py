"""Live review scrapes (Apify zen-studio/software-review-scraper: G2 + Capterra + TrustRadius + Gartner in one schema).

    scrape(name)            -> raw items for one product (cached in cache/live/<slug>.json; ~$0.54 per 100 reviews)
    frame(name)             -> those reviews in corpus.py's schema (source "live", site = platform)
    named_competitors(...)  -> the product's direct competitors, named by the model from its page (cached call)

Token: APIFY_TOKEN, or ~/.config/apify/token. A failed run raises; nothing is substituted.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402

ACTOR = "zen-studio~software-review-scraper"
LIVE = E.CACHE / "live"
MAX_RESULTS = 100  # the actor's minimum
_SLOTS = threading.BoundedSemaphore(4)  # account: 5 concurrent runs, 16 GB


def token() -> str:
    tok = os.environ.get("APIFY_TOKEN", "").strip()
    if not tok:
        f = Path.home() / ".config" / "apify" / "token"
        tok = f.read_text().strip() if f.is_file() else ""
    if not tok:
        raise RuntimeError("APIFY_TOKEN missing")
    return tok


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _redact(msg: str, tok: str) -> str:
    return re.sub(r"token=[^&\s')\"]+", "token=<redacted>", msg.replace(tok, "<redacted>"))


def scrape(name: str, *, wait_s: float = 900.0) -> list[dict]:
    dest = LIVE / f"{slug(name)}.json"
    if dest.is_file():
        return json.loads(dest.read_text())["items"]
    tok = token()
    payload = {"query": name, "platforms": ["g2", "capterra", "trustradius", "gartner"], "maxResults": MAX_RESULTS,
               "sort": "most_recent", "starRatings": []}
    with _SLOTS:
        for attempt in range(4):
            try:
                r = requests.post(f"https://api.apify.com/v2/acts/{ACTOR}/runs", params={"token": tok}, json=payload, timeout=60)
                r.raise_for_status()
                run = r.json()["data"]
                deadline = time.monotonic() + wait_s
                while run["status"] in {"READY", "RUNNING"} and time.monotonic() < deadline:
                    time.sleep(10)
                    run = requests.get(f"https://api.apify.com/v2/actor-runs/{run['id']}", params={"token": tok},
                                       timeout=30).json()["data"]
                break
            except requests.RequestException as exc:  # proxy resets; 402 = memory cap (too many parallel runs)
                if attempt == 3:
                    raise RuntimeError(_redact(f"{name}: {exc!r}", tok)) from None
                time.sleep(15 * (attempt + 1))
    if run["status"] != "SUCCEEDED":
        raise RuntimeError(f"{name}: run {run['id']} ended {run['status']}")
    items = requests.get(f"https://api.apify.com/v2/datasets/{run['defaultDatasetId']}/items",
                         params={"token": tok, "clean": "true"}, timeout=120).json()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"query": name, "run_id": run["id"], "usd": run.get("usageTotalUsd"),
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": items}))
    return items


def size3(size: str | None, unit: str | None) -> str | None:
    """G2's three bands. Employee counts map exactly; Gartner revenue bands map approximately (<$50M small,
    $50M-1B mid, $1B+ enterprise)."""
    s = (size or "").strip()
    if not s:
        return None
    if s.startswith(("Small-Business", "Mid-Market", "Enterprise")):
        return s
    if unit == "revenue" or "USD" in s:
        if s.startswith("<50M"):
            return "Small-Business (50 or fewer emp.)"
        if s.startswith("50M"):
            return "Mid-Market (51-1000 emp.)"
        if s.startswith(("1B", "10B")):
            return "Enterprise (> 1000 emp.)"
        return None
    if s.lower().startswith("self"):
        return "Small-Business (50 or fewer emp.)"
    m = re.match(r"([\d,]+)", s)
    if not m:
        return None
    lo = int(m.group(1).replace(",", ""))
    return ("Small-Business (50 or fewer emp.)" if lo <= 50 else "Mid-Market (51-1000 emp.)" if lo <= 1000
            else "Enterprise (> 1000 emp.)")


def industry(v: str | None) -> str | None:
    """Sites spell industries differently ('IT & Services' / 'Information Technology and Services')."""
    v = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (v or "").lower().replace("&", " and "))).strip()
    v = v.replace("information technology", "it").replace("it and services", "it services")
    return v or None


def frame(name: str, items: list[dict] | None = None, *, product: str | None = None) -> pd.DataFrame:
    items = scrape(name) if items is None else items
    rows = []
    for x in items:
        rv = x.get("reviewer") or {}
        pd_ = x.get("platformData") or {}
        rating = x.get("rating")
        rows.append({
            "source": "live", "site": x.get("platform"), "rid": f"L:{x.get('platform')}:{x.get('reviewId')}",
            "product": product or name, "found_as": x.get("productName"), "category": None,
            "title": rv.get("jobTitle"), "role_family": E.role_family(rv.get("jobTitle") or ""),
            "size_fine": None, "size3": size3(rv.get("companySize"), rv.get("companySizeUnit")),
            "time_used": pd_.get("timeUsedProduct"), "industry": industry(rv.get("industry")),
            "pros": x.get("pros"), "cons": x.get("cons"), "review_text": x.get("text"), "headline": x.get("title"),
            "overall_rating": float(rating) if isinstance(rating, (int, float)) and rating > 0 else np.nan,
            "recommendation_score": x.get("recommendationScore"), "date": x.get("date"),
            "problems_solved": None, "structured": None})
    return pd.DataFrame(rows)


COMP_PROMPT = """Name the direct competitors of {product} ({url}): products a buyer would compare it against, that do the same
job for the same kind of customer. Real, currently sold software products only, most direct first, using the names
they go by on G2 / Capterra.
{page}
Return {{"competitors": ["name", ...]}} with exactly {n} names. Do not include {product} itself or another edition of it."""


def named_competitors(product: str, url: str, page_text: str = "", n: int = 5) -> list[str]:
    rec = E.call_model("live_competitors", "gemini-2.5-flash", "You know the B2B software market. Return JSON only.",
                       COMP_PROMPT.format(product=product, url=url, n=n,
                                          page=f"Product page text:\n{page_text[:4000]}\n" if page_text else ""),
                       temperature=0.0, seed=42, max_tokens=2048, thinking_budget=512)
    j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    own = slug(product).split("-")[0]
    return [c for c in (j.get("competitors") or []) if isinstance(c, str) and slug(c).split("-")[0] != own][:n]
