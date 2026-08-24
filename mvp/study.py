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

from google import genai
from google.genai import types

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL as GEMINI_MODEL
from mvp.browser_agent import run_browser_agent
from mvp.page_access import SiteAccessBlockedError, fetch_page_access

# Parallel Gemini calls (rate-limit safe). Not browser sessions.
_AGENT_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("MVP_AGENT_CONCURRENCY", "4")))

# Local Chromium instances. Cap so we don't overload the machine running the study.
_BROWSER_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("MVP_BROWSER_CONCURRENCY", "3")))

_genai_client: genai.Client | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Model did not return JSON")
    return json.loads(match.group(0))


def _gemini_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True,
            project=GCP_PROJECT,
            location=GCP_LOCATION,
            credentials=vertex_credentials(),
        )
    return _genai_client


async def _gemini_chat(
    messages: list[dict[str, str]],
    *,
    model: str = GEMINI_MODEL,
    temperature: float = 0.4,
    max_retries: int = 5,
) -> str:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n".join(m["content"] for m in messages if m["role"] == "user")
    client = _gemini_client()
    for attempt in range(max_retries):
        try:
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system or None,
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )
            return resp.text or ""
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            retryable = "429" in msg or "resource exhausted" in msg or "503" in msg or "500" in msg
            if retryable and attempt < max_retries - 1:
                await asyncio.sleep(min(60.0, 5.0 * (2**attempt)))
                continue
            raise
    raise RuntimeError("Gemini request failed after retries")


@dataclass
class StudyState:
    id: str
    url: str
    segment: str
    status: str = "queued"
    phase: str = "Starting"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    personas: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    agent_results: list[dict[str, Any]] = field(default_factory=list)
    live_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    activity_log: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    error: str | None = None
    access_backend: str | None = None
    browserbase_session_url: str | None = None


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


def _agent_phase_label(study: StudyState) -> str:
    total = len(study.tasks) or 4
    done = len(study.agent_results)
    running = sum(1 for s in study.live_sessions.values() if s.get("status") == "running")
    summarizing = sum(
        1 for s in study.live_sessions.values() if s.get("status") == "summarizing"
    )
    queued = sum(1 for s in study.live_sessions.values() if s.get("status") == "pending")
    steps = sum(int(s.get("num_steps") or 0) for s in study.live_sessions.values())
    active = running + summarizing
    parts = [f"{done}/{total} done", f"{active} active"]
    if queued:
        parts.append(f"{queued} queued")
    parts.append(f"{steps} steps")
    return "Live browser agents — " + " · ".join(parts)


STUDIES: dict[str, StudyState] = {}


async def generate_plan(url: str, segment: str, page_text: str) -> dict[str, Any]:
    prompt = f"""You are designing a synthetic user-research study for a product team.

Target site: {url}
Customer segment: {segment}

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
      "goals": ["goal1", "goal2"]
    }}
  ],
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
- Derive what the product does ONLY from the page content above. Never infer it from the
  domain name or guess an industry. If the page is about AI infrastructure, do not write
  tasks about branding or design.
- Every task must target something that actually appears on the page (a real nav item,
  section, CTA, or feature name). Quote or reference that element in the task prompt.
- If the page has no pricing page, do not create a "find the pricing page" task. Instead
  write the task the persona would really attempt given what IS on the page.
- Create exactly 4 personas that fit the segment (diverse within the segment).
- Create exactly 4 tasks (one primary task per persona)."""
    raw = await _gemini_chat(
        [
            {
                "role": "system",
                "content": (
                    "You output valid JSON only. You never invent product features or "
                    "industries that are absent from the supplied page content."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    return _extract_json(raw)


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
        raw = await _gemini_chat(
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
        raw = await _gemini_chat(
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
    raw = await _gemini_chat(
        [
            {"role": "system", "content": "You are a senior UX researcher. JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return _extract_json(raw)


async def run_study(study_id: str) -> None:
    study = STUDIES[study_id]

    def touch(phase: str, status: str | None = None) -> None:
        study.phase = phase
        if status:
            study.status = status
        study.updated_at = _now()

    try:
        log_activity(study, "phase", "Study queued")
        touch("Fetching site", "running")
        log_activity(study, "fetch", f"Fetching {study.url}")
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

        touch("Generating personas & tasks")
        log_activity(study, "plan", "Reading page content and generating personas & tasks")
        plan = await generate_plan(study.url, study.segment, page_text)
        study.personas = plan.get("personas") or []
        study.tasks = plan.get("tasks") or []
        agent_cap = int(os.environ.get("MVP_AGENT_COUNT", "4"))
        if agent_cap > 0 and len(study.tasks) > agent_cap:
            study.tasks = study.tasks[:agent_cap]
            used_persona_ids = {t.get("persona_id") for t in study.tasks}
            study.personas = [p for p in study.personas if p.get("id") in used_persona_ids][
                :agent_cap
            ]
        site_summary = plan.get("site_summary", "")
        if site_summary:
            log_activity(study, "plan", f"Site: {site_summary}")
        for persona in study.personas:
            log_activity(
                study,
                "persona",
                f"Persona: {persona.get('name')}",
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
                "status": "pending",
                "trace": [],
                "num_steps": 0,
            }

        touch(f"Live browser agents — 0/{len(study.tasks)} done · 0 active · {len(study.tasks)} queued · 0 steps")
        log_activity(study, "agents", f"Launching {len(study.tasks)} live browser agents")
        done_count = 0

        def refresh_agent_phase() -> None:
            touch(_agent_phase_label(study))

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
            log_activity(
                study,
                "agent_step",
                f"{sess.get('persona_name')}: step {step.get('step')} — {step.get('action', '')[:120]}",
                agent_id=agent_id,
                step=step.get("step"),
            )

        async def _run_one(task: dict[str, Any]) -> dict[str, Any]:
            nonlocal done_count
            persona = persona_by_id.get(task.get("persona_id")) or study.personas[0]
            agent_id = task.get("id") or f"agent_{uuid.uuid4().hex[:8]}"
            sess = study.live_sessions.setdefault(
                agent_id,
                {
                    "agent_id": agent_id,
                    "persona_name": persona.get("name"),
                    "status": "pending",
                    "trace": [],
                },
            )
            log_activity(
                study,
                "agent_start",
                f"{persona.get('name')} started browsing",
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
                        url=study.url,
                        task_prompt=task.get("prompt") or task.get("title") or "",
                        persona=persona,
                        segment=study.segment,
                        on_step=lambda step: _on_agent_step(agent_id, step),
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
                    f"{persona.get('name')} browser failed — using snapshot fallback",
                    agent_id=agent_id,
                    error=str(exc)[:200],
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
                result["browser_error"] = (str(exc) or repr(exc))[:300]

            result["persona_id"] = persona.get("id")
            result["persona_name"] = persona.get("name")
            result["persona_bio"] = persona.get("bio")
            result["task_id"] = task.get("id")
            result["task_title"] = task.get("title")
            result["task_prompt"] = task.get("prompt")
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

        touch("Writing executive summary")
        log_activity(study, "summary", "Synthesizing executive summary from all sessions")
        study.summary = await synthesize_summary(
            url=study.url,
            segment=study.segment,
            site_summary=site_summary,
            agent_results=study.agent_results,
        )
        study.summary["site_summary"] = site_summary
        if study.access_backend:
            study.summary["access_backend"] = study.access_backend
        if study.browserbase_session_url:
            study.summary["browserbase_session_url"] = study.browserbase_session_url
        touch("Complete", "complete")
        log_activity(study, "complete", "Study complete")
    except SiteAccessBlockedError as exc:
        study.status = "error"
        study.error = (str(exc) or repr(exc))[:500]
        study.phase = "Site blocked"
        study.updated_at = _now()
    except Exception as exc:  # noqa: BLE001
        study.status = "error"
        study.error = (str(exc) or repr(exc))[:500]
        study.phase = "Failed"
        study.updated_at = _now()


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
    }
