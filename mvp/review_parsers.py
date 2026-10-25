"""Parse G2 / Capterra / Product Hunt review pages (fetched in-house via mvp.review_fetch) into the review schema the
Apify actors produced (mvp.review_context): source, product, role, size, industry, time_used, rating, pros, cons,
text, date (plus name where the site shows it).

Each parser takes one page's HTML and returns its reviews; next_page_url() says where the next page is. Built against
real pages fetched Oct 2026 (fixtures in mvp/fixtures/reviews/).
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any

PER_PRODUCT = 50


def _lines(fragment: str) -> list[str]:
    """Visible text of an HTML fragment, one line per block element."""
    x = re.sub(r"(?is)<(script|style|svg|button)[^>]*>.*?</\1>", " ", fragment)
    x = re.sub(r"(?i)<br\s*/?>", "\n", x)
    x = re.sub(r"(?i)</(div|p|h\d|li|span|section|article)>", "\n", x)
    x = _html.unescape(re.sub(r"<[^>]+>", "", x))
    return [ln.strip() for ln in x.split("\n") if ln.strip()]


def _clean(lines: list[str]) -> list[str]:
    """Drop leftovers of a tag the split cut through (the card's own class attribute) and UI-only lines."""
    return [ln for ln in lines if '">' not in ln and ln not in ("Link Copied!",)]


# ---------------------------------------------------------------- Capterra

_CAP_STOP = ("Review Source", "View less", "Switched from", "Reasons for choosing", "Vendor Response", "Response from")


def parse_capterra(page: str, product: str = "") -> list[dict[str, Any]]:
    """Review cards on a capterra.com/p/<id>/<name>/reviews/ page (25 per page, server-rendered)."""
    start = page.find('data-test-id="review-cards-container"')
    if start < 0:
        return []
    out = []
    for card in re.split(r'<div class="e1xzmg0z c1ofrhif', page[start:])[1:]:
        lines = _clean(_lines(card))
        if not lines:
            continue
        try:
            used_i = next(i for i, ln in enumerate(lines) if ln.startswith("Used the software for"))
        except StopIteration:
            used_i = None
        head = lines[: used_i if used_i is not None else 4]
        name = head[0] if head else None
        meta = head[1:]
        size = next((m for m in meta if re.search(r"employees", m, re.I)), None)
        role = meta[0] if meta and meta[0] != size else None
        industry = next((m for m in meta[1:] if m != size), None)
        body = lines[(used_i or 0) + 1:]
        title = next((ln.strip('"“”') for ln in body if ln.startswith(('"', "“"))), None)
        date = next((ln for ln in body if re.fullmatch(r"[A-Z][a-z]+ \d{1,2}, \d{4}", ln)), None)
        rating = None
        if "Overall Rating" in body:
            i = body.index("Overall Rating")
            if i and re.fullmatch(r"\d(\.\d)?", body[i - 1]):
                rating = float(body[i - 1])

        def section(begin: tuple[str, ...], end: tuple[str, ...]) -> str:
            try:
                i = next(k for k, ln in enumerate(body) if ln in begin)
            except StopIteration:
                return ""
            out_lines = []
            for ln in body[i + 1:]:
                if ln in end or ln.startswith(end):
                    break
                out_lines.append(ln)
            return " ".join(out_lines)
        overall = ""
        if "10/10" in body or any(re.fullmatch(r"\d+/10", ln) for ln in body):
            k = next(k for k, ln in enumerate(body) if re.fullmatch(r"\d+/10", ln))
            rest = []
            for ln in body[k + 1:]:
                if ln in ("Pros", "Continue reading Pros", "Cons") or ln.startswith(_CAP_STOP):
                    break
                rest.append(ln)
            overall = " ".join(rest)
        pros = section(("Pros", "Continue reading Pros"), ("Cons",) + _CAP_STOP)
        cons = section(("Cons",), _CAP_STOP)
        if not (pros or cons or overall):
            continue
        out.append({"source": "capterra", "product": product, "name": name, "role": role, "size": size,
                    "industry": industry, "time_used": lines[used_i].split(":", 1)[1].strip() if used_i is not None else None,
                    "rating": rating, "title": title, "date": date, "pros": pros or None, "cons": cons or None,
                    "text": overall or None})
    return out


def capterra_reviews_url(url: str) -> str:
    """The /reviews/ page of a Capterra listing: discovery passes the product root (/p/<id>/<name>/), which shows a few
    review snippets but no review cards."""
    m = re.match(r"(https?://(?:www\.)?capterra\.com/p/\d+/[^/?#]+)", url)
    return f"{m.group(1)}/reviews/" if m else url


def capterra_next(url: str, page_no: int) -> str:
    return f"{capterra_reviews_url(url.split('?')[0])}?page={page_no}"


# ---------------------------------------------------------------- G2

_G2_TAIL = re.compile(r"\s*Review collected by and hosted on G2\.com\.?\s*$")


def parse_g2(page: str, product: str = "") -> list[dict[str, Any]]:
    """<article> review cards on a g2.com/products/<slug>/reviews page (10 per page, server-rendered)."""
    out = []
    for art in re.findall(r"(?is)<article\b.*?</article>", page):
        lines = [_G2_TAIL.sub("", ln) for ln in _clean(_lines(art))]
        lines = [ln for ln in lines if ln]
        date_i = next((i for i, ln in enumerate(lines) if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", ln)), None)
        if date_i is None:
            continue
        head = lines[:date_i]
        if head and re.fullmatch(r"[A-Z]{1,3}", head[0]):  # avatar initials
            head = head[1:]
        name = head[0] if head else None
        meta = head[1:]
        size = next((m for m in meta if re.search(r"emp\.|employees", m)), None)
        rest = [m for m in meta if m != size]
        verified = next((m for m in [name or ""] + rest if m.startswith("Verified User in ")), None)
        role = rest[0] if rest and not rest[0].startswith("Verified User") else None
        industry = rest[1] if len(rest) > 1 else (verified.removeprefix("Verified User in ") if verified else None)
        body = lines[date_i + 1:]
        title = next((ln.strip('"“”') for ln in body if ln.startswith(('"', "“"))), None)
        rating = next((float(m.group(1)) for ln in body if (m := re.fullmatch(r"(\d(?:\.\d)?)/5", ln))), None)

        def answer(prefix: str) -> str:
            try:
                i = next(k for k, ln in enumerate(body) if ln.startswith(prefix))
            except StopIteration:
                return ""
            got = []
            for ln in body[i + 1:]:
                if ln.startswith(("What do you like best", "What do you dislike", "What problems is", "Recommendations to")):
                    break
                got.append(ln)
            return " ".join(got)
        pros, cons, problems = answer("What do you like best"), answer("What do you dislike"), answer("What problems is")
        if not (pros or cons):
            continue
        out.append({"source": "g2", "product": product, "name": None if name and name.startswith("Verified User") else name,
                    "role": role, "size": size, "industry": industry, "rating": rating, "title": title,
                    "date": lines[date_i], "pros": pros or None, "cons": cons or None, "problems": problems or None})
    return out


def g2_next(url: str, page_no: int) -> str:
    return f"{url.split('?')[0]}?page={page_no}"


# ---------------------------------------------------------------- Product Hunt

_DECODER = json.JSONDecoder()


def parse_producthunt(page: str, product: str = "") -> list[dict[str, Any]]:
    """DetailedReview objects embedded as JSON in a producthunt.com/products/<slug>/reviews page (~20 per page)."""
    found: dict[str, dict[str, Any]] = {}
    for m in re.finditer(r'\{"__typename":"DetailedReview",', page):
        try:
            obj, _ = _DECODER.raw_decode(page, m.start())
        except ValueError:
            continue
        user = obj.get("user") or {}
        parts = [(obj.get("overallExperience"), ""), (obj.get("positiveFeedback"), "Liked: "),
                 (obj.get("negativeFeedback"), "Disliked: "), (obj.get("alternativesFeedback"), "Vs alternatives: ")]
        text = " / ".join(f"{label}{_html.unescape(str(v))}" for v, label in parts if v)
        if not obj.get("id") or not text or not user:
            continue
        found[str(obj["id"])] = {"source": "producthunt", "product": product, "name": user.get("name"),
                                 "role": user.get("headline") or None, "rating": obj.get("overallRating"),
                                 "text": text, "pros": obj.get("positiveFeedback"), "cons": obj.get("negativeFeedback"),
                                 "date": (obj.get("createdAt") or "")[:10], "review_type": obj.get("reviewType"),
                                 "title": str(obj["id"])}
    return list(found.values())


def producthunt_next(url: str, page_no: int) -> str:
    return f"{url.split('?')[0]}?page={page_no}"


# ---------------------------------------------------------------- helpers shared by the JSON-LD based parsers

def json_ld(page: str) -> list[Any]:
    out = []
    for block in re.findall(r'(?is)<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', page):
        try:
            out.append(json.loads(block))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- collecting a product's reviews across pages

PARSERS: dict[str, tuple[Any, Any]] = {"capterra": (parse_capterra, capterra_next), "g2": (parse_g2, g2_next),
                                       "producthunt": (parse_producthunt, producthunt_next)}


def collect(platform: str, url: str, product: str, fetch_page: Any, *, want: int = PER_PRODUCT,
            max_pages: int = 6) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and parse pages of one product's reviews until `want` reviews, a page that loads but adds nothing, or two
    failed pages in a row (G2 paging through the Apify Unblocker times out or 502s now and then, Oct 2026).
    fetch_page(url) -> (status, html). Returns (reviews, {pages, statuses})."""
    parse, next_url = PARSERS[platform]
    reviews: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    statuses = []
    page_url = capterra_reviews_url(url) if platform == "capterra" else url
    failures = 0
    for page_no in range(1, max_pages + 1):
        status, page = fetch_page(page_url)
        statuses.append(status)
        rows = parse(page, product) if status == 200 else []
        fresh = [r for r in rows if (r.get("name"), r.get("title"), r.get("date"), (r.get("text") or r.get("pros") or "")[:60]) not in seen]
        for r in fresh:
            seen.add((r.get("name"), r.get("title"), r.get("date"), (r.get("text") or r.get("pros") or "")[:60]))
        reviews += fresh
        failures = failures + 1 if not rows else 0
        if len(reviews) >= want or (rows and not fresh) or failures >= 2:
            break
        page_url = next_url(url, page_no + 1)
    return reviews[:want], {"pages": len(statuses), "statuses": statuses}
