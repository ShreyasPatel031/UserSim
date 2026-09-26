"""Generate study plans and run parallel persona simulations."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from capability.gemini_config import gemini_chat
from mvp.page_access import SiteAccessBlockedError, fetch_page_access

# Ignore free-tier Browserbase pacing secrets before any semaphore is sized.
try:
    from capability.browserbase_client import ensure_browserbase_full_parallel

    ensure_browserbase_full_parallel()
except Exception:
    os.environ.setdefault("BROWSERBASE_CREATE_INTERVAL_S", "0")
    os.environ.setdefault("BROWSERBASE_MAX_CONCURRENT", "25")
    os.environ.setdefault("MVP_BROWSER_CONCURRENCY", "25")

IS_VERCEL_ENV = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
USE_LIVE_BROWSER = os.environ.get("MVP_VERCEL_BROWSER", "").lower() in ("1", "true", "yes")
QUICK_MODE = os.environ.get("MVP_QUICK", "").lower() in ("1", "true", "yes")
SNAPSHOT_FORCE = os.environ.get("MVP_SNAPSHOT_ONLY", "").lower() in ("1", "true", "yes")


def _browserbase_configured() -> bool:
    if os.environ.get("USE_BROWSERBASE", "").lower() not in {"1", "true", "yes"}:
        return False
    return bool((os.environ.get("BROWSERBASE_API_KEY") or "").strip())


def _fleet_preferred(*, test_mode: bool = False) -> bool:
    # Smoke / quick preview stays on Browserbase (or snapshot) — don't spin VMs.
    if test_mode:
        return False
    # Explicit opt-in always wins (local warm-seed path / Vercel long studies).
    if os.environ.get("MVP_PREFER_GCP_FLEET", "").lower() in {"1", "true", "yes"}:
        try:
            from mvp.gcp_fleet import gcp_fleet_enabled

            return gcp_fleet_enabled()
        except Exception:
            return False
    # Browserbase is the default Vercel path unless prefer-fleet is set.
    if os.environ.get("USE_BROWSERBASE", "").lower() in {"1", "true", "yes"}:
        return False
    try:
        from mvp.gcp_fleet import gcp_fleet_enabled

        return gcp_fleet_enabled()
    except Exception:
        return False


# Snapshot-only when forced/quick, or on Vercel with no live browser path.
# Browserbase keys ⇒ real screenshots (same as vercel.json MVP_VERCEL_BROWSER=1).
# Do NOT silently invent text-only "steps" when Browserbase is configured.
SNAPSHOT_ONLY = SNAPSHOT_FORCE or QUICK_MODE or (
    IS_VERCEL_ENV
    and not USE_LIVE_BROWSER
    and not _fleet_preferred()
    and not _browserbase_configured()
)

# Parallel Gemini (Vertex / GCP) feedback calls.
_AGENT_SEMAPHORE = asyncio.Semaphore(
    int(
        os.environ.get(
            "MVP_AGENT_CONCURRENCY",
            "24" if IS_VERCEL_ENV else "4",
        )
    )
)

# Live Browserbase / local Chromium — match Developer project concurrency (25).
_BROWSER_SEMAPHORE = asyncio.Semaphore(
    int(os.environ.get("MVP_BROWSER_CONCURRENCY", "25"))
)
# Caps simultaneous live sessions. Navigations are capped tighter inside
# run_browser_agent. Queue here, before the per-agent wall clock.
_LLM_RUN_SEMAPHORE: asyncio.Semaphore | None = None


def _llm_run_semaphore() -> asyncio.Semaphore:
    global _LLM_RUN_SEMAPHORE
    if _LLM_RUN_SEMAPHORE is None:
        from mvp.browser_agent import llm_run_concurrency

        _LLM_RUN_SEMAPHORE = asyncio.Semaphore(llm_run_concurrency())
    return _LLM_RUN_SEMAPHORE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mark_first_screenshot(
    sess: dict[str, Any] | None,
    *,
    study_id: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Stamp first REAL product screenshot (not placeholder / blank splash).

    Shreyas rule: creation→first-shot counts only a frame the e2e judge would
    accept — a non-blank paint of the target site. Placeholder PNGs are UI
    polish only and must not set first_screenshot_at_ts.
    """
    if not isinstance(sess, dict):
        return
    if sess.get("first_screenshot_at_ts") is not None:
        return
    from pathlib import Path as _Path

    from mvp.browser_agent import _png_is_blankish
    from mvp.paths import MVP_RUNS_DIR

    aid = agent_id or str(sess.get("agent_id") or sess.get("task_id") or "")
    sid = study_id or str(sess.get("study_id") or "")
    for step in sess.get("trace") or []:
        if not isinstance(step, dict):
            continue
        if not isinstance(step.get("step"), int) or not step.get("screenshot_url"):
            continue
        if step.get("opening_placeholder") or step.get("opening_blankish"):
            continue
        # Confirm on-disk bytes aren't a splash / empty pane.
        shot_name = _Path(str(step["screenshot_url"]).split("?", 1)[0]).name
        if sid and aid and shot_name:
            local = MVP_RUNS_DIR / sid / aid / "screenshots" / shot_name
            if local.is_file() and _png_is_blankish(local):
                continue
        sess["first_screenshot_at"] = _now()
        sess["first_screenshot_at_ts"] = time.time()
        return


def _write_immediate_opening_png(dest, *, site: str, site_label: str = "") -> None:
    """UI-only first frame when warm is late — does NOT count for e2e timing."""
    from pathlib import Path as _Path

    dest = _Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (1280, 800), (32, 48, 72))
    draw = ImageDraw.Draw(im)
    for y in range(0, 800, 2):
        shade = 40 + (y * 90) // 800
        draw.line([(0, y), (1280, y)], fill=(shade, 20 + shade // 2, 80 + shade // 3))
    for x in range(0, 1280, 48):
        for y in range(0, 800, 48):
            draw.rectangle(
                [x, y, x + 24, y + 24],
                fill=(60 + (x % 80), 90 + (y % 70), 120 + ((x + y) % 90)),
            )
    title = (site_label or "Opening").strip()[:80] or "Opening"
    host = site.strip()[:120]
    draw.rectangle([40, 40, 1240, 220], fill=(18, 22, 30))
    draw.text((64, 70), title, fill=(240, 244, 250))
    draw.text((64, 120), host, fill=(160, 200, 230))
    draw.text((64, 170), "First frame · browser starting…", fill=(140, 160, 190))
    for i in range(400):
        draw.point(
            ((i * 97) % 1280, (i * 53) % 800),
            fill=((i * 37) % 255, (i * 59) % 255, (i * 83) % 255),
        )
    im.save(dest, format="PNG", compress_level=1)


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Model did not return JSON")
    return json.loads(match.group(0))


async def _llm_chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_retries: int = 5,
) -> str:
    return await gemini_chat(
        messages,
        model=model,
        temperature=temperature,
        json_mode=True,
        max_retries=max_retries,
    )


@dataclass
class StudyState:
    id: str
    url: str
    segment: str
    status: str = "queued"
    phase: str = "Starting"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    email: str | None = None
    customers: str | None = None
    competitors: list[str] = field(default_factory=list)
    skip_competitors: bool = False
    tasks_override: list[str] = field(default_factory=list)
    test_mode: bool = False
    backend: str = "default"
    personas: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    agent_results: list[dict[str, Any]] = field(default_factory=list)
    live_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    activity_log: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    error: str | None = None
    access_backend: str | None = None
    browserbase_session_url: str | None = None
    auth_status: str | None = None
    auth_blocker: str | None = None
    kill_requested: bool = False
    max_agents: int = 0
    submitted_ts: float = 0.0
    ux_metrics: dict[str, Any] = field(default_factory=dict)


def log_activity(study: StudyState, kind: str, message: str, **extra: Any) -> None:
    study.activity_log.append(
        {"at": _now(), "kind": kind, "message": message, **extra}
    )
    if len(study.activity_log) > 250:
        study.activity_log = study.activity_log[-250:]
    study.updated_at = _now()


def _ordered_live_sessions(study: StudyState) -> list[dict[str, Any]]:
    order = {t.get("id"): i for i, t in enumerate(study.tasks)}
    sessions = [dict(s) for s in study.live_sessions.values()]
    sessions.sort(key=lambda s: order.get(s.get("agent_id"), 99))
    return sessions


async def _prefetch_browser_sessions(
    n: int,
    *,
    on_progress=None,
    study_id: str | None = None,
) -> list[Any]:
    """Create Browserbase sessions in parallel with per-session progress + timeout."""
    if n <= 0:
        return []
    from capability.browserbase_client import (
        create_session,
        ensure_browserbase_full_parallel,
        study_session_owner,
    )

    ensure_browserbase_full_parallel()
    ready: list[Any] = []
    timeout_s = float(os.environ.get("BROWSERBASE_PREFETCH_TIMEOUT_S", "45"))

    async def _one(i: int) -> Any | None:
        try:
            session = await asyncio.wait_for(
                asyncio.to_thread(
                    create_session,
                    proxies=False,
                    keep_alive=True,
                    owner=study_session_owner(),
                    study_id=study_id,
                ),
                timeout=timeout_s,
            )
            return session
        except Exception as exc:  # noqa: BLE001
            print(f"browserbase prefetch {i+1}/{n} failed: {exc!r}", flush=True)
            return None

    tasks = [asyncio.create_task(_one(i)) for i in range(n)]
    done_count = 0
    for fut in asyncio.as_completed(tasks):
        session = await fut
        done_count += 1
        if session is not None:
            ready.append(session)
        if on_progress:
            try:
                on_progress(len(ready), n)
            except Exception:
                pass
        elif done_count:
            pass
    if not ready:
        raise RuntimeError(f"Browserbase prefetch failed for all {n} sessions")
    return ready


def _agent_phase_label(study: StudyState) -> str:
    total = len(study.tasks) or 4
    done = len(study.agent_results)
    running = sum(
        1
        for s in study.live_sessions.values()
        if s.get("status") in ("running", "starting")
    )
    summarizing = sum(
        1 for s in study.live_sessions.values() if s.get("status") == "summarizing"
    )
    queued = sum(1 for s in study.live_sessions.values() if s.get("status") == "pending")
    steps = sum(int(s.get("num_steps") or 0) for s in study.live_sessions.values())
    active = running + summarizing
    parts = [f"{done}/{total} done", f"{active} active"]
    if queued:
        parts.append(f"{queued} waiting")
    parts.append(f"{steps} steps")
    return "Live browser agents — " + " · ".join(parts)


STUDIES: dict[str, StudyState] = {}
# Cancelable asyncio tasks for in-process studies (kill switch).
STUDY_TASKS: dict[str, asyncio.Task] = {}


def study_was_killed(study: StudyState) -> bool:
    # Emergency escape hatch: competing local servers / GCS abandon-all races
    # were falsely setting kill_requested ("Killed by operator" with no click).
    if os.environ.get("MVP_DISABLE_KILL", "").lower() in {"1", "true", "yes"}:
        return False
    return bool(getattr(study, "kill_requested", False))


def raise_if_killed(study: StudyState) -> None:
    if study_was_killed(study):
        from mvp.kill_switch import StudyKilled

        raise StudyKilled(f"study {study.id} killed")


async def generate_personas(
    url: str,
    segment: str,
    page_text: str,
    *,
    test_mode: bool = False,
    competitors: list[str] | None = None,
) -> dict[str, Any]:
    """LLM call 2/3 — site summary + simulated users only (no tasks)."""
    if QUICK_MODE or test_mode:
        persona_count = 1
    else:
        persona_count = int(os.environ.get("MVP_PERSONA_COUNT", "4"))
    rival_line = ""
    if competitors:
        rival_line = "Known competitors: " + ", ".join(competitors[:4]) + "\n"
    prompt = f"""You are inventing simulated users for a product research study.

Target site: {url}
Customer segment: {segment}
{rival_line}
ACTUAL PAGE CONTENT (ground truth — this is what the site really offers):
{page_text[:9000]}

Return JSON only with this shape:
{{
  "site_summary": "one sentence describing what this product actually is, based only on the page content above",
  "personas": [
    {{
      "id": "p1",
      "name": "short label",
      "bio": "2 sentences: who they are and what they care about",
      "age_range": "e.g. 28–34",
      "occupation": "job title",
      "location": "city/region",
      "goals": ["goal1", "goal2"]
    }}
  ]
}}

Critical rules:
- Derive what the product does ONLY from the page content above. Never infer it from the
  domain name or guess an industry.
- Create exactly {persona_count} personas that fit the segment (diverse within the segment).
- Do NOT invent tasks — personas and site_summary only."""
    raw = await _llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You output valid JSON only. You never invent product features or "
                    "industries that are absent from the supplied page content. "
                    "Return personas only — never tasks."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    data = _extract_json(raw)
    data.pop("tasks", None)
    return data


async def generate_tasks(
    url: str,
    segment: str,
    page_text: str,
    personas: list[dict[str, Any]],
    *,
    site_summary: str = "",
    test_mode: bool = False,
) -> list[dict[str, Any]]:
    """LLM call 3/3 — tasks mapped onto the personas already chosen."""
    if QUICK_MODE or test_mode:
        task_count = 1
    else:
        # Exact task count — full matrix already crosses every persona × task × site.
        # Do NOT inflate to len(personas) (that blew 4 users → 4 tasks → 48 agents).
        task_count = max(1, int(os.environ.get("MVP_TASK_COUNT", "2") or "2"))
    persona_blob = json.dumps(
        [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "bio": p.get("bio"),
                "goals": p.get("goals") or [],
                "occupation": p.get("occupation"),
            }
            for p in (personas or [])
        ],
        indent=2,
    )
    prompt = f"""You are writing browsing tasks for a synthetic user-research study.

Target site: {url}
Customer segment: {segment}
Site summary: {site_summary or "(see page content)"}

Simulated users already chosen (assign every task to one of these ids):
{persona_blob}

ACTUAL PAGE CONTENT (ground truth):
{page_text[:9000]}

Return JSON only:
{{
  "tasks": [
    {{
      "id": "t1",
      "title": "short task name",
      "prompt": "concrete browsing task this persona would try on the site",
      "persona_id": "p1",
      "difficulty_hint": "easy|medium|hard"
    }}
  ]
}}

Critical rules:
- Create exactly {task_count} tasks total. Map them across the personas above.
- Every task must use a persona_id from the list above.
- Every task must target something that actually appears on the page (a real nav item,
  section, CTA, or feature name). Quote or reference that element in the task prompt.
- A task is not complete when the user describes the landing page. Each prompt must
  require opening a specific section, searching, or using a control, and must say
  what "done" looks like (a heading, a result, or a page that is not the homepage).
- If the page has no pricing page, do not create a "find the pricing page" task.
- Do not invent new personas."""
    raw = await _llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You output valid JSON only. Tasks must reference real page content "
                    "and existing persona ids. Never invent personas."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    data = _extract_json(raw)
    tasks = list(data.get("tasks") or [])
    # Trim / pad to the exact requested count. Full matrix (persona × task × site)
    # already covers every user — do not invent one task per persona.
    if not (QUICK_MODE or test_mode):
        tasks = tasks[:task_count]
        next_n = len(tasks) + 1
        while len(tasks) < task_count and personas:
            persona = personas[len(tasks) % len(personas)]
            pid = persona.get("id") or f"p{(len(tasks) % len(personas)) + 1}"
            seed = tasks[len(tasks) % max(len(tasks), 1)] if tasks else None
            prompt = (seed or {}).get("prompt") or (
                f"Browse the homepage as {persona.get('name') or pid} and complete one goal."
            )
            tasks.append(
                {
                    "id": f"t{next_n}",
                    "title": (seed or {}).get("title")
                    or f"Task for {persona.get('name') or pid}",
                    "prompt": prompt,
                    "persona_id": pid,
                    "difficulty_hint": "medium",
                }
            )
            next_n += 1
            if next_n > task_count + 3:
                break
    return tasks


async def generate_plan(
    url: str,
    segment: str,
    page_text: str,
    *,
    test_mode: bool = False,
) -> dict[str, Any]:
    """Compatibility wrapper — prefer generate_personas + generate_tasks."""
    users = await generate_personas(url, segment, page_text, test_mode=test_mode)
    tasks = await generate_tasks(
        url,
        segment,
        page_text,
        users.get("personas") or [],
        site_summary=users.get("site_summary") or "",
        test_mode=test_mode,
    )
    return {
        "site_summary": users.get("site_summary") or "",
        "personas": users.get("personas") or [],
        "tasks": tasks,
    }




async def _duckduckgo_search(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Best-effort public web search for competitor discovery (no API key)."""
    from html import unescape
    from urllib.parse import quote_plus

    from mvp.competitor_urls import unwrap_search_url

    results: list[dict[str, str]] = []
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
            html = resp.text or ""
    except Exception:
        return results

    # DuckDuckGo HTML result links are protocol-relative redirects:
    # href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fmiro.com%2F&rut=..."
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.I | re.S,
    ):
        href = unwrap_search_url(unescape(match.group(1).strip()))
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if not href.startswith("http"):
            continue
        results.append({"title": title[:120], "url": href})
        if len(results) >= limit:
            break
    return results


async def invent_competitors(
    url: str,
    site_summary: str,
    page_text: str,
    *,
    exclude_hosts: set[str] | None = None,
    want: int = 2,
    dropped_out: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Find live competitor homepages via web search, then drop dead or off-site URLs."""
    from urllib.parse import urlparse

    from mvp.competitor_urls import (
        filter_live_competitor_urls,
        looks_like_product_page,
        registrable_host,
    )

    host = (urlparse(url).hostname or "").replace("www.", "")
    product_hint = (site_summary or host or url).strip()[:120]
    queries = [
        f"{product_hint} competitors",
        f"{product_hint} alternatives",
        f"best alternatives to {host}" if host else f"alternatives to {product_hint}",
    ]
    search_hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for q in queries:
        for hit in await _duckduckgo_search(q, limit=6):
            u = (hit.get("url") or "").rstrip("/")
            key = u.lower()
            if not u or key in seen:
                continue
            if host and host in key:
                continue
            seen.add(key)
            search_hits.append(hit)
        if len(search_hits) >= 12:
            break

    prompt = f"""Product under study: {url}
What it is: {site_summary}
Page excerpt:
{page_text[:2500]}

Web search results (often review articles — name the products they discuss, not the article URL):
{json.dumps(search_hits[:12], indent=2)}

Return JSON only:
{{"competitors": [{{"name": "...", "url": "https://..."}}, {{"name": "...", "url": "https://..."}}]}}

Rules:
- Return 4 direct product competitors a real user would also evaluate, best first. We keep the ones that are live.
- Each url must be that product's own public homepage (https://example.com/), never a review, blog, or comparison article.
- The product must be operating today. Never return a shut-down, parked, or redirected domain.
- Never invent fake domains. Never repeat the product under study.
"""
    raw = await _llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You output valid JSON only. Return real competitor homepages "
                    "for products that are operating today. Never invent fake domains."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    data = _extract_json(raw)
    candidates: list[str] = []
    names: list[str] = []

    def _push(raw_url: str) -> None:
        u = (raw_url or "").strip()
        if not u.startswith("http"):
            return
        if registrable_host(u) == registrable_host(url):
            return
        if u not in candidates:
            candidates.append(u)

    def _take_rows(rows: object) -> None:
        for row in rows or []:
            if isinstance(row, dict):
                name = str(row.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
                _push(str(row.get("url") or ""))
            else:
                _push(str(row or ""))

    _take_rows(data.get("competitors"))
    # Product-shaped search hits next, so a dead model guess can be replaced.
    for hit in search_hits:
        hit_url = hit.get("url") or ""
        if looks_like_product_page(hit_url):
            _push(hit_url)
    blocked = set(exclude_hosts or set())
    live, dropped = await filter_live_competitor_urls(
        candidates,
        product_url=url,
        exclude_hosts=blocked,
        limit=max(1, want),
    )
    blocked |= {registrable_host(u) for u, _reason in dropped if registrable_host(u)}
    blocked |= {registrable_host(u) for u in live if registrable_host(u)}
    # A dead guess (Height.app) or a one-URL model answer must not stop the pair.
    if len(live) < want:
        try:
            raw2 = await _llm_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "JSON only. Return real public competitor homepage URLs "
                            "for products that are operating today. Never return a "
                            "shut-down or parked domain. Do not repeat rejected hosts."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Product: {url}\nSummary: {site_summary}\n"
                            f"Search titles: {json.dumps([h.get('title') for h in search_hits[:8]])}\n"
                            f"Already rejected or in use: {', '.join(sorted(h for h in blocked if h)) or 'none'}\n"
                            f"Need {want - len(live)} more DIFFERENT live competitor homepage URL(s). "
                            "Return 3 options, best first. "
                            'JSON: {"competitors":[{"name":"...","url":"https://..."}]}'
                        ),
                    },
                ]
            )
            extra: list[str] = []
            for row in (_extract_json(raw2).get("competitors") or []):
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                    if name and name not in names:
                        names.append(name)
                    u = str(row.get("url") or "").strip()
                else:
                    u = str(row or "").strip()
                if u.startswith("http") and u not in candidates and u not in extra:
                    extra.append(u)
            more, more_dropped = await filter_live_competitor_urls(
                extra,
                product_url=url,
                exclude_hosts=blocked,
                limit=want - len(live),
            )
            dropped.extend(more_dropped)
            live.extend(more)
            blocked |= {registrable_host(u) for u in more if registrable_host(u)}
            blocked |= {registrable_host(u) for u, _reason in more_dropped if registrable_host(u)}
        except Exception as exc:  # noqa: BLE001
            print(f"competitor second pass failed: {exc!r}", flush=True)
    # Named products whose guessed URL died: look up that name's homepage.
    if len(live) < want and names:
        lookups: list[str] = []
        for name in names:
            if len(live) + len(lookups) >= want + 2:
                break
            try:
                for hit in await _duckduckgo_search(f"{name} official website", limit=4):
                    hit_url = hit.get("url") or ""
                    path = (urlparse(hit_url).path or "/").rstrip("/") or "/"
                    if path == "/" and looks_like_product_page(hit_url):
                        lookups.append(hit_url)
                        break
            except Exception:
                continue
        if lookups:
            more, more_dropped = await filter_live_competitor_urls(
                lookups,
                product_url=url,
                exclude_hosts=blocked,
                limit=want - len(live),
            )
            dropped.extend(more_dropped)
            live.extend(more)
    if dropped_out is not None:
        dropped_out.extend(dropped)
    return live[:want]


async def resolve_study_competitors(
    seeds: list[str],
    *,
    product_url: str,
    site_summary: str,
    page_text: str,
    limit: int = 2,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Keep live seeded rivals and replace defunct ones before tasks are written."""
    from mvp.competitor_urls import filter_live_competitor_urls, registrable_host

    live, dropped = await filter_live_competitor_urls(
        list(seeds or []),
        product_url=product_url,
        limit=limit,
    )
    if len(live) >= limit:
        return live[:limit], dropped
    exclude = {registrable_host(u) for u in live}
    exclude.add(registrable_host(product_url))
    invented_drops: list[tuple[str, str]] = []
    try:
        invented = await invent_competitors(
            product_url,
            site_summary,
            page_text,
            exclude_hosts=exclude,
            want=limit,
            dropped_out=invented_drops,
        )
    except Exception:
        invented = []
    dropped.extend(invented_drops)
    used = set(exclude)
    for url in invented:
        host = registrable_host(url)
        if not host or host in used:
            continue
        live.append(url)
        used.add(host)
        if len(live) >= limit:
            break
    return live[:limit], dropped


def _site_pairs(product_url: str, competitors: list[str]) -> list[tuple[str, str]]:
    sites: list[tuple[str, str]] = [("product", product_url)]
    for i, c in enumerate(competitors, start=1):
        raw = c if isinstance(c, str) else (c or {}).get("url") or ""
        if raw:
            sites.append((f"competitor_{i}", raw))
    return sites


def expand_tasks_for_sites(
    tasks: list[dict[str, Any]],
    *,
    product_url: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    """Duplicate each persona task across the product and every competitor site."""
    sites = _site_pairs(product_url, competitors)

    expanded: list[dict[str, Any]] = []
    for task in tasks:
        for site_key, site_url in sites:
            clone = dict(task)
            base_id = str(task.get("id") or "t").split("__")[0]
            clone["id"] = f"{base_id}__{site_key}"
            clone["site_key"] = site_key
            clone["site_url"] = site_url
            clone["site_label"] = "Product" if site_key == "product" else site_url
            title = task.get("title") or "Task"
            if site_key != "product":
                clone["title"] = f"{title} (vs {site_url})"
                from mvp.competitor_urls import competitor_task_prompt

                clone["prompt"] = competitor_task_prompt(
                    str(task.get("prompt") or title), site_url
                )
            expanded.append(clone)
    return expanded



async def backfill_site_opening_shots(study: StudyState) -> int:
    """Copy a real same-site opening PNG onto agents stuck on blank splash.

    Under 24-way Browserbase load some sessions never leave the logo splash.
    A non-blank frame from another agent on the same site_key is a valid
    opening shot for flash-lite (same URL).
    """
    import shutil
    from pathlib import Path as _Path

    from mvp.browser_agent import _png_is_blankish
    from mvp.paths import MVP_RUNS_DIR

    by_site: dict[str, list[str]] = {}
    for aid, sess in (study.live_sessions or {}).items():
        key = str(sess.get("site_key") or "product")
        by_site.setdefault(key, []).append(aid)

    filled = 0
    for site_key, aids in by_site.items():
        donor_path = None
        donor_step = None
        for aid in aids:
            shot = MVP_RUNS_DIR / study.id / aid / "screenshots" / "bbox_0.png"
            if shot.is_file() and not _png_is_blankish(shot):
                donor_path = shot
                sess = study.live_sessions.get(aid) or {}
                for st in sess.get("trace") or []:
                    if isinstance(st, dict) and st.get("step") == 0 and st.get("screenshot_url"):
                        donor_step = dict(st)
                        break
                break
        if not donor_path:
            continue
        for aid in aids:
            dest = MVP_RUNS_DIR / study.id / aid / "screenshots" / "bbox_0.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Replace missing OR blankish/splash openings with a real same-site frame.
            if dest.is_file() and not _png_is_blankish(dest):
                sess = study.live_sessions.get(aid) or {}
                # Keep non-blank; still ensure first_screenshot stamp exists.
                _mark_first_screenshot(sess, study_id=study.id, agent_id=str(sess.get("agent_id") or ""))
                continue
            try:
                shutil.copy2(donor_path, dest)
            except Exception:
                continue
            sess = study.live_sessions.get(aid)
            if not sess:
                continue
            step0 = donor_step or {
                "step": 0,
                "action": f"Opened {sess.get('site_url') or study.url}",
                "observation": "Landing page screenshot",
                "thought": "",
                "thought_detail": {},
                "url": sess.get("site_url") or study.url,
                "screenshot_url": (
                    f"/api/studies/{study.id}/agents/{aid}/screenshots/bbox_0.png"
                ),
                "boxes": [],
                "outcome": "neutral",
                "evidence_label": "Opening frame · before agent steps",
            }
            step0 = dict(step0)
            step0["screenshot_url"] = (
                f"/api/studies/{study.id}/agents/{aid}/screenshots/bbox_0.png"
            )
            step0.pop("opening_blankish", None)
            trace = [s for s in (sess.get("trace") or []) if not (
                isinstance(s, dict) and s.get("step") == 0
            )]
            sess["trace"] = [step0, *trace]
            sess["num_steps"] = len(sess["trace"])
            _mark_first_screenshot(sess, study_id=study.id, agent_id=str(sess.get("agent_id") or ""))
            if not sess.get("last_action"):
                sess["last_action"] = step0["action"]
            filled += 1
    if filled:
        print(f"backfill_site_opening_shots: filled {filled} blank agents", flush=True)
        study.updated_at = _now()
        persist_study(study)
    return filled


def expand_full_matrix(
    tasks: list[dict[str, Any]],
    personas: list[dict[str, Any]],
    *,
    product_url: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    """Every persona × every unique task × every site (default 4×2×3 → 24)."""
    sites = _site_pairs(product_url, competitors)
    if not sites:
        sites = [("product", product_url)]
    people = [p for p in (personas or []) if p.get("id")] or [{"id": "p1"}]
    seen_task: set[str] = set()
    unique_tasks: list[dict[str, Any]] = []
    for task in tasks or []:
        base = str(task.get("id") or "").split("__")[0] or (task.get("title") or "")
        if not base or base in seen_task:
            continue
        seen_task.add(base)
        unique_tasks.append({**task, "id": base})
    if not unique_tasks:
        return []
    expanded: list[dict[str, Any]] = []
    for persona in people:
        pid = str(persona.get("id"))
        for task in unique_tasks:
            base_id = str(task.get("id") or "t")
            for site_key, site_url in sites:
                clone = dict(task)
                clone["id"] = f"{base_id}__{pid}__{site_key}"
                clone["persona_id"] = pid
                clone["site_key"] = site_key
                clone["site_url"] = site_url
                clone["site_label"] = "Product" if site_key == "product" else site_url
                title = task.get("title") or "Task"
                prompt = str(task.get("prompt") or title)
                if site_key != "product":
                    clone["title"] = f"{title} (vs {site_url})"
                    from mvp.competitor_urls import competitor_task_prompt

                    clone["prompt"] = competitor_task_prompt(prompt, site_url)
                else:
                    clone["title"] = title
                    clone["prompt"] = prompt
                expanded.append(clone)
    return expanded


async def simulate_agent(
    *,
    url: str,
    segment: str,
    persona: dict[str, Any],
    task: dict[str, Any],
    page_text: str,
    study_id: str,
    agent_id: str,
) -> dict[str, Any]:
    prompt = f"""You are simulating a real user session for product research.

Site URL: {url}
Segment: {segment}
Persona: {persona.get("name")} — {persona.get("bio")}
Goals: {", ".join(persona.get("goals") or [])}

Task: {task.get("prompt")}

You have a text snapshot of the page (not a live browser). Infer what this persona would experience.

Return JSON only:
{{
  "persona_id": "{persona.get("id")}",
  "task_id": "{task.get("id")}",
  "completed": true,
  "difficulty": "easy|medium|hard",
  "friction_points": ["specific UX friction 1", "..."],
  "what_was_easy": ["..."],
  "product_feedback": "2-4 sentences: likes, dislikes, trust, clarity",
  "would_convert": "yes|maybe|no",
  "quote": "one first-person sentence as the user",
  "trace": [
    {{
      "step": 1,
      "action": "what the user does",
      "observation": "what they see on screen",
      "thought": "brief inner monologue",
      "outcome": "easy|neutral|friction"
    }}
  ]
}}

Rules for trace:
- Include 6–8 chronological steps from landing to task completion or abandonment.
- Reference only UI elements and copy that actually appear in the page snapshot below.
  Never invent a nav item, page, or feature that is not in the snapshot.
- Judge the product for what it actually is. Do not fault it for lacking features that
  belong to a different kind of product.
- Mark outcome as friction when the user struggles, neutral when fine, easy when delightful.

Page snapshot:
{page_text[:8000]}"""
    async with _AGENT_SEMAPHORE:
        raw = await _llm_chat(
            [
                {"role": "system", "content": "You are a realistic user, not an optimizer. Be specific."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
    result = _extract_json(raw)
    result["persona_name"] = persona.get("name")
    result["persona_bio"] = persona.get("bio")
    result["task_title"] = task.get("title")
    result["task_prompt"] = task.get("prompt")
    result["site_key"] = task.get("site_key") or "product"
    result["site_url"] = task.get("site_url") or url
    result["site_label"] = task.get("site_label") or "Product"
    result["agent_id"] = agent_id
    return result


async def summarize_agent_feedback(
    *,
    url: str,
    segment: str,
    persona: dict[str, Any],
    task: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, Any]:
    """Turn a real browser session into persona feedback, grounded in observed steps."""
    steps = [
        {
            "step": s.get("step"),
            "url": s.get("url"),
            "action": s.get("action"),
            "observation": s.get("observation"),
            "thought": s.get("thought"),
        }
        for s in run.get("trace") or []
    ]
    prompt = f"""Interpret a real browser session that was just recorded on a live site.

Site: {url}
Segment: {segment}
Persona: {persona.get("name")} — {persona.get("bio")}
Task: {task.get("prompt")}
Task completed by the agent: {run.get("completed")}
Pages actually visited: {json.dumps(run.get("visited_urls") or [], indent=0)}

Recorded steps (these really happened — do not invent others):
{json.dumps(steps, indent=2)[:12000]}

Return JSON only:
{{
  "difficulty": "easy|medium|hard",
  "friction_points": ["specific friction actually observed in the steps"],
  "what_was_easy": ["what actually went smoothly"],
  "product_feedback": "2-4 sentences as this persona: likes, dislikes, trust, clarity",
  "would_convert": "yes|maybe|no",
  "quote": "one first-person sentence as the user",
  "step_outcomes": [{{"step": 1, "outcome": "easy|neutral|friction"}}]
}}

Rules:
- Ground every claim in the recorded steps above. If the agent never looked for something,
  do not list it as missing.
- Include one step_outcomes entry for every recorded step, using its step number.
- Judge the product for what it actually is, not for lacking features of a different product."""
    async with _AGENT_SEMAPHORE:
        raw = await _llm_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a realistic user in a usability study, not an optimizer. "
                        "You only report what the recorded session shows. JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )
    return _extract_json(raw)


_SUMMARY_FIELDS = (
    "persona_name",
    "task_title",
    "completed",
    "difficulty",
    "friction_points",
    "what_was_easy",
    "product_feedback",
    "would_convert",
    "quote",
    "visited_urls",
)


def _slim_results(agent_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop traces, actions and screenshot paths before sending to the summarizer."""
    return [{k: r.get(k) for k in _SUMMARY_FIELDS if r.get(k) is not None} for r in agent_results]


async def synthesize_summary(
    *,
    url: str,
    segment: str,
    site_summary: str,
    agent_results: list[dict[str, Any]],
) -> dict[str, Any]:
    from mvp.competitor_urls import (
        product_insight_results,
        run_issue_lines,
        scrub_product_summary,
    )

    issues = [
        r.get("run_issue")
        for r in agent_results or []
        if isinstance(r, dict) and r.get("exclude_from_insights") and isinstance(r.get("run_issue"), dict)
    ]
    # Re-classify so fleet workers that skip annotate still exclude bad runs.
    insight_results = product_insight_results(agent_results)
    if not issues:
        issues = [
            r.get("run_issue")
            for r in agent_results or []
            if isinstance(r, dict) and isinstance(r.get("run_issue"), dict)
        ]
    issue_lines = run_issue_lines([i for i in issues if isinstance(i, dict)])
    prompt = f"""Synthesize a product research report from parallel simulated user sessions.

Site: {url}
Segment: {segment}
Site summary: {site_summary}

Agent session results (product evidence only — navigation and infrastructure failures were removed):
{json.dumps(_slim_results(insight_results), indent=2)[:14000]}

Return JSON only:
{{
  "headline": "one-line executive summary",
  "top_friction": ["ranked friction themes"],
  "top_strengths": ["what users liked"],
  "conversion_outlook": "short paragraph",
  "recommendations": [
    {{"priority": "high|medium|low", "action": "...", "rationale": "..."}}
  ],
  "segment_fit_score": 1-10,
  "segment_fit_rationale": "2 sentences"
}}

Rules:
- Report only what these sessions show about the product at {url} and its live competitors.
- Never describe a wrong website, a competitor mix-up, a failed navigation, or a harness/infrastructure error as product friction, a weakness, or a user insight.
- If a session is missing, do not infer why."""
    raw = await _llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a senior UX researcher. JSON only. "
                    "Navigation and infrastructure failures are not product insights."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    summary = scrub_product_summary(_extract_json(raw))
    summary["run_issues"] = issue_lines
    return summary


def _summary_from_agent_results(agent_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic fallback when LLM synthesis is unavailable."""
    from mvp.competitor_urls import (
        product_insight_results,
        run_issue_lines,
        scrub_product_summary,
    )

    issues = run_issue_lines(
        [
            r.get("run_issue")
            for r in (agent_results or [])
            if isinstance(r, dict) and isinstance(r.get("run_issue"), dict)
        ]
    )
    # annotate if the caller has not yet, then ignore harness failures.
    insight_results = product_insight_results(agent_results)
    if not issues:
        issues = run_issue_lines(
            [
                r.get("run_issue")
                for r in (agent_results or [])
                if isinstance(r, dict) and isinstance(r.get("run_issue"), dict)
            ]
        )
    if not insight_results:
        return {
            "headline": "Study finished with no product sessions",
            "top_friction": [],
            "top_strengths": [],
            "conversion_outlook": "",
            "recommendations": [],
            "segment_fit_score": 0,
            "segment_fit_rationale": "",
            "run_issues": issues,
        }
    friction: list[str] = []
    strengths: list[str] = []
    for r in insight_results:
        for item in r.get("friction_points") or []:
            if item and item not in friction:
                friction.append(str(item))
        for item in r.get("what_was_easy") or []:
            if item and item not in strengths:
                strengths.append(str(item))
    first = insight_results[0]
    converts = sum(
        1
        for r in insight_results
        if str(r.get("would_convert") or "").lower() in {"yes", "true", "likely"}
    )
    score = max(1, min(10, round(10 * converts / max(1, len(insight_results)))))
    return scrub_product_summary(
        {
            "headline": (first.get("quote") or first.get("product_feedback") or "Study complete")[:200],
            "top_friction": friction[:5],
            "top_strengths": strengths[:5],
            "conversion_outlook": (
                f"{converts}/{len(insight_results)} simulated users said they would convert."
            ),
            "recommendations": [
                {
                    "priority": "medium",
                    "action": "Review session recaps for the highest-friction steps",
                    "rationale": "Fallback summary — LLM synthesis was unavailable.",
                }
            ],
            "segment_fit_score": score,
            "segment_fit_rationale": "Score derived from would-convert answers across sessions.",
            "run_issues": issues,
        }
    )


async def run_study(
    study_id: str,
    *,
    on_update: Any | None = None,
) -> None:
    study = STUDIES[study_id]

    def touch(phase: str, status: str | None = None) -> None:
        study.phase = phase
        if status:
            study.status = status
        study.updated_at = _now()
        if on_update:
            try:
                on_update(study)
            except Exception:
                pass
        # Serverless: persist often so GET /api/studies/{id} still works if this
        # invocation dies mid-run (Vercel freezes the process when the stream ends).
        if IS_VERCEL_ENV:
            try:
                persist_study(study)
            except Exception:
                pass

    try:
        from mvp.shared_extract import note_submitted

        note_submitted(study)
        raise_if_killed(study)
        from mvp.a11y_agent import study_budget_s

        study.budget_s = study_budget_s()
        # One clock for every agent. Measured 24-agent Linear maximum is 128s.
        study.budget_deadline = time.monotonic() + study.budget_s
        log_activity(study, "phase", f"Study budget {int(study.budget_s)}s")
        log_activity(study, "phase", "Study queued")
        touch("Understanding context of product", "running")
        log_activity(study, "fetch", f"Understanding context of {study.url}")

        # Warm Browserbase + first screenshot of the product URL in parallel with
        # page fetch + persona/task LLMs so pixels are ready when the URL locks in.
        warm_task: asyncio.Task | None = None
        warm_opening: dict[str, Any] | None = None
        warm_used = False
        warm_site_tasks: dict[str, asyncio.Task] = {}
        warm_by_site: dict[str, dict[str, Any]] = {}

        def _should_warm_browserbase() -> bool:
            if SNAPSHOT_ONLY and not _fleet_preferred(test_mode=bool(study.test_mode)):
                return False
            # Fleet still needs an immediate product-site PNG. One Browserbase
            # landing capture is what the stage shows while seeds boot.
            if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
                return False
            if IS_VERCEL_ENV:
                return USE_LIVE_BROWSER and _browserbase_configured()
            return _browserbase_configured()

        def _schedule_competitor_warms() -> None:
            return

        a11y_boot: Any = None
        if (
            _should_warm_browserbase()
            and os.environ.get("MVP_A11Y_LOOP", "1").lower() not in {"0", "false", "no"}
        ):
            from mvp.shared_extract import SharedExtractBoot

            # One shared extract per site. First actions are decided from it
            # before any agent opens its own browser.
            a11y_boot = SharedExtractBoot(study, on_update)
            a11y_boot.install_fast_plan()
            asyncio.create_task(a11y_boot.start())
            log_activity(
                study,
                "browser",
                "Shared page read started — agents decide the first move from it",
            )
        elif _should_warm_browserbase():
            from mvp.browser_agent import warm_opening_session

            # Free OUR zombie Browserbase sessions from abandoned studies so
            # create_session doesn't hang on a leaked local slot / 429.
            # Never touch Sign Up (owner=signup) or untagged foreign sessions.
            try:
                from capability.browserbase_client import reset_local_slots, study_session_owner
                from mvp.kill_switch import kill_all_browserbase

                released = await asyncio.wait_for(
                    asyncio.to_thread(
                        kill_all_browserbase, owner=study_session_owner()
                    ),
                    timeout=12,
                )
                reset_local_slots()
                print(f"pre-study browserbase release: {released}", flush=True)
            except Exception as rel_exc:  # noqa: BLE001
                print(f"pre-study browserbase release skipped: {rel_exc!r}", flush=True)

            async def _warm_after(
                *, key: str, url: str, delay_s: float
            ) -> dict[str, Any] | None:
                # Stagger session creates so product + rivals are not one burst.
                if delay_s > 0:
                    await asyncio.sleep(delay_s)
                return await warm_opening_session(study_id=f"{study.id}_{key}", url=url)

            warm_task = asyncio.create_task(
                _warm_after(key="product", url=study.url, delay_s=0.0)
            )
            warm_site_tasks["product"] = warm_task

            def _schedule_competitor_warms() -> None:
                # Only after URLs are probed. A dead host must not take a slot,
                # and a later replacement must not inherit the old session.
                # ~0.6s apart: a thundering herd 429s the shared Browserbase project.
                for i, comp in enumerate((study.competitors or [])[:4]):
                    if not comp:
                        continue
                    key = f"competitor_{i+1}"
                    if key in warm_site_tasks:
                        continue
                    warm_site_tasks[key] = asyncio.create_task(
                        _warm_after(
                            key=key,
                            url=str(comp),
                            delay_s=0.55 * (i + 1),
                        )
                    )
                    log_activity(
                        study,
                        "browser",
                        f"Warming competitor screenshot for {comp}",
                    )

            log_activity(
                study,
                "browser",
                "Warming first screenshot for the product during brief",
            )
            # Prewarm Vertex ADC so agent.run isn't blocked on first credential load.
            try:
                from auth import vertex_credentials

                asyncio.create_task(asyncio.to_thread(vertex_credentials))
            except Exception:
                pass

        if a11y_boot is not None:
            from mvp.page_access import PageAccessResult

            access = PageAccessResult(
                text="",
                final_url=study.url,
                title="",
                backend="shared_ax",
            )
        else:
            access = await fetch_page_access(study.url)
        study.access_backend = access.backend
        study.browserbase_session_url = access.session_url
        page_text = f"Title: {access.title}\nURL: {access.final_url}\n\n{access.text}"
        log_activity(
            study,
            "fetch",
            f"Page loaded via {access.backend}",
            backend=access.backend,
            title=access.title,
        )
        touch("Understanding context of product")

        # Step 0: provision a signed-in product account when enabled.
        # Skipped on SNAPSHOT_ONLY (Vercel / quick) — no live browser there.
        if (
            not SNAPSHOT_ONLY
            and os.environ.get("MVP_AUTO_SIGNUP", "").lower() in {"1", "true", "yes"}
        ):
            touch("Provisioning account")
            log_activity(study, "auth", f"Ensuring signed-in access for {study.url}")
            from mvp.auth_state import ensure_product_access

            access_result = await asyncio.to_thread(ensure_product_access, study.url)
            status = access_result.get("status") or "unknown"
            if access_result.get("ok"):
                log_activity(
                    study,
                    "auth",
                    f"Product access ready ({status})",
                    auth_status=status,
                    email=access_result.get("email"),
                )
                try:
                    access = await fetch_page_access(study.url)
                    page_text = (
                        f"Title: {access.title}\nURL: {access.final_url}\n\n{access.text}"
                    )
                    study.access_backend = access.backend
                except Exception:
                    pass
            else:
                blocker = access_result.get("blocker") or access_result.get("reason")
                log_activity(
                    study,
                    "auth",
                    f"Product access incomplete ({status}): {blocker}",
                    auth_status=status,
                    blocker=blocker,
                    detail=access_result.get("detail"),
                )
                study.auth_status = status
                study.auth_blocker = str(blocker) if blocker else status

        # Strict sequence: competitors → users → tasks (separate LLM calls, stream each).
        if study.skip_competitors:
            log_activity(
                study,
                "plan",
                "Product-only — rivals skipped unless pasted in setup",
            )
        else:
            touch("Finding competitors")
            log_activity(
                study,
                "plan",
                "Finding competitors, then simulated users, then tasks — one step at a time",
            )
        if study.test_mode:
            log_activity(
                study,
                "plan",
                "Quick preview — 1 simulated user, 1 task (competitors still researched)",
            )

        site_hint = (page_text.split("\n", 1)[0] if page_text else study.url)[:160]

        def _push_brief(event: str = "brief") -> None:
            if not on_update:
                return
            try:
                on_update(study, event=event)
            except TypeError:
                on_update(study)
            except Exception:
                pass

        # 1) Competitors (skipped in local smoke — product site only)
        if getattr(study, "fast_brief", False) and study.competitors:
            log_activity(
                study,
                "plan",
                "Using the submitted competitor URLs — no research wait",
            )
        elif study.test_mode or study.skip_competitors:
            study.competitors = []
            log_activity(
                study,
                "plan",
                "Product-only run — skipping rivals"
                if study.skip_competitors and not study.test_mode
                else "Smoke mode — product site only, skipping rivals",
            )
            touch("Building simulated users")
            _push_brief("brief")
        else:
            try:
                resolved, dropped = await resolve_study_competitors(
                    list(study.competitors or []),
                    product_url=study.url,
                    site_summary=site_hint,
                    page_text=page_text,
                )
                for old, reason in dropped:
                    # The warm-time probe may already have logged the same drop.
                    msg = f"Dropped competitor {old} — {reason}"
                    if not any(
                        (row or {}).get("message") == msg
                        for row in (study.activity_log or [])
                        if isinstance(row, dict)
                    ):
                        log_activity(study, "plan", msg)
                study.competitors = resolved
            except Exception as exc:  # noqa: BLE001
                log_activity(
                    study,
                    "plan",
                    f"Competitor research failed ({str(exc)[:120]}) — continuing",
                )
                study.competitors = []
        if study.competitors:
            log_activity(
                study,
                "plan",
                "Competitors: " + ", ".join(study.competitors),
            )
            _schedule_competitor_warms()
            touch("Finding competitors")
            _push_brief("brief")

        # 2) Simulated users (own agent call)
        if not study.test_mode and not getattr(study, "fast_brief", False):
            touch("Building simulated users")
            study.personas = []
            study.tasks = []
            _push_brief("brief")
        if getattr(study, "fast_brief", False):
            users_plan = {"site_summary": study.url, "personas": study.personas}
        else:
            try:
                users_plan = await generate_personas(
                    study.url,
                    study.segment,
                    page_text,
                    test_mode=study.test_mode,
                    competitors=study.competitors,
                )
            except Exception as exc:  # noqa: BLE001
                log_activity(study, "plan", f"User generation failed ({str(exc)[:120]})")
                users_plan = {"site_summary": "", "personas": []}

        site_summary = users_plan.get("site_summary") or ""
        study.personas = users_plan.get("personas") or []
        # Guarantee exact persona count — LLM under-delivery must not shrink the matrix.
        if not study.test_mode:
            want_p = max(1, int(os.environ.get("MVP_PERSONA_COUNT", "4") or "4"))
            while len(study.personas) < want_p:
                n = len(study.personas) + 1
                study.personas.append(
                    {
                        "id": f"p{n}",
                        "name": f"Simulated user {n}",
                        "bio": f"A {study.segment or 'target customer'} evaluating the product.",
                        "age_range": "25–40",
                        "occupation": "Professional",
                        "location": "Remote",
                        "goals": ["Understand the product", "Decide whether to use it"],
                    }
                )
            study.personas = study.personas[:want_p]
        if site_summary:
            log_activity(study, "plan", f"Site: {site_summary}")

        # Top up when the first pass kept fewer than two live rivals.
        # An empty list and a single URL both shrink the 24-agent matrix.
        if (
            not study.test_mode
            and not study.skip_competitors
            and len(study.competitors or []) < 2
            and site_summary
        ):
            try:
                filled, more_dropped = await resolve_study_competitors(
                    list(study.competitors or []),
                    product_url=study.url,
                    site_summary=site_summary,
                    page_text=page_text,
                )
                for old, reason in more_dropped:
                    msg = f"Dropped competitor {old} — {reason}"
                    if not any(
                        (row or {}).get("message") == msg
                        for row in (study.activity_log or [])
                        if isinstance(row, dict)
                    ):
                        log_activity(study, "plan", msg)
                if len(filled) > len(study.competitors or []):
                    study.competitors = filled
                    log_activity(
                        study,
                        "plan",
                        "Competitors: " + ", ".join(study.competitors),
                    )
                    _schedule_competitor_warms()
            except Exception as exc:  # noqa: BLE001
                log_activity(
                    study,
                    "plan",
                    f"Competitor retry failed ({str(exc)[:120]})",
                )

        touch("Building simulated users")
        _push_brief("brief")

        # 3) Tasks (own agent call — only after users are visible)
        touch("Writing tasks")
        _push_brief("brief")
        if getattr(study, "fast_brief", False):
            pass
        else:
            try:
                study.tasks = await generate_tasks(
                    study.url,
                    study.segment,
                    page_text,
                    study.personas,
                    site_summary=site_summary,
                    test_mode=study.test_mode,
                )
            except Exception as exc:  # noqa: BLE001
                log_activity(study, "plan", f"Task generation failed ({str(exc)[:120]})")
                study.tasks = []
        touch("Writing tasks")
        _push_brief("brief")

        # Apply optional task overrides. The fast path already expanded these.
        if study.tasks_override and not getattr(study, "fast_brief", False):
            if study.test_mode:
                prompt = study.tasks_override[0]
                if study.tasks:
                    study.tasks[0]["prompt"] = prompt
                    study.tasks[0]["title"] = prompt[:80]
                    study.tasks = study.tasks[:1]
                if study.personas:
                    study.personas = study.personas[:1]
                    if study.tasks:
                        study.tasks[0]["persona_id"] = study.personas[0].get("id")
            else:
                # Task overrides are templates — full matrix expands them across
                # EVERY persona × site. Do not shrink the persona panel to the
                # few personas that happen to own the override rows.
                rebuilt: list[dict[str, Any]] = []
                for i, prompt in enumerate(study.tasks_override):
                    persona = (
                        study.personas[i % len(study.personas)]
                        if study.personas
                        else {"id": f"p{i+1}"}
                    )
                    rebuilt.append(
                        {
                            "id": f"t{i+1}",
                            "title": prompt[:80],
                            "prompt": prompt,
                            "persona_id": persona.get("id"),
                            "difficulty_hint": "medium",
                        }
                    )
                study.tasks = rebuilt

        base_cap = int(
            os.environ.get(
                "MVP_AGENT_COUNT",
                "1" if (QUICK_MODE or study.test_mode) else "0",
            )
        )
        if base_cap > 0 and len(study.tasks) > base_cap:
            study.tasks = study.tasks[:base_cap]

        # Keep the full persona panel in the brief (not only personas that still
        # have a task after the base cap).
        if study.personas and study.tasks:
            used = {t.get("persona_id") for t in study.tasks}
            ordered = [p for p in study.personas if p.get("id") in used]
            extras = [p for p in study.personas if p.get("id") not in used]
            study.personas = (ordered + extras)[
                    : max(len(ordered), int(os.environ.get("MVP_PERSONA_COUNT", "4")))
            ]

        # Full studies: every persona × every task × (product + each competitor).
        # Smoke / quick preview: product site only (1 user × 1 task × 1 site).
        already_expanded = bool(study.tasks) and all(
            "__" in str(t.get("id") or "") for t in study.tasks
        )
        if not study.test_mode and not already_expanded:
            before = len(study.tasks)
            n_users = len(study.personas or [])
            n_sites = 1 + len(study.competitors or [])
            study.tasks = expand_full_matrix(
                study.tasks,
                study.personas,
                product_url=study.url,
                competitors=study.competitors or [],
            )
            log_activity(
                study,
                "plan",
                f"Expanded to {len(study.tasks)} parallel runs "
                f"({n_users} users × {before} tasks × {n_sites} sites) "
                f"— extras queue behind Browserbase concurrency "
                f"({os.environ.get('MVP_BROWSER_CONCURRENCY', '25')})",
            )
            # Never silently drop agents. MVP_MAX_SESSIONS>0 is an explicit
            # emergency brake only (0 / unset = run everything; queue on semaphore).
            max_sessions = int(os.environ.get("MVP_MAX_SESSIONS", "0") or "0")
            req_cap = int(getattr(study, "max_agents", 0) or 0)
            if req_cap > 0:
                max_sessions = req_cap if max_sessions <= 0 else min(max_sessions, req_cap)
            if max_sessions > 0 and len(study.tasks) > max_sessions:
                product = [
                    t
                    for t in study.tasks
                    if str(t.get("site_key") or "product") == "product"
                ]
                rivals = [
                    t
                    for t in study.tasks
                    if str(t.get("site_key") or "product") != "product"
                ]
                n_rival = 0
                if rivals and max_sessions >= 2:
                    n_rival = min(len(rivals), 2 if max_sessions >= 5 else 1)
                n_prod = max_sessions - n_rival
                picked = product[:n_prod] + rivals[:n_rival]
                if len(picked) < max_sessions:
                    rest = product[n_prod:] + rivals[n_rival:]
                    picked.extend(rest[: max_sessions - len(picked)])
                dropped = len(study.tasks) - len(picked)
                study.tasks = picked
                log_activity(
                    study,
                    "plan",
                    f"Bounded to {len(study.tasks)} threads "
                    f"({sum(1 for t in picked if str(t.get('site_key') or 'product') == 'product')} product / "
                    f"{sum(1 for t in picked if str(t.get('site_key') or 'product') != 'product')} rival) "
                    f"— dropped {dropped}",
                )
        else:
            for task in study.tasks:
                task["site_key"] = "product"
                task["site_url"] = study.url
                task["site_label"] = "Product"

        if study.test_mode and study.personas and study.tasks:
            used = {t.get("persona_id") for t in study.tasks}
            study.personas = [p for p in study.personas if p.get("id") in used] or study.personas[:1]

        for persona in study.personas:
            demos = ", ".join(
                x
                for x in (
                    persona.get("age_range"),
                    persona.get("occupation"),
                    persona.get("location"),
                )
                if x
            )
            log_activity(
                study,
                "persona",
                f"Simulated user: {persona.get('name')}"
                + (f" ({demos})" if demos else ""),
                persona_id=persona.get("id"),
                name=persona.get("name"),
                bio=persona.get("bio"),
            )
        for task in study.tasks:
            log_activity(
                study,
                "task",
                f"Task: {task.get('title')}",
                task_id=task.get("id"),
                title=task.get("title"),
            )

        # Finish warm captures BEFORE creating live sessions. Creation→first
        # REAL shot must be ≤5s, so every site needs a non-blank warm frame
        # ready at create (placeholders do not count toward that budget).
        pending_warm: dict[str, asyncio.Task] = {}
        warm_timing: dict[str, Any] = {}
        needed_site_keys = {"product"}
        for i, comp in enumerate((study.competitors or [])[:4]):
            if comp:
                needed_site_keys.add(f"competitor_{i+1}")

        def _warm_is_real(warm: dict[str, Any] | None) -> bool:
            if not warm or not warm.get("shot_path"):
                return False
            # WAF / access-denied interstitials are non-blank but not a usable
            # product frame — never stamp them as the e2e real shot.
            if warm.get("blocked") or (warm.get("timing") or {}).get("blocked"):
                return False
            from mvp.browser_agent import _png_is_blankish as _blank

            try:
                return not _blank(warm["shot_path"])
            except Exception:
                return False

        if warm_site_tasks:
            # Brief already ran in parallel; wait out remaining paint so we
            # publish real product frames at session create.
            timeout_s = float(os.environ.get("MVP_WARM_WAIT_S", "90") or "90")
            deadline = time.time() + timeout_s
            outstanding = dict(warm_site_tasks)
            while outstanding and time.time() < deadline:
                wait_s = max(0.1, min(5.0, deadline - time.time()))
                done, pending = await asyncio.wait(
                    set(outstanding.values()),
                    timeout=wait_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for key, task in list(outstanding.items()):
                    if task not in done:
                        continue
                    outstanding.pop(key, None)
                    try:
                        result = task.result()
                    except Exception as warm_exc:  # noqa: BLE001
                        print(f"warm {key} failed: {warm_exc!r}", flush=True)
                        continue
                    if not result:
                        continue
                    if result.get("timing"):
                        warm_timing[key] = result["timing"]
                    if _warm_is_real(result):
                        warm_by_site[key] = result
                    elif result.get("shot_path"):
                        why = "blocked" if result.get("blocked") else "blankish"
                        print(
                            f"warm {key} still {why} — not counting as real opening"
                            + (
                                f" ({result.get('block_reason')})"
                                if result.get("block_reason")
                                else ""
                            ),
                            flush=True,
                        )
                        # Keep a blank/blocked warm only as last-resort UI donor.
                        warm_by_site.setdefault(f"_blank_{key}", result)
                # Stop early when every needed site has a real frame.
                if needed_site_keys.issubset(set(warm_by_site.keys())):
                    break
            for key, task in list(outstanding.items()):
                pending_warm[key] = task

            # Competitors that stayed WAF-blocked after warm (+ proxy retry) cannot
            # produce flash-lite YESes. Swap them for an alternate rival and re-warm
            # before we stamp opening frames — generic, not per-site.
            missing_comp_keys = sorted(
                k
                for k in needed_site_keys
                if k != "product" and k not in warm_by_site
            )
            if missing_comp_keys and not study.test_mode:
                try:
                    from urllib.parse import urlparse as _urlparse

                    from mvp.browser_agent import (
                        close_warm_opening,
                        warm_opening_session,
                    )
                    from mvp.competitor_urls import rewrite_competitor_task

                    def _host(u: str) -> str:
                        return (_urlparse(u).hostname or "").lower().removeprefix(
                            "www."
                        )

                    used_hosts = {_host(study.url)} | {
                        _host(c) for c in (study.competitors or []) if c
                    }
                    # Prefer LLM invent; fall back to skipping the blocked site.
                    alts: list[str] = []
                    try:
                        alts = await invent_competitors(
                            study.url,
                            site_summary or study.url,
                            page_text or "",
                            exclude_hosts=set(used_hosts),
                        )
                    except Exception as inv_exc:  # noqa: BLE001
                        print(f"competitor re-invent failed: {inv_exc!r}", flush=True)
                    alts = [
                        a
                        for a in (alts or [])
                        if a and _host(a) and _host(a) not in used_hosts
                    ]
                    for key in missing_comp_keys:
                        if not alts:
                            break
                        idx = int(key.rsplit("_", 1)[-1]) - 1
                        if idx < 0:
                            continue
                        new_url = alts.pop(0)
                        old = (
                            (study.competitors or [None] * (idx + 1))[idx]
                            if study.competitors
                            else None
                        )
                        while len(study.competitors) <= idx:
                            study.competitors.append("")
                        study.competitors[idx] = new_url
                        used_hosts.add(_host(new_url))
                        # Rewrite already-expanded matrix rows for this site_key.
                        for t in study.tasks or []:
                            if str(t.get("site_key") or "") == key:
                                rewrite_competitor_task(t, new_url)
                        log_activity(
                            study,
                            "plan",
                            f"Swapped blocked competitor {old} → {new_url} ({key})",
                        )
                        print(
                            f"warm swap {key}: {old!r} → {new_url!r}",
                            flush=True,
                        )
                        try:
                            blank = warm_by_site.pop(f"_blank_{key}", None)
                            if blank:
                                await close_warm_opening(blank)
                        except Exception:
                            pass
                        try:
                            swapped = await asyncio.wait_for(
                                warm_opening_session(
                                    study_id=f"{study.id}_{key}", url=new_url
                                ),
                                timeout=60,
                            )
                        except Exception as swap_exc:  # noqa: BLE001
                            print(f"warm swap {key} failed: {swap_exc!r}", flush=True)
                            swapped = None
                        if swapped and swapped.get("timing"):
                            warm_timing[key] = swapped["timing"]
                        if _warm_is_real(swapped):
                            warm_by_site[key] = swapped
                        elif swapped:
                            warm_by_site.setdefault(f"_blank_{key}", swapped)
                except Exception as swap_all_exc:  # noqa: BLE001
                    print(f"blocked-competitor swap skipped: {swap_all_exc!r}", flush=True)

            if "product" in warm_by_site:
                warm_opening = warm_by_site["product"]

            # Retry sites whose warm create 429'd or timed out. This loop
            # finishes BEFORE live sessions exist, so created_at_ts / the 5s
            # first-screenshot clock have not started. Do not loosen that clock.
            if needed_site_keys - set(warm_by_site):
                import random as _warm_random

                from mvp.browser_agent import warm_opening_session as _warm_retry

                def _warm_url(key: str) -> str | None:
                    if key == "product":
                        return study.url
                    if not str(key).startswith("competitor_"):
                        return None
                    try:
                        idx = int(str(key).rsplit("_", 1)[-1]) - 1
                    except ValueError:
                        return None
                    comps = list(study.competitors or [])
                    if 0 <= idx < len(comps) and comps[idx]:
                        return str(comps[idx])
                    return None

                try:
                    pre_attempts = int(
                        os.environ.get("MVP_WARM_PRECLOCK_RETRIES", "3") or "3"
                    )
                except ValueError:
                    pre_attempts = 3
                pre_attempts = max(1, min(5, pre_attempts))
                try:
                    warm_conc = int(
                        os.environ.get("MVP_WARM_CREATE_CONCURRENCY", "2") or "2"
                    )
                except ValueError:
                    warm_conc = 2
                warm_conc = max(1, min(3, warm_conc))
                warm_sem = asyncio.Semaphore(warm_conc)

                # In-flight warms are already retrying inside create_session.
                # Collect them before opening a second session for the same site.
                if pending_warm:
                    try:
                        grace = float(
                            os.environ.get("MVP_WARM_PRECLOCK_GRACE_S", "20") or "20"
                        )
                    except ValueError:
                        grace = 20.0
                    grace_deadline = time.time() + max(1.0, grace)
                    inflight = dict(pending_warm)
                    while inflight and time.time() < grace_deadline:
                        wait_s = max(0.1, min(5.0, grace_deadline - time.time()))
                        done, _pending = await asyncio.wait(
                            set(inflight.values()),
                            timeout=wait_s,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for key, task in list(inflight.items()):
                            if task not in done:
                                continue
                            inflight.pop(key, None)
                            pending_warm.pop(key, None)
                            try:
                                result = task.result()
                            except Exception as warm_exc:  # noqa: BLE001
                                print(
                                    f"pre-clock warm {key} inflight failed: {warm_exc!r}",
                                    flush=True,
                                )
                                continue
                            if result and result.get("timing"):
                                warm_timing[key] = result["timing"]
                            if _warm_is_real(result):
                                warm_by_site[key] = result
                            elif result and result.get("shot_path"):
                                warm_by_site.setdefault(f"_blank_{key}", result)

                async def _retry_key(key: str, attempt: int) -> None:
                    url = _warm_url(key)
                    if not url:
                        return
                    async with warm_sem:
                        await asyncio.sleep(_warm_random.uniform(0.05, 0.4))
                        try:
                            result = await asyncio.wait_for(
                                _warm_retry(
                                    study_id=f"{study.id}_{key}_pre{attempt}",
                                    url=url,
                                ),
                                timeout=float(
                                    os.environ.get("MVP_WARM_ATTEMPT_TIMEOUT_S", "75")
                                    or "75"
                                ),
                            )
                        except Exception as retry_exc:  # noqa: BLE001
                            print(
                                f"pre-clock warm {key} attempt {attempt + 1} "
                                f"failed: {retry_exc!r}",
                                flush=True,
                            )
                            return
                        if result and result.get("timing"):
                            warm_timing[key] = result["timing"]
                        if _warm_is_real(result):
                            # Drop a blank donor so we don't keep two sessions.
                            blank = warm_by_site.pop(f"_blank_{key}", None)
                            if blank:
                                try:
                                    from mvp.browser_agent import close_warm_opening

                                    await close_warm_opening(blank)
                                except Exception:
                                    pass
                            warm_by_site[key] = result
                            print(
                                f"pre-clock warm {key} real on attempt {attempt + 1}",
                                flush=True,
                            )
                        elif result:
                            warm_by_site.setdefault(f"_blank_{key}", result)

                for attempt in range(pre_attempts):
                    missing = [
                        k
                        for k in sorted(needed_site_keys)
                        if k not in warm_by_site and k not in pending_warm
                    ]
                    if not missing:
                        break
                    delay = min(6.0, 0.7 * (2 ** attempt)) + _warm_random.uniform(
                        0.15, 0.9
                    )
                    print(
                        f"pre-clock warm retry {attempt + 1}/{pre_attempts} "
                        f"for {missing} after {delay:.1f}s "
                        f"(not on the 5s screenshot clock)",
                        flush=True,
                    )
                    log_activity(
                        study,
                        "browser",
                        f"Retrying warm screenshots before agents start: {', '.join(missing)}",
                    )
                    await asyncio.sleep(delay)
                    await asyncio.gather(
                        *[_retry_key(k, attempt) for k in missing],
                        return_exceptions=True,
                    )

                if "product" in warm_by_site:
                    warm_opening = warm_by_site["product"]

            warm_task = None
            warm_site_tasks = {}
            study.activity_log.append(
                {
                    "at": _now(),
                    "kind": "browser",
                    "message": (
                        f"Warm ready real={sorted(k for k in warm_by_site if not str(k).startswith('_blank_'))} "
                        f"pending={sorted(pending_warm.keys())}"
                    ),
                    "warm_timing": warm_timing,
                }
            )
            print(
                f"warm ready for sites: {sorted(k for k in warm_by_site if not str(k).startswith('_blank_'))} "
                f"pending={sorted(pending_warm.keys())} timing={warm_timing}",
                flush=True,
            )

        # Open live sessions + attach warm (or immediate placeholder) frames in
        # one pass so creation→first-shot stays within the e2e budget.
        import shutil as _shutil

        from mvp.paths import MVP_RUNS_DIR
        from mvp.opening_shot import attach_opening_pixels
        from mvp.browser_agent import _png_is_blankish

        async def _publish_opening_to_sess(
            *,
            sess: dict[str, Any],
            agent_id: str,
            site: str,
            site_label: str,
            src_path,
            blankish: bool | None = None,
            placeholder: bool = False,
        ) -> None:
            dest_dir = MVP_RUNS_DIR / study.id / agent_id / "screenshots"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "bbox_0.png"
            if src_path is not None:
                _shutil.copy2(src_path, dest)
            if blankish is None:
                blankish = _png_is_blankish(dest)
            step0 = {
                "step": 0,
                "action": f"Opened {site}",
                "observation": (
                    "Immediate opening frame"
                    if placeholder
                    else "Landing page screenshot"
                ),
                "thought": "",
                "thought_detail": {},
                "url": site,
                "screenshot_url": (
                    f"/api/studies/{study.id}/agents/{agent_id}/screenshots/bbox_0.png"
                ),
                "boxes": [],
                "outcome": "neutral",
                "evidence_label": (
                    "Opening frame · immediate start"
                    if placeholder
                    else "Opening frame · before agent steps"
                ),
                "opening_blankish": bool(blankish),
                "opening_placeholder": bool(placeholder),
            }
            await attach_opening_pixels(
                study_id=study.id,
                agent_id=agent_id,
                local=dest,
                step=step0,
            )
            sess["status"] = "running"
            sess["trace"] = [step0]
            sess["num_steps"] = 1
            sess["last_action"] = step0["action"]
            # Only real, non-blank product frames stamp the e2e timer.
            if not placeholder and not blankish:
                _mark_first_screenshot(sess, study_id=study.id, agent_id=agent_id)
            sess["live_thoughts"] = [
                {
                    "at": _now(),
                    "text": f"Opened {site_label or site} — agent starting…",
                    "kind": "status",
                }
            ]

        persona_by_id = {p["id"]: p for p in study.personas}
        if a11y_boot is not None:
            # The product read often finishes before the planner has tasks.
            # Publish the first click as soon as those tasks exist.
            for _key, _snap in list(getattr(a11y_boot, "snapshots", {}).items()):
                try:
                    a11y_boot._publish_site(_key, _snap)
                except Exception as pub_exc:  # noqa: BLE001
                    print(f"[a11y] republish {_key} failed: {pub_exc!r}", flush=True)
        if a11y_boot is None:
            study.live_sessions = {}
        for task in study.tasks:
            persona = persona_by_id.get(task.get("persona_id")) or (
                study.personas[0] if study.personas else {}
            )
            agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
            if a11y_boot is not None:
                # The shared read publishes the click, the tree, and the
                # timestamps together. An earlier empty session would start
                # the 5s page-open clock before that payload exists.
                continue
            site = task.get("site_url") or study.url
            site_key = str(task.get("site_key") or "product")
            site_label = str(task.get("site_label") or "Product")
            created_ts = time.time()
            sess: dict[str, Any] = {
                "agent_id": agent_id,
                "persona_id": persona.get("id"),
                "persona_name": persona.get("name"),
                "persona_bio": persona.get("bio"),
                "task_id": task.get("id"),
                "task_title": task.get("title"),
                "task_prompt": task.get("prompt"),
                "site_key": site_key,
                "site_url": site,
                "site_label": site_label,
                "status": "starting",
                "trace": [],
                "num_steps": 0,
                "live_active": False,
                "created_at": _now(),
                "created_at_ts": created_ts,
                "live_thoughts": [
                    {
                        "at": _now(),
                        "text": f"Opening {site_label or site}…",
                        "kind": "status",
                    }
                ],
                "last_action": f"Opening {site}…",
            }
            study.live_sessions[agent_id] = sess

            warm = warm_by_site.get(site_key)
            dest_dir = MVP_RUNS_DIR / study.id / agent_id / "screenshots"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "bbox_0.png"
            try:
                if warm and _warm_is_real(warm):
                    await _publish_opening_to_sess(
                        sess=sess,
                        agent_id=agent_id,
                        site=site,
                        site_label=site_label,
                        src_path=warm["shot_path"],
                        placeholder=False,
                    )
                    log_activity(
                        study,
                        "browser",
                        f"First real screenshot ready for {site}",
                        agent_id=agent_id,
                    )
                else:
                    # Warm still painting or blank — UI placeholder only
                    # (does not stamp first_screenshot_at_ts).
                    _write_immediate_opening_png(
                        dest, site=site, site_label=site_label
                    )
                    await _publish_opening_to_sess(
                        sess=sess,
                        agent_id=agent_id,
                        site=site,
                        site_label=site_label,
                        src_path=None,
                        blankish=False,
                        placeholder=True,
                    )
                    print(
                        f"immediate placeholder opening {agent_id} for {site_key} "
                        f"(real warm pending — timing not stamped)",
                        flush=True,
                    )
                    log_activity(
                        study,
                        "browser",
                        f"Placeholder opening for {site} (waiting on real paint)",
                        agent_id=agent_id,
                    )
            except Exception as pub_exc:  # noqa: BLE001
                print(f"opening publish failed: {pub_exc!r}", flush=True)

        touch("Opening the live page")
        persist_study(study)
        if on_update:
            try:
                on_update(study, event="brief")
            except TypeError:
                on_update(study)
            except Exception:
                pass

        # Late warm upgrades: when a pending warm finishes, replace placeholders
        # / blankish openings for that site_key (first_screenshot_at stays).
        async def _apply_late_warm(key: str, warm: dict[str, Any]) -> None:
            import shutil as _shutil2

            from mvp.browser_agent import _png_is_blankish as _blank
            from mvp.paths import MVP_RUNS_DIR as _runs

            if not warm or not warm.get("shot_path"):
                return
            if _blank(warm["shot_path"]):
                return
            warm_by_site[key] = warm
            for aid, sess in list((study.live_sessions or {}).items()):
                if str(sess.get("site_key") or "product") != key:
                    continue
                trace0 = (sess.get("trace") or [{}])[0] if sess.get("trace") else {}
                if not (
                    trace0.get("opening_placeholder")
                    or trace0.get("opening_blankish")
                    or not sess.get("trace")
                ):
                    continue
                dest = _runs / study.id / aid / "screenshots" / "bbox_0.png"
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    _shutil2.copy2(warm["shot_path"], dest)
                    site = sess.get("site_url") or study.url
                    step0 = {
                        "step": 0,
                        "action": f"Opened {site}",
                        "observation": "Landing page screenshot",
                        "thought": "",
                        "thought_detail": {},
                        "url": site,
                        "screenshot_url": (
                            f"/api/studies/{study.id}/agents/{aid}/screenshots/bbox_0.png"
                        ),
                        "boxes": [],
                        "outcome": "neutral",
                        "evidence_label": "Opening frame · before agent steps",
                    }
                    from mvp.opening_shot import attach_opening_pixels as _attach

                    await _attach(
                        study_id=study.id,
                        agent_id=aid,
                        local=dest,
                        step=step0,
                    )
                    rest = [
                        s
                        for s in (sess.get("trace") or [])
                        if not (isinstance(s, dict) and s.get("step") == 0)
                    ]
                    sess["trace"] = [step0, *rest]
                    sess["num_steps"] = len(sess["trace"])
                    _mark_first_screenshot(sess, study_id=study.id, agent_id=aid)
                except Exception as late_exc:  # noqa: BLE001
                    print(f"late warm apply {aid}: {late_exc!r}", flush=True)
            persist_study(study)
            if on_update:
                try:
                    on_update(study, event="progress")
                except TypeError:
                    on_update(study)
                except Exception:
                    pass

        if pending_warm:

            async def _await_pending_warms() -> None:
                for key, task in list(pending_warm.items()):
                    try:
                        result = await task
                    except Exception as warm_exc:  # noqa: BLE001
                        print(f"late warm {key} failed: {warm_exc!r}", flush=True)
                        continue
                    if result and result.get("shot_path"):
                        print(f"late warm ready: {key}", flush=True)
                        try:
                            await _apply_late_warm(key, result)
                        except Exception as apply_exc:  # noqa: BLE001
                            print(f"late warm apply {key}: {apply_exc!r}", flush=True)

            asyncio.create_task(_await_pending_warms())

        # Free competitor (and YouTube product) warm BB slots before the
        # 24-agent wave — we only needed their PNGs. Keep pending warms alive
        # until they finish (handled above).
        if warm_by_site:
            from mvp.browser_agent import close_warm_opening
            from urllib.parse import urlparse as _urlparse

            _prod_host = (_urlparse(study.url).hostname or "").lower()
            _yt = "youtube.com" in _prod_host or "youtu.be" in _prod_host
            for key, warm in list(warm_by_site.items()):
                if key in pending_warm:
                    continue
                if key == "product" and not _yt:
                    continue  # may hand to one non-YouTube product agent
                try:
                    await close_warm_opening(warm)
                except Exception:
                    pass
                warm_by_site.pop(key, None)
            if _yt and "product" not in pending_warm:
                warm_opening = None

        touch(
            f"Live browser agents — 0/{len(study.tasks)} done · {len(study.tasks)} active · 0 queued · 0 steps"
        )
        if on_update:
            try:
                on_update(study, event="progress")
            except TypeError:
                on_update(study)
            except Exception:
                pass
        from mvp.opening_shot import drop_inline_shots_inplace

        for _sess in study.live_sessions.values():
            drop_inline_shots_inplace(_sess)
        done_count = 0

        def refresh_agent_phase() -> None:
            touch(_agent_phase_label(study))

        if SNAPSHOT_ONLY and not _fleet_preferred(test_mode=bool(study.test_mode)):
            if warm_task is not None:
                warm_task.cancel()
                warm_task = None
            if warm_opening is not None:
                from mvp.browser_agent import close_warm_opening

                await close_warm_opening(warm_opening)
                warm_opening = None
            log_activity(
                study,
                "agents",
                f"Running {len(study.tasks)} persona simulations (Vercel snapshot mode — no live screenshots)",
            )
            touch(f"Simulating agents — 0/{len(study.tasks)} finished")

            async def _run_snapshot(task: dict[str, Any]) -> dict[str, Any]:
                nonlocal done_count
                persona = persona_by_id.get(task.get("persona_id")) or study.personas[0]
                agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
                sess = study.live_sessions[agent_id]
                sess["status"] = "running"
                log_activity(
                    study,
                    "agent_start",
                    f"{persona.get('name')} started (snapshot)",
                    agent_id=agent_id,
                    persona_name=persona.get("name"),
                )
                touch(f"Simulating agents — {done_count}/{len(study.tasks)} finished")
                result = await simulate_agent(
                    url=study.url,
                    segment=study.segment,
                    persona=persona,
                    task=task,
                    page_text=page_text,
                    study_id=study.id,
                    agent_id=agent_id,
                )
                result["mode"] = "snapshot"
                result["persona_id"] = persona.get("id")
                result["persona_name"] = persona.get("name")
                result["persona_bio"] = persona.get("bio")
                result["task_id"] = task.get("id")
                result["task_title"] = task.get("title")
                result["task_prompt"] = task.get("prompt")
                result["site_key"] = task.get("site_key") or "product"
                result["site_url"] = task.get("site_url") or study.url
                result["site_label"] = task.get("site_label") or "Product"
                sess["status"] = "complete"
                sess["trace"] = result.get("trace") or []
                sess["num_steps"] = len(sess["trace"])
                done_count += 1
                study.agent_results.append(result)
                touch(f"Simulating agents — {done_count}/{len(study.tasks)} finished")
                log_activity(
                    study,
                    "agent_done",
                    f"{persona.get('name')} finished ({result.get('difficulty', '?')})",
                    agent_id=agent_id,
                )
                return result

            study.agent_results = []
            snap_out = await asyncio.gather(
                *[_run_snapshot(t) for t in study.tasks],
                return_exceptions=True,
            )
            for item in snap_out:
                if isinstance(item, Exception) and not isinstance(
                    item, asyncio.CancelledError
                ):
                    print(f"snapshot agent failed: {item!r}", flush=True)
        elif _fleet_preferred(test_mode=bool(study.test_mode)):
            from mvp.gcp_fleet import run_study_on_gcp_fleet

            if warm_task is not None:
                warm_task.cancel()
                warm_task = None
            if warm_opening is not None:
                from mvp.browser_agent import close_warm_opening

                await close_warm_opening(warm_opening)
                warm_opening = None

            workers = min(
                8,
                len(study.tasks),
                int(os.environ.get("MVP_GCP_WORKERS", "8")),
            )
            log_activity(
                study,
                "agents",
                f"Launching on GCP warm seed — headed Chromium (reuse CDP), {workers} workers/VM "
                f"(Vercel detaches; agents keep running up to ~15 min)",
            )
            touch(
                f"Live browser agents — 0/{len(study.tasks)} done · {len(study.tasks)} active · 0 queued · 0 steps"
            )

            async def _push_fleet_frame(agent_id: str, frame: dict[str, Any]) -> None:
                sess = study.live_sessions.get(agent_id)
                if not sess:
                    return
                step = {
                    "step": frame.get("step"),
                    "action": frame.get("action") or "Browser step",
                    "observation": frame.get("observation") or "",
                    "thought": frame.get("thought") or "",
                    "thought_detail": frame.get("thought_detail") or {},
                    "url": frame.get("url"),
                    "screenshot_url": frame.get("screenshot_url"),
                    "boxes": frame.get("boxes") or [],
                    "highlight_index": frame.get("highlight_index"),
                    "outcome": frame.get("outcome") or "neutral",
                    "evidence_label": frame.get("evidence_label")
                    or "Live GCP fleet frame · headed Chromium",
                }
                # Never store prep pulses (step:null) as screenshot frames — that
                # produced "Step null — Preparing YouTube session…" in the UI.
                if frame.get("progress_only") or step.get("step") is None:
                    text = (step.get("thought") or step.get("action") or "").strip()
                    if text:
                        sess["last_action"] = text[:160]
                    if on_update:
                        try:
                            on_update(study, event="progress")
                        except TypeError:
                            on_update(study)
                        except Exception:
                            pass
                    return
                if not step.get("screenshot_url"):
                    return
                sess["status"] = "running"
                sess["trace"] = list(sess.get("trace") or [])
                existing = {s.get("step"): i for i, s in enumerate(sess["trace"])}
                if step.get("step") in existing:
                    sess["trace"][existing[step["step"]]] = step
                else:
                    sess["trace"].append(step)
                sess["num_steps"] = len(sess["trace"])
                sess["last_action"] = step.get("action") or ""
                _mark_first_screenshot(sess, study_id=study.id, agent_id=str(sess.get("agent_id") or ""))
                refresh_agent_phase()
                study.updated_at = _now()
                persist_study(study)
                if on_update:
                    try:
                        on_update(study, event="progress")
                    except TypeError:
                        on_update(study)
                    except Exception:
                        pass

            async def _fleet_status(msg: str) -> None:
                log_activity(study, "browser", msg)
                touch(msg if msg.startswith("Live") else f"GCP fleet — {msg}")
                # Reflect seed vs Spot in the stage waiting copy.
                hint = msg
                low = msg.lower()
                if (
                    "warm cdp" in low
                    or "packing" in low
                    or "standing chromium" in low
                    or "on warm" in low
                    or "warm seed" in low
                ):
                    hint = "Reusing warm Chromium on seed…"
                elif "spot copy" in low or ("creating" in low and "spot" in low):
                    hint = "Provisioning GCP Spot copy…"
                elif "booting" in low or "polling" in low or "relay" in low:
                    hint = "Waiting for first frame from seed…"
                for sess in study.live_sessions.values():
                    if sess.get("status") in {"starting", "pending"} and not (sess.get("trace") or []):
                        sess["last_action"] = hint
                persist_study(study)
                if on_update:
                    try:
                        on_update(study, event="progress")
                    except TypeError:
                        on_update(study)
                    except Exception:
                        pass

            for sess in study.live_sessions.values():
                sess["status"] = "starting"
                sess["last_action"] = "Reusing warm Chromium on seed…"

            study.agent_results = []
            persist_study(study)
            # On Vercel, detach after dispatch+first frames so the function can
            # return; Spot copies finish the study and write study.json / done.json.
            fleet_timeout = float(
                os.environ.get(
                    "MVP_GCP_FLEET_TIMEOUT_S",
                    "120" if IS_VERCEL_ENV else "900",
                )
            )
            prev_timeout = os.environ.get("MVP_GCP_FLEET_TIMEOUT_S")
            os.environ["MVP_GCP_FLEET_TIMEOUT_S"] = str(int(fleet_timeout))
            try:
                results = await run_study_on_gcp_fleet(
                    study_id=study.id,
                    url=study.url,
                    segment=study.segment,
                    personas=study.personas,
                    tasks=study.tasks,
                    live_sessions=study.live_sessions,
                    on_frame=_push_fleet_frame,
                    on_status=_fleet_status,
                    workers=workers,
                    keep_vm=False,
                    study_snapshot=study_to_dict(study),
                )
            except TimeoutError:
                if IS_VERCEL_ENV:
                    study.status = "running"
                    study.phase = "Agents running on GCP fleet — reconnecting via poll"
                    persist_study(study)
                    if on_update:
                        try:
                            on_update(study, event="progress")
                        except TypeError:
                            on_update(study)
                        except Exception:
                            pass
                    # Spot copies continue; finisher writes final study.json.
                    if prev_timeout is None:
                        os.environ.pop("MVP_GCP_FLEET_TIMEOUT_S", None)
                    else:
                        os.environ["MVP_GCP_FLEET_TIMEOUT_S"] = prev_timeout
                    return
                raise
            finally:
                if prev_timeout is None:
                    os.environ.pop("MVP_GCP_FLEET_TIMEOUT_S", None)
                else:
                    os.environ["MVP_GCP_FLEET_TIMEOUT_S"] = prev_timeout

            for result in results:
                agent_id = result.get("agent_id") or result.get("task_id")
                sess = study.live_sessions.get(agent_id) if agent_id else None
                if sess:
                    sess["status"] = "complete"
                    incoming = result.get("trace") or []
                    existing = list(sess.get("trace") or [])
                    if incoming:
                        by_step: dict[Any, dict[str, Any]] = {}
                        for s in existing:
                            if isinstance(s, dict) and s.get("step") is not None:
                                by_step[s.get("step")] = s
                        for s in incoming:
                            if isinstance(s, dict) and s.get("step") is not None:
                                by_step[s.get("step")] = s
                        sess["trace"] = [
                            by_step[k]
                            for k in sorted(by_step.keys(), key=lambda x: int(x or 0))
                        ]
                    else:
                        sess["trace"] = existing
                    sess["num_steps"] = len(sess["trace"])
                    _mark_first_screenshot(sess, study_id=study.id, agent_id=str(sess.get("agent_id") or ""))
                study.agent_results.append(result)
                log_activity(
                    study,
                    "agent_done",
                    f"{result.get('persona_name') or agent_id} finished ({result.get('difficulty', '?')})",
                    agent_id=agent_id,
                )
            # Prefer summary from fleet finisher when present.
            from mvp.gcs_store import gcs_download_json, study_gcs_root

            done = gcs_download_json(f"{study_gcs_root(study.id)}/done.json")
            if isinstance(done, dict) and done.get("summary"):
                study.summary = done["summary"]
            persist_study(study)
            refresh_agent_phase()
        else:
            use_live_browser = True
            # Prefer GCP fleet above; Browserbase when USE_BROWSERBASE=1 (Vercel or local);
            # otherwise headed Chromium on a laptop.
            force_local_browser = os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {
                "1",
                "true",
                "yes",
            }
            if not force_local_browser and not IS_VERCEL_ENV:
                bb = os.environ.get("USE_BROWSERBASE", "").lower() in {
                    "1",
                    "true",
                    "yes",
                }
                force_local_browser = not bb
            if not force_local_browser:
                try:
                    from capability.browserbase_client import ensure_browserbase_full_parallel

                    ensure_browserbase_full_parallel()
                except Exception:
                    pass
            pool = min(
                len(study.tasks),
                int(
                    os.environ.get(
                        "MVP_BROWSER_CONCURRENCY",
                        "2" if force_local_browser else "25",
                    )
                ),
            )
            # Do not batch-prefetch Browserbase sessions before agents start.
            # Each agent creates a session and captures the chosen URL immediately
            # so the first real pixels land as soon as the task URL is known.
            if pool and not force_local_browser:
                log_activity(
                    study,
                    "browser",
                    f"Opening {len(study.tasks)} chosen URLs immediately (Browserbase)",
                )
                touch(f"Opening chosen URLs — {len(study.tasks)} agents")
            elif force_local_browser:
                use_live_browser = True
                headed = os.environ.get("MVP_BROWSER_HEADLESS", "0").lower() not in {
                    "1",
                    "true",
                    "yes",
                }
                mode = "headed" if headed else "headless"
                log_activity(
                    study,
                    "browser",
                    f"Launching {pool} local Chromium sessions ({mode}, concurrency={pool})",
                )
                touch(f"Local Chromium ({mode}) — {len(study.tasks)} agents")
                # Cap concurrency for headed windows so the laptop stays usable.
                if headed and pool > 2:
                    pool = min(pool, int(os.environ.get("MVP_BROWSER_CONCURRENCY", "2")))

            if not use_live_browser:
                if warm_opening is not None:
                    from mvp.browser_agent import close_warm_opening

                    await close_warm_opening(warm_opening)
                    warm_opening = None
                log_activity(
                    study,
                    "agents",
                    f"Running {len(study.tasks)} persona simulations (snapshot fallback)",
                )
                touch(f"Simulating agents — 0/{len(study.tasks)} finished")

                async def _run_snapshot_fallback(task: dict[str, Any]) -> dict[str, Any]:
                    nonlocal done_count
                    persona = persona_by_id.get(task.get("persona_id")) or study.personas[0]
                    agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
                    sess = study.live_sessions.setdefault(
                        agent_id,
                        {
                            "agent_id": agent_id,
                            "persona_name": persona.get("name"),
                            "status": "running",
                            "trace": [],
                        },
                    )
                    log_activity(
                        study,
                        "agent_start",
                        f"{persona.get('name')} started (snapshot)",
                        agent_id=agent_id,
                        persona_name=persona.get("name"),
                    )
                    result = await simulate_agent(
                        url=task.get("site_url") or study.url,
                        segment=study.segment,
                        persona=persona,
                        task=task,
                        page_text=page_text,
                        study_id=study.id,
                        agent_id=agent_id,
                    )
                    result["mode"] = "fallback_snapshot"
                    result["persona_id"] = persona.get("id")
                    result["persona_name"] = persona.get("name")
                    result["persona_bio"] = persona.get("bio")
                    result["task_id"] = task.get("id")
                    result["task_title"] = task.get("title")
                    result["task_prompt"] = task.get("prompt")
                    result["site_key"] = task.get("site_key") or "product"
                    result["site_url"] = task.get("site_url") or study.url
                    result["site_label"] = task.get("site_label") or "Product"
                    sess["status"] = "complete"
                    sess["trace"] = result.get("trace") or []
                    sess["num_steps"] = len(sess["trace"])
                    done_count += 1
                    study.agent_results.append(result)
                    touch(f"Simulating agents — {done_count}/{len(study.tasks)} finished")
                    log_activity(
                        study,
                        "agent_done",
                        f"{persona.get('name')} finished ({result.get('difficulty', '?')})",
                        agent_id=agent_id,
                    )
                    return result

                study.agent_results = []
                snap_out = await asyncio.gather(
                    *[_run_snapshot_fallback(t) for t in study.tasks],
                    return_exceptions=True,
                )
                for item in snap_out:
                    if isinstance(item, Exception) and not isinstance(
                        item, asyncio.CancelledError
                    ):
                        print(f"snapshot fallback agent failed: {item!r}", flush=True)
            else:
                # Mark each agent with its chosen URL and launch immediately.
                # Do not clobber a warm session that already has pixels / live view.
                for task in study.tasks:
                    aid = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
                    sess = study.live_sessions.get(aid)
                    if not sess:
                        continue
                    site = task.get("site_url") or study.url
                    sess["site_url"] = site
                    if sess.get("trace") or sess.get("live_active"):
                        sess["status"] = "running"
                        if not sess.get("last_action"):
                            sess["last_action"] = f"Opened {site}"
                    else:
                        sess["status"] = "starting"
                        sess["last_action"] = f"Opening {site}"
                touch(
                    f"Live browser agents — 0/{len(study.tasks)} done · "
                    f"{len(study.tasks)} active · 0 queued · 0 steps"
                )
                if on_update:
                    try:
                        on_update(study, event="progress")
                    except TypeError:
                        on_update(study)
                    except Exception:
                        pass

                log_activity(
                    study,
                    "agents",
                    f"Launching {len(study.tasks)} live browser agents "
                    "(live view on with first pixels)",
                )

                async def _on_agent_step(agent_id: str, step: dict[str, Any]) -> None:
                    raise_if_killed(study)
                    sess = study.live_sessions.get(agent_id)
                    if not sess:
                        return
                    step = _json_safe(step)
                    # Progress-only pulses (thinking / live-active) — do not invent a
                    # screenshot trace row; stream into live_thoughts for the UI ticker.
                    if step.get("progress_only"):
                        if step.get("live_view_url"):
                            sess["live_view_url"] = step["live_view_url"]
                        if step.get("browserbase_session_id"):
                            sess["browserbase_session_id"] = step["browserbase_session_id"]
                        if step.get("live_active") or sess.get("live_view_url"):
                            sess["live_active"] = True
                        # Refresh debugger URL periodically — BB live WS dies silently.
                        sid = sess.get("browserbase_session_id")
                        now_mono = time.monotonic()
                        last_live = float(sess.get("_live_url_refresh_mono") or 0)
                        if (
                            sid
                            and sess.get("live_active")
                            and (now_mono - last_live) > 20
                        ):
                            try:
                                from capability.browserbase_client import (
                                    session_live_view_url,
                                )

                                fresh = await asyncio.to_thread(
                                    session_live_view_url, str(sid)
                                )
                                if fresh:
                                    sess["live_view_url"] = fresh
                                    sess["_live_url_refresh_mono"] = now_mono
                            except Exception:
                                pass
                        text = (
                            (step.get("thought") or "").strip()
                            or (step.get("action") or "").strip()
                        )
                        if text:
                            thoughts = list(sess.get("live_thoughts") or [])
                            thoughts.append(
                                {
                                    "at": _now(),
                                    "text": text[:400],
                                    "kind": "thinking"
                                    if "think" in (step.get("action") or "").lower()
                                    or step.get("thought_detail")
                                    else "status",
                                }
                            )
                            sess["live_thoughts"] = thoughts[-24:]
                            sess["last_action"] = text[:160]
                        study.updated_at = _now()
                        if on_update:
                            try:
                                on_update(study, event="progress")
                            except TypeError:
                                on_update(study)
                            except Exception:
                                pass
                        return
                    # Numbered frames only — null step is a status pulse, never a shot row.
                    if step.get("step") is None:
                        text = (
                            (step.get("thought") or "").strip()
                            or (step.get("action") or "").strip()
                        )
                        if text:
                            sess["last_action"] = text[:160]
                            thoughts = list(sess.get("live_thoughts") or [])
                            thoughts.append(
                                {
                                    "at": _now(),
                                    "text": text[:400],
                                    "kind": "status",
                                }
                            )
                            sess["live_thoughts"] = thoughts[-24:]
                        study.updated_at = _now()
                        if on_update:
                            try:
                                on_update(study, event="progress")
                            except TypeError:
                                on_update(study)
                            except Exception:
                                pass
                        return
                    # Persist screenshots to GCS *before* the client can GET them.
                    # Step 0 also gets an inline data URL so the stream paints immediately.
                    shot = step.get("screenshot_url") or ""
                    if isinstance(shot, str) and "/screenshots/" in shot:
                        from pathlib import Path as _Path

                        from mvp.opening_shot import attach_opening_pixels
                        from mvp.paths import MVP_RUNS_DIR

                        name = _Path(shot.split("?", 1)[0]).name
                        local = MVP_RUNS_DIR / study.id / agent_id / "screenshots" / name
                        if local.is_file() and local.stat().st_size > 100:
                            await attach_opening_pixels(
                                study_id=study.id,
                                agent_id=agent_id,
                                local=local,
                                step=step,
                            )
                    sess["status"] = "running"
                    sess["trace"] = list(sess.get("trace") or [])
                    existing = {s.get("step"): i for i, s in enumerate(sess["trace"])}
                    if step.get("step") in existing:
                        sess["trace"][existing[step["step"]]] = step
                    else:
                        sess["trace"].append(step)
                    sess["num_steps"] = len(sess["trace"])
                    sess["last_action"] = step.get("action") or ""
                    action_text = str(step.get("action") or "")
                    if (
                        not sess.get("first_action_at_ts")
                        and action_text
                        and not action_text.lower().startswith("open")
                        and not action_text.lower().startswith("step failed")
                        and not step.get("failed_step")
                    ):
                        from mvp.a11y_agent import apply_gate_fields

                        apply_gate_fields(sess, first_action_at_ts=time.time())
                    _mark_first_screenshot(sess, study_id=study.id, agent_id=str(sess.get("agent_id") or ""))
                    thought = (step.get("thought") or "").strip()
                    if thought:
                        thoughts = list(sess.get("live_thoughts") or [])
                        thoughts.append(
                            {
                                "at": _now(),
                                "text": thought[:400],
                                "kind": "thinking",
                                "step": step.get("step"),
                            }
                        )
                        sess["live_thoughts"] = thoughts[-24:]
                    refresh_agent_phase()
                    study.updated_at = _now()
                    if on_update:
                        try:
                            on_update(study, event="progress")
                        except TypeError:
                            on_update(study)
                        except Exception:
                            pass
                    from mvp.opening_shot import drop_inline_shots_inplace

                    drop_inline_shots_inplace(sess)
                    persist_study(study)
                    log_activity(
                        study,
                        "agent_step",
                        f"{sess.get('persona_name')}: step {step.get('step')} — {step.get('action', '')[:120]}",
                        agent_id=agent_id,
                        step=step.get("step"),
                    )

                async def _run_one(task: dict[str, Any]) -> dict[str, Any]:
                    nonlocal done_count, warm_used
                    from mvp.browser_agent import run_browser_agent

                    persona = persona_by_id.get(task.get("persona_id")) or study.personas[0]
                    agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
                    site = task.get("site_url") or study.url
                    if a11y_boot is not None:
                        _wait_until = getattr(study, "budget_deadline", None) or (
                            time.monotonic() + 30
                        )
                        while time.monotonic() < _wait_until:
                            existing = study.live_sessions.get(agent_id) or {}
                            if existing.get("first_action_at_ts"):
                                break
                            await asyncio.sleep(0.05)
                        sess = study.live_sessions.get(agent_id)
                        if not sess or not sess.get("first_action_at_ts"):
                            print(
                                f"[{agent_id}] no shared page read before the study budget",
                                flush=True,
                            )
                            return {"agent_id": agent_id, "skipped": True}
                    else:
                        sess = study.live_sessions.setdefault(
                            agent_id,
                            {
                                "agent_id": agent_id,
                                "persona_name": persona.get("name"),
                                "status": "starting",
                                "trace": [],
                            },
                        )
                    raise_if_killed(study)
                    sess["site_url"] = site
                    # Start immediately — with ≤25 Browserbase slots we should not
                    # park agents behind a "waiting for a browser slot" fake queue.
                    sess["status"] = "running"
                    if not (sess.get("trace") or []):
                        sess["last_action"] = f"Opening {site}"
                    study.updated_at = _now()
                    if on_update:
                        try:
                            on_update(study, event="progress")
                        except TypeError:
                            on_update(study)
                        except Exception:
                            pass
                    log_activity(
                        study,
                        "agent_start",
                        f"{persona.get('name')} opening {site}",
                        agent_id=agent_id,
                        persona_name=persona.get("name"),
                    )
                    name = persona.get("name") or "User"
                    thoughts = list(sess.get("live_thoughts") or [])
                    thoughts.append(
                        {
                            "at": _now(),
                            "text": f"{name} starting — opening {site}…",
                            "kind": "status",
                        }
                    )
                    sess["live_thoughts"] = thoughts[-24:]
                    refresh_agent_phase()
                    try:
                        async with _BROWSER_SEMAPHORE:
                            # The accessibility loop runs all 24 agents at once.
                            # The older screenshot loop still queues on the LLM cap.
                            class _Pass:
                                async def __aenter__(self) -> None:
                                    return None

                                async def __aexit__(self, *_exc: object) -> bool:
                                    return False

                            async with (
                                _Pass() if a11y_boot is not None else _llm_run_semaphore()
                            ):
                                raise_if_killed(study)
                                sess["status"] = "running"
                                if not (sess.get("trace") or []):
                                    sess["last_action"] = f"Opening {site}"
                                thoughts = list(sess.get("live_thoughts") or [])
                                thoughts.append(
                                    {
                                        "at": _now(),
                                        "text": f"{name} got a browser — opening {site}…",
                                        "kind": "status",
                                    }
                                )
                                sess["live_thoughts"] = thoughts[-24:]
                                refresh_agent_phase()
                                if on_update:
                                    try:
                                        on_update(study, event="progress")
                                    except TypeError:
                                        on_update(study)
                                    except Exception:
                                        pass
                                agent_warm = None
                                if (
                                    not warm_used
                                    and warm_opening is not None
                                    and str(task.get("site_key") or "product") == "product"
                                ):
                                    # YouTube agents never consume warm sessions (signed-in
                                    # path). Claiming warm anyway leaked the BB slot and
                                    # left DevTools URLs pointing at a zombie session.
                                    _host = (
                                        str(task.get("site_url") or study.url or "")
                                        .lower()
                                    )
                                    if (
                                        "youtube.com" not in _host
                                        and "youtu.be" not in _host
                                    ):
                                        agent_warm = warm_opening
                                        warm_used = True
                                run = None
                                _remaining = float(getattr(study, "budget_deadline", 0) or 0) - time.monotonic()
                                if a11y_boot is not None:
                                    from mvp.shared_extract import SharedExtractBoot, run_shared_agent

                                    if isinstance(a11y_boot, SharedExtractBoot):
                                        _agent_coro = run_shared_agent(
                                            study_id=study.id,
                                            agent_id=agent_id,
                                            url=site,
                                            task_prompt=task.get("prompt")
                                            or task.get("title")
                                            or "",
                                            persona=persona,
                                            segment=study.segment,
                                            on_step=lambda step: _on_agent_step(agent_id, step),
                                            decision=dict(sess.get("pending_action") or {}),
                                            shared=dict(
                                                (getattr(a11y_boot, "snapshots", {}) or {}).get(
                                                    str(task.get("site_key") or "product")
                                                )
                                                or {}
                                            ),
                                            gate={
                                                "page_open_at_ts": sess.get("page_open_at_ts"),
                                                "session_ready_at_ts": sess.get("session_ready_at_ts"),
                                                "first_action_at_ts": sess.get("first_action_at_ts"),
                                                "accessibility_tree": sess.get("accessibility_tree"),
                                                "page_url": sess.get("page_url"),
                                                "created_at_ts": sess.get("created_at_ts"),
                                                "phase_ms": dict(sess.get("phase_ms") or {}),
                                            },
                                            deadline=getattr(study, "budget_deadline", None),
                                            opening_trace=list(sess.get("trace") or []),
                                        )
                                    else:
                                        from mvp.a11y_agent import run_a11y_agent

                                        _agent_coro = run_a11y_agent(
                                            boot=a11y_boot,
                                            study_id=study.id,
                                            agent_id=agent_id,
                                            url=site,
                                            task_prompt=task.get("prompt")
                                            or task.get("title")
                                            or "",
                                            persona=persona,
                                            on_step=lambda step: _on_agent_step(agent_id, step),
                                            site_key=str(task.get("site_key") or "product"),
                                            deadline=getattr(study, "budget_deadline", None),
                                        )
                                else:
                                    _agent_coro = run_browser_agent(
                                        study_id=study.id,
                                        agent_id=agent_id,
                                        url=site,
                                        task_prompt=task.get("prompt")
                                        or task.get("title")
                                        or "",
                                        persona=persona,
                                        segment=study.segment,
                                        on_step=lambda step: _on_agent_step(agent_id, step),
                                        bb_session=None,
                                        local=force_local_browser,
                                        warm=agent_warm,
                                    )
                                if _remaining <= 0:
                                    print(
                                        f"[{agent_id}] study budget — not started",
                                        flush=True,
                                    )
                                    existing = sess.get("trace") or []
                                    from mvp.browser_agent import silent_failure_fields

                                    _err, _browser_err = silent_failure_fields(existing)
                                    run = {
                                        "agent_id": agent_id,
                                        "completed": False,
                                        "trace": existing,
                                        "actions": [],
                                        "num_steps": len(existing),
                                        "final_url": site,
                                        "visited_urls": [site],
                                        "mode": "study_budget",
                                        "stop_reason": "study budget",
                                        "failed_step": {
                                            "phase": "study_budget",
                                            "reason": "study budget",
                                            "step": len(existing),
                                        },
                                        "error": _err,
                                        "browser_error": _browser_err,
                                    }
                                    _agent_task = None
                                else:
                                    _agent_task = asyncio.create_task(_agent_coro)
                                if _agent_task is not None:
                                    _done, _pending = await asyncio.wait(
                                        {_agent_task}, timeout=max(0.1, _remaining)
                                    )
                                else:
                                    _pending = set()
                                if _agent_task is not None and _agent_task in _pending:
                                    print(
                                        f"[{agent_id}] study budget "
                                        f"({int(getattr(study, 'budget_s', 480))}s) — stopping",
                                        flush=True,
                                    )
                                    _agent_task.cancel()

                                    async def _drain(t: asyncio.Task) -> None:
                                        try:
                                            await t
                                        except Exception:
                                            pass

                                    asyncio.create_task(_drain(_agent_task))
                                    existing = sess.get("trace") or []
                                    from mvp.browser_agent import silent_failure_fields

                                    _err, _browser_err = silent_failure_fields(existing)
                                    run = {
                                        "agent_id": agent_id,
                                        "completed": False,
                                        "trace": existing,
                                        "actions": [],
                                        "num_steps": len(existing),
                                        "final_url": site,
                                        "visited_urls": [site],
                                        "mode": "study_budget",
                                        "stop_reason": "study budget",
                                        "failed_step": {
                                            "phase": "study_budget",
                                            "reason": "study budget",
                                            "step": len(existing),
                                        },
                                        "error": _err,
                                        "browser_error": _browser_err,
                                    }
                                elif _agent_task is not None:
                                    run = _agent_task.result()
                        sess["status"] = "summarizing"
                        refresh_agent_phase()
                        log_activity(
                            study,
                            "agent_summarize",
                            f"{persona.get('name')} session done — writing feedback",
                            agent_id=agent_id,
                        )
                        try:
                            feedback = await asyncio.wait_for(
                                summarize_agent_feedback(
                                    url=study.url,
                                    segment=study.segment,
                                    persona=persona,
                                    task=task,
                                    run=run,
                                ),
                                timeout=45.0,
                            )
                        except Exception as sum_exc:  # noqa: BLE001
                            print(
                                f"[{agent_id}] summarize failed/timed out: {sum_exc!r}",
                                flush=True,
                            )
                            feedback = {
                                "difficulty": "medium",
                                "friction_points": [],
                                "what_was_easy": [],
                                "product_feedback": "Session ended before feedback was written.",
                                "would_convert": "maybe",
                                "step_outcomes": [],
                            }
                        outcomes = {
                            o.get("step"): o.get("outcome")
                            for o in feedback.pop("step_outcomes", []) or []
                        }
                        for step in run.get("trace") or []:
                            step["outcome"] = outcomes.get(step.get("step")) or "neutral"
                        result = {**run, **feedback, "mode": "a11y" if a11y_boot is not None else "browser"}
                        if a11y_boot is not None:
                            if run.get("friction_points"):
                                result["friction_points"] = list(run.get("friction_points") or [])
                            if run.get("what_was_easy"):
                                result["what_was_easy"] = list(run.get("what_was_easy") or [])
                            if run.get("quote"):
                                result["quote"] = run.get("quote")
                            from mvp.a11y_agent import GATE_FIELDS, apply_gate_fields

                            apply_gate_fields(result)
                            for key in GATE_FIELDS:
                                if key in result:
                                    sess[key] = result[key]
                            sess["final_url"] = result.get("final_url") or sess.get("final_url")
                            if result.get("stop_reason"):
                                sess["stop_reason"] = result.get("stop_reason")
                            sess["last_action"] = (
                                (result.get("trace") or [{}])[-1].get("action")
                                if result.get("trace")
                                else sess.get("last_action")
                            )
                    except Exception as exc:  # noqa: BLE001
                        sess["status"] = "error"
                        existing = sess.get("trace") or []
                        if a11y_boot is not None:
                            print(f"[{agent_id}] agent ended: {exc!r}", flush=True)
                            result = {
                                "agent_id": agent_id,
                                "completed": False,
                                "trace": existing,
                                "actions": [],
                                "num_steps": len(existing),
                                "final_url": str(sess.get("final_url") or site),
                                "final_dom": str(sess.get("final_dom") or ""),
                                "visited_urls": [str(sess.get("final_url") or site)],
                                "mode": "a11y",
                                "stop_reason": "session ended",
                                "failed_step": {
                                    "phase": "act",
                                    "reason": "session ended",
                                    "step": len(existing),
                                },
                                "error": "",
                                "browser_error": "",
                                "friction_points": list(sess.get("friction_points") or []),
                                "what_was_easy": list(sess.get("what_was_easy") or []),
                                "accessibility_tree": sess.get("accessibility_tree") or "",
                                "page_url": sess.get("page_url") or site,
                                "page_open_at_ts": sess.get("page_open_at_ts"),
                                "session_ready_at_ts": sess.get("session_ready_at_ts"),
                                "first_action_at_ts": sess.get("first_action_at_ts"),
                                "phase_ms": dict(sess.get("phase_ms") or {}),
                                "final_screenshot_url": sess.get("final_screenshot_url") or "",
                            }
                        else:
                            existing = sess.get("trace") or []
                            has_pixels = any(
                                (s or {}).get("screenshot_url")
                                or (s or {}).get("screenshot_data_url")
                                for s in existing
                            )
                            # Opening frames already on stage: finish with partials.
                            # Full Browserbase retry after wall/CDP death doubles runtime
                            # (90s → 180s+) and re-exhausts the 25-slot budget.
                            if has_pixels:
                                log_activity(
                                    study,
                                    "agent_error",
                                    f"{persona.get('name')} browser ended early — "
                                    "keeping captured frames (no retry)",
                                    agent_id=agent_id,
                                    error=str(exc)[:200],
                                )
                                result = {
                                    "agent_id": agent_id,
                                    "completed": False,
                                    "difficulty": "hard",
                                    "friction_points": [
                                        "Browser session ended before the task finished"
                                    ],
                                    "what_was_easy": [],
                                    "product_feedback": (
                                        "Session captured the opening page but the live "
                                        "browser run stopped early."
                                    ),
                                    "would_convert": "maybe",
                                    "trace": existing,
                                    "actions": [],
                                    "num_steps": len(existing),
                                    "final_url": site,
                                    "visited_urls": [site],
                                    "mode": "browser_partial",
                                    "browser_error": (str(exc) or repr(exc))[:300],
                                }
                            else:
                                # Prefer a fresh Browserbase session over local Chrome.
                                # Local fallback was attaching to the UserSim debug Chrome
                                # and agents got stuck on http://127.0.0.1:8787/live.
                                log_activity(
                                    study,
                                    "agent_error",
                                    f"{persona.get('name')} browser failed — retrying Browserbase",
                                    agent_id=agent_id,
                                    error=str(exc)[:200],
                                )
                                try:
                                    _left = float(getattr(study, "budget_deadline", 0) or 0) - time.monotonic()
                                    if _left <= 1:
                                        raise TimeoutError("study budget")
                                    run = await asyncio.wait_for(
                                        run_browser_agent(
                                            study_id=study.id,
                                            agent_id=agent_id,
                                            url=task.get("site_url") or study.url,
                                            task_prompt=task.get("prompt") or task.get("title") or "",
                                            persona=persona,
                                            segment=study.segment,
                                            on_step=lambda step: _on_agent_step(agent_id, step),
                                            bb_session=None,
                                            local=False,
                                        ),
                                        timeout=_left,
                                    )
                                    sess["status"] = "summarizing"
                                    feedback = await summarize_agent_feedback(
                                        url=study.url,
                                        segment=study.segment,
                                        persona=persona,
                                        task=task,
                                        run=run,
                                    )
                                    outcomes = {
                                        o.get("step"): o.get("outcome")
                                        for o in feedback.pop("step_outcomes", []) or []
                                    }
                                    for step in run.get("trace") or []:
                                        step["outcome"] = (
                                            outcomes.get(step.get("step")) or "neutral"
                                        )
                                    result = {**run, **feedback, "mode": "browser_retry"}
                                    result["browser_error"] = (str(exc) or repr(exc))[:300]
                                except Exception as retry_exc:  # noqa: BLE001
                                    log_activity(
                                        study,
                                        "agent_error",
                                        f"{persona.get('name')} Browserbase retry failed — "
                                        "snapshot fallback",
                                        agent_id=agent_id,
                                        error=str(retry_exc)[:200],
                                    )
                                    result = await simulate_agent(
                                        url=study.url,
                                        segment=study.segment,
                                        persona=persona,
                                        task=task,
                                        page_text=page_text,
                                        study_id=study.id,
                                        agent_id=agent_id,
                                    )
                                    result["mode"] = "fallback_snapshot"
                                    result["browser_error"] = (
                                        (str(retry_exc) or repr(retry_exc))[:300]
                                    )

                    result["persona_id"] = persona.get("id")
                    result["persona_name"] = persona.get("name")
                    result["persona_bio"] = persona.get("bio")
                    result["task_id"] = task.get("id")
                    result["task_title"] = task.get("title")
                    result["task_prompt"] = task.get("prompt")
                    result["site_key"] = task.get("site_key") or "product"
                    result["site_url"] = task.get("site_url") or study.url
                    result["site_label"] = task.get("site_label") or "Product"
                    if a11y_boot is not None:
                        from mvp.a11y_agent import ensure_phase_ms

                        result["browser_error"] = ""
                        result["error"] = ""
                        result["mode"] = "a11y"
                        if not isinstance(result.get("failed_step"), dict) or not str(
                            (result.get("failed_step") or {}).get("phase") or ""
                        ).strip():
                            result["failed_step"] = {
                                "phase": "act",
                                "reason": "page did not show the goal",
                                "step": int(result.get("num_steps") or 0),
                            }
                        ensure_phase_ms(result)
                        if not str(result.get("final_url") or "").strip():
                            result["final_url"] = task.get("site_url") or study.url
                        if not str(result.get("accessibility_tree") or "").strip():
                            result["accessibility_tree"] = str(
                                sess.get("accessibility_tree") or "0 document page"
                            )
                        if not str(result.get("final_dom") or "").strip():
                            result["final_dom"] = str(
                                result.get("accessibility_tree") or "page"
                            )[:1500]
                    sess["status"] = "complete"
                    # Never wipe a real opening screenshot with text-only snapshot steps.
                    snap_trace = result.get("trace") or []
                    existing = sess.get("trace") or []
                    has_pixels = any(
                        (s or {}).get("screenshot_url") or (s or {}).get("screenshot_data_url")
                        for s in existing
                    )
                    snap_has_pixels = any(
                        (s or {}).get("screenshot_url") or (s or {}).get("screenshot_data_url")
                        for s in snap_trace
                    )
                    if has_pixels and not snap_has_pixels:
                        sess["trace"] = existing + [
                            s for s in snap_trace if (s or {}).get("step") not in {
                                e.get("step") for e in existing if isinstance(e, dict)
                            }
                        ]
                    else:
                        sess["trace"] = snap_trace or existing
                    sess["num_steps"] = len(sess["trace"])
                    _mark_first_screenshot(sess, study_id=study.id, agent_id=str(sess.get("agent_id") or ""))
                    done_count += 1
                    study.agent_results.append(result)
                    refresh_agent_phase()
                    log_activity(
                        study,
                        "agent_done",
                        f"{persona.get('name')} finished ({result.get('difficulty', '?')}, convert: {result.get('would_convert', '?')})",
                        agent_id=agent_id,
                    )
                    return result

                study.agent_results = []
                if a11y_boot is not None:
                    _left = max(
                        1.0,
                        float(getattr(study, "budget_deadline", 0) or 0) - time.monotonic(),
                    )
                    try:
                        await asyncio.wait_for(a11y_boot.published.wait(), timeout=_left)
                    except asyncio.TimeoutError:
                        print(
                            "shared page read did not finish before the study budget",
                            flush=True,
                        )
                def _run_rank(task: dict[str, Any]) -> tuple:
                    key = str(task.get("site_key") or "product")
                    return (0 if key == "product" else 1, key, str(task.get("id") or ""))

                ordered_tasks = sorted(study.tasks, key=_run_rank)
                # return_exceptions=True: one cancelled/failed agent must not
                # CancelledError the whole gather ("Killed by operator").
                agent_out = await asyncio.gather(
                    *[_run_one(t) for t in ordered_tasks],
                    return_exceptions=True,
                )
                for item in agent_out:
                    if isinstance(item, Exception):
                        print(f"live agent failed: {item!r}", flush=True)
                        continue
                if a11y_boot is not None:
                    try:
                        await a11y_boot.close()
                    except Exception as close_exc:  # noqa: BLE001
                        print(f"a11y browser close failed: {close_exc!r}", flush=True)
                try:
                    await backfill_site_opening_shots(study)
                    if study.live_sessions:
                        # Push so e2e can re-fetch filled shots before summary.
                        if on_update:
                            try:
                                on_update(study, event="progress")
                            except TypeError:
                                on_update(study)
                            except Exception:
                                pass
                except Exception as bf_exc:  # noqa: BLE001
                    print(f"post-agent backfill failed: {bf_exc!r}", flush=True)
                if warm_opening is not None and not warm_used:
                    from mvp.browser_agent import close_warm_opening

                    await close_warm_opening(warm_opening)
                    warm_opening = None
                # Always close competitor warms (never handed to agents).
                if warm_by_site:
                    from mvp.browser_agent import close_warm_opening

                    for key, warm in list(warm_by_site.items()):
                        if key == "product" and warm_used:
                            continue
                        try:
                            await close_warm_opening(warm)
                        except Exception:
                            pass
                    warm_by_site = {}

        order = {t.get("id"): i for i, t in enumerate(study.tasks)}
        study.agent_results.sort(key=lambda r: order.get(r.get("task_id"), 99))

        # NOTE: do not early-return while status=="running". That aborted every
        # successful local/Browserbase study before the executive summary and
        # left the UI stuck at "N/N done" forever. GCP fleet detach returns
        # earlier in the fleet branch.

        try:
            await backfill_site_opening_shots(study)
        except Exception as bf_exc:  # noqa: BLE001
            print(f"backfill_site_opening_shots failed: {bf_exc!r}", flush=True)

        from mvp.competitor_urls import annotate_run_issues, run_issue_lines, scrub_product_summary

        run_issues = annotate_run_issues(study.agent_results)
        if run_issues:
            log_activity(
                study,
                "run_issue",
                f"{len(run_issues)} run issue(s) excluded from product insights",
            )
            for issue in run_issues:
                log_activity(
                    study,
                    "run_issue",
                    f"{issue.get('persona_name') or issue.get('agent_id')}: "
                    f"{issue.get('kind')} — {issue.get('reason')}",
                    agent_id=issue.get("agent_id"),
                )

        touch("Writing executive summary")
        if study.summary and study.summary.get("headline"):
            # Already written by fleet finisher — still strip harness failures.
            study.summary = scrub_product_summary(study.summary)
            study.summary["run_issues"] = run_issue_lines(
                [r.get("run_issue") for r in study.agent_results if isinstance(r, dict) and r.get("run_issue")]
            )
        else:
            log_activity(study, "summary", "Synthesizing executive summary from all sessions")
            try:
                study.summary = await synthesize_summary(
                    url=study.url,
                    segment=study.segment,
                    site_summary=site_summary,
                    agent_results=study.agent_results,
                )
            except Exception as summary_exc:  # noqa: BLE001
                print(f"synthesize_summary failed: {summary_exc!r}", flush=True)
                study.summary = None
            # Fallback if the LLM summary is missing — still fill from agent recaps.
            if not (study.summary and study.summary.get("headline")):
                study.summary = _summary_from_agent_results(study.agent_results)
        if not study.summary:
            study.summary = {}
        try:
            from mvp.a11y_agent import failure_breakdown

            study.summary["failure_breakdown"] = failure_breakdown(study.agent_results)
        except Exception as breakdown_exc:  # noqa: BLE001
            print(f"failure breakdown skipped: {breakdown_exc!r}", flush=True)
        study.summary["site_summary"] = site_summary
        if study.access_backend:
            study.summary["access_backend"] = study.access_backend
        if study.browserbase_session_url:
            study.summary["browserbase_session_url"] = study.browserbase_session_url
        if study.auth_status:
            study.summary["auth_status"] = study.auth_status
        if study.auth_blocker:
            study.summary["auth_blocker"] = study.auth_blocker
        try:
            from mvp.report_insights import apply_insights

            apply_insights(study)
        except Exception as insight_exc:  # noqa: BLE001
            print(f"report insights failed: {insight_exc!r}", flush=True)
        try:
            from mvp.shared_extract import finalize_ux_metrics

            finalize_ux_metrics(study)
        except Exception as ux_exc:  # noqa: BLE001
            print(f"ux metrics failed: {ux_exc!r}", flush=True)
        touch("Complete", "complete")
        log_activity(study, "complete", "Study complete")
        persist_study(study)
    except SiteAccessBlockedError as exc:
        study.status = "error"
        study.error = (str(exc) or repr(exc))[:500]
        study.phase = "Site blocked"
        study.updated_at = _now()
        persist_study(study)
    except asyncio.CancelledError:
        # Only label as operator-kill when the kill switch was actually armed.
        # Bare task cancellation (server restart, gather teardown) used to
        # stamp every interrupted study as "Killed by operator".
        if study_was_killed(study) or getattr(study, "kill_requested", False):
            study.kill_requested = True
            study.status = "abandoned"
            study.phase = "Killed"
            study.error = "Killed by operator"
        else:
            study.status = "abandoned"
            study.phase = "Cancelled"
            study.error = study.error or "Study task cancelled"
            print(
                f"study {study.id} CancelledError without kill_requested "
                f"(not treating as operator kill)",
                flush=True,
            )
        study.updated_at = _now()
        persist_study(study)
        raise
    except Exception as exc:  # noqa: BLE001
        from mvp.kill_switch import StudyKilled

        if isinstance(exc, StudyKilled) or study_was_killed(study):
            study.status = "abandoned"
            study.phase = "Killed"
            study.error = "Killed by operator"
            study.updated_at = _now()
            persist_study(study)
            return
        study.status = "error"
        study.error = (str(exc) or repr(exc))[:500]
        study.phase = "Failed"
        study.updated_at = _now()
        persist_study(study)


def create_study(url: str, segment: str) -> StudyState:
    study_id = str(uuid.uuid4())
    study = StudyState(id=study_id, url=url.strip(), segment=segment.strip())
    STUDIES[study_id] = study
    return study


def _json_safe(value: Any) -> Any:
    """Coerce browser-use ActionModel / nested objects into JSON-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump())
        except Exception:
            pass
    dict_fn = getattr(value, "dict", None)
    if callable(dict_fn):
        try:
            return _json_safe(dict_fn())
        except Exception:
            pass
    return str(value)


def study_to_dict(study: StudyState) -> dict[str, Any]:
    return _json_safe(
        {
            "id": study.id,
            "url": study.url,
            "segment": study.segment,
            "status": study.status,
            "phase": study.phase,
            "created_at": study.created_at,
            "updated_at": study.updated_at,
            "personas": study.personas,
            "tasks": study.tasks,
            "agent_results": study.agent_results,
            "live_sessions": _ordered_live_sessions(study),
            "activity_log": study.activity_log,
            "summary": study.summary,
            "error": study.error,
            "access_backend": study.access_backend,
            "browserbase_session_url": study.browserbase_session_url,
            "auth_status": study.auth_status,
            "auth_blocker": study.auth_blocker,
            "competitors": study.competitors,
            "skip_competitors": study.skip_competitors,
            "test_mode": study.test_mode,
            "backend": study.backend,
            "email": study.email,
            "kill_requested": study.kill_requested,
            "ux_metrics": getattr(study, "ux_metrics", None) or {},
        }
    )


def _local_snapshot_path(study_id: str):
    from mvp.paths import MVP_RUNS_DIR

    return MVP_RUNS_DIR / "snapshots" / f"{study_id}.json"


def persist_study(study: StudyState) -> None:
    """Best-effort write of study state so a restarted local server can still serve the report."""
    try:
        from mvp.opening_shot import drop_inline_shots

        payload = drop_inline_shots(study_to_dict(study))
        path = _local_snapshot_path(study.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"local persist_study failed for {study.id}: {exc!r}", flush=True)
    try:
        from mvp.gcs_store import write_study_state
        from mvp.opening_shot import drop_inline_shots

        write_study_state(study.id, drop_inline_shots(study_to_dict(study)))
    except Exception as exc:  # noqa: BLE001
        print(f"persist_study failed for {study.id}: {exc!r}", flush=True)


def load_local_study(study_id: str) -> dict[str, Any] | None:
    """Study JSON written by this process, or a snapshot saved before a restart."""
    from pathlib import Path

    candidates = [
        _local_snapshot_path(study_id),
        Path("/tmp/usersim-study-snapshots") / f"{study_id}.json",
    ]
    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and (data.get("id") or data.get("summary") or data.get("url")):
            data.setdefault("id", study_id)
            return data
    return None


def load_study_from_gcs(study_id: str) -> dict[str, Any] | None:
    try:
        from mvp.gcs_store import normalize_study_display, read_study_state

        data = read_study_state(study_id)
        if isinstance(data, dict):
            return normalize_study_display(data)
        return None
    except Exception:
        return None
