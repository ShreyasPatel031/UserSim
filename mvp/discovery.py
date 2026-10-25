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


def google_search(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Google results via Apify (blocking, ~10-30 s). Needs APIFY_TOKEN."""
    from mvp import review_context

    token = review_context.apify_token()
    if not token:
        return []
    items = review_context._apify_run(GOOGLE_ACTOR, {"queries": query, "resultsPerPage": 10, "maxPagesPerQuery": 1,
                                                     "countryCode": "us", "languageCode": "en"}, token, wait_s=120.0)
    rows = [{"title": (r.get("title") or "")[:140], "url": r.get("url") or "", "snippet": (r.get("description") or "")[:300],
             "engine": "google"} for item in items for r in (item.get("organicResults") or [])]
    return [r for r in rows if r["url"].startswith("http")][:limit]


async def web_search(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Google via Apify when APIFY_TOKEN is set; otherwise (or if that fails) keyless DuckDuckGo HTML."""
    try:
        rows = await asyncio.to_thread(google_search, query, limit)
    except Exception as exc:  # noqa: BLE001 - fall back to DuckDuckGo
        print(f"[discovery] google search failed: {exc!r}"[:300], flush=True)
        rows = []
    if rows:
        return rows
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        r = await client.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
    # 202 = DuckDuckGo's bot check (seen from some cloud IPs): no results rather than a parse of the challenge page
    rows = parse_ddg(r.text or "", limit) if r.status_code == 200 else []
    for row in rows:
        row["engine"] = "duckduckgo"
    return rows


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


def fetch_reviews(name: str) -> dict[str, Any]:
    """G2 + Capterra (+ TrustRadius, Gartner) reviews of one product via Apify, cached per product."""
    from mvp import review_context

    return review_context.live_reviews(name)


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
        self.web_search = web_search
        self.ph_post_by_slug = ph_post_by_slug
        self.ph_topic_posts = ph_topic_posts
        self.ph_topics = ph_topics
        self.ph_configured = ph_configured
        self.fetch_reviews = fetch_reviews
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

    async def _search(self, query: str) -> list[dict[str, str]]:
        step = self.trace.start("search", f"Web search: {query}", {"query": query, "engine": "google (apify), else duckduckgo"})
        try:
            rows = await self.web_search(query)
        except Exception as exc:
            self.trace.end(step, "error", repr(exc)[:300])
            return []
        engines = sorted({r.get("engine") or "?" for r in rows})
        self.trace.end(step, "done", f"{len(rows)} results" + (f" ({', '.join(engines)})" if rows else ""), rows)
        return rows

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
    async def product_hunt(self, profile: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """The product's own PH post (if any) and the top posts in its topics."""
        if not self.ph_configured():
            s = self.trace.start("producthunt", "Product Hunt")
            self.trace.end(s, "skipped", "PH_TOKEN (or PH_CLIENT_ID + PH_CLIENT_SECRET) is not set")
            return None, []
        own = None
        for slug in dict.fromkeys([_slug(profile.get("name", "")), _slug(registrable_host(self.run.url).split(".")[0])]):
            if not slug:
                continue
            s = self.trace.start("producthunt", f"Product Hunt post '{slug}'", {"query": "post(slug)", "slug": slug})
            try:
                node = await self.ph_post_by_slug(slug)
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
                continue
            if node:
                own = node
                self.trace.end(s, "done", f"found: {node.get('name')} — {node.get('tagline')} ({node.get('votesCount')} votes)", _ph_post(node))
                break
            self.trace.end(s, "done", "no post with this slug")
        topics = list((_ph_post(own)["topics"] if own else []))
        for name in profile.get("ph_topics") or []:
            if len(topics) >= 3:
                break
            s = self.trace.start("producthunt", f"Product Hunt topic search '{name}'", {"query": "topics(query)", "q": name})
            try:
                found = await self.ph_topics(name)
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
        seen, uniq = {_slug(profile.get("name", ""))}, []
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
  "overlap": "direct|partial|adjacent", "source": "web|producthunt|model_knowledge", "ph_slug": "slug if from Product Hunt, else ''",
  "review_name": "name as listed on G2/Capterra"}}]}}""")
        return [c for c in (out.get("candidates") or []) if c.get("name") and c.get("url")]

    async def keep_live(self, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(chosen live competitors, the unprobed remaining candidates as similar products); dead ones are dropped."""
        chosen, rest = [], []
        step = self.trace.start("probe", "Check competitor homepages are live", {"urls": [c["url"] for c in candidates]})
        checks = []
        for c in candidates:
            if len(chosen) >= self.run.max_competitors:
                rest.append(c)
                continue
            if same_site(c["url"], self.run.url):
                checks.append({"name": c["name"], "url": c["url"], "ok": False, "why": "same site as the product"})
                continue
            try:
                ok, info = await self.probe(_norm_url(c["url"]))
            except Exception as exc:
                ok, info = False, repr(exc)[:200]
            checks.append({"name": c["name"], "url": c["url"], "ok": ok, "why": "" if ok else info})
            if ok:
                chosen.append(c | {"url": info})
        self.trace.end(step, "done", f"{len(chosen)} live: " + ", ".join(c["name"] for c in chosen), checks)
        return chosen, rest

    # 5. users
    async def ph_users(self, own: dict[str, Any] | None, profile: dict[str, Any], comps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.ph_configured():
            return []
        users = _ph_users(own, profile.get("name") or "") if own else []
        for c in comps:
            slug = c.get("ph_slug") or _slug(c["name"])
            s = self.trace.start("producthunt", f"Product Hunt comments on '{slug}'", {"query": "post(slug).comments", "slug": slug})
            try:
                node = await self.ph_post_by_slug(slug)
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
                continue
            got = _ph_users(node, c["name"]) if node else []
            self.trace.end(s, "done", f"{len(got)} commenters" if node else "no post with this slug", got)
            users += got
        return users

    async def reviews(self, names: list[str], backups: list[str]) -> list[dict[str, Any]]:
        if not self.run.scrape_reviews:
            s = self.trace.start("reviews", "G2 / Capterra reviews")
            self.trace.end(s, "skipped", "turned off for this run")
            return []
        if not self.apify_token():
            s = self.trace.start("reviews", "G2 / Capterra reviews")
            self.trace.end(s, "skipped", "APIFY_TOKEN is not set")
            return []

        async def one(name: str) -> list[dict[str, Any]]:
            s = self.trace.start("reviews", f"G2 / Capterra reviews of {name}",
                                 {"actor": "apify zen-studio~software-review-scraper", "query": name,
                                  "platforms": ["g2", "capterra", "trustradius", "gartner"]})
            try:
                got = await asyncio.wait_for(asyncio.to_thread(self.fetch_reviews, name), REVIEW_WAIT_S)
            except asyncio.TimeoutError:
                self.trace.end(s, "error", f"still scraping after {REVIEW_WAIT_S:.0f}s (keeps running; cached for next run)")
                return []
            except Exception as exc:
                self.trace.end(s, "error", repr(exc)[:300])
                return []
            rows = [_reviewer(r) for r in got.get("reviews") or []]
            by = {}
            for r in rows:
                by[r["source"]] = by.get(r["source"], 0) + 1
            note = "; ".join(got.get("errors") or [])
            self.trace.end(s, "done" if rows else "error",
                           (f"{len(rows)} reviews (" + ", ".join(f"{k} {v}" for k, v in by.items()) + ")" if rows else "no reviews")
                           + (f" — {note}" if note else ""), rows)
            return rows

        out = [r for rows in await asyncio.gather(*(one(n) for n in names)) for r in rows]
        if len(out) < MIN_REVIEWS and backups:
            # Too few reviews of the product and its picked rivals: use the next-closest similar products' users.
            out += [r for rows in await asyncio.gather(*(one(n) for n in backups[:2])) for r in rows]
        return out

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
        web_rows, (own, ph) = await asyncio.gather(
            asyncio.gather(*(self._search(q) for q in queries)), self.product_hunt(prof))
        web = [r for rows in web_rows for r in rows]
        candidates = await self.pick(prof, web, ph)
        comps, rest = await self.keep_live(candidates)
        ph_people, reviewers = await asyncio.gather(
            self.ph_users(own, prof, comps),
            self.reviews([name] + [c.get("review_name") or c["name"] for c in comps],
                         [c.get("review_name") or c["name"] for c in rest]))
        users = reviewers + ph_people
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
