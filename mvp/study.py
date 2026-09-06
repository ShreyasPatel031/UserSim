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

IS_VERCEL_ENV = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
USE_LIVE_BROWSER = os.environ.get("MVP_VERCEL_BROWSER", "").lower() in ("1", "true", "yes")
QUICK_MODE = os.environ.get("MVP_QUICK", "").lower() in ("1", "true", "yes")
SNAPSHOT_FORCE = os.environ.get("MVP_SNAPSHOT_ONLY", "").lower() in ("1", "true", "yes")


def _fleet_preferred() -> bool:
    try:
        from mvp.gcp_fleet import gcp_fleet_enabled

        return gcp_fleet_enabled()
    except Exception:
        return False


# Snapshot-only when forced/quick, or on Vercel when the GCP seed fleet is unavailable.
SNAPSHOT_ONLY = SNAPSHOT_FORCE or QUICK_MODE or (
    IS_VERCEL_ENV and not USE_LIVE_BROWSER and not _fleet_preferred()
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

# Live Browserbase / local Chromium sessions.
_BROWSER_SEMAPHORE = asyncio.Semaphore(
    int(
        os.environ.get(
            "MVP_BROWSER_CONCURRENCY",
            "8" if IS_VERCEL_ENV else "2",
        )
    )
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


def log_activity(study: StudyState, kind: str, message: str, **extra: Any) -> None:
    study.activity_log.append(
        {"at": _now(), "kind": kind, "message": message, **extra}
    )
    if len(study.activity_log) > 250:
        study.activity_log = study.activity_log[-250:]
    study.updated_at = _now()


def _ordered_live_sessions(study: StudyState) -> list[dict[str, Any]]:
    order = {t.get("id"): i for i, t in enumerate(study.tasks)}
    sessions = list(study.live_sessions.values())
    sessions.sort(key=lambda s: order.get(s.get("agent_id"), 99))
    return sessions


async def _prefetch_browser_sessions(n: int) -> list[Any]:
    """Stagger Browserbase session creates so the first N agents can start together."""
    if n <= 0:
        return []
    from capability.browserbase_client import create_session

    interval = float(os.environ.get("BROWSERBASE_CREATE_INTERVAL_S", "13"))
    sessions: list[Any] = []
    for i in range(n):
        if i:
            await asyncio.sleep(interval)
        sessions.append(await asyncio.to_thread(create_session, proxies=False, keep_alive=False))
    return sessions


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
        task_count = int(os.environ.get("MVP_TASK_COUNT", "6"))
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
    return list(data.get("tasks") or [])


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

    try:
        log_activity(study, "phase", "Study queued")
        touch("Understanding context of product", "running")
        log_activity(study, "fetch", f"Understanding context of {study.url}")
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
        if study.test_mode:
            study.competitors = []
            log_activity(study, "plan", "Smoke mode — product site only, skipping rivals")
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
        if not study.test_mode and not study.competitors and site_summary:
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
            }

        touch(
            f"Live browser agents — 0/{len(study.tasks)} done · {len(study.tasks)} active · 0 queued · 0 steps"
        )
        done_count = 0

        def refresh_agent_phase() -> None:
            touch(_agent_phase_label(study))

        if SNAPSHOT_ONLY and not _fleet_preferred():
            log_activity(
                study,
                "agents",
                f"Running {len(study.tasks)} persona simulations (Vercel snapshot mode)",
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

            workers = min(
                8,
                len(study.tasks),
                int(os.environ.get("MVP_GCP_WORKERS", "8")),
            )
            log_activity(
                study,
                "agents",
                f"Launching GCP seed-image fleet — headed Chromium, {workers}/VM, copies self-delete",
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
                if "warm seed" in low or "on warm seed" in low:
                    hint = "Starting warm seed…"
                elif "spot copy" in low or "creating" in low and "spot" in low:
                    hint = "Provisioning GCP Spot copy…"
                elif "booting" in low or "polling" in low:
                    hint = "Seed booting — waiting for first frame…"
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
                sess["last_action"] = "Starting warm seed…"

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
            # Prefer GCP fleet above; local Chromium only when fleet disabled.
            force_local = (
                os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower()
                in {"1", "true", "yes"}
                or not IS_VERCEL_ENV
            )
            force_local_browser = force_local
            pool = min(
                len(study.tasks),
                int(
                    os.environ.get(
                        "MVP_BROWSER_CONCURRENCY",
                        "2" if force_local_browser else ("8" if IS_VERCEL_ENV else "2"),
                    )
                ),
            )
            prefetched_sessions: list[Any] = []
            if pool and not force_local_browser:
                log_activity(
                    study,
                    "browser",
                    f"Preparing {pool} browser sessions (Browserbase)",
                )
                touch(f"Preparing browser sessions — 0/{pool} ready")
                try:
                    prefetched_sessions = await _prefetch_browser_sessions(pool)
                except Exception as exc:  # noqa: BLE001
                    if IS_VERCEL_ENV:
                        use_live_browser = False
                        force_local_browser = False
                        log_activity(
                            study,
                            "browser",
                            f"Browserbase unavailable ({str(exc)[:160]}) — "
                            "using Vertex Gemini snapshots on GCP",
                        )
                        touch("Live browser unavailable — Vertex snapshot agents")
                    else:
                        use_live_browser = True
                        force_local_browser = True
                        log_activity(
                            study,
                            "browser",
                            f"Browserbase unavailable ({str(exc)[:160]}) — "
                            "using headed local Chromium",
                        )
                        touch("Browserbase unavailable — headed Chromium agents")
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
                for i, _ in enumerate(prefetched_sessions, start=1):
                    log_activity(study, "browser", f"Browser session {i}/{pool} ready")
                    touch(f"Preparing browser sessions — {i}/{pool} ready")
                prefetch_q: asyncio.Queue[Any] = asyncio.Queue()
                for session in prefetched_sessions:
                    await prefetch_q.put(session)

                log_activity(study, "agents", f"Launching {len(study.tasks)} live browser agents")

                async def _on_agent_step(agent_id: str, step: dict[str, Any]) -> None:
                    sess = study.live_sessions.get(agent_id)
                    if not sess:
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
                    if on_update:
                        try:
                            on_update(study, event="progress")
                        except TypeError:
                            on_update(study)
                        except Exception:
                            pass
                    log_activity(
                        study,
                        "agent_step",
                        f"{sess.get('persona_name')}: step {step.get('step')} — {step.get('action', '')[:120]}",
                        agent_id=agent_id,
                        step=step.get("step"),
                    )

                async def _take_prefetched_session() -> Any | None:
                    try:
                        return prefetch_q.get_nowait()
                    except asyncio.QueueEmpty:
                        return None

                async def _run_one(task: dict[str, Any]) -> dict[str, Any]:
                    nonlocal done_count
                    from mvp.browser_agent import run_browser_agent

                    persona = persona_by_id.get(task.get("persona_id")) or study.personas[0]
                    agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
                    sess = study.live_sessions.setdefault(
                        agent_id,
                        {
                            "agent_id": agent_id,
                            "persona_name": persona.get("name"),
                            "status": "starting",
                            "trace": [],
                        },
                    )
                    sess["status"] = "starting"
                    prefetched = await _take_prefetched_session()
                    log_activity(
                        study,
                        "agent_start",
                        f"{persona.get('name')} launching browser",
                        agent_id=agent_id,
                        persona_name=persona.get("name"),
                    )
                    refresh_agent_phase()
                    try:
                        async with _BROWSER_SEMAPHORE:
                            sess["status"] = "running"
                            refresh_agent_phase()
                            run = await run_browser_agent(
                                study_id=study.id,
                                agent_id=agent_id,
                                url=task.get("site_url") or study.url,
                                task_prompt=task.get("prompt") or task.get("title") or "",
                                persona=persona,
                                segment=study.segment,
                                on_step=lambda step: _on_agent_step(agent_id, step),
                                bb_session=None if force_local_browser else prefetched,
                                local=force_local_browser,
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
                        log_activity(
                            study,
                            "agent_error",
                            f"{persona.get('name')} browser failed — retrying with local Chromium",
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
                                local=True,
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
                            result = {**run, **feedback, "mode": "local_browser"}
                            result["browser_error"] = (str(exc) or repr(exc))[:300]
                        except Exception as local_exc:  # noqa: BLE001
                            log_activity(
                                study,
                                "agent_error",
                                f"{persona.get('name')} local browser failed — snapshot fallback",
                                agent_id=agent_id,
                                error=str(local_exc)[:200],
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
                            result["browser_error"] = (str(local_exc) or repr(local_exc))[:300]

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
                    sess["trace"] = result.get("trace") or sess.get("trace") or []
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

        order = {t.get("id"): i for i, t in enumerate(study.tasks)}
        study.agent_results.sort(key=lambda r: order.get(r.get("task_id"), 99))

        # Fleet detach on Vercel: Spot copies finish + write summary themselves.
        if study.status == "running":
            persist_study(study)
            return

        touch("Writing executive summary")
        if study.summary and study.summary.get("headline"):
            # Already written by fleet finisher.
            pass
        elif QUICK_MODE or study.test_mode:
            if study.agent_results:
                first = study.agent_results[0]
                study.summary = {
                    "headline": (first.get("quote") or first.get("product_feedback") or "Quick run")[:200],
                    "top_friction": (first.get("friction_points") or [])[:3],
                    "segment_fit_score": 7,
                    "quick_mode": True,
                }
            else:
                study.summary = {
                    "headline": "Quick run finished with no agent results",
                    "top_friction": [],
                    "segment_fit_score": 0,
                    "quick_mode": True,
                }
        else:
            log_activity(study, "summary", "Synthesizing executive summary from all sessions")
            study.summary = await synthesize_summary(
                url=study.url,
                segment=study.segment,
                site_summary=site_summary,
                agent_results=study.agent_results,
            )
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
    except Exception as exc:  # noqa: BLE001
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


def study_to_dict(study: StudyState) -> dict[str, Any]:
    return {
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
        "test_mode": study.test_mode,
        "backend": study.backend,
        "email": study.email,
    }


def persist_study(study: StudyState) -> None:
    """Best-effort write of study state to GCS so Vercel clients can reconnect."""
    try:
        from mvp.gcs_store import write_study_state

        write_study_state(study.id, study_to_dict(study))
    except Exception:
        pass


def load_study_from_gcs(study_id: str) -> dict[str, Any] | None:
    try:
        from mvp.gcs_store import read_study_state

        return read_study_state(study_id)
    except Exception:
        return None
