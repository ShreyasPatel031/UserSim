"""Live-competitor URL checks and run-issue classification.

Competitors must be reachable product homepages. A URL that fails TLS, returns
an error, redirects to a different site, or announces a shutdown is dropped.
Agent runs that leave the task's target domain, or whose instructions name a
different site than the URL they open, are infrastructure errors — never
product friction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

# Review roundups and search engines are not products an agent should open.
_NON_PRODUCT_HOSTS = frozenset(
    {
        "duckduckgo.com",
        "google.com",
        "bing.com",
        "yahoo.com",
        "wikipedia.org",
        "g2.com",
        "capterra.com",
        "producthunt.com",
        "reddit.com",
        "medium.com",
        "youtube.com",
        "youtu.be",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "news.ycombinator.com",
        "techcrunch.com",
        "theverge.com",
        "forbes.com",
        "nytimes.com",
    }
)

_DEFUNCT_RE = re.compile(
    r"shut\s*down|we(?:'ve| have) (?:closed|shut)|no longer (?:available|operating|in business)|"
    r"this product (?:has )?(?:shut|closed)|permanently closed|"
    r"domain (?:is )?for sale|buy this domain|parked (?:free|domain)|"
    r"this (?:site|page|domain) (?:can(?:no|')t be reached|is (?:unavailable|for sale))|"
    r"website (?:has )?expired|account (?:has been )?suspended",
    re.I,
)

# Phrases that describe our harness, not the product.
_OUR_FAULT_RE = re.compile(
    r"incorrect competitor|wrong competitor|wrong website|wrong site|"
    r"landed on (?:the )?(?:wrong|incorrect)|"
    r"instead of (?:the )?(?:intended |correct )?(?:competitor|site|website)|"
    r"task misdirection|misdirection to competitor|"
    r"navigation error|infrastructure error|"
    r"derail(?:ing|ed) comparative|"
    r"not the (?:intended|right|correct) (?:site|website|competitor)|"
    r"ended up on (?!the (?:homepage|page)\b)",
    re.I,
)

_VS_URL_RE = re.compile(r"\s*\(vs\s+https?://[^)]+\)\s*$", re.I)
_INSTR_RE = re.compile(
    r"\n*You are evaluating the competitor site https?://\S+ only\. "
    r"Stay on that site — do not open the original product or other rivals\.\s*$",
    re.I,
)
_EXPLICIT_TARGET_RE = re.compile(
    r"(?:\(vs\s+|evaluating the competitor site\s+)(https?://[^\s)]+)",
    re.I,
)

FetchResult = tuple[int, str, str]
Fetcher = Callable[[str], Awaitable[FetchResult]]


def registrable_host(url: str) -> str:
    """Lowercase hostname without a leading www."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(a: str, b: str) -> bool:
    """True when both URLs are the same host or one is a subdomain of the other."""
    ha, hb = registrable_host(a), registrable_host(b)
    if not ha or not hb:
        return False
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def is_non_product_host(url: str) -> bool:
    host = registrable_host(url)
    if not host:
        return True
    return any(host == blocked or host.endswith("." + blocked) for blocked in _NON_PRODUCT_HOSTS)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    url: str
    final_url: str
    reason: str


def _normalize_final(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if text.endswith("/") and urlparse(text).path not in {"", "/"}:
        text = text.rstrip("/")
    return text


async def probe_competitor_url(
    url: str,
    *,
    fetch: Fetcher | None = None,
) -> ProbeResult:
    """Follow redirects. Keep the URL only when the final host is the same product."""
    requested = (url or "").strip()
    if not requested.startswith("http"):
        return ProbeResult(False, requested, "", "not_http")
    if is_non_product_host(requested):
        return ProbeResult(False, requested, "", "not_a_product_site")
    getter = fetch or _httpx_fetch
    try:
        status, final_url, body = await getter(requested)
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc!r}".replace("\n", " ")[:180]
        kind = "tls_or_connect_error"
        low = detail.lower()
        if "ssl" in low or "tls" in low or "certificate" in low:
            kind = "tls_error"
        elif "timed out" in low or "timeout" in low:
            kind = "timeout"
        return ProbeResult(False, requested, "", f"{kind}:{detail}")
    final_url = _normalize_final(final_url or requested)
    if status < 200 or status >= 400:
        return ProbeResult(False, requested, final_url, f"http_{status}")
    if not same_site(requested, final_url):
        return ProbeResult(
            False,
            requested,
            final_url,
            f"redirected_off_site:{registrable_host(final_url) or final_url}",
        )
    if is_non_product_host(final_url):
        return ProbeResult(False, requested, final_url, "not_a_product_site")
    snippet = (body or "")[:6000]
    if _DEFUNCT_RE.search(snippet):
        return ProbeResult(False, requested, final_url, "defunct_page")
    # Prefer the resolved URL so agents open the live origin, not a dead alias.
    canonical = final_url or requested
    if not canonical.endswith("/") and (urlparse(canonical).path in {"", "/"}):
        canonical = canonical.rstrip("/") + "/"
    return ProbeResult(True, canonical, final_url, "ok")


async def _httpx_fetch(url: str) -> FetchResult:
    import httpx

    async with httpx.AsyncClient(
        timeout=12.0,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        },
    ) as client:
        resp = await client.get(url)
        return resp.status_code, str(resp.url), resp.text or ""


async def filter_live_competitor_urls(
    urls: list[str],
    *,
    product_url: str,
    exclude_hosts: set[str] | None = None,
    fetch: Fetcher | None = None,
    limit: int = 2,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Probe candidates. Return (live canonical URLs, dropped (url, reason))."""
    product_host = registrable_host(product_url)
    blocked = {product_host} | {h.lower().removeprefix("www.") for h in (exclude_hosts or set()) if h}
    live: list[str] = []
    dropped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in urls:
        url = (raw or "").strip()
        if not url:
            continue
        host = registrable_host(url)
        if not host or host in blocked or host in seen:
            if url:
                dropped.append((url, "duplicate_or_product_host"))
            continue
        probe = await probe_competitor_url(url, fetch=fetch)
        if not probe.ok:
            dropped.append((url, probe.reason))
            blocked.add(host)
            continue
        final_host = registrable_host(probe.url)
        if not final_host or final_host in blocked or final_host in seen:
            dropped.append((url, "duplicate_or_product_host"))
            continue
        live.append(probe.url)
        seen.add(final_host)
        blocked.add(final_host)
        if len(live) >= limit:
            break
    return live, dropped


def rewrite_competitor_task(task: dict[str, Any], new_url: str) -> None:
    """Point site URL, title, and prompt at the same competitor."""
    new_url = (new_url or "").strip()
    host = registrable_host(new_url) or new_url
    title = _VS_URL_RE.sub("", str(task.get("title") or "Task")).strip()
    prompt = _INSTR_RE.sub("", str(task.get("prompt") or title)).strip()
    task["site_url"] = new_url
    task["site_label"] = f"Competitor · {host}"
    task["title"] = f"{title} (vs {new_url})"
    task["prompt"] = (
        f"{prompt}\n\n"
        f"You are evaluating the competitor site {new_url} only. "
        f"Stay on that site — do not open the original product or other rivals."
    )


def explicit_task_targets(result: dict[str, Any]) -> list[str]:
    text = f"{result.get('task_title') or ''}\n{result.get('task_prompt') or ''}"
    return [m.group(1).strip().rstrip(".,") for m in _EXPLICIT_TARGET_RE.finditer(text)]


def classify_run_issue(result: dict[str, Any]) -> dict[str, str] | None:
    """Flag harness failures. Product opinions on the right site are left alone."""
    if not isinstance(result, dict):
        return None
    target = str(result.get("site_url") or "").strip()
    final = str(result.get("final_url") or "").strip()
    if not target.startswith("http"):
        return None
    for instructed in explicit_task_targets(result):
        if instructed.startswith("http") and not same_site(instructed, target):
            return {
                "kind": "infrastructure",
                "reason": (
                    f"Task told the agent to evaluate {instructed} "
                    f"but the run opened {target}"
                ),
                "target_url": target,
                "final_url": final,
            }
    if not final or final.startswith("about:") or final.startswith("chrome-error"):
        return {
            "kind": "navigation",
            "reason": f"Agent never reached {target} (ended on {final or 'unknown'})",
            "target_url": target,
            "final_url": final,
        }
    if not same_site(final, target):
        return {
            "kind": "navigation",
            "reason": f"Agent ended on {final} instead of task target {target}",
            "target_url": target,
            "final_url": final,
        }
    return None


def annotate_run_issues(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Mark off-domain and mismatched-instruction runs. Returns the issue rows."""
    issues: list[dict[str, str]] = []
    for result in results or []:
        if not isinstance(result, dict):
            continue
        issue = classify_run_issue(result)
        if not issue:
            result.pop("run_issue", None)
            result.pop("exclude_from_insights", None)
            continue
        result["run_issue"] = issue
        result["exclude_from_insights"] = True
        issues.append(
            {
                **issue,
                "agent_id": str(result.get("agent_id") or result.get("task_id") or ""),
                "persona_name": str(result.get("persona_name") or ""),
                "task_title": str(result.get("task_title") or ""),
            }
        )
    return issues


def product_insight_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sessions that actually evaluated the task URL."""
    annotate_run_issues(results)
    return [r for r in results or [] if isinstance(r, dict) and not r.get("exclude_from_insights")]


def run_issue_lines(issues: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        who = issue.get("persona_name") or issue.get("agent_id") or "Agent"
        kind = issue.get("kind") or "infrastructure"
        reason = issue.get("reason") or "Run failed"
        lines.append(f"{who}: {kind} — {reason}")
    return lines


def _scrub_sentence(text: str) -> str:
    if not text or not _OUR_FAULT_RE.search(text):
        return text
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [p for p in parts if p and not _OUR_FAULT_RE.search(p)]
    return " ".join(kept).strip()


def scrub_product_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Remove harness failures from headline, friction, strengths, and recommendations."""
    if not isinstance(summary, dict):
        return {}
    out = dict(summary)
    friction = [
        str(item)
        for item in (out.get("top_friction") or [])
        if item and not _OUR_FAULT_RE.search(str(item))
    ]
    strengths = [
        str(item)
        for item in (out.get("top_strengths") or [])
        if item and not _OUR_FAULT_RE.search(str(item))
    ]
    recs = []
    for rec in out.get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        blob = f"{rec.get('action') or ''} {rec.get('rationale') or ''}"
        if _OUR_FAULT_RE.search(blob):
            continue
        recs.append(rec)
    headline = _scrub_sentence(str(out.get("headline") or ""))
    if not headline:
        headline = (
            strengths[0]
            if strengths
            else "Simulated users reviewed the product on its live site."
        )
    outlook = _scrub_sentence(str(out.get("conversion_outlook") or ""))
    rationale = _scrub_sentence(str(out.get("segment_fit_rationale") or ""))
    out["top_friction"] = friction
    out["top_strengths"] = strengths
    out["recommendations"] = recs
    out["headline"] = headline
    out["conversion_outlook"] = outlook
    out["segment_fit_rationale"] = rationale
    return out
