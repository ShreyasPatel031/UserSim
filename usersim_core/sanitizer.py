"""Strict backtest leak sanitizer & structured product-surface extractor.

When evaluating historical post-cutoff launches (or live launches after 00:05 PT), visiting
a live URL or reading scraped HTML risks two leaks:
1. Post-launch Product Hunt badges ("#1 Product of the Day", widget embeds, upvote counts).
2. Post-launch social-proof counters ("Trusted by 50,000+ developers") or post-D dates.

This module strips all such signals BEFORE any feature extractor or LLM sees the text/DOM,
and extracts structured, verifiable product-execution signals (interactive demo, free tier,
open-source installability, pricing visibility, waitlist/book-demo friction, platform type).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

# Patterns that could leak post-launch outcome or accumulated traction
_PH_LEAK_RE = re.compile(
    r"("
    r"product\s*hunt|"
    r"producthunt\.com|"
    r"api\.producthunt\.com|"
    r"#\s*[1-5]\s*(product|launch|app|tool)?\s*(of\s+the\s+(day|week|month|year))|"
    r"product\s+of\s+the\s+(day|week|month|year)|"
    r"golden\s+kitty|"
    r"\b\d[\d,]*\+?\s*upvotes?\b|"
    r"featured\s+on\s+ph\b|"
    r"top\s+[1-5]\s+on\s+ph\b"
    r")",
    re.IGNORECASE,
)

_TRACTION_LEAK_RE = re.compile(
    r"\b\d[\d,.]*\s*[kKmM+]?\+?\s*(active\s+|happy\s+|paying\s+)?"
    r"(users|customers|developers|teams|companies|engineers|creators|downloads|installs|stars|reviews|signups)\b",
    re.IGNORECASE,
)

_DEMO_RE = re.compile(
    r"\b(live\s+demo|try\s+(it\s+)?(now|free|live|online)|interactive\s+demo|playground|sandbox|"
    r"no\s+sign\s*-?\s*up(\s+required)?|without\s+signing\s+up|open\s+playground|launch\s+playground)\b",
    re.IGNORECASE,
)
_FREE_RE = re.compile(
    r"(\$\s*0\b|\bfree\s+(forever|tier|plan|trial|to\s+use|version)\b|\bno\s+credit\s+card(\s+required)?\b|\bstart\s+for\s+free\b)",
    re.IGNORECASE,
)
_OSS_RE = re.compile(
    r"(\bopen\s*-?\s*source\b|github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|\b(pip\s+install|npm\s+i(nstall)?|npx\s+|brew\s+install|cargo\s+install|docker\s+run|git\s+clone)\b|\b(mit|apache\s*2\.0)\s+licen[sc]e\b)",
    re.IGNORECASE,
)
_WAITLIST_RE = re.compile(
    r"\b(join\s+(the\s+)?waitlist|request\s+(early\s+)?access|early\s+access\s+waitlist|coming\s+soon|notify\s+me\s+when)\b",
    re.IGNORECASE,
)
_ENTERPRISE_GATE_RE = re.compile(
    r"\b(book\s+a\s+demo|schedule\s+a\s+(call|demo)|contact\s+sales|talk\s+to\s+sales|request\s+a\s+quote)\b",
    re.IGNORECASE,
)
_PRICE_DOLLAR_RE = re.compile(r"\$\s*\d+(?:\.\d{1,2})?\s*(?:/|\s*per\s*)\s*(?:mo|month|yr|year|seat|user)\b", re.IGNORECASE)
_DOCS_RE = re.compile(r"\b(documentation|api\s+reference|quickstart|sdk|cli|docs)\b", re.IGNORECASE)
_PLATFORM_ONLY_RE = re.compile(
    r"\b(download\s+for\s+(mac|macos|windows|ios)|available\s+on\s+the\s+app\s+store|apple\s+silicon|chrome\s+web\s+store|add\s+to\s+chrome|macos\s+\d+)\b",
    re.IGNORECASE,
)


@dataclass
class SanitizedSurface:
    url: str
    http_status: int
    load_ms: float
    access_status: str
    product_trait: str
    badges_stripped_n: int
    has_interactive_demo: bool
    has_free_tier: bool
    has_open_source: bool
    has_visible_pricing: bool
    has_docs: bool
    is_waitlist: bool
    is_enterprise_gated: bool
    is_platform_only: bool
    cta_texts: list[str]
    sanitized_text: str


def sanitize_text(raw_text: str, item_day: str | None = None) -> tuple[str, int]:
    """Strip PH badges, upvote mentions, traction counters, and post-launch year/month stamps."""
    if not raw_text:
        return "", 0
    text = raw_text
    n_ph = len(_PH_LEAK_RE.findall(text))
    # Remove entire lines/clauses centered on Product Hunt badges
    text = re.sub(r"[^.!?\n]*?" + _PH_LEAK_RE.pattern + r"[^.!?\n]*", " ", text, flags=re.IGNORECASE)
    n_tr = len(_TRACTION_LEAK_RE.findall(text))
    text = _TRACTION_LEAK_RE.sub("[REDACTED_METRIC]", text)

    # Strip explicit ISO / month-year dates strictly after item_day
    if item_day and len(item_day) >= 7:
        y_item, m_item = int(item_day[:4]), int(item_day[5:7])
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }

        def _scrub_iso(m: re.Match) -> str:
            yr, mo = int(m.group(1)), int(m.group(2))
            return "[REDACTED_DATE]" if (yr, mo) > (y_item, m_item) else m.group(0)

        text = re.sub(r"\b(202[5-9])-(0[1-9]|1[0-2])(?:-\d{2})?\b", _scrub_iso, text)

        def _scrub_mname(m: re.Match) -> str:
            mo = month_map.get(m.group(1)[:3].lower(), 0)
            yr = int(m.group(2))
            return "[REDACTED_DATE]" if (yr, mo) > (y_item, m_item) else m.group(0)

        text = re.sub(
            r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(202[5-9])\b",
            _scrub_mname,
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(r"\s+", " ", text).strip()
    return text, (n_ph + n_tr)


def parse_html_surface(
    html: str,
    url: str,
    http_status: int = 200,
    load_ms: float = 0.0,
    item_day: str | None = None,
) -> SanitizedSurface:
    """Parse raw HTML into leak-scrubbed structured product reality."""
    if not html or http_status <= 0 or http_status >= 400:
        return SanitizedSurface(
            url=url or "",
            http_status=http_status,
            load_ms=load_ms,
            access_status="dead_host" if http_status < 0 or http_status >= 500 else "block",
            product_trait="none",
            badges_stripped_n=0,
            has_interactive_demo=False,
            has_free_tier=False,
            has_open_source=False,
            has_visible_pricing=False,
            has_docs=False,
            is_waitlist=False,
            is_enterprise_gated=False,
            is_platform_only=False,
            cta_texts=[],
            sanitized_text="",
        )

    soup = BeautifulSoup(html, "lxml")
    stripped_dom = 0
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    # Remove PH embed iframes and links
    for el in soup.find_all(["iframe", "a", "img"]):
        attrs = " ".join(str(v) for v in (el.attrs or {}).values())
        if "producthunt.com" in attrs.lower():
            stripped_dom += 1
            el.decompose()

    title = (soup.title.string or "").strip() if soup.title else ""
    meta_desc = ""
    for m in soup.find_all("meta"):
        if str(m.get("name", "")).lower() in ("description", "og:description") or str(m.get("property", "")).lower() == "og:description":
            meta_desc = str(m.get("content") or "").strip()
            if meta_desc:
                break

    ctas = []
    seen_cta = set()
    for el in soup.find_all(["a", "button"]):
        t = " ".join(el.get_text(" ", strip=True).split())
        if 2 <= len(t) <= 45 and not _PH_LEAK_RE.search(t):
            tl = t.lower()
            if tl not in seen_cta:
                seen_cta.add(tl)
                ctas.append(t)
        if len(ctas) >= 12:
            break

    headings = [" ".join(h.get_text(" ", strip=True).split()) for h in soup.find_all(["h1", "h2", "h3"])[:12]]
    body_text = soup.get_text(" ", strip=True)
    raw_combined = f"Title: {title}\nSummary: {meta_desc}\nHeadings: {' | '.join(h for h in headings if h)}\nCTAs: {', '.join(ctas)}\nBody: {body_text[:4500]}"
    clean_txt, n_txt_leaks = sanitize_text(raw_combined, item_day=item_day)
    if len(clean_txt) < 80:
        return SanitizedSurface(
            url=url,
            http_status=http_status,
            load_ms=load_ms,
            access_status="js_only",
            product_trait="none",
            badges_stripped_n=stripped_dom + n_txt_leaks,
            has_interactive_demo=False,
            has_free_tier=False,
            has_open_source=False,
            has_visible_pricing=False,
            has_docs=False,
            is_waitlist=False,
            is_enterprise_gated=False,
            is_platform_only=False,
            cta_texts=ctas,
            sanitized_text=clean_txt,
        )

    return _surface_from_clean_text(
        clean_txt=clean_txt,
        url=url,
        http_status=http_status,
        load_ms=load_ms,
        badges_stripped=stripped_dom + n_txt_leaks,
        ctas=ctas,
    )


def surface_from_cached_scrape(rec: dict[str, Any], item_day: str | None = None) -> SanitizedSurface:
    """Build leak-scrubbed surface from launch-era `sites_ph.jsonl` record (zero survivorship drift!)."""
    url = str(rec.get("url") or "")
    status = int(rec.get("status") or -1)
    raw_text = str(rec.get("text") or "")
    if not url or status < 200 or status >= 400 or rec.get("parked") or len(raw_text.strip()) < 60:
        acc = "no_url" if not url else ("dead_host" if status < 0 or status >= 500 else "js_only")
        return SanitizedSurface(
            url=url, http_status=status, load_ms=0.0, access_status=acc, product_trait="none",
            badges_stripped_n=0, has_interactive_demo=False, has_free_tier=False, has_open_source=False,
            has_visible_pricing=False, has_docs=False, is_waitlist=False, is_enterprise_gated=False,
            is_platform_only=False, cta_texts=[], sanitized_text="",
        )
    clean_txt, n_leaks = sanitize_text(raw_text[:5500], item_day=item_day)
    return _surface_from_clean_text(clean_txt, url=url, http_status=status, load_ms=0.0, badges_stripped=n_leaks, ctas=[])


def _surface_from_clean_text(
    clean_txt: str,
    url: str,
    http_status: int,
    load_ms: float,
    badges_stripped: int,
    ctas: list[str],
) -> SanitizedSurface:
    has_demo = bool(_DEMO_RE.search(clean_txt))
    has_free = bool(_FREE_RE.search(clean_txt))
    has_oss = bool(_OSS_RE.search(clean_txt)) or "github.com/" in (url or "").lower()
    has_price = bool(_PRICE_DOLLAR_RE.search(clean_txt))
    has_docs = bool(_DOCS_RE.search(clean_txt))
    is_wait = bool(_WAITLIST_RE.search(clean_txt)) and not has_demo and not has_oss
    is_ent = bool(_ENTERPRISE_GATE_RE.search(clean_txt)) and not has_free and not has_oss
    is_plat = bool(_PLATFORM_ONLY_RE.search(clean_txt))

    if is_wait:
        trait = "waitlist_only"
    elif has_demo or has_oss:
        trait = "instant_demo"
    elif has_free:
        trait = "free_tier"
    elif is_plat:
        trait = "platform_only"
    else:
        trait = "none"

    return SanitizedSurface(
        url=url,
        http_status=http_status,
        load_ms=load_ms,
        access_status="clean",
        product_trait=trait,
        badges_stripped_n=badges_stripped,
        has_interactive_demo=has_demo,
        has_free_tier=has_free,
        has_open_source=has_oss,
        has_visible_pricing=has_price,
        has_docs=has_docs,
        is_waitlist=is_wait,
        is_enterprise_gated=is_ent,
        is_platform_only=is_plat,
        cta_texts=ctas,
        sanitized_text=clean_txt[:2400],
    )
