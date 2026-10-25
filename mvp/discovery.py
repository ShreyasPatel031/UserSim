"""Part 1 of a study: discovery. Product URL in; competitors, real users and comparison tasks out.

Nothing here opens a browser or runs a simulated user. Steps, in order:

1. Read the product's own site (homepage plus up to two about/pricing/features pages) and search the web for it.
2. One LLM call turns that into a product profile (what it is, who it is for, search keywords).
3. Gather competitor candidates: web searches ("<name> alternatives", ...) and Product Hunt (the product's own post,
   its topics, and the top posts in those topics).
4. One LLM call picks the closest competitors from those candidates; their homepages are probed and dead ones dropped.
5. Real users: Product Hunt commenters (name, headline, comment) on the product's and competitors' posts, and G2 /
   Capterra reviewers via Apify (role, company size, industry, rating, pros/cons). When the product and its picked
   competitors have few reviews, the next-closest similar products are scraped too.
6. One LLM call writes user segments (grounded in those users) and tasks to run on the product and every competitor.

Every step is recorded in a trace (what was asked, how long it took, what came back) so the /discovery page can show
what the agent searched and retrieved. Secrets: PH_TOKEN, or PH_CLIENT_ID + PH_CLIENT_SECRET (Product Hunt API v2;
same names as scripts/ph_crawl.py, see docs/producthunt/README.md) and APIFY_TOKEN (see mvp.review_context); a missing token skips that source and the trace says so.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from html import unescape
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


def ph_configured() -> bool:
    env = os.environ.get
    return bool((env("PH_TOKEN") or "").strip() or ((env("PH_CLIENT_ID") or "").strip() and (env("PH_CLIENT_SECRET") or "").strip()))


async def ph_bearer() -> str:
    """PH_TOKEN (developer token), else a public-scope token minted from PH_CLIENT_ID + PH_CLIENT_SECRET."""
    token = (os.environ.get("PH_TOKEN") or "").strip()
    if token:
        return token
    cid, secret = (os.environ.get("PH_CLIENT_ID") or "").strip(), (os.environ.get("PH_CLIENT_SECRET") or "").strip()
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


GOOGLE_ACTOR = "apify~google-search-scraper"


def google_search_many(queries: list[str], limit: int = 8) -> dict[str, list[dict[str, str]]]:
    """Google results for several queries in ONE Apify run (blocking, ~15-40 s). Needs APIFY_TOKEN."""
    from mvp import review_context

    out: dict[str, list[dict[str, str]]] = {q: [] for q in queries}
    token = review_context.apify_token()
    if not token or not queries:
        return out
    items = review_context._apify_run(GOOGLE_ACTOR, {"queries": "\n".join(queries), "resultsPerPage": 10,
                                                     "maxPagesPerQuery": 1, "countryCode": "us", "languageCode": "en"},
                                      token, wait_s=180.0)
    for item in items:
        term = (item.get("searchQuery") or {}).get("term")
        if term not in out:
            continue
        out[term] += [{"title": (r.get("title") or "")[:140], "url": r.get("url") or "",
                       "snippet": (r.get("description") or "")[:300], "engine": "google"}
                      for r in (item.get("organicResults") or []) if (r.get("url") or "").startswith("http")]
    return {q: rows[:limit] for q, rows in out.items()}


async def ddg_search(query: str, limit: int = 8) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        r = await client.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
    # 202 = DuckDuckGo's bot check (seen from some cloud IPs): no results rather than a parse of the challenge page
    rows = parse_ddg(r.text or "", limit) if r.status_code == 200 else []
    for row in rows:
        row["engine"] = "duckduckgo"
    return rows


async def web_search_many(queries: list[str], *, limit: int = 8) -> dict[str, list[dict[str, str]]]:
    """Google via Apify (one run for all queries). DuckDuckGo only when Google is unavailable (no APIFY_TOKEN or the
    run failed), never to second-guess an empty Google answer."""
    try:
        if apify_token():
            return await asyncio.to_thread(google_search_many, queries, limit)
    except Exception as exc:  # noqa: BLE001 - fall back to DuckDuckGo
        print(f"[discovery] google search failed: {exc!r}"[:300], flush=True)
    rows = await asyncio.gather(*(ddg_search(q, limit) for q in queries), return_exceptions=True)
    return {q: (r if isinstance(r, list) else []) for q, r in zip(queries, rows)}


async def web_search(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    return (await web_search_many([query], limit=limit))[query]


_PH_POST_FIELDS = """name slug tagline description url website votesCount commentsCount reviewsCount reviewsRating
  topics(first: 6) { edges { node { name slug } } }"""
_PH_COMMENTS = """comments(first: 20, order: VOTES_COUNT) { edges { node { body votesCount createdAt
  user { name username headline } } } }"""


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


def _redacted(v: Any) -> bool:
    return not v or "redacted" in str(v).lower()


def _ph_users(node: dict[str, Any], product: str) -> list[dict[str, Any]]:
    """Commenters on a post. Product Hunt redacts other users' names for most API tokens; the comment stays."""
    users = []
    for c in _edges(node.get("comments")):
        u = c.get("user") or {}
        body = _clean_text(c.get("body") or "")
        if len(body) < 25:
            continue
        users.append({"source": "producthunt", "product": product,
                      "name": None if _redacted(u.get("name")) else u.get("name"),
                      "role": None if _redacted(u.get("headline")) else u.get("headline"),
                      "username": None if _redacted(u.get("username")) else u.get("username"),
                      "text": body[:600], "votes": c.get("votesCount")})
    return users


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


_PH_SLUG_RES = (re.compile(r"producthunt\.com/posts/([a-z0-9-]+)", re.I),
                re.compile(r"producthunt\.com/products/[a-z0-9-]+/launches/([a-z0-9-]+)", re.I),
                re.compile(r"producthunt\.com/products/([a-z0-9-]+)", re.I))
# Topics too broad to say anything about similar products.
GENERIC_PH_TOPICS = frozenset({"tech", "technology", "web-app", "android", "iphone", "mac", "windows", "chrome-extensions"})
_STOP = frozenset("""with your that this from more they their them have what into just than make made best free tool tools
platform team teams work works product products help helps build easy simple every using based like over about which will
most also only other such when where while across into each your youre need needs want wants within without software
online powered allows lets used uses makes better faster world first""".split())


def ph_slugs_from_results(rows: list[dict[str, str]]) -> list[str]:
    """Product Hunt post slugs in search-rank order, from /posts/<slug>, /products/<p>/launches/<slug>, /products/<slug>."""
    found = []
    for r in rows:
        url = r.get("url") or ""
        for rx in _PH_SLUG_RES:
            m = rx.search(url)
            if m:
                found.append(m.group(1).lower())
                break
    return list(dict.fromkeys(found))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _STOP}


def ph_post_matches(node: dict[str, Any], name: str, context: str) -> tuple[bool, str]:
    """Same name AND the launch copy shares words with what we know of the product. Product Hunt has many products
    with the same name (slug 'shortcut' is a 2014 IoT launch, not the issue tracker)."""
    found, want = _slug(node.get("name") or ""), _slug(name)
    if not (found == want or found.startswith(want + "-") or want.startswith(found + "-")):
        return False, f"named '{node.get('name')}', not '{name}'"
    overlap = _words(f"{node.get('tagline')} {node.get('description')}") & _words(context)
    if not overlap:
        return False, f"'{node.get('tagline')}' shares no words with the product"
    return True, "copy mentions " + ", ".join(sorted(overlap)[:6])


async def ph_post_by_slug(slug: str) -> dict[str, Any] | None:
    data = await ph_query(f"query($slug: String!) {{ post(slug: $slug) {{ {_PH_POST_FIELDS} {_PH_COMMENTS} }} }}",
                          {"slug": slug})
    return data.get("post")


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

    return review_context.apify_token()


G2_ACTOR = "automation-lab~g2-scraper"
CAPTERRA_ACTOR = "trakk~capterra-reviews-scraper"
_G2_RE = re.compile(r"g2\.com/products/([a-z0-9-]+)", re.I)
_CAPTERRA_RE = re.compile(r"capterra\.com/p/(\d+)/([A-Za-z0-9_-]+)", re.I)
REVIEWS_PER_SITE = 50


def _same_name(found: str, wanted: str) -> bool:
    from mvp import review_context

    return review_context._same_product(found.replace("-", " "), wanted)


def review_page(rows: list[dict[str, str]], platform: str, name: str) -> tuple[str | None, str]:
    """The product's own G2 / Capterra page from search results (first whose name matches), and why."""
    seen = []
    for r in rows:
        url = r.get("url") or ""
        m = (_G2_RE if platform == "g2" else _CAPTERRA_RE).search(url)
        if not m:
            continue
        page_name = m.group(1) if platform == "g2" else m.group(2)
        if _same_name(page_name, name):
            canon = (f"https://www.g2.com/products/{m.group(1).lower()}/reviews" if platform == "g2"
                     else f"https://www.capterra.com/p/{m.group(1)}/{m.group(2)}/")
            return canon, f"matched {url}"
        seen.append(page_name)
    return None, (f"{platform} pages in results are for other products: {sorted(set(seen))}" if seen
                  else f"no {platform} product page in the search results")


def scrape_review_page(platform: str, url: str) -> list[dict[str, Any]]:
    """Reviews from one exact G2 or Capterra product page via Apify (blocking), cached per URL."""
    from mvp import review_context

    token = review_context.apify_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN missing")
    cache = review_context._APIFY_CACHE / f"page-{_slug(url)}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    if platform == "g2":
        items = review_context._apify_run(G2_ACTOR, {"mode": "product_reviews", "productUrls": [url],
                                                     "maxReviews": REVIEWS_PER_SITE}, token)
        # automation-lab/g2-scraper: no job title; companySegment/industry may be numeric ids (see review_context)
        rows = [{"source": "g2", "product": r.get("productName") or "", "role": None,
                 "size": review_context.G2_SEGMENTS.get(str(r.get("companySegment"))),
                 "industry": review_context._text(r.get("industry")), "rating": r.get("starRating"),
                 "text": r.get("reviewText"), "date": r.get("publishedAt") or r.get("date")} for r in items]
    else:
        items = review_context._apify_run(CAPTERRA_ACTOR, {"productUrls": [url], "maxReviewsPerProduct": REVIEWS_PER_SITE,
                                                           "maxItems": REVIEWS_PER_SITE, "includeProductAggregate": False}, token)
        rows = [{"source": "capterra", "product": r.get("productName") or "", "role": r.get("reviewerJobTitle"),
                 "size": r.get("reviewerCompanySize"), "industry": r.get("reviewerIndustry"),
                 "time_used": r.get("timeUsedProduct"), "rating": r.get("overallRating"),
                 "pros": r.get("pros"), "cons": r.get("cons"), "date": r.get("reviewDate") or r.get("date")} for r in items]
    review_context._APIFY_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def _reviewer(r: dict[str, Any]) -> dict[str, Any]:
    text = r.get("text") or " / ".join(x for x in (r.get("pros") and f"Liked: {r['pros']}",
                                                   r.get("cons") and f"Disliked: {r['cons']}") if x)
    return {"source": r.get("source"), "product": r.get("product"), "role": r.get("role"), "size": r.get("size"),
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
                 on_change: Callable[[Discovery], None] | None = None):
        self.run = run
        self.trace = Trace(run, on_change)
        self.llm = llm or _default_llm
        self.fetch_html = fetch_html
        self.web_search_many = web_search_many
        self.ph_post_by_slug = ph_post_by_slug
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
        steps = {q: self.trace.start("search", f"Web search: {q}", {"query": q, "engine": "google (apify)"}) for q in queries}
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
    async def find_ph_post(self, name: str, context: str, rows: list[dict[str, str]]) -> dict[str, Any] | None:
        """This product's Product Hunt post. The API has no search, so slugs come only from Google results for
        site:producthunt.com (never guessed from the name); each candidate must pass ph_post_matches."""
        slugs = ph_slugs_from_results(rows)[:5]
        if not slugs:
            s = self.trace.start("producthunt", f"Product Hunt post for {name}")
            self.trace.end(s, "done", "no producthunt.com result in the search: no post")
            return None
        for slug in slugs:
            s = self.trace.start("producthunt", f"Product Hunt post '{slug}' for {name}", {"query": "post(slug)", "slug": slug})
            try:
                node = await self.ph_post_by_slug(slug)
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
                continue
            if not node:
                self.trace.end(s, "done", "no post with this slug")
                continue
            ok, why = ph_post_matches(node, name, context)
            if ok:
                self.trace.end(s, "done", f"match: {node.get('name')} — {node.get('tagline')} ({node.get('votesCount')} votes); {why}",
                               _ph_post(node) | {"commenters": len(_ph_users(node, name))})
                return node
            self.trace.end(s, "done", f"rejected: {why}", _ph_post(node))
        return None

    def _context(self, profile: dict[str, Any], extra: str = "") -> str:
        return " ".join([extra, str(profile.get("one_liner") or ""), str(profile.get("what_they_do") or ""),
                         str(profile.get("category") or ""), " ".join(profile.get("key_features") or []),
                         " ".join(profile.get("target_users") or [])])

    async def product_hunt(self, profile: dict[str, Any], rows: list[dict[str, str]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """The product's own PH post (if any, from the site:producthunt.com search rows) and the top posts in its topics."""
        if not self.ph_configured():
            s = self.trace.start("producthunt", "Product Hunt")
            self.trace.end(s, "skipped", "PH_TOKEN (or PH_CLIENT_ID + PH_CLIENT_SECRET) is not set")
            return None, []
        name = profile.get("name") or registrable_host(self.run.url)
        own = await self.find_ph_post(name, self._context(profile), rows)
        topics = [t for t in (_ph_post(own)["topics"] if own else []) if t not in GENERIC_PH_TOPICS]
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
        seen, uniq = {_slug(name), _ph_post(own)["slug"] if own else ""}, []
        for p in posts:
            if p["slug"] not in seen:
                seen.add(p["slug"])
                uniq.append(p)
        return own, uniq

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
            hosts = [registrable_host(r["url"]) for r in found.get(q_of[c["name"]]) or []]
            hosts = [h for h in dict.fromkeys(hosts) if h and not any(h == b or h.endswith("." + b) for b in _NON_PRODUCT_HOSTS)]
            brand = _slug(c["name"]).replace("-", "")
            llm_host = registrable_host(c["url"])
            if llm_host in hosts:
                url, how = _norm_url(llm_host), "the LLM's URL is in the Google results"
            else:
                match = next((h for h in hosts if brand and brand in h.replace("-", "").replace(".", "")), None)
                if not match:
                    checks.append({"name": c["name"], "ok": False, "why": f"no homepage in Google results (hosts: {hosts[:5]})"})
                    continue
                url, how = _norm_url(match), f"Google result host contains '{brand}'"
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
    async def users_for(self, products: list[tuple[str, str]], ph_done: dict[str, Any]) -> list[dict[str, Any]]:
        """Real users of each (name, context) product: Product Hunt commenters and G2 / Capterra reviewers, all from
        pages found by one batched Google search (site:producthunt.com / site:g2.com / site:capterra.com)."""
        want_ph = self.ph_configured()
        want_rv = self.run.scrape_reviews and bool(self.apify_token())
        if not want_rv and not any(st.title == "G2 / Capterra reviews" for st in self.run.steps):
            s = self.trace.start("reviews", "G2 / Capterra reviews")
            self.trace.end(s, "skipped", "turned off for this run" if not self.run.scrape_reviews else "APIFY_TOKEN is not set")
        queries = []
        for name, _ctx in products:
            if want_ph and name not in ph_done:
                queries.append(f"site:producthunt.com {name}")
            if want_rv:
                queries += [f"site:g2.com {name} reviews", f"site:capterra.com {name} reviews"]
        found = await self._search_many(queries) if queries else {}

        async def scrape(name: str, platform: str) -> list[dict[str, Any]]:
            url, why = review_page(found.get(f"site:{platform}.com {name} reviews") or [], platform, name)
            s = self.trace.start("reviews", f"{'G2' if platform == 'g2' else 'Capterra'} reviews of {name}",
                                 {"page": url, "how": why, "actor": G2_ACTOR if platform == "g2" else CAPTERRA_ACTOR})
            if not url:
                self.trace.end(s, "error", why)
                return []
            try:
                got = await asyncio.wait_for(asyncio.to_thread(self.scrape_review_page, platform, url), REVIEW_WAIT_S)
            except asyncio.TimeoutError:
                self.trace.end(s, "error", f"still scraping after {REVIEW_WAIT_S:.0f}s (keeps running; cached for next run)")
                return []
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
                return []
            rows = [_reviewer(r | {"product": name}) for r in got]
            self.trace.end(s, "done" if rows else "error",
                           f"{len(rows)} reviews from {url}, {sum(1 for r in rows if r['role'])} with a job title" if rows
                           else f"no reviews on {url}", rows)
            return rows

        async def ph(name: str, ctx: str) -> list[dict[str, Any]]:
            node = ph_done[name] if name in ph_done else \
                await self.find_ph_post(name, ctx, found.get(f"site:producthunt.com {name}") or [])
            return _ph_users(node, name) if node else []

        jobs = [scrape(n, p) for n, _ in products for p in ("g2", "capterra") if want_rv]
        jobs += [ph(n, c) for n, c in products if want_ph]
        return [u for rows in await asyncio.gather(*jobs) for u in rows]

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
REAL USERS (Product Hunt commenters and G2/Capterra reviewers of this product, its competitors, or similar products):
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
        site, about = await asyncio.gather(self.read_site(), self._search(f"what is {host}"))
        prof = await self.profile(site, about)
        name = prof.get("name") or host
        queries = [f"{name} alternatives", f"{name} competitors"] + [f"best {t}" for t in (prof.get("search_terms") or [])[:2]]
        ph_q = f"site:producthunt.com {name}"
        found = await self._search_many(queries + ([ph_q] if self.ph_configured() else []))
        own, ph = await self.product_hunt(prof, found.get(ph_q) or [])
        web = [r for q in queries for r in found.get(q) or []]
        candidates = await self.pick(prof, web, ph)
        comps, rest = await self.keep_live(candidates, str(prof.get("category") or ""))
        products = [(name, self._context(prof))] + [(c["name"], self._context(prof, str(c.get("why") or ""))) for c in comps]
        users = await self.users_for(products, {name: own} if own else {})
        reviewers = [u for u in users if u["source"] != "producthunt"]
        if len(reviewers) < MIN_REVIEWS and rest:
            # Too few reviews of the product and its competitors: add the next-closest similar products' users.
            users += await self.users_for([(c["name"], self._context(prof, str(c.get("why") or ""))) for c in rest[:2]], {})
        reviewers = [u for u in users if u["source"] != "producthunt"]
        ph_people = [u for u in users if u["source"] == "producthunt"]
        out = await self.synthesize(prof, comps, users)
        # Sources that gave nothing, and why: shown at the top of the result so 0 users is never silent.
        gaps = [{"source": s.title, "status": s.status, "why": s.summary} for s in self.run.steps
                if s.kind in {"producthunt", "reviews"} and s.status in {"skipped", "error"}]
        return {"product": prof | {"url": self.run.url,
                                   "producthunt": _ph_post(own) if own else None},
                "competitors": comps, "similar_products": rest,
                "users": users, "segments": out["segments"], "tasks": out["tasks"], "source_gaps": gaps,
                "counts": {"web_results": len(web), "ph_launches": len(ph), "ph_commenters": len(ph_people),
                           "reviews": len(reviewers),
                           "reviews_by_source": {s: sum(1 for u in reviewers if u["source"] == s)
                                                 for s in sorted({u["source"] for u in reviewers if u.get("source")})}}}

    async def go(self) -> Discovery:
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
