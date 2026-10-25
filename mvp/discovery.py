"""Part 1 of a study: discovery. Product URL in; competitors, real users and comparison tasks out.

Nothing here opens a browser or runs a simulated user. Every web page used is one Google returned (Gemini's Google
Search grounding on Vertex, queries in parallel); nothing is reached by guessing a URL or slug. Apify only scrapes
review pages. Steps, in order:

1. Read the product's own site (homepage plus up to two about/pricing/features pages).
2. One LLM call turns that into a product profile (what it is, who it is for, search keywords).
3. Gather competitor candidates: web searches ("<name> alternatives", ...) and similar Product Hunt launches (API:
   top posts in the topics that match the product).
4. One LLM call picks the closest competitors; each homepage must appear in Google results for "<name> <category>",
   and is probed live.
5. Real users: for the product and each competitor, Google site:g2.com / site:capterra.com / site:producthunt.com
   finds its exact review pages; each page is scraped by URL (G2 and Capterra reviewers with job titles, Product
   Hunt reviewers with headlines). With few reviews, the next-closest similar products are scraped too.
6. One LLM call writes user segments (grounded in those users) and tasks to run on the product and every competitor.

Every step is recorded in a trace (what was asked, how long it took, what came back) so the /discovery page can show
what the agent searched and retrieved. Secrets: APIFY_TOKEN (review scrapes) and PH_TOKEN, or PH_CLIENT_ID +
PH_CLIENT_SECRET (Product Hunt API, same names as scripts/ph_crawl.py); a missing one skips that source, and the trace
says so.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from mvp.competitor_urls import registrable_host, same_site, unwrap_search_url

LLM = Callable[[list[dict[str, str]]], Awaitable[str]]

PH_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0.0.0 Safari/537.36")
_SUBPAGE_RE = re.compile(r"/(about|pricing|features|product|how-it-works|customers|solutions)(/|$)", re.I)
# Enough reviews to describe users without scraping more similar products.
MIN_REVIEWS = 30
REVIEW_WAIT_S = float(os.environ.get("MVP_DISCOVERY_REVIEW_WAIT_S", "240"))


PH_TOKEN_URL = "https://api.producthunt.com/v2/oauth/token"
_PH_MINTED: dict[str, str] = {}  # client id -> client-credentials access token


# Credentials passed with one run (the /discovery form) override the server's for that run only. A ContextVar keeps
# concurrent runs apart and reaches asyncio.to_thread workers; nothing here is stored on the run or written to disk.
CREDENTIAL_NAMES = ("APIFY_TOKEN", "PH_TOKEN", "PH_CLIENT_ID", "PH_CLIENT_SECRET")
_RUN_CREDS: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("discovery_creds", default={})


# Keys saved once through the /discovery page (POST /api/discovery/keys), for servers whose Secret Manager lacks them.
# Outside the app directory (each deploy replaces /opt/usersim/app); falls back to the runs dir where /var/lib is not
# writable. Never returned by any endpoint: keys_status() reports presence only.
_KEYS_FILE: Path | None = None


def keys_file() -> Path:
    global _KEYS_FILE
    if _KEYS_FILE is None:
        from mvp.paths import MVP_RUNS_DIR

        env = os.environ.get("MVP_DISCOVERY_KEYS_FILE")
        for cand in ([Path(env)] if env else [Path("/var/lib/usersim/discovery_keys.json"), MVP_RUNS_DIR / "_discovery_keys.json"]):
            try:
                cand.parent.mkdir(parents=True, exist_ok=True)
                if os.access(cand.parent, os.W_OK):
                    _KEYS_FILE = cand
                    break
            except OSError:
                continue
        else:
            _KEYS_FILE = MVP_RUNS_DIR / "_discovery_keys.json"
    return _KEYS_FILE


def stored_keys() -> dict[str, str]:
    try:
        data = json.loads(keys_file().read_text())
    except (OSError, ValueError):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in CREDENTIAL_NAMES and str(v or "").strip()}


def save_keys(new: dict[str, str], current_apify: str = "") -> tuple[bool, str]:
    """Save keys on the server. Once an Apify key is stored, replacing anything needs that key (proof of ownership)."""
    old = stored_keys()
    if old.get("APIFY_TOKEN") and (current_apify or "").strip() != old["APIFY_TOKEN"]:
        return False, "keys are already saved; to replace them, also send the currently saved Apify token"
    merged = old | {k: v.strip() for k, v in new.items() if k in CREDENTIAL_NAMES and v and v.strip()}
    path = keys_file()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(merged, f)
    os.replace(tmp, path)
    return True, "saved"


def keys_status() -> dict[str, dict[str, Any]]:
    """Which keys a run would use and from where (never the values)."""
    from mvp import review_context

    stored = stored_keys()
    out = {}
    for name in CREDENTIAL_NAMES:
        env = (os.environ.get(name) or "").strip() or (review_context.apify_token() if name == "APIFY_TOKEN" else "")
        out[name] = {"present": bool(stored.get(name) or env), "source": "saved" if stored.get(name) else ("server" if env else "missing")}
    return out


def _cred(name: str) -> str:
    """Per-run key, else the key saved through the page, else the server's environment / Secret Manager."""
    return (_RUN_CREDS.get().get(name) or stored_keys().get(name) or os.environ.get(name) or "").strip()


def ph_configured() -> bool:
    return bool(_cred("PH_TOKEN") or (_cred("PH_CLIENT_ID") and _cred("PH_CLIENT_SECRET")))


async def ph_bearer() -> str:
    """PH_TOKEN (developer token), else a public-scope token minted from PH_CLIENT_ID + PH_CLIENT_SECRET."""
    token = _cred("PH_TOKEN")
    if token:
        return token
    cid, secret = _cred("PH_CLIENT_ID"), _cred("PH_CLIENT_SECRET")
    if not (cid and secret):
        raise RuntimeError("set PH_TOKEN, or PH_CLIENT_ID and PH_CLIENT_SECRET")
    if cid not in _PH_MINTED:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(PH_TOKEN_URL, json={"client_id": cid, "client_secret": secret,
                                                      "grant_type": "client_credentials"})
            r.raise_for_status()
            _PH_MINTED[cid] = r.json()["access_token"]
    return _PH_MINTED[cid]


@dataclass
class Step:
    id: int
    kind: str  # fetch | search | llm | producthunt | probe | reviews
    title: str
    status: str = "running"  # running | done | error | skipped
    input: Any = None
    summary: str = ""
    data: Any = None
    started_at: float = field(default_factory=time.time)
    ms: int | None = None


@dataclass
class Discovery:
    id: str
    url: str
    max_competitors: int = 2
    task_count: int = 6
    scrape_reviews: bool = True
    status: str = "running"  # running | done | error
    error: str | None = None
    steps: list[Step] = field(default_factory=list)
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Trace:
    """Records each step of one discovery run; on_change lets the caller persist after every update."""

    def __init__(self, run: Discovery, on_change: Callable[[Discovery], None] | None = None):
        self.run = run
        self._on_change = on_change or (lambda _r: None)

    def start(self, kind: str, title: str, input: Any = None) -> Step:
        step = Step(id=len(self.run.steps) + 1, kind=kind, title=title, input=input)
        self.run.steps.append(step)
        self._on_change(self.run)
        return step

    def end(self, step: Step, status: str = "done", summary: str = "", data: Any = None) -> None:
        step.status, step.summary, step.data = status, summary, data
        step.ms = int((time.time() - step.started_at) * 1000)
        self._on_change(self.run)


# ---------------------------------------------------------------- sources

def _clean_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", html)
    text = unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


def _meta(html: str, name: str) -> str:
    m = re.search(rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)', html, re.I) \
        or re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']', html, re.I)
    return unescape(m.group(1)).strip() if m else ""


def parse_page(url: str, html: str) -> dict[str, Any]:
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    links = []
    for href in re.findall(r'<a[^>]+href=["\']([^"\'#]+)', html, re.I):
        full = urljoin(url, unescape(href))
        if full.startswith("http") and same_site(full, url) and _SUBPAGE_RE.search(urlparse(full).path):
            links.append(full.split("?")[0].rstrip("/"))
    return {"url": url, "title": unescape(title.group(1)).strip() if title else "",
            "description": _meta(html, "description") or _meta(html, "og:description"),
            "site_name": _meta(html, "og:site_name"), "text": _clean_text(html)[:6000],
            "subpages": list(dict.fromkeys(links))}


async def fetch_html(url: str) -> tuple[int, str, str]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        r = await client.get(url)
        return r.status_code, str(r.url), r.text or ""


def parse_ddg(html: str, limit: int) -> list[dict[str, str]]:
    out = []
    for block in re.split(r'class="result results_links', html)[1:]:
        a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        href = unwrap_search_url(unescape(a.group(1).strip()))
        if not href.startswith("http"):
            continue
        snip = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        out.append({"title": _clean_text(a.group(2))[:140], "url": href,
                    "snippet": _clean_text(snip.group(1))[:300] if snip else ""})
        if len(out) >= limit:
            break
    return out


SEARCH_CONCURRENCY = int(os.environ.get("MVP_DISCOVERY_SEARCH_CONCURRENCY", "16"))
# gemini-2.5-flash-lite runs the search but returns no grounding links (checked Oct 2026); 2.5 Flash returns them.
SEARCH_MODEL = os.environ.get("MVP_DISCOVERY_SEARCH_MODEL", "gemini-2.5-flash")
_SEARCH_GATE: asyncio.Semaphore | None = None


async def _resolve(client: httpx.AsyncClient, uri: str) -> str:
    """Grounding links are vertexaisearch.cloud.google.com redirects; the Location header is the real page."""
    if "grounding-api-redirect" not in uri:
        return uri
    try:
        r = await client.get(uri, follow_redirects=False)
        return r.headers.get("location") or uri
    except httpx.HTTPError:
        return uri


async def google_search(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Google results through Gemini's Google Search grounding on Vertex (the LLM this repo already uses): one call,
    a few seconds, no extra key and no Apify. Returns the pages Google returned for the query."""
    from auth import cached_vertex_credentials, vertex_credentials
    from capability.gemini_config import _endpoint

    global _SEARCH_GATE
    if _SEARCH_GATE is None:
        _SEARCH_GATE = asyncio.Semaphore(SEARCH_CONCURRENCY)
    payload = {"contents": [{"role": "user", "parts": [{"text":
                   f"Run exactly this Google search and list every result you get, with its URL:\n{query}"}]}],
               "tools": [{"googleSearch": {}}], "generationConfig": {"temperature": 0}}
    async with _SEARCH_GATE:
        creds = cached_vertex_credentials() or await asyncio.to_thread(vertex_credentials)
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(_endpoint(SEARCH_MODEL), json=payload,
                                  headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"})
            r.raise_for_status()
            meta = ((r.json().get("candidates") or [{}])[0].get("groundingMetadata") or {})
            chunks = [c["web"] for c in meta.get("groundingChunks") or [] if (c.get("web") or {}).get("uri")]
            urls = await asyncio.gather(*(_resolve(client, c["uri"]) for c in chunks))
    rows, seen = [], set()
    for c, url in zip(chunks, urls):
        if url.startswith("http") and url not in seen:
            seen.add(url)
            rows.append({"title": (c.get("title") or "")[:140], "url": url, "snippet": "", "engine": "google"})
    return rows[:limit]


async def ddg_search(query: str, limit: int = 8) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        r = await client.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
    # 202 = DuckDuckGo's bot check (seen from some cloud IPs): no results rather than a parse of the challenge page
    rows = parse_ddg(r.text or "", limit) if r.status_code == 200 else []
    for row in rows:
        row["engine"] = "duckduckgo"
    return rows


async def web_search_many(queries: list[str], *, limit: int = 8) -> dict[str, list[dict[str, str]]]:
    """Every query at the same time. 'site:' queries go to DuckDuckGo (Gemini's search drops the site: operator);
    the rest to Google via Gemini grounding, with DuckDuckGo only if that call fails."""
    async def one(q: str) -> list[dict[str, str]]:
        if q.startswith("site:"):
            try:
                return await ddg_search(q, limit)
            except httpx.HTTPError:
                return []
        try:
            return await google_search(q, limit)
        except Exception as exc:  # noqa: BLE001 - fall back to DuckDuckGo for this query
            print(f"[discovery] google search failed for {q!r}: {exc!r}"[:300], flush=True)
        try:
            return await ddg_search(q, limit)
        except httpx.HTTPError:
            return []
    rows = await asyncio.gather(*(one(q) for q in queries))
    return dict(zip(queries, rows))


async def web_search(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    return (await web_search_many([query], limit=limit))[query]


_PH_POST_FIELDS = """name slug tagline description url website votesCount commentsCount reviewsCount reviewsRating
  topics(first: 6) { edges { node { name slug } } }"""


async def ph_query(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    token = await ph_bearer()
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(PH_ENDPOINT, json={"query": query, "variables": variables or {}},
                              headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        r.raise_for_status()
        body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"Product Hunt: {body['errors'][0].get('message')}")
    return body.get("data") or {}


def _edges(conn: Any) -> list[dict[str, Any]]:
    return [e["node"] for e in ((conn or {}).get("edges") or []) if e.get("node")]


def _ph_post(node: dict[str, Any]) -> dict[str, Any]:
    out = {k: node.get(k) for k in ("name", "slug", "tagline", "description", "url", "website", "votesCount",
                                    "commentsCount", "reviewsCount", "reviewsRating")}
    out["topics"] = [t["slug"] for t in _edges(node.get("topics"))]
    return out


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# Topics too broad to say anything about similar products.
GENERIC_PH_TOPICS = frozenset({"tech", "technology", "web-app", "android", "iphone", "mac", "windows", "chrome-extensions"})


async def ph_topic_posts(topic: str, first: int = 15) -> list[dict[str, Any]]:
    data = await ph_query(f"query($t: String!, $n: Int!) {{ posts(topic: $t, order: VOTES, first: $n) "
                          f"{{ edges {{ node {{ {_PH_POST_FIELDS} }} }} }} }}", {"t": topic, "n": first})
    return [_ph_post(n) for n in _edges(data.get("posts"))]


async def ph_topics(query: str, first: int = 3) -> list[dict[str, Any]]:
    data = await ph_query("query($q: String!, $n: Int!) { topics(query: $q, first: $n, order: FOLLOWERS_COUNT) "
                          "{ edges { node { name slug postsCount } } } }", {"q": query, "n": first})
    return _edges(data.get("topics"))


def apify_token() -> str | None:
    from mvp import review_context

    return _RUN_CREDS.get().get("APIFY_TOKEN") or stored_keys().get("APIFY_TOKEN") or review_context.apify_token()


# Each platform's reviews come from its exact page found on Google. Actors checked live (Oct 2026):
# zen-studio takes a G2 URL directly and returns job titles (it also auto-finds other platforms by name: dropped);
# trakk takes Capterra product URLs as {"url": ...}; eiv takes a Product Hunt /products/<slug>/reviews URL.
G2_ACTOR = "zen-studio~software-review-scraper"
CAPTERRA_ACTOR = "trakk~capterra-reviews-scraper"
PH_REVIEWS_ACTOR = "eiv~producthunt-reviews-scraper"
REVIEW_ACTORS = {"g2": G2_ACTOR, "capterra": CAPTERRA_ACTOR, "producthunt": PH_REVIEWS_ACTOR}
PLATFORM_LABEL = {"g2": "G2", "capterra": "Capterra", "producthunt": "Product Hunt"}
_PAGE_RES = {"g2": re.compile(r"g2\.com/products/([a-z0-9-]+)", re.I),
             "capterra": re.compile(r"capterra\.com/p/(\d+)/([A-Za-z0-9_-]+)", re.I),
             "producthunt": re.compile(r"producthunt\.com/products/([a-z0-9-]+)", re.I)}
REVIEWS_PER_SITE = 50


def page_queries(platform: str, name: str) -> list[str]:
    """Searches that find a product's page on one review site. Gemini's Google search returns only a handful of
    sources per query, and the two phrasings find different pages (Oct 2026: each ~half of 12 pages, together 8/12),
    so all are run at once and merged; the site: query goes to DuckDuckGo."""
    return [f"{name} reviews on {PLATFORM_LABEL[platform]}", f"{name} reviews {platform}.com", f"site:{platform}.com {name} reviews"]


# Edition suffixes a product's own listing can carry (Capterra lists Vimeo as 'Vimeo-Pro', G2 has 'dailymotion-pro').
_EDITION = r"(?:\d+|pro|business|enterprise|teams?|app|software|platform|cloud|online|hq)"


def _same_name(found: str, wanted: str) -> bool:
    """Exact product name, a vendor prefix ('atlassian-jira'), or an edition / numbered slug ('vimeo-pro', 'linear-2');
    never a longer different product ('jira-service-management', 'youtube-live', 'linear-agent')."""
    f, w = _slug(found), _slug(wanted)
    return bool(f) and (f == w or f.endswith("-" + w) or bool(re.fullmatch(re.escape(w) + "-" + _EDITION, f)))


def review_page(rows: list[dict[str, str]], platform: str, name: str) -> tuple[str | None, str]:
    """The product's own G2 / Capterra / Product Hunt page from search results (first whose name matches), and why."""
    seen = []
    for r in rows:
        url = r.get("url") or ""
        m = _PAGE_RES[platform].search(url)
        if not m:
            continue
        page_name = m.group(2) if platform == "capterra" else m.group(1)
        if _same_name(page_name, name):
            canon = {"g2": lambda: f"https://www.g2.com/products/{m.group(1).lower()}/reviews",
                     "capterra": lambda: f"https://www.capterra.com/p/{m.group(1)}/{m.group(2)}/",
                     "producthunt": lambda: f"https://www.producthunt.com/products/{m.group(1).lower()}/reviews"}[platform]()
            return canon, f"matched {url}"
        seen.append(page_name)
    return None, (f"{platform} pages in the results are for other products: {sorted(set(seen))[:8]}" if seen
                  else f"no {platform} product page in the search results")


def _redact(msg: str) -> str:
    from mvp import review_context

    tok = apify_token() or ""
    return re.sub(r"apify_api_[A-Za-z0-9]+", "<redacted>", review_context._redact(msg, tok) if tok else msg)


def scrape_review_page(platform: str, url: str) -> list[dict[str, Any]]:
    """Reviews from one exact G2 / Capterra / Product Hunt page via Apify (blocking), cached per URL."""
    from mvp import review_context

    token = apify_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN missing")
    cache = review_context._APIFY_CACHE / f"page2-{_slug(url)}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    if platform == "g2":
        items = review_context._apify_run(G2_ACTOR, {"query": url, "platforms": ["g2", "capterra"], "maxResults": 100,
                                                     "sort": "most_recent", "starRatings": []}, token, wait_s=900.0)
        rows = [review_context._all_in_one_item(x) for x in items if x.get("platform") == "g2"]
    elif platform == "capterra":
        items = review_context._apify_run(CAPTERRA_ACTOR, {"productUrls": [{"url": url}], "maxReviewsPerProduct": REVIEWS_PER_SITE,
                                                           "maxItems": REVIEWS_PER_SITE, "includeProductAggregate": False}, token)
        rows = [{"source": "capterra", "product": r.get("productName") or "", "role": r.get("reviewerJobTitle"),
                 "size": r.get("reviewerCompanySize"), "industry": r.get("reviewerIndustry"),
                 "time_used": r.get("timeUsedProduct"), "rating": r.get("overallRating"), "pros": r.get("pros"),
                 "cons": r.get("cons"), "date": r.get("publishedDate")} for r in items]
    else:
        items = review_context._apify_run(PH_REVIEWS_ACTOR, {"startUrls": [{"url": url}],
                                                             "maxReviewsPerProduct": REVIEWS_PER_SITE}, token, wait_s=600.0)
        rows = [{"source": "producthunt", "product": r.get("productName") or "", "name": r.get("reviewerName"),
                 "role": r.get("reviewerHeadline"), "rating": r.get("overallRating"),
                 "text": " / ".join(str(x) for x in (r.get("overallExperience"), r.get("positiveFeedback") and f"Liked: {r['positiveFeedback']}",
                                                     r.get("negativeFeedback") and f"Disliked: {r['negativeFeedback']}",
                                                     r.get("alternativesFeedback") and f"Vs alternatives: {r['alternativesFeedback']}") if x),
                 "date": (r.get("createdAt") or "")[:10], "review_type": r.get("reviewType")} for r in items]
    review_context._APIFY_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def _reviewer(r: dict[str, Any]) -> dict[str, Any]:
    text = r.get("text") or " / ".join(x for x in (r.get("pros") and f"Liked: {r['pros']}",
                                                   r.get("cons") and f"Disliked: {r['cons']}") if x)
    return {"source": r.get("source"), "product": r.get("product"), "name": r.get("name"), "role": r.get("role"), "size": r.get("size"),
            "industry": r.get("industry"), "rating": r.get("rating"), "time_used": r.get("time_used"),
            "text": _clean_text(str(text or ""))[:600], "date": r.get("date")}


# ---------------------------------------------------------------- the agent

def _json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


async def _default_llm(messages: list[dict[str, str]]) -> str:
    from capability.gemini_config import gemini_chat

    return await gemini_chat(messages, temperature=0.3, json_mode=True)


def _norm_url(url: str) -> str:
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


async def _probe(url: str) -> tuple[bool, str]:
    from mvp.competitor_urls import filter_live_competitor_urls

    live, dropped = await filter_live_competitor_urls([url], product_url="https://usersim.invalid/", limit=1)
    return (True, live[0]) if live else (False, dropped[0][1] if dropped else "unreachable")


class DiscoveryAgent:
    """Runs one discovery. Sources are attributes so tests (and dry runs) can replace them."""

    def __init__(self, run: Discovery, *, llm: LLM | None = None,
                 on_change: Callable[[Discovery], None] | None = None, credentials: dict[str, str] | None = None):
        self.run = run
        self._credentials = {k: v.strip() for k, v in (credentials or {}).items() if k in CREDENTIAL_NAMES and v and v.strip()}
        self.trace = Trace(run, on_change)
        self.llm = llm or _default_llm
        self.fetch_html = fetch_html
        self.web_search_many = web_search_many
        self.ph_topic_posts = ph_topic_posts
        self.ph_topics = ph_topics
        self.ph_configured = ph_configured
        self.scrape_review_page = scrape_review_page
        self.apify_token = apify_token
        self.probe = _probe

    async def _ask(self, title: str, system: str, prompt: str) -> dict[str, Any]:
        step = self.trace.start("llm", title, {"prompt": prompt[:12000]})
        try:
            out = _json(await self.llm([{"role": "system", "content": system}, {"role": "user", "content": prompt}]))
        except Exception as exc:
            self.trace.end(step, "error", repr(exc)[:300])
            raise
        self.trace.end(step, "done", ", ".join(f"{k}: {len(v) if isinstance(v, list) else 1}" for k, v in out.items()), out)
        return out

    async def _search_many(self, queries: list[str]) -> dict[str, list[dict[str, str]]]:
        """One batched search; one trace step per query."""
        queries = list(dict.fromkeys(queries))
        steps = {q: self.trace.start("search", f"Web search: {q}", {"query": q, "engine": "google (gemini grounding)"}) for q in queries}
        try:
            got = await self.web_search_many(queries)
        except Exception as exc:
            for st in steps.values():
                self.trace.end(st, "error", repr(exc)[:300])
            return {q: [] for q in queries}
        for q, st in steps.items():
            rows = got.get(q) or []
            engines = sorted({r.get("engine") or "?" for r in rows})
            self.trace.end(st, "done", f"{len(rows)} results" + (f" ({', '.join(engines)})" if rows else ""), rows)
        return {q: got.get(q) or [] for q in queries}

    async def _search(self, query: str) -> list[dict[str, str]]:
        return (await self._search_many([query]))[query]

    # 1. the product's own site
    async def read_site(self) -> dict[str, Any]:
        url = _norm_url(self.run.url)
        step = self.trace.start("fetch", f"Read {url}", {"url": url})
        try:
            status, final, html = await self.fetch_html(url)
            home = parse_page(final, html)
        except Exception as exc:
            self.trace.end(step, "error", repr(exc)[:300])
            return {"url": url, "pages": []}
        pages = [home]
        self.trace.end(step, "done" if status < 400 else "error",
                       f"HTTP {status}, {len(home['text'])} chars, title '{home['title'][:80]}'",
                       {k: home[k] for k in ("url", "title", "description", "subpages")} | {"text": home["text"][:2000]})
        for sub in home["subpages"][:2]:
            s = self.trace.start("fetch", f"Read {sub}", {"url": sub})
            try:
                st, fin, h = await self.fetch_html(sub)
                page = parse_page(fin, h)
                pages.append(page)
                self.trace.end(s, "done", f"HTTP {st}, {len(page['text'])} chars", {"title": page["title"], "text": page["text"][:1500]})
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
        return {"url": final, "pages": pages}

    # 2. profile
    async def profile(self, site: dict[str, Any], about: list[dict[str, str]]) -> dict[str, Any]:
        pages = "\n\n".join(f"### {p['url']}\nTitle: {p['title']}\nDescription: {p['description']}\n{p['text'][:4000]}"
                            for p in site["pages"]) or "(the site could not be read)"
        hits = "\n".join(f"- {r['title']} ({r['url']}): {r['snippet']}" for r in about) or "(none)"
        return await self._ask(
            "Understand the product",
            "You output valid JSON only. Describe the product from the supplied evidence; never guess from the domain.",
            f"""Product URL: {site['url']}

THE PRODUCT'S OWN PAGES:
{pages[:12000]}

WEB SEARCH RESULTS ABOUT IT:
{hits}

Return JSON:
{{"name": "product name", "one_liner": "what it is in one sentence", "category": "software category, 2-4 words",
  "what_they_do": "3-4 sentences: what the product does and how", "target_users": ["who it is for", "..."],
  "key_features": ["feature named on the site", "..."], "pricing": "pricing model if stated, else ''",
  "search_terms": ["2-4 short phrases a buyer would search to find products like this"],
  "ph_topics": ["2-3 Product Hunt topic names this fits, e.g. 'Productivity', 'Developer Tools'"]}}""")

    # 3. candidates
    async def product_hunt(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        """Similar Product Hunt launches: top posts in the topics that match the product (API topics search)."""
        if not self.ph_configured():
            s = self.trace.start("producthunt", "Product Hunt launches")
            self.trace.end(s, "skipped", "PH_TOKEN (or PH_CLIENT_ID + PH_CLIENT_SECRET) is not set")
            return []
        topics: list[str] = []
        for q in profile.get("ph_topics") or []:
            if len(topics) >= 3:
                break
            s = self.trace.start("producthunt", f"Product Hunt topic search '{q}'", {"query": "topics(query)", "q": q})
            try:
                found = [t for t in await self.ph_topics(q) if t["slug"] not in GENERIC_PH_TOPICS]
                self.trace.end(s, "done", ", ".join(t["slug"] for t in found) or "no topics", found)
                topics += [t["slug"] for t in found[:1] if t["slug"] not in topics]
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
        posts: list[dict[str, Any]] = []
        for t in topics[:3]:
            s = self.trace.start("producthunt", f"Top Product Hunt posts in '{t}'", {"query": "posts(topic, order: VOTES)", "topic": t})
            try:
                rows = await self.ph_topic_posts(t)
                self.trace.end(s, "done", f"{len(rows)} posts: " + ", ".join(r["name"] for r in rows[:8]), rows)
                posts += rows
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
        seen, uniq = {_slug(profile.get("name") or "")}, []
        for p in posts:
            if p["slug"] not in seen:
                seen.add(p["slug"])
                uniq.append(p)
        return uniq

    # 4. pick competitors
    async def pick(self, profile: dict[str, Any], web: list[dict[str, str]], ph: list[dict[str, Any]]) -> list[dict[str, Any]]:
        web_txt = "\n".join(f"- {r['title']} ({r['url']}): {r['snippet']}" for r in web[:30]) or "(none)"
        ph_txt = "\n".join(f"- {p['name']} [slug {p['slug']}]: {p['tagline']} ({p['votesCount']} votes; topics {', '.join(p['topics'][:3])})"
                           for p in ph[:40]) or "(none)"
        want = self.run.max_competitors
        out = await self._ask(
            "Pick competitors",
            "You output valid JSON only. You pick real products with real public homepages.",
            f"""The product: {profile.get('name')} — {profile.get('one_liner')}
Category: {profile.get('category')}. For: {', '.join(profile.get('target_users') or [])}.
Key features: {', '.join(profile.get('key_features') or [])}

WEB SEARCH RESULTS (alternatives / competitors pages):
{web_txt}

SIMILAR PRODUCT HUNT LAUNCHES:
{ph_txt}

Rank up to {want + 4} products a buyer of {profile.get('name')} would seriously compare it with: same job, same kind of
user. Prefer candidates named in the evidence above; you may add a well-known direct competitor the evidence missed
(set source to "model_knowledge"). Never list {profile.get('name')} itself, review sites, or listicles.

Return JSON:
{{"candidates": [{{"name": "...", "url": "https://their-homepage", "why": "one sentence: what overlaps and how they differ",
  "overlap": "direct|partial|adjacent", "source": "web|producthunt|model_knowledge"}}]}}""")
        return [c for c in (out.get("candidates") or []) if c.get("name") and c.get("url")]

    async def keep_live(self, candidates: list[dict[str, Any]], category: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(chosen competitors, the remaining candidates as similar products). A homepage is taken from Google results
        for '<name> <category>', never from the LLM alone; candidates Google cannot place, or whose site is down, are dropped."""
        from mvp.competitor_urls import _NON_PRODUCT_HOSTS

        cands = [c for c in candidates if not same_site(c["url"], self.run.url)]
        q_of = {c["name"]: f"{c['name']} {category}".strip() for c in cands}
        found = await self._search_many(list(q_of.values()))
        chosen, rest, checks = [], [], []
        step = self.trace.start("probe", "Confirm competitor homepages on Google and check they are live",
                                {"candidates": [{"name": c["name"], "llm_url": c["url"]} for c in cands]})
        for c in cands:
            first_url: dict[str, str] = {}  # host -> its result URL closest to a homepage (fewest path segments)
            for r in found.get(q_of[c["name"]]) or []:
                h = registrable_host(r["url"])
                if not h or any(h == b or h.endswith("." + b) for b in _NON_PRODUCT_HOSTS):
                    continue
                depth = len([x for x in urlparse(r["url"]).path.split("/") if x])
                if h not in first_url or depth < len([x for x in urlparse(first_url[h]).path.split("/") if x]):
                    first_url[h] = r["url"]
            hosts = list(first_url)
            brand = _slug(c["name"]).replace("-", "")
            llm_host = registrable_host(c["url"])
            if llm_host in hosts:
                url, how = first_url[llm_host], "the LLM's site is in the Google results"
            else:
                match = next((h for h in hosts if brand and brand in h.replace("-", "").replace(".", "")), None)
                if not match:
                    checks.append({"name": c["name"], "ok": False, "why": f"no homepage in Google results (hosts: {hosts[:5]})"})
                    continue
                url, how = first_url[match], f"Google result host contains '{brand}'"
            if len(chosen) >= self.run.max_competitors:
                rest.append(c | {"url": url})
                continue
            try:
                ok, info = await self.probe(url)
            except Exception as exc:
                ok, info = False, repr(exc)[:200]
            checks.append({"name": c["name"], "url": url, "how": how, "ok": ok, "why": "" if ok else info})
            if ok:
                chosen.append(c | {"url": info})
        self.trace.end(step, "done", f"{len(chosen)} confirmed and live: " + ", ".join(c["name"] for c in chosen), checks)
        return chosen, rest

    # 5. users
    async def users_for(self, names: list[str]) -> list[dict[str, Any]]:
        """Real users of each product: G2, Capterra and Product Hunt reviewers, each scraped from the product's exact
        page on that site as found by one batched Google search (site:<platform>.com <name> reviews)."""
        if not (self.run.scrape_reviews and self.apify_token()):
            if not any(st.title == "G2 / Capterra / Product Hunt reviews" for st in self.run.steps):
                s = self.trace.start("reviews", "G2 / Capterra / Product Hunt reviews")
                self.trace.end(s, "skipped", "turned off for this run" if not self.run.scrape_reviews else "APIFY_TOKEN is not set")
            return []
        platforms = ("g2", "capterra", "producthunt")
        found = await self._search_many([q for n in names for p in platforms for q in page_queries(p, n)])

        def rows_for(platform: str, name: str) -> list[dict[str, str]]:
            return [r for q in page_queries(platform, name) for r in found.get(q) or []]

        async def scrape(name: str, platform: str) -> list[dict[str, Any]]:
            url, why = review_page(rows_for(platform, name), platform, name)
            s = self.trace.start("reviews", f"{PLATFORM_LABEL[platform]} reviews of {name}",
                                 {"page": url, "how": why, "actor": REVIEW_ACTORS[platform]})
            if not url:
                self.trace.end(s, "error", why)
                return []
            try:
                got = await asyncio.wait_for(asyncio.to_thread(self.scrape_review_page, platform, url), REVIEW_WAIT_S)
            except asyncio.TimeoutError:
                self.trace.end(s, "error", f"still scraping after {REVIEW_WAIT_S:.0f}s (keeps running; cached for next run)")
                return []
            except Exception as exc:
                self.trace.end(s, "error", _redact(repr(exc))[:300])
                return []
            rows = [_reviewer(r | {"product": name}) for r in got]
            self.trace.end(s, "done" if rows else "error",
                           f"{len(rows)} reviews from {url}, {sum(1 for r in rows if r['role'])} with a job title or headline"
                           if rows else f"no reviews on {url}", rows)
            return rows

        return [u for rows in await asyncio.gather(*(scrape(n, p) for n in names for p in platforms)) for u in rows]

    # 6. segments + tasks
    async def synthesize(self, profile: dict[str, Any], comps: list[dict[str, Any]], users: list[dict[str, Any]]) -> dict[str, Any]:
        """Segments come only from the real users retrieved: with none, there are no segments (never invented)."""
        def line(i: int, u: dict[str, Any]) -> str:
            who = "; ".join(f"{k}: {u[k]}" for k in ("role", "size", "industry", "rating") if u.get(k))
            return f"[u{i}] ({u['source']} / {u['product']}) {who or 'no profile'}\n    {u['text'][:350]}"
        shown = users[:80]
        sample = "\n".join(line(i, u) for i, u in enumerate(shown))
        sites = "\n".join(f"- {c['name']} ({c['url']}): {c.get('why', '')}" for c in comps) or "(no competitors)"
        head = f"""The product: {profile.get('name')} ({self.run.url}) — {profile.get('one_liner')}
What it does: {profile.get('what_they_do')}
Key features: {', '.join(profile.get('key_features') or [])}

COMPETITORS IT WILL BE TESTED AGAINST:
{sites}
"""
        task_rules = f"""Write exactly {self.run.task_count} tasks to run on {profile.get('name')} AND on every competitor, so the sites
can be compared. Each task is a real job this kind of product is used for, phrased so it makes sense on any of the sites
(never name a site-specific button). Say what done looks like. Mix first-run tasks (sign up, onboarding, first core
action) with core-job tasks"""
        task_shape = """"tasks": [{"id": "t1", "title": "short name", "prompt": "the task as given to a user, works on every site",
   "segment_id": "s1 or ''", "done_when": "what success looks like", "why": "what comparing the sites on this shows",
   "kind": "first_run|core_job|pain_probe", "evidence": ["user ids whose words motivated this task, if any"]}]"""
        if not shown:
            out = await self._ask(
                "Write comparison tasks (no real users retrieved, so no segments)",
                "You output valid JSON only. Tasks must be doable on every site and based on the product's real features.",
                f"""{head}
No real users were retrieved, so write no user segments and do not describe any users.
{task_rules}, based only on the features above. Leave segment_id empty.

Return JSON:
{{{task_shape}}}""")
            return {"segments": [], "tasks": [t | {"segment_id": ""} for t in out.get("tasks") or []]}
        out = await self._ask(
            "Write user segments and comparison tasks",
            "You output valid JSON only. Segments must be grounded in the real users supplied; tasks must be doable on every site.",
            f"""{head}
REAL USERS (G2, Capterra and Product Hunt reviewers of this product, its competitors, or similar products):
{sample}

1. Group the real users above into 2-6 user segments. Every segment must cite at least two users by id, and its jobs
   and pains must come from what those users said. Do not add segments that no user above supports.
2. {task_rules}, and one or two tasks that probe a pain the real users complained about.

Return JSON:
{{"segments": [{{"id": "s1", "name": "short label", "who": "role, company size, context", "jobs": ["what they need done"],
   "pains": ["what frustrates them, from the reviews"], "evidence": ["u3", "u17"], "share": "share of the users above, e.g. 30%"}}],
  {task_shape}}}""")
        segments = []
        for seg in out.get("segments") or []:
            ids = [f"u{n}" for n in (int(m) for e in seg.get("evidence") or [] for m in re.findall(r"\d+", str(e)))
                   if n < len(shown)]
            if ids:  # a segment no retrieved user backs is dropped
                segments.append(seg | {"evidence": list(dict.fromkeys(ids))})
        kept = {seg.get("id") for seg in segments}
        tasks = [t if t.get("segment_id") in kept else t | {"segment_id": ""} for t in out.get("tasks") or []]
        return {"segments": segments, "tasks": tasks}

    async def execute(self) -> dict[str, Any]:
        host = registrable_host(self.run.url)
        site = await self.read_site()
        prof = await self.profile(site, [])
        name = prof.get("name") or host
        # The product's own reviewers are searched and scraped while its competitors are still being found.
        own_users = asyncio.create_task(self.users_for([name]))
        queries = [f"{name} alternatives", f"{name} competitors"] + [f"best {t}" for t in (prof.get("search_terms") or [])[:2]]
        found, ph = await asyncio.gather(self._search_many(queries), self.product_hunt(prof))
        web = [r for q in queries for r in found.get(q) or []]
        candidates = await self.pick(prof, web, ph)
        comps, rest = await self.keep_live(candidates, str(prof.get("category") or ""))
        rival_users = await self.users_for([c["name"] for c in comps]) if comps else []
        users = await own_users + rival_users
        if len(users) < MIN_REVIEWS and rest:
            # Too few reviews of the product and its competitors: add the next-closest similar products' users.
            users += await self.users_for([c["name"] for c in rest[:2]])
        reviewers = [u for u in users if u["source"] != "producthunt"]
        ph_people = [u for u in users if u["source"] == "producthunt"]
        out = await self.synthesize(prof, comps, users)
        # Sources that gave nothing, and why: shown at the top of the result so 0 users is never silent.
        gaps = [{"source": s.title, "status": s.status, "why": s.summary} for s in self.run.steps
                if s.kind in {"producthunt", "reviews"} and s.status in {"skipped", "error"}]
        return {"product": prof | {"url": self.run.url},
                "competitors": comps, "similar_products": rest,
                "users": users, "segments": out["segments"], "tasks": out["tasks"], "source_gaps": gaps,
                "counts": {"web_results": len(web), "ph_launches": len(ph), "ph_reviewers": len(ph_people),
                           "reviews": len(reviewers),
                           "reviews_by_source": {s: sum(1 for u in reviewers if u["source"] == s)
                                                 for s in sorted({u["source"] for u in reviewers if u.get("source")})}}}

    async def go(self) -> Discovery:
        _RUN_CREDS.set(self._credentials)  # this task's context only
        try:
            self.run.result = await self.execute()
            self.run.status = "done"
        except Exception as exc:
            self.run.status, self.run.error = "error", repr(exc)[:500]
        self.run.finished_at = time.time()
        self.trace._on_change(self.run)
        return self.run


def new_run(url: str, *, max_competitors: int = 2, task_count: int = 6, scrape_reviews: bool = True) -> Discovery:
    return Discovery(id=uuid.uuid4().hex[:12], url=_norm_url(url), max_competitors=max(1, min(5, max_competitors)),
                     task_count=max(1, min(12, task_count)), scrape_reviews=scrape_reviews)
