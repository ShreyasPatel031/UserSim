"""Generate study plans and run parallel persona simulations."""

from __future__ import annotations

import asyncio
import json
import os
import re
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


def _fleet_preferred() -> bool:
    # Explicit opt-in always wins (local warm-seed path).
    if os.environ.get("MVP_PREFER_GCP_FLEET", "").lower() in {"1", "true", "yes"}:
        try:
            from mvp.gcp_fleet import gcp_fleet_enabled

            return gcp_fleet_enabled()
        except Exception:
            return False
    # Browserbase is the Vercel production path. Cloud secrets often still inject
    # MVP_GCP_FLEET=1; that steals the run and fails without seed VMs.
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
) -> list[Any]:
    """Create Browserbase sessions in parallel with per-session progress + timeout."""
    if n <= 0:
        return []
    from capability.browserbase_client import create_session, ensure_browserbase_full_parallel

    ensure_browserbase_full_parallel()
    ready: list[Any] = []
    timeout_s = float(os.environ.get("BROWSERBASE_PREFETCH_TIMEOUT_S", "45"))

    async def _one(i: int) -> Any | None:
        try:
            session = await asyncio.wait_for(
                asyncio.to_thread(create_session, proxies=False, keep_alive=True),
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
        persona_count = int(os.environ.get("MVP_PERSONA_COUNT", "5"))
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
        # At least one task per persona so every simulated user actually runs.
        requested = int(os.environ.get("MVP_TASK_COUNT", "6"))
        task_count = max(requested, len(personas) or 1)
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
    # LLMs sometimes under-deliver. Guarantee ≥1 task per persona so the stage
    # shows every simulated user, not a single orphaned session.
    if not (QUICK_MODE or test_mode) and personas:
        covered = {str(t.get("persona_id") or "") for t in tasks}
        next_n = len(tasks) + 1
        for persona in personas:
            pid = str(persona.get("id") or "")
            if not pid or pid in covered:
                continue
            name = persona.get("name") or pid
            tasks.append(
                {
                    "id": f"t{next_n}",
                    "title": f"Explore as {name}",
                    "prompt": (
                        f"Browse the site as {name}. Open the main navigation, "
                        "find something relevant to your goals, and try one concrete action."
                    ),
                    "persona_id": pid,
                    "difficulty_hint": "medium",
                }
            )
            covered.add(pid)
            next_n += 1
        # If still short of requested count, round-robin personas so the
        # parallel stage stays sized for multi-user UX.
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
                    or f"Follow-up for {persona.get('name') or pid}",
                    "prompt": prompt,
                    "persona_id": pid,
                    "difficulty_hint": "medium",
                }
            )
            next_n += 1
            if next_n > task_count + len(personas) + 2:
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
    from urllib.parse import quote_plus

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

    # DuckDuckGo HTML result links look like:
    # <a rel="nofollow" class="result__a" href="https://...">Title</a>
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.I | re.S,
    ):
        href = match.group(1).strip()
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if not href.startswith("http"):
            continue
        results.append({"title": title[:120], "url": href})
        if len(results) >= limit:
            break
    return results


async def invent_competitors(url: str, site_summary: str, page_text: str) -> list[str]:
    """Find 2 real competitor homepage URLs via web search + LLM selection."""
    from urllib.parse import urlparse

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

Live web search results (use these — do not invent domains):
{json.dumps(search_hits[:12], indent=2)}

Return JSON only:
{{"competitors": [{{"name": "...", "url": "https://..."}}, {{"name": "...", "url": "https://..."}}]}}

Rules:
- Exactly 2 direct product competitors a real user would also evaluate.
- Prefer URLs from the search results above. Only use other well-known live public sites if search is empty.
- Public marketing homepages only (https), no app login URLs.
- Never invent fake domains.
"""
    raw = await _llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You output valid JSON only. Prefer competitor URLs from the provided "
                    "web search results. Never invent fake domains."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    data = _extract_json(raw)
    urls: list[str] = []
    for row in data.get("competitors") or []:
        u = (row.get("url") if isinstance(row, dict) else str(row) or "").strip()
        if u.startswith("http") and u.rstrip("/") != url.rstrip("/"):
            urls.append(u)
    if not urls and search_hits:
        # Fallback: first two distinct search result hosts.
        for hit in search_hits:
            u = hit.get("url") or ""
            if u.startswith("http") and u.rstrip("/") != url.rstrip("/"):
                urls.append(u)
            if len(urls) >= 2:
                break
    # Still short? Ask the model for well-known public alternatives without search.
    if len(urls) < 2:
        try:
            raw2 = await _llm_chat(
                [
                    {
                        "role": "system",
                        "content": "JSON only. Return real public competitor homepage URLs.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Product: {url}\nSummary: {site_summary}\n"
                            f"Need {2 - len(urls)} more competitor homepage URL(s). "
                            'Return {"competitors":[{"name":"...","url":"https://..."}]}'
                        ),
                    },
                ]
            )
            for row in (_extract_json(raw2).get("competitors") or []):
                u = (row.get("url") if isinstance(row, dict) else str(row) or "").strip()
                if u.startswith("http") and u.rstrip("/") != url.rstrip("/") and u not in urls:
                    urls.append(u)
                if len(urls) >= 2:
                    break
        except Exception:
            pass
    return urls[:2]


def expand_tasks_for_sites(
    tasks: list[dict[str, Any]],
    *,
    product_url: str,
    competitors: list[str],
) -> list[dict[str, Any]]:
    """Duplicate each persona task across the product and every competitor site."""
    sites: list[tuple[str, str]] = [("product", product_url)]
    for i, c in enumerate(competitors, start=1):
        sites.append((f"competitor_{i}", c))

    expanded: list[dict[str, Any]] = []
    for task in tasks:
        for site_key, site_url in sites:
            clone = dict(task)
            base_id = task.get("id") or "t"
            clone["id"] = f"{base_id}__{site_key}"
            clone["site_key"] = site_key
            clone["site_url"] = site_url
            clone["site_label"] = "Product" if site_key == "product" else site_url
            title = task.get("title") or "Task"
            if site_key != "product":
                clone["title"] = f"{title} (vs {site_url})"
                prompt = str(task.get("prompt") or title)
                clone["prompt"] = (
                    f"{prompt}\n\n"
                    f"You are evaluating the competitor site {site_url} only. "
                    f"Stay on that site — do not open the original product or other rivals."
                )
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
    prompt = f"""Synthesize a product research report from parallel simulated user sessions.

Site: {url}
Segment: {segment}
Site summary: {site_summary}

Agent session results:
{json.dumps(_slim_results(agent_results), indent=2)[:14000]}

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
}}"""
    raw = await _llm_chat(
        [
            {"role": "system", "content": "You are a senior UX researcher. JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return _extract_json(raw)


def _summary_from_agent_results(agent_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic fallback when LLM synthesis is unavailable."""
    if not agent_results:
        return {
            "headline": "Study finished with no agent results",
            "top_friction": [],
            "top_strengths": [],
            "conversion_outlook": "",
            "recommendations": [],
            "segment_fit_score": 0,
            "segment_fit_rationale": "",
        }
    friction: list[str] = []
    strengths: list[str] = []
    for r in agent_results:
        for item in r.get("friction_points") or []:
            if item and item not in friction:
                friction.append(str(item))
        for item in r.get("what_was_easy") or []:
            if item and item not in strengths:
                strengths.append(str(item))
    first = agent_results[0]
    converts = sum(
        1
        for r in agent_results
        if str(r.get("would_convert") or "").lower() in {"yes", "true", "likely"}
    )
    score = max(1, min(10, round(10 * converts / max(1, len(agent_results)))))
    return {
        "headline": (first.get("quote") or first.get("product_feedback") or "Study complete")[:200],
        "top_friction": friction[:5],
        "top_strengths": strengths[:5],
        "conversion_outlook": (
            f"{converts}/{len(agent_results)} simulated users said they would convert."
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
    }


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
        raise_if_killed(study)
        log_activity(study, "phase", "Study queued")
        touch("Understanding context of product", "running")
        log_activity(study, "fetch", f"Understanding context of {study.url}")

        # Warm Browserbase + first screenshot of the product URL in parallel with
        # page fetch + persona/task LLMs so pixels are ready when the URL locks in.
        warm_task: asyncio.Task | None = None
        warm_opening: dict[str, Any] | None = None
        warm_used = False

        def _should_warm_browserbase() -> bool:
            if SNAPSHOT_ONLY and not _fleet_preferred():
                return False
            if _fleet_preferred():
                return False
            if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
                return False
            if IS_VERCEL_ENV:
                return USE_LIVE_BROWSER and _browserbase_configured()
            return _browserbase_configured()

        if _should_warm_browserbase():
            from mvp.browser_agent import warm_opening_session

            warm_task = asyncio.create_task(
                warm_opening_session(study_id=study.id, url=study.url)
            )
            log_activity(
                study,
                "browser",
                f"Warming first screenshot for {study.url} during brief",
            )
            # Prewarm Vertex ADC so agent.run isn't blocked on first credential load.
            try:
                from auth import vertex_credentials

                asyncio.create_task(asyncio.to_thread(vertex_credentials))
            except Exception:
                pass

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
        if study.test_mode or study.skip_competitors:
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
        elif not study.competitors:
            try:
                study.competitors = await invent_competitors(
                    study.url, site_hint, page_text
                )
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
            touch("Finding competitors")
            _push_brief("brief")

        # 2) Simulated users (own agent call)
        if not study.test_mode:
            touch("Building simulated users")
            study.personas = []
            study.tasks = []
            _push_brief("brief")
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
        if site_summary:
            log_activity(study, "plan", f"Site: {site_summary}")

        # Retry competitors with richer summary if the first pass was empty.
        if (
            not study.test_mode
            and not study.skip_competitors
            and not study.competitors
            and site_summary
        ):
            try:
                study.competitors = await invent_competitors(
                    study.url, site_summary, page_text
                )
                if study.competitors:
                    log_activity(
                        study,
                        "plan",
                        "Competitors: " + ", ".join(study.competitors),
                    )
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

        # Apply optional task overrides.
        if study.tasks_override:
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
                rebuilt: list[dict[str, Any]] = []
                for i, prompt in enumerate(study.tasks_override):
                    persona = (
                        study.personas[i]
                        if i < len(study.personas)
                        else (study.personas[-1] if study.personas else {"id": f"p{i+1}"})
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
                used = {t.get("persona_id") for t in study.tasks}
                study.personas = [p for p in study.personas if p.get("id") in used] or study.personas

        base_cap = int(
            os.environ.get(
                "MVP_AGENT_COUNT",
                "1" if (QUICK_MODE or study.test_mode) else "6",
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
                : max(len(ordered), int(os.environ.get("MVP_PERSONA_COUNT", "5")))
            ]

        # Full studies: every task × (product + each competitor), all parallel.
        # Smoke / quick preview: product site only (1 user × 1 task × 1 site).
        if study.competitors and not study.test_mode:
            before = len(study.tasks)
            study.tasks = expand_tasks_for_sites(
                study.tasks,
                product_url=study.url,
                competitors=study.competitors,
            )
            log_activity(
                study,
                "plan",
                f"Expanded to {len(study.tasks)} parallel runs "
                f"({before} tasks × {1 + len(study.competitors)} sites)",
            )
            # Cap total Browserbase sessions so Vercel survives product+rivals.
            # Prefer distinct product-site personas first so user/task dropdowns
            # aren't stuck on a single simulated user (old round-robin-by-site
            # always kept task t1 × every site).
            max_sessions = int(
                os.environ.get(
                    "MVP_MAX_SESSIONS",
                    "9" if IS_VERCEL_ENV else "15",
                )
            )
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
                picked: list[dict[str, Any]] = []
                for t in product:
                    if len(picked) >= max_sessions:
                        break
                    picked.append(t)
                if len(picked) < max_sessions:
                    # Fill with competitors for personas already included, then others.
                    have = {p.get("persona_id") for p in picked}
                    primary = [t for t in rivals if t.get("persona_id") in have]
                    secondary = [t for t in rivals if t.get("persona_id") not in have]
                    for t in primary + secondary:
                        if len(picked) >= max_sessions:
                            break
                        picked.append(t)
                study.tasks = picked
                log_activity(
                    study,
                    "plan",
                    f"Capped to {len(study.tasks)} parallel sessions "
                    f"(MVP_MAX_SESSIONS={max_sessions}; "
                    f"{sum(1 for t in picked if (t.get('site_key') or 'product') == 'product')} on product)",
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

        # Brief is ready — surface competitors / users / tasks before browsers start.
        touch("Brief ready")
        if on_update:
            try:
                on_update(study, event="brief")
            except TypeError:
                on_update(study)
            except Exception:
                pass

        # Finish warm capture BEFORE exposing live_sessions so the first poll
        # that sees agents also sees real pixels (no empty stage gap).
        if warm_task is not None:
            try:
                warm_opening = await warm_task
            except Exception as warm_exc:  # noqa: BLE001
                print(f"warm opening await failed: {warm_exc!r}", flush=True)
                warm_opening = None
            warm_task = None

        persona_by_id = {p["id"]: p for p in study.personas}
        study.live_sessions = {}
        for task in study.tasks:
            persona = persona_by_id.get(task.get("persona_id")) or (study.personas[0] if study.personas else {})
            agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
            study.live_sessions[agent_id] = {
                "agent_id": agent_id,
                "persona_id": persona.get("id"),
                "persona_name": persona.get("name"),
                "persona_bio": persona.get("bio"),
                "task_id": task.get("id"),
                "task_title": task.get("title"),
                "task_prompt": task.get("prompt"),
                "site_key": task.get("site_key") or "product",
                "site_url": task.get("site_url") or study.url,
                "site_label": task.get("site_label") or "Product",
                "status": "starting",
                "trace": [],
                "num_steps": 0,
                "live_active": False,
                "live_thoughts": [
                    {
                        "at": _now(),
                        "text": (
                            f"Preparing browser for {task.get('site_label') or task.get('site_url') or study.url}…"
                        ),
                        "kind": "status",
                    }
                ],
                "last_action": (
                    f"Preparing browser for {task.get('site_label') or 'site'}…"
                ),
            }

        # If warm screenshot is already on disk, publish it onto the first product
        # agent NOW — stage shows real pixels as soon as the task URL is chosen.
        if warm_opening and warm_opening.get("shot_path"):
            from pathlib import Path as _Path

            from mvp.paths import MVP_RUNS_DIR

            for task in study.tasks:
                if str(task.get("site_key") or "product") != "product":
                    continue
                aid = task.get("id") or ""
                sess = study.live_sessions.get(aid)
                if not sess:
                    continue
                site = task.get("site_url") or study.url
                dest_dir = MVP_RUNS_DIR / study.id / aid / "screenshots"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "bbox_0.png"
                try:
                    import shutil as _shutil

                    from mvp.opening_shot import attach_opening_pixels

                    _shutil.copy2(warm_opening["shot_path"], dest)
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
                    await attach_opening_pixels(
                        study_id=study.id,
                        agent_id=aid,
                        local=dest,
                        step=step0,
                    )
                    sess["status"] = "running"
                    sess["trace"] = [step0]
                    sess["num_steps"] = 1
                    sess["last_action"] = step0["action"]
                    # Stash live URL early but keep live_active OFF — UI shows
                    # screenshot until the agent loop actually starts.
                    if warm_opening.get("live_view_url"):
                        sess["live_view_url"] = warm_opening["live_view_url"]
                    if warm_opening.get("browserbase_session_id"):
                        sess["browserbase_session_id"] = warm_opening[
                            "browserbase_session_id"
                        ]
                    sess["live_active"] = False
                    sess["live_thoughts"] = [
                        {
                            "at": _now(),
                            "text": f"Opened {site} — waiting for the simulated user to start…",
                            "kind": "status",
                        }
                    ]
                    study.updated_at = _now()
                    log_activity(
                        study,
                        "browser",
                        f"First screenshot ready for {site}",
                        agent_id=aid,
                    )
                    break
                except Exception as pub_exc:  # noqa: BLE001
                    print(f"warm publish failed: {pub_exc!r}", flush=True)

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

        if SNAPSHOT_ONLY and not _fleet_preferred():
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
            await asyncio.gather(*[_run_snapshot(t) for t in study.tasks])
        elif _fleet_preferred():
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
                f"Launching on GCP warm seed — headed Chromium (reuse CDP), {workers} workers/VM",
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
                if not step.get("screenshot_url") and step.get("step") is None:
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
                await asyncio.gather(*[_run_snapshot_fallback(t) for t in study.tasks])
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
                        if step.get("live_active"):
                            sess["live_active"] = True
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
                    # Keep warm pixels / live_active visible — don't flash "starting".
                    if not (sess.get("trace") or sess.get("live_active")):
                        sess["status"] = "starting"
                        sess["last_action"] = f"Opening {site}"
                    else:
                        sess["status"] = "running"
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
                    already = any(
                        name in (t.get("text") or "") for t in thoughts[-3:]
                    )
                    if not already:
                        thoughts.append(
                            {
                                "at": _now(),
                                "text": f"{name} is acting — reading {site}…",
                                "kind": "thinking",
                            }
                        )
                        sess["live_thoughts"] = thoughts[-24:]
                    refresh_agent_phase()
                    try:
                        async with _BROWSER_SEMAPHORE:
                            raise_if_killed(study)
                            sess["status"] = "running"
                            refresh_agent_phase()
                            agent_warm = None
                            if (
                                not warm_used
                                and warm_opening is not None
                                and str(task.get("site_key") or "product") == "product"
                            ):
                                agent_warm = warm_opening
                                warm_used = True
                            run = await run_browser_agent(
                                study_id=study.id,
                                agent_id=agent_id,
                                url=site,
                                task_prompt=task.get("prompt") or task.get("title") or "",
                                persona=persona,
                                segment=study.segment,
                                on_step=lambda step: _on_agent_step(agent_id, step),
                                bb_session=None,
                                local=force_local_browser,
                                warm=agent_warm,
                            )
                        sess["status"] = "summarizing"
                        refresh_agent_phase()
                        log_activity(
                            study,
                            "agent_summarize",
                            f"{persona.get('name')} session done — writing feedback",
                            agent_id=agent_id,
                        )
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
                            step["outcome"] = outcomes.get(step.get("step")) or "neutral"
                        result = {**run, **feedback, "mode": "browser"}
                    except Exception as exc:  # noqa: BLE001
                        sess["status"] = "error"
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
                            run = await run_browser_agent(
                                study_id=study.id,
                                agent_id=agent_id,
                                url=task.get("site_url") or study.url,
                                task_prompt=task.get("prompt") or task.get("title") or "",
                                persona=persona,
                                segment=study.segment,
                                on_step=lambda step: _on_agent_step(agent_id, step),
                                bb_session=None,
                                local=False,
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
                                step["outcome"] = outcomes.get(step.get("step")) or "neutral"
                            result = {**run, **feedback, "mode": "browser_retry"}
                            result["browser_error"] = (str(exc) or repr(exc))[:300]
                        except Exception as retry_exc:  # noqa: BLE001
                            log_activity(
                                study,
                                "agent_error",
                                f"{persona.get('name')} Browserbase retry failed — snapshot fallback",
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
                            result["browser_error"] = (str(retry_exc) or repr(retry_exc))[:300]

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
                await asyncio.gather(*[_run_one(t) for t in study.tasks])
                if warm_opening is not None and not warm_used:
                    from mvp.browser_agent import close_warm_opening

                    await close_warm_opening(warm_opening)
                    warm_opening = None

        order = {t.get("id"): i for i, t in enumerate(study.tasks)}
        study.agent_results.sort(key=lambda r: order.get(r.get("task_id"), 99))

        # NOTE: do not early-return while status=="running". That aborted every
        # successful local/Browserbase study before the executive summary and
        # left the UI stuck at "N/N done" forever. GCP fleet detach returns
        # earlier in the fleet branch.

        touch("Writing executive summary")
        if study.summary and study.summary.get("headline"):
            # Already written by fleet finisher.
            pass
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
        study.summary["site_summary"] = site_summary
        if study.access_backend:
            study.summary["access_backend"] = study.access_backend
        if study.browserbase_session_url:
            study.summary["browserbase_session_url"] = study.browserbase_session_url
        if study.auth_status:
            study.summary["auth_status"] = study.auth_status
        if study.auth_blocker:
            study.summary["auth_blocker"] = study.auth_blocker
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
        study.kill_requested = True
        study.status = "abandoned"
        study.phase = "Killed"
        study.error = "Killed by operator"
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
        }
    )


def persist_study(study: StudyState) -> None:
    """Best-effort write of study state to GCS so Vercel clients can reconnect."""
    try:
        from mvp.gcs_store import write_study_state
        from mvp.opening_shot import drop_inline_shots

        write_study_state(study.id, drop_inline_shots(study_to_dict(study)))
    except Exception as exc:  # noqa: BLE001
        print(f"persist_study failed for {study.id}: {exc!r}", flush=True)


def load_study_from_gcs(study_id: str) -> dict[str, Any] | None:
    try:
        from mvp.gcs_store import normalize_study_display, read_study_state

        data = read_study_state(study_id)
        if isinstance(data, dict):
            return normalize_study_display(data)
        return None
    except Exception:
        return None
