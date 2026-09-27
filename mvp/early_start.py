"""Start the first agent while the comparison plan is still being written.

The compare plan (3 rivals, 5 personas, 6 tasks) is one ~5-7s model call and
sat entirely on the time-to-first-value path (kolanut TTFV 11.3s on an idle
queue, target 10s). A tiny starter call (~1-2s) names the product, one buyer
who fits it and its core job. That buyer starts on the product (agent
t1__p1__product, on the browser preopened while the URL was submitted) while
the full plan finishes; the full plan is then spliced so the starter buyer is
p1 and the starter job is t1, and the study adopts the running agent instead
of launching it again.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

EARLY_AGENT_ID = "t1__p1__product"

_STARTER = """Reply with JSON only. A buyer is about to try this product.
Product URL: {url}
Page title: {title}
Page text: {text}

Return {{"product": "short product name",
  "persona": {{"name": "first and last name", "role": "job title and company type",
               "bio": "at most 20 words: situation, need, how they judge a tool", "why": "at most 10 words"}},
  "task": "3-8 word task"}}
persona: a realistic target customer for whom this product is the natural fit.
task: the core job this product does for them, an imperative verb and a concrete object (for example
"Identify at-risk customer accounts"), generic enough to try on competing products too. Never a task that
needs the customer's own outside credentials or data (connect or sync a data source, API keys, payment),
and never a pricing task. No quotes."""


def enabled() -> bool:
    return os.environ.get("MVP_EARLY_START", "1").strip().lower() not in {"0", "false", "no"}


async def starter_plan(url: str, *, timeout: float = 6.0) -> dict[str, Any] | None:
    from capability.gemini_config import extract_json, gemini_chat
    from mvp.fast_plan import _page_read

    async def _run() -> dict[str, Any] | None:
        t0 = time.monotonic()
        read = await _page_read(url)
        from mvp.fast_plan import prompt_text, read_rule

        raw = await gemini_chat(
            [{"role": "user", "content": _STARTER.format(
                url=url, title=read.get("title") or "", text=prompt_text(read, 900)
            ) + read_rule()}],
            model=os.environ.get("MVP_FAST_PLAN_MODEL") or "gemini-2.5-flash",
            temperature=0.3,
            json_mode=True,
            max_retries=1,
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            return None
        p = data.get("persona") if isinstance(data.get("persona"), dict) else {}
        task = " ".join(str(data.get("task") or "").replace('"', "").split())[:80]
        if not task or not p.get("name"):
            return None
        from mvp.fast_plan import unique_persona_names

        # A testimonial author on the page is a real customer, not an invented buyer.
        p = unique_persona_names([dict(p)], seed=url, read=read)[0]
        took = round(time.monotonic() - t0, 2)
        print(f"[early] starter {took}s {p.get('name')!r} task={task!r}", flush=True)
        return {
            "product": str(data.get("product") or "")[:60],
            "persona": {
                "name": str(p.get("name") or "")[:60],
                "role": str(p.get("role") or "")[:80],
                "bio": str(p.get("bio") or "")[:200],
                "favors": "product",
                "favors_why": str(p.get("why") or "")[:80],
            },
            "task": task,
            "starter_s": took,
        }

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[early] starter skipped: {exc!r}", flush=True)
        return None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 3}


def splice_plan(plan: dict[str, Any], starter: dict[str, Any]) -> dict[str, Any]:
    """Make the starter buyer p1 and the starter job t1 of the full plan.

    The starter buyer replaces the plan's first product-fit buyer (the plan
    keeps one per rival). The starter job replaces the most similar plan job,
    else the first product-favoring one, so the task mix still favors each
    site at least once.
    """
    plan = dict(plan)
    persona = dict(starter["persona"])
    personas = [dict(p) for p in plan.get("personas") or [] if isinstance(p, dict)]
    drop = next((i for i, p in enumerate(personas) if p.get("favors") == "product"), None)
    if drop is None and personas:
        drop = len(personas) - 1
    if drop is not None:
        personas.pop(drop)
    from mvp.fast_plan import unique_persona_names

    # Both calls tend to invent the same few names (Alex Chen twice in one study):
    # the running early buyer keeps its name, a plan persona that repeats it is renamed.
    plan["personas"] = unique_persona_names([persona] + personas, seed=str(plan.get("product") or ""), keep_first=1)

    task = starter["task"]
    specs = [dict(t) for t in plan.get("task_specs") or [] if isinstance(t, dict)]
    mine = _words(task)
    best, best_overlap = None, 0.0
    for i, t in enumerate(specs):
        theirs = _words(str(t.get("prompt") or ""))
        overlap = len(mine & theirs) / max(1, len(mine | theirs))
        if overlap > best_overlap:
            best, best_overlap = i, overlap
    if best is None or best_overlap < 0.34:
        best = next((i for i, t in enumerate(specs) if t.get("favors") == "product"), None)
    if best is None and specs:
        best = len(specs) - 1
    favors, why = "product", persona.get("favors_why") or ""
    if best is not None:
        # The starter job takes over the replaced job's tag, so each site keeps its two jobs.
        gone = specs.pop(best)
        favors, why = gone.get("favors") or favors, gone.get("favors_why") or why
    spec = {"prompt": task, "favors": favors, "favors_why": why}
    plan["task_specs"] = [spec] + specs
    plan["tasks"] = [t["prompt"] for t in plan["task_specs"]]
    if not plan.get("product"):
        plan["product"] = starter.get("product") or ""
    return plan


class EarlySteps:
    """on_step for the early agent: record steps until the study adopts it, then forward."""

    def __init__(self, study: Any, agent_id: str) -> None:
        self.study = study
        self.agent_id = agent_id
        self.buffer: list[dict[str, Any]] = []
        self.forward: Any = None

    async def __call__(self, step: dict[str, Any]) -> None:
        if self.forward is not None:
            await self.forward(self.agent_id, step)
            return
        self.buffer.append(step)
        if not isinstance(step, dict) or step.get("progress_only"):
            return
        sess = self.study.live_sessions.get(self.agent_id)
        if not isinstance(sess, dict):
            return
        trace = list(sess.get("trace") or [])
        by_step = {s.get("step"): i for i, s in enumerate(trace) if isinstance(s, dict)}
        if step.get("step") in by_step:
            trace[by_step[step["step"]]] = step
        else:
            trace.append(step)
        sess["trace"] = trace
        sess["num_steps"] = len(trace)
        sess["last_action"] = step.get("action") or ""
        action = str(step.get("action") or "")
        if not sess.get("first_action_at_ts") and action and not action.lower().startswith("open"):
            from mvp.a11y_agent import apply_gate_fields
            from mvp.study import note_first_value

            apply_gate_fields(sess, first_action_at_ts=time.time())
            note_first_value(self.study, sess)

    async def adopt(self, forward: Any) -> None:
        """Replay what happened before adoption through the study's handler, then go live."""
        pending, self.buffer = self.buffer, []
        for step in pending:
            try:
                await forward(self.agent_id, step)
            except Exception as exc:  # noqa: BLE001
                print(f"[early] replay step failed: {exc!r}", flush=True)
        self.forward = forward


def start_early_agent(study: Any, url: str, starter: dict[str, Any]) -> None:
    """Launch t1__p1__product now; the study picks the task up from study.early_runs."""
    from mvp.a11y_agent import A11yBoot, run_a11y_agent

    p = starter["persona"]
    persona = {
        "id": "p1",
        "name": p.get("name") or "Buyer",
        "bio": p.get("bio") or "",
        "occupation": p.get("role") or "",
        "age_range": "",
        "location": "Remote",
        "goals": ["Decide which product fits", "Notice what is confusing"],
        "favors": "product",
        "favors_why": p.get("favors_why") or "",
    }
    task = {
        "id": EARLY_AGENT_ID,
        "title": starter["task"][:80],
        "prompt": starter["task"],
        "persona_id": "p1",
        "difficulty_hint": "medium",
        "site_key": "product",
        "site_url": url,
        "site_label": "Product",
    }
    # Visible right away; the full plan replaces these lists and keeps this row.
    study.personas = [persona]
    study.tasks = [task]
    study.live_sessions[EARLY_AGENT_ID] = {
        "agent_id": EARLY_AGENT_ID,
        "persona_id": "p1",
        "persona_name": persona["name"],
        "persona_bio": persona["bio"],
        "task_id": EARLY_AGENT_ID,
        "task_title": task["title"],
        "task_prompt": task["prompt"],
        "site_key": "product",
        "site_url": url,
        "site_label": "Product",
        "status": "running",
        "trace": [],
        "num_steps": 0,
        "live_thoughts": [],
        "early_start": True,
    }
    steps = EarlySteps(study, EARLY_AGENT_ID)
    boot = A11yBoot(study, None)
    run = asyncio.create_task(
        run_a11y_agent(
            boot=boot,
            study_id=study.id,
            agent_id=EARLY_AGENT_ID,
            url=url,
            task_prompt=task["prompt"],
            persona=persona,
            on_step=steps,
            site_key="product",
            deadline=None,
        )
    )
    study.early_runs = {EARLY_AGENT_ID: run}
    study.early_steps = {EARLY_AGENT_ID: steps}
    study.early_task = dict(task)
    print(f"[early] {EARLY_AGENT_ID} started before the plan: {task['prompt']!r}", flush=True)


def claim(study: Any, agent_id: str) -> tuple[asyncio.Task | None, EarlySteps | None]:
    runs = getattr(study, "early_runs", None) or {}
    task = runs.pop(agent_id, None)
    steps = (getattr(study, "early_steps", None) or {}).pop(agent_id, None)
    return task, steps
