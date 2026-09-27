"""One quick model call that turns a bare product URL into a study plan.

A URL typed on the home page with no tasks used to wait on competitor
research and persona planning (about 20s) before any agent opened a page.
This asks Gemini once for the segment, two rival URLs, and two short tasks:
one core task done in the product (it may need an account) and one task
grounded in the opening page read: a public task only when the page's links
expose it (pricing needs a pricing link), else a second in-app task. The
study then starts on the fast path.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from urllib.parse import urlsplit

_PROMPT = """You plan a short usability study for a web product. Reply with JSON only.
Product URL: {url}
Page title: {title}
Page text: {text}
Links and buttons on the page (label -> target): {links}

Return:
{{"product": "short product name",
  "segment": "one short phrase naming who evaluates this product",
  "competitors": ["https://rival-one.com/", "https://rival-two.com/", "https://rival-three.com/"],
  "core_task": "core task",
  "public_task": "public task",
  "app_task": "second task done in the product"}}

Rules:
- competitors: the three best-known direct competitors, best first, as homepage URLs of real public
  sites. A direct competitor is a standalone product in the same category that a buyer would try
  side by side for the same job (a design tool for a design tool, a scheduler for a scheduler).
  Never a parent company, a multi-product suite or vendor homepage, a marketplace, or a
  discontinued product. Use the rival product's own site.
- core_task: the one thing a new user comes to do in the product itself, 3-8 words,
  an imperative verb and a concrete object (never a tagline), generic enough to try on the rivals too (for example "Create a new project",
  "Draw a rectangle on the canvas", "Create a new event type"). One action whose result shows on
  one screen, never a broad activity (not "Design and prototype an interface"; say "Create a new
  design file"). If doing it needs an account,
  keep it that way; never turn it into a logged-out task. A brand-new trial account must be able to
  finish it alone: never a task that needs the customer's own outside credentials or data (connect,
  integrate or sync a data source, database, auth provider or ad account; API keys; service accounts;
  payment). Pick what the product does once it is open, with the sample data a new account starts with.
- public_task: 3-8 words a logged-out visitor can finish from this page using only the links,
  buttons and text listed above. Use "Look for pricing or how to get started" only when a
  pricing or plans link is listed. Never name a page, link or feature that is not listed.
- app_task: a second simple action in the product itself with a visible result, 3-8 words, with
  the same no-outside-credentials rule
  (for example "Add a text label that says hello", "Add a second task to the list"); used
  when the page is the app and lists no links.
- No quotes inside tasks. No explanations."""

# Comparison study (default): who each product is best for, not whether one
# task finished. One call returns three rivals, five target customers spread
# across all four products, and five tasks that between them favor each one.
_COMPARE_PROMPT = """You plan a head-to-head product comparison study. Reply with JSON only.
Product URL: {url}
Page title: {title}
Page text: {text}
Links and buttons on the page (label -> target): {links}

Return:
{{"product": "short product name",
  "segment": "one short phrase naming who evaluates products in this category",
  "competitors": [{{"url": "https://rival-one.com/", "name": "Rival One"}}, {{"url": "...", "name": "..."}}, {{"url": "...", "name": "..."}}],
  "personas": [{{"name": "first and last name", "role": "job title and company type",
                 "bio": "at most 20 words: situation, need, how they judge a tool",
                 "favors": "product or the competitor url this person is the natural fit for",
                 "why": "at most 10 words"}}],
  "tasks": [{{"task": "3-8 word task", "favors": "product or a competitor url", "why": "at most 10 words"}}]}}

Rules:
- competitors: exactly three best-known direct competitors, best first, homepage URLs of real public
  sites. A direct competitor is a standalone product in the same category that a buyer would compare
  side by side. Never a parent company, multi-product suite homepage, marketplace or discontinued product.
  Rivals may be sales-led (demo only); that is fine. Each rival must still be sold under its own name
  at that domain today: never one that was acquired, merged or rebranded (its site redirects elsewhere).
- personas: exactly five realistic target customers of this category. Spread them evenly across the four
  products: at least one natural fit for the product and at least one natural fit for each competitor
  (for example an enterprise CS leader fits an enterprise suite, a two-person startup fits a self-serve
  tool). favors must be "product" or one of the competitor urls exactly as written above.
- tasks: six representative jobs a buyer in this category needs done, best first (the study keeps five), 3-8 words each, an
  imperative verb and a concrete object (for example "Identify at-risk customer accounts",
  "Compare plan prices for 20 seats"). Choose them so at least one favors the product and at least one
  favors each competitor. Each task must make sense on every one of the four sites: done in the product
  where a trial account allows, or judged from the website (feature pages, docs, pricing, proof) where
  the product is demo-only. Never a task that needs the customer's own outside credentials or data
  (connect or sync a data source, API keys, payment). At most one pricing task.
- No quotes inside strings. No explanations."""

# Split plan (default): a tiny competitor call first, then tasks and personas
# in parallel. One big call took 5-7s of model time on the first-action path.
_CMP_COMPETITORS = """Name the three best-known direct competitors of this product. Reply with JSON only.
Product URL: {url}
Page title: {title}
Page text: {text}

Return {{"product": "short product name", "segment": "one short phrase naming who evaluates products in this category",
  "competitors": [{{"url": "https://rival.com/", "name": "Rival"}}, ...3 items]}}
Rules: standalone products in the same category a buyer would compare side by side, best known first, homepage
URLs of real public sites. Sales-led (demo only) rivals are fine. Never a parent company, multi-product suite
homepage, marketplace or discontinued product, and never one that was acquired, merged or rebranded (its site
redirects elsewhere)."""

_CMP_TASKS = """Pick five tasks for a head-to-head comparison of {product} ({url}) against {rivals}. Reply with JSON only.
{product} page text: {text}

Return {{"tasks": [{{"task": "3-8 word task", "favors": "product or one competitor url exactly as listed", "why": "at most 12 words"}}]}}
Rules: five representative jobs a buyer in this category needs done, an imperative verb and a concrete object
(for example "Identify at-risk customer accounts"). At least one favors the product and at least one favors each
competitor. Each must make sense on all four sites: done in the product where a trial allows, or judged from the
website (feature pages, docs, pricing, proof) where the product is demo-only. Never a task needing the customer's
own outside credentials or data (connect or sync a data source, API keys, payment). At most one pricing task. No quotes."""

_CMP_PERSONAS = """Invent five target customers for a head-to-head comparison of {product} ({url}) against {rivals}. Reply with JSON only.
{product} page text: {text}

Return {{"personas": [{{"name": "first and last name", "role": "job title and company type",
  "bio": "at most 25 words: situation, what they need, how they judge a tool",
  "favors": "product or one competitor url exactly as listed", "why": "at most 12 words"}}]}}
Rules: realistic buyers in this category, spread evenly: at least one natural fit for the product and at least one
natural fit for each competitor (for example an enterprise CS leader fits an enterprise suite, a two-person startup
fits a self-serve tool). No quotes."""

# Framing fix "position": one small call on the full page read decides what
# category the product is in before rivals, buyers and tasks are picked.
_POSITIONING = """Say what this product is. Reply with JSON only.
Product URL: {url}
Page title: {title}
Page text (the whole page, including customer quotes): {text}

Return {{"product": "short product name", "category": "2-6 word product category, e.g. semantic search API",
  "what_it_is": "one sentence: what the product itself does for its user",
  "buyer": "who evaluates products in this category",
  "compared_with": ["2-4 well-known products buyers compare it with"],
  "not": "an adjacent category it could be mistaken for, and why not"}}
Rules: judge from what the product does, not from what customers happened to build with it (quotes and showcases
are examples). Use the site's own words where it names its category or alternatives. No quotes inside strings."""

# Framing fix "verify": a self-check of the drafted plan against the full page.
_VERIFY = """Check a drafted competitor list for a product comparison study. Reply with JSON only.
Product URL: {url}
Page title: {title}
Page text (the whole page): {text}
Drafted segment: {segment}
Drafted competitors: {rivals}

Return {{"category": "2-6 word category of this product, judged from what it does (customer showcases are examples, not the category)",
  "segment": "one short phrase naming who evaluates products in this category",
  "fits": [{{"url": "drafted competitor url", "same_job": true, "why": "at most 10 words"}}],
  "replacements": [{{"url": "https://rival.com/", "name": "Rival"}}]}}
Rules: same_job is true only if a buyer of this product would try that competitor side by side for the same job.
If any same_job is false, replacements lists exactly three best-known direct competitors in the category, best first,
homepage URLs of real public standalone products operating today (never a parent company, suite homepage or
marketplace). If all fit, replacements is empty. No quotes inside strings."""


_PRICING_TASK = "Look for pricing or how to get started"
_PRICING_RE = re.compile(r"pric|\bplans?\b|upgrade|billing|subscri", re.I)
_STOP = {
    "a", "an", "the", "or", "and", "to", "for", "of", "on", "in", "into", "with", "how", "get", "your",
    "look", "find", "open", "see", "view", "read", "check", "browse", "go", "visit", "try", "page", "site",
    "started", "start", "new", "what", "is", "are", "about", "out", "more", "learn", "explore", "section",
}


def _clean_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if not parts.hostname or "." not in parts.hostname:
        return ""
    return f"https://{parts.hostname}/"


def page_read_from_html(html: str) -> dict[str, Any]:
    """The opening page as the planner sees it: title, text, and the links and buttons.

    A client-rendered app ships an almost empty document, so ``links`` is
    empty there and the plan stays inside the product.
    """
    html = (html or "")[:600_000]
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = _plain(m.group(1))[:120]
    desc = ""
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        desc = _plain(m.group(1))
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", html, flags=re.S | re.I)
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r"<(a|button)\b([^>]*)>(.*?)</\1>", body, re.S | re.I):
        attrs, inner = m.group(2), m.group(3)
        href = ""
        hm = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
        if hm:
            href = hm.group(1)
        label = _plain(re.sub(r"<[^>]+>", " ", inner))
        if not label:
            am = re.search(r'aria-label=["\']([^"\']+)["\']', attrs, re.I)
            label = _plain(am.group(1)) if am else ""
        if not label or len(label) > 60 or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        links.append((label, href[:80]))
    text = _plain(re.sub(r"<[^>]+>", " ", body))
    return {
        "title": title,
        "text": f"{desc} {text}".strip()[:800],
        "links": links[:300],
        # What the site says it is (meta, og, JSON-LD, keywords, headings) and a
        # longer body read. The 800-char text above can be all customer quotes.
        "about": _site_about(html, desc, text),
        "full_text": text[:4000],
    }


def _meta_tags(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"<meta\b([^>]*)>", html, re.I):
        attrs = {k.lower(): (v1 if v1 is not None else v2) for k, v1, v2 in re.findall(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', m.group(1))}
        key = (attrs.get("name") or attrs.get("property") or "").lower()
        if key and attrs.get("content") and key not in out:
            out[key] = _plain(attrs["content"])
    return out


def _json_ld_about(html: str) -> list[str]:
    import json

    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            kind = str(node.get("@type") or "")
            if re.search(r"Application|Product|Service|Organization|WebSite", kind):
                for key in ("applicationCategory", "category", "description", "slogan"):
                    val = node.get(key)
                    if isinstance(val, str) and val.strip():
                        found.append(_plain(val))
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in node:
                    walk(node[key])

    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            walk(json.loads(m.group(1)))
        except Exception:  # noqa: BLE001
            continue
    return found


_NOT_A_NAME = {"the", "this", "that", "our", "your", "we", "you", "it", "a", "an", "me", "us", "them", "other", "any", "most"}


def _site_named_rivals(keywords: str, text: str) -> list[str]:
    """Products the site names itself against ("Zapier alternative", "Is Zo like OpenClaw or Hermes?")."""
    found: list[str] = []
    for m in re.finditer(r"([A-Za-z][\w.]*(?: [A-Z][\w.]*)?) alternative", keywords or ""):
        found.append(m.group(1))
    pat = r"\b(?:[Ll]ike|[Tt]han|[Uu]nlike|[Vv]s\.?|[Vv]ersus|[Cc]ompared to|[Ii]nstead of)\s+([A-Z][\w.-]+(?:,? (?:or|and) [A-Z][\w.-]+)*)"
    for m in re.finditer(pat, text or ""):
        found += re.split(r",? (?:or|and) ", m.group(1))
    out: list[str] = []
    for name in found:
        name = name.strip(" .,")
        if name and name.lower() not in _NOT_A_NAME and name.lower() not in {o.lower() for o in out}:
            out.append(name)
    return out[:8]


def _site_about(html: str, desc: str = "", text: str = "") -> str:
    """The site's own one-line positioning: descriptions, JSON-LD category, keywords, headings, named rivals."""
    meta = _meta_tags(html)
    parts: list[str] = [desc, meta.get("og:description", ""), meta.get("twitter:description", "")]
    parts += _json_ld_about(html)
    if meta.get("keywords"):
        parts.append("Keywords: " + meta["keywords"][:300])
    heads = [_plain(re.sub(r"<[^>]+>", " ", h)) for h in re.findall(r"<h[12][^>]*>(.*?)</h[12]>", html, re.I | re.S)]
    heads = [h for h in heads if 3 <= len(h) <= 90][:6]
    if heads:
        parts.append("Headings: " + " / ".join(heads))
    rivals = _site_named_rivals(meta.get("keywords", ""), text)
    if rivals:
        parts.insert(1, "The site compares itself with: " + ", ".join(rivals))
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        key = part.lower().strip(" .")
        if key and key not in seen:
            seen.add(key)
            out.append(part.strip())
    return " | ".join(out)[:700]


def framing_modes() -> set[str]:
    """Which framing fixes run (MVP_PLAN_FRAMING, comma list): read, position, verify. "off" = none."""
    raw = os.environ.get("MVP_PLAN_FRAMING", _DEFAULT_FRAMING)
    return {m.strip().lower() for m in raw.split(",") if m.strip() and m.strip().lower() not in {"off", "none", "0"}}


_DEFAULT_FRAMING = "off"

_READ_RULE = (
    "\nThe About line is the site's own description, category and keywords: judge the product category from it"
    " first. Customer quotes and showcase examples on the page are use cases, not the category."
)


def prompt_text(read: dict[str, Any], limit: int = 800) -> str:
    """Page text for a planner prompt. With the read fix: the site's About line first, then a longer body."""
    if "read" in framing_modes() and (read.get("about") or read.get("full_text")):
        body = str(read.get("full_text") or read.get("text") or "")
        return f"About: {read.get('about') or ''}\nPage: {body}"[: max(limit, 1500)]
    return str(read.get("text") or "")[:limit]


def read_rule() -> str:
    return _READ_RULE if "read" in framing_modes() else ""


def _plain(text: str) -> str:
    import html as _html

    return " ".join(_html.unescape(text or "").split())


async def _page_read(url: str) -> dict[str, Any]:
    """The product homepage read over HTTP, 3s max. Empty on any failure."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True, headers={"user-agent": "Mozilla/5.0"}) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {"title": "", "text": "", "links": [], "failed": True}
        return page_read_from_html(resp.text)
    except Exception:
        return {"title": "", "text": "", "links": [], "failed": True}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+]{3,}", (text or "").lower()) if w not in _STOP}


def task_grounded(task: str, read: dict[str, Any]) -> bool:
    """True when a logged-out task only names things this page exposes.

    Pricing needs a pricing or plans link. Any other public task needs one
    of its content words in a link label, a link target, or the page text.
    """
    links = list(read.get("links") or [])
    exposed = " ".join(f"{label} {href}" for label, href in links)
    if _PRICING_RE.search(task or ""):
        return bool(_PRICING_RE.search(exposed))
    words = _words(task)
    if not words:
        return False
    pool = _words(exposed) | _words(str(read.get("title") or "")) | _words(str(read.get("text") or ""))
    return bool(words & pool)


_CREDENTIAL_TASK_RE = re.compile(
    r"\b(?:connect|integrate|sync|hook up)\b|\bdata ?sources?\b|\bintegrations?\b|"
    r"\bimport (?:from|your|data|contacts|users|customers)\b|\bapi keys?\b|\bservice accounts?\b",
    re.I,
)


def needs_customer_credentials(task: str) -> bool:
    """A task only the real customer can finish (their data source, keys, or outside account)."""
    return bool(_CREDENTIAL_TASK_RE.search(task or ""))


def choose_tasks(data: dict[str, Any], read: dict[str, Any]) -> list[str]:
    """[core task, second task]: the public task when the page exposes it, else a second in-app task."""

    def clean(value: Any) -> str:
        return " ".join(str(value or "").split())[:120]

    legacy = [clean(t) for t in (data.get("tasks") or []) if clean(t)]
    core = clean(data.get("core_task")) or (legacy[0] if legacy else "")
    public = clean(data.get("public_task")) or (legacy[1] if len(legacy) > 1 else "")
    app = clean(data.get("app_task"))
    if core and needs_customer_credentials(core) and app and not needs_customer_credentials(app):
        # A fresh account cannot connect the customer's own data source: every
        # agent would stop at the connect form. Test what the product does instead.
        core, app = app, ""
    if app and needs_customer_credentials(app):
        app = ""
    if not core:
        return []
    links = list(read.get("links") or [])
    if read.get("failed"):
        # The page could not be read: nothing to ground on, keep the usual pair.
        return [core, public or _PRICING_TASK]
    if links and task_grounded(_PRICING_TASK, read):
        # The page links to pricing: the one public task every rival can be
        # judged on the same way (the pricing page itself).
        second = _PRICING_TASK
    elif links and public and task_grounded(public, read) and _checkable(public):
        second = public
    elif app and app.lower() != core.lower():
        # The page is the app (no links) or exposes no checkable public page:
        # a second thing to do in the product.
        second = app
    else:
        second = ""
    return [core, second] if second else [core]


def _checkable(task: str) -> bool:
    """A public task whose finish the agent can check from the page it lands on."""
    from mvp.a11y_agent import task_kind

    return task_kind(task) in {"pricing", "changelog", "help", "export"}


def _links_for_prompt(read: dict[str, Any]) -> str:
    links = list(read.get("links") or [])
    if not links:
        return "none (the page lists no links; it is probably the app itself)"
    # Mega-menus list dozens of features first; keep pricing and sign-up links in view.
    key = [pair for pair in links if _PRICING_RE.search(" ".join(pair)) or re.search(r"sign|log ?in|start|try", pair[0], re.I)]
    shown = links[:40] + [pair for pair in key if pair not in links[:40]][:8]
    return "; ".join(f"{label} -> {href}" if href else label for label, href in shown)


# Homepages of vendors that sell many unrelated products. A bare root URL of one
# of these is a company, not a competing product (figma.com -> adobe.com).
_SUITE_HOSTS = {
    "adobe.com", "google.com", "microsoft.com", "apple.com", "amazon.com", "aws.amazon.com",
    "oracle.com", "salesforce.com", "ibm.com", "meta.com", "sap.com", "zoho.com", "atlassian.com",
    "autodesk.com", "alphabet.com", "office.com",
}


def pick_competitors(items: list[Any], own: str, limit: int = 2) -> list[str]:
    """Up to ``limit`` direct rivals: not this site, not a suite vendor's bare homepage."""
    comps: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = item.get("url") or ""
        clean = _clean_url(str(item))
        parts = urlsplit(clean)
        host = (parts.hostname or "").removeprefix("www.")
        if not clean or not host or host == own or clean in comps:
            continue
        if host in _SUITE_HOSTS and parts.path.strip("/") == "":
            continue
        comps.append(clean)
        if len(comps) == limit:
            break
    return comps


def _host_of(url: str) -> str:
    return (urlsplit(_clean_url(url)).hostname or "").removeprefix("www.")


def resolve_favors(
    value: Any, own: str, comps: list[str], names: dict[str, str] | None = None, product: str = ""
) -> str:
    """'product' or the competitor URL (as picked) a persona or task favors; '' when unknown."""
    text = str(value or "").strip()
    low = text.lower()
    if not text:
        return ""
    own_words = {"product", "the product", own.lower(), own.lower().split(".")[0]}
    if product:
        own_words.add(product.lower())
    if low in own_words or _host_of(text) == own:
        return "product"
    for c in comps:
        host = _host_of(c)
        if host and (host == _host_of(text) or host.split(".")[0] in low):
            return c
    for raw, name in (names or {}).items():
        if name and name.lower() in low:
            for c in comps:
                if _host_of(c) == _host_of(raw):
                    return c
    return ""


def compare_personas(
    data: dict[str, Any], own: str, comps: list[str], names: dict[str, str], read: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Five personas with distinct names, each tagged with the product it is expected to favor and why."""
    out: list[dict[str, Any]] = []
    for item in data.get("personas") or []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        out.append(
            {
                "name": " ".join(str(item.get("name")).split())[:40],
                "role": " ".join(str(item.get("role") or "").split())[:80],
                "bio": " ".join(str(item.get("bio") or "").split())[:240],
                "favors": resolve_favors(item.get("favors"), own, comps, names),
                "favors_why": " ".join(str(item.get("why") or "").split())[:120],
            }
        )
    return unique_persona_names(out[:5], seed=own, read=read)


# Replacement names when the model repeats one. Two separate model calls (the
# early-start buyer and the full plan) each default to the same few names
# (Alex Chen, Sarah Chen, David Lee), so a spliced plan could list one twice.
_FIRST_NAMES = (
    "Priya", "Tomasz", "Amara", "Kenji", "Lucia", "Oluwaseun", "Ingrid", "Rafael", "Mei", "Dmitri",
    "Fatima", "Mateo", "Hana", "Kwame", "Sofia", "Arjun", "Leila", "Bruno", "Yuki", "Nadia",
    "Tobias", "Zanele", "Diego", "Aisha", "Henrik", "Camila", "Ravi", "Elif", "Marcus", "Noor",
)
_LAST_NAMES = (
    "Okafor", "Lindqvist", "Nakamura", "Haddad", "Kowalski", "Mensah", "Varga", "Castillo", "Iyer",
    "Petrov", "Duarte", "Brennan", "Sato", "Abara", "Moreau", "Novak", "Rahman", "Keller", "Osei",
    "Tanaka", "Ferreira", "Quinn", "Adeyemi", "Horvath", "Bianchi", "Nair", "Jensen", "Alvarez", "Kaur", "Dubois",
)


def _name_parts(name: str) -> tuple[str, str]:
    bits = str(name or "").lower().split()
    return (bits[0] if bits else "", bits[-1] if len(bits) > 1 else "")


def name_on_page(name: str, read: dict[str, Any] | None) -> bool:
    """True when a persona name was lifted from the page (a testimonial author, a showcase site)."""
    bits = [b for b in re.findall(r"[a-z]+", str(name or "").lower()) if len(b) > 1]
    if len(bits) < 2 or not read:
        return False
    blob = " ".join(
        [str(read.get("text") or ""), str(read.get("full_text") or "")]
        + [f"{label} {href}" for label, href in (read.get("links") or [])]
    ).lower()
    return (" ".join(bits) in blob) or ("".join(bits) in blob.replace(" ", ""))


def unique_persona_names(
    personas: list[dict[str, Any]], *, seed: str = "", keep_first: int = 0, read: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Give every persona a distinct first and last name.

    The first ``keep_first`` personas keep their names (the early buyer is
    already running under its name). A later persona that repeats a first or
    last name already used, or whose name was lifted from the page, gets a
    replacement picked deterministically from a fixed pool (seeded by
    ``seed``) that avoids every name already in the plan.
    """
    import zlib

    out = [dict(p) for p in personas]
    used_first: set[str] = set()
    used_last: set[str] = set()
    for p in out:
        first, last = _name_parts(p.get("name") or "")
        used_first.add(first)
        used_last.add(last)
    taken_first: set[str] = set()
    taken_last: set[str] = set()
    start = zlib.crc32(seed.encode()) if seed else 0
    for i, p in enumerate(out):
        first, last = _name_parts(p.get("name") or "")
        clash = (first in taken_first) or (last and last in taken_last)
        if i >= keep_first and (clash or not first or name_on_page(p.get("name") or "", read)):
            k = start + i * 7
            nf = next(f for j in range(len(_FIRST_NAMES)) if (f := _FIRST_NAMES[(k + j) % len(_FIRST_NAMES)]).lower() not in used_first | taken_first)
            nl = next(n for j in range(len(_LAST_NAMES)) if (n := _LAST_NAMES[(k * 3 + j) % len(_LAST_NAMES)]).lower() not in used_last | taken_last)
            p["name"] = f"{nf} {nl}"
            first, last = nf.lower(), nl.lower()
        taken_first.add(first)
        if last:
            taken_last.add(last)
    return out


def compare_tasks(data: dict[str, Any], own: str, comps: list[str], names: dict[str, str]) -> list[dict[str, Any]]:
    """Up to five tasks (no customer-credential tasks, one pricing task at most)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    pricing = 0
    for item in data.get("tasks") or []:
        if isinstance(item, str):
            item = {"task": item}
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("task") or "").split()).strip(" .")[:120]
        if not text or text.lower() in seen or needs_customer_credentials(text):
            continue
        if _PRICING_RE.search(text):
            pricing += 1
            if pricing > 1:
                continue
        seen.add(text.lower())
        out.append(
            {
                "prompt": text,
                "favors": resolve_favors(item.get("favors"), own, comps, names),
                "favors_why": " ".join(str(item.get("why") or "").split())[:120],
            }
        )
    return out[:5]


def compare_mode() -> bool:
    """5 personas x 5 tasks x product + 3 rivals, scored head to head (MVP_STUDY_MODE=compare).

    Off by default until the study output is agreed: a compare study is 100 agents.
    """
    return os.environ.get("MVP_STUDY_MODE", "classic").strip().lower() == "compare"


async def plan_from_url(url: str, *, timeout: float | None = None) -> dict[str, Any] | None:
    """{"segment", "competitors", "tasks"} for a bare URL, or None on any failure."""
    if compare_mode():
        plan = await compare_plan_from_url(url, timeout=timeout or float(os.environ.get("MVP_COMPARE_PLAN_TIMEOUT_S", "25")))
        if plan:
            return plan
    return await _classic_plan_from_url(url, timeout=timeout or 9.0)


async def compare_plan_from_url(url: str, *, timeout: float = 25.0) -> dict[str, Any] | None:
    """Split plan: competitors, then tasks and personas in parallel. Falls back to the single call."""
    if os.environ.get("MVP_COMPARE_PLAN_SPLIT", "0") == "1":
        plan = await _split_compare_plan(url, timeout=timeout)
        if plan:
            return plan
    return await _single_compare_plan(url, timeout=timeout)


async def _split_compare_plan(url: str, *, timeout: float = 25.0) -> dict[str, Any] | None:
    from capability.gemini_config import extract_json, gemini_chat

    model = os.environ.get("MVP_FAST_PLAN_MODEL") or "gemini-2.5-flash"

    async def ask(prompt: str) -> Any:
        raw = await gemini_chat(
            [{"role": "user", "content": prompt}], model=model, temperature=0.3, json_mode=True, max_retries=2
        )
        return extract_json(raw)

    async def _run() -> dict[str, Any] | None:
        t0 = asyncio.get_running_loop().time()
        read = await _page_read(url)
        text = prompt_text(read, 600)
        head = await ask(_CMP_COMPETITORS.format(url=url, title=read.get("title") or "", text=text) + read_rule())
        if not isinstance(head, dict):
            return None
        own = (urlsplit(url).hostname or "").removeprefix("www.")
        items = list(head.get("competitors") or [])
        names = {_clean_url(str(i.get("url") or "")): str(i.get("name") or "") for i in items if isinstance(i, dict)}
        raw_comps = pick_competitors(items, own, limit=3)
        if not raw_comps:
            return None
        product = str(head.get("product") or "")[:60] or own
        rivals = ", ".join(f"{names.get(c) or c} ({c})" for c in raw_comps)
        from mvp.server import _landing_url

        landed_f = asyncio.gather(*(_landing_url(c) for c in raw_comps))
        tasks_raw, personas_raw, landed = await asyncio.gather(
            ask(_CMP_TASKS.format(product=product, url=url, rivals=rivals, text=text)),
            ask(_CMP_PERSONAS.format(product=product, url=url, rivals=rivals, text=text)),
            landed_f,
        )
        landed = list(landed)
        personas = compare_personas(personas_raw if isinstance(personas_raw, dict) else {}, own, raw_comps, names, read)
        tasks = compare_tasks(tasks_raw if isinstance(tasks_raw, dict) else {}, own, raw_comps, names)
        if len(tasks) < 2 or len(personas) < 2:
            return None
        remap = dict(zip(raw_comps, landed))
        for row in personas + tasks:
            row["favors"] = remap.get(row["favors"], row["favors"])
        comp_names = {remap.get(k, k): v for k, v in names.items() if k in remap}
        took = round(asyncio.get_running_loop().time() - t0, 2)
        print(f"[fast_plan] compare(split {took}s) {url} rivals={landed} tasks={[t['prompt'] for t in tasks]}", flush=True)
        return {
            "mode": "compare",
            "product": product,
            "segment": " ".join(str(head.get("segment") or "").split())[:140],
            "competitors": landed,
            "competitor_names": comp_names,
            "personas": personas,
            "task_specs": tasks,
            "tasks": [t["prompt"] for t in tasks],
            "plan_s": took,
        }

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[fast_plan] split compare plan skipped: {exc!r}", flush=True)
        return None


def _positioning_note(pos: dict[str, Any]) -> str:
    """Prompt addendum carrying the positioning call's answer (empty when it did not run)."""
    if not pos or not str(pos.get("category") or "").strip():
        return ""
    alts = ", ".join(str(a) for a in (pos.get("compared_with") or []) if str(a).strip())[:200]
    return (
        f"\nPositioning, decided from the whole page (follow it): category: {pos.get('category')}. "
        f"What it is: {pos.get('what_it_is') or ''} Buyer: {pos.get('buyer') or ''}. "
        f"Buyers compare it with: {alts or 'unknown'}. It is not: {pos.get('not') or ''}\n"
        "Competitors, personas and tasks must all be in that category; the segment names that buyer."
    )


async def _verify_plan(
    url: str, title: str, full: str, data: dict[str, Any], prompt: str, ask: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Self-check: do the drafted rivals do the same job? If not, redo the plan with the corrected rivals."""
    items = [i for i in (data.get("competitors") or []) if isinstance(i, dict)]
    rivals = "; ".join(f"{i.get('name') or ''} ({i.get('url') or ''})" for i in items)
    check = await ask(_VERIFY.format(url=url, title=title, text=full, segment=data.get("segment") or "", rivals=rivals))
    if not isinstance(check, dict):
        return data, {}
    fits = [f for f in (check.get("fits") or []) if isinstance(f, dict)]
    bad = [f for f in fits if f.get("same_job") is False or str(f.get("same_job")).lower() == "false"]
    repl = [r for r in (check.get("replacements") or []) if isinstance(r, dict) and r.get("url")]
    verdict = {"category": check.get("category"), "rejected": [f.get("url") for f in bad], "replacements": repl[:3]}
    if not bad or len(repl) < 2:
        verdict["redo"] = False
        return data, verdict
    fixed = ", ".join(f"{r.get('name') or ''} ({r.get('url')})" for r in repl[:3])
    redo = await ask(
        prompt
        + f"\nA check of the whole page found this product's category is: {check.get('category')}. "
        f"Segment: {check.get('segment') or ''}. Use exactly these competitors, in this order: {fixed}. "
        "Write personas and tasks for that category."
    )
    verdict["redo"] = isinstance(redo, dict)
    return (redo if isinstance(redo, dict) else data), verdict


async def _single_compare_plan(url: str, *, timeout: float = 25.0) -> dict[str, Any] | None:
    """Comparison plan: 3 rivals, 5 personas spread across all 4 products, 5 tasks favoring each."""
    from capability.gemini_config import extract_json, gemini_chat

    modes = framing_modes()

    async def ask(prompt: str) -> Any:
        raw = await gemini_chat(
            [{"role": "user", "content": prompt}],
            model=os.environ.get("MVP_FAST_PLAN_MODEL") or "gemini-2.5-flash",
            temperature=0.3,
            json_mode=True,
            max_retries=2,
        )
        return extract_json(raw)

    async def _run() -> dict[str, Any] | None:
        read = await _page_read(url)
        title = read.get("title") or ""
        full = f"{read.get('text') or ''} {read.get('full_text') or ''}"[:3800]
        base_prompt = _COMPARE_PROMPT.format(url=url, title=title, text=prompt_text(read), links=_links_for_prompt(read))
        base_prompt += read_rule()
        positioning: dict[str, Any] = {}
        if "position" in modes:
            try:
                got = await ask(_POSITIONING.format(url=url, title=title, text=full))
                positioning = got if isinstance(got, dict) else {}
            except Exception as exc:  # noqa: BLE001
                print(f"[fast_plan] positioning skipped: {exc!r}", flush=True)
        prompt = base_prompt + _positioning_note(positioning)
        data = await ask(prompt)
        if not isinstance(data, dict):
            return None
        verified: dict[str, Any] = {}
        if "verify" in modes:
            try:
                data, verified = await _verify_plan(url, title, full, data, prompt, ask)
            except Exception as exc:  # noqa: BLE001
                print(f"[fast_plan] verify skipped: {exc!r}", flush=True)
        own = (urlsplit(url).hostname or "").removeprefix("www.")
        items = list(data.get("competitors") or [])
        names = {
            _clean_url(str(i.get("url") or "")): str(i.get("name") or "")
            for i in items
            if isinstance(i, dict)
        }
        raw_comps = pick_competitors(items, own, limit=3)
        if not raw_comps:
            return None
        from mvp.server import _landing_url

        landed = list(await asyncio.gather(*(_landing_url(c) for c in raw_comps)))
        # Tags were written against the planner's URLs; map them to where the rival lands.
        personas = compare_personas(data, own, raw_comps, names, read)
        tasks = compare_tasks(data, own, raw_comps, names)
        remap = dict(zip(raw_comps, landed))
        for row in personas + tasks:
            row["favors"] = remap.get(row["favors"], row["favors"])
        if len(tasks) < 2 or len(personas) < 2:
            return None
        comp_names = {remap.get(k, k): v for k, v in names.items() if k in remap}
        print(f"[fast_plan] compare {url} rivals={landed} tasks={[t['prompt'] for t in tasks]}", flush=True)
        return {
            "mode": "compare",
            "product": str(data.get("product") or "")[:60],
            "segment": " ".join(str(data.get("segment") or "").split())[:140],
            "competitors": landed,
            "competitor_names": comp_names,
            "personas": personas,
            "task_specs": tasks,
            "tasks": [t["prompt"] for t in tasks],
            "framing": sorted(modes),
            "positioning": positioning or None,
            "verified": verified or None,
        }

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[fast_plan] compare plan skipped: {exc!r}", flush=True)
        return None


async def _classic_plan_from_url(url: str, *, timeout: float = 9.0) -> dict[str, Any] | None:
    from capability.gemini_config import extract_json, gemini_chat

    async def _run() -> dict[str, Any] | None:
        read = await _page_read(url)
        prompt = _PROMPT.format(
            url=url, title=read.get("title") or "", text=read.get("text") or "", links=_links_for_prompt(read)
        )
        raw = await gemini_chat(
            [{"role": "user", "content": prompt}],
            model=os.environ.get("MVP_FAST_PLAN_MODEL") or "gemini-2.5-flash",
            temperature=0.2,
            json_mode=True,
            max_retries=2,
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            return None
        own = urlsplit(url).hostname or ""
        own = own.removeprefix("www.")
        comps = pick_competitors(data.get("competitors") or [], own)
        if comps:
            from mvp.server import _landing_url

            comps = list(await asyncio.gather(*(_landing_url(c) for c in comps[:2])))
        tasks = choose_tasks(data, read)
        if not tasks:
            return None
        print(f"[fast_plan] {url} links={len(read.get('links') or [])} tasks={tasks}", flush=True)
        return {
            "product": str(data.get("product") or "")[:60],
            "segment": " ".join(str(data.get("segment") or "").split())[:140],
            "competitors": comps[:2],
            "tasks": tasks[:2],
        }

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[fast_plan] skipped: {exc!r}", flush=True)
        return None
