"""Canonical full-study shape (see docs/E2E_TEST.md)."""

from __future__ import annotations

from typing import Any

from mvp.fast_plan import PERSONA_COUNT, RIVAL_COUNT, TASK_COUNT, compare_plan_from_url

E2E_DOC = "docs/E2E_TEST.md"


class E2EStudyRejected(ValueError):
    """A study start request does not meet the full e2e definition."""


def _reject(message: str) -> None:
    raise E2EStudyRejected(f"{message} See {E2E_DOC}.")


def reject_disallowed_flags(*, test_mode: bool = False, skip_competitors: bool = False) -> None:
    if test_mode:
        _reject("Smoke / test_mode studies are not allowed")
    if skip_competitors:
        _reject("Product-only studies (skip_competitors) are not allowed")


def validate_supplied_counts(
    competitors: list[str] | None,
    personas: list[Any] | None,
    tasks: list[Any] | None,
) -> None:
    """Reject partial lists that are non-empty but not exactly the required size."""
    comps = [c.strip() for c in (competitors or []) if str(c).strip()]
    if comps and len(comps) != RIVAL_COUNT:
        _reject(f"Need exactly {RIVAL_COUNT} competitor URLs (3 products total); got {len(comps)}")
    pers = list(personas or [])
    if pers and len(pers) != PERSONA_COUNT:
        _reject(f"Need exactly {PERSONA_COUNT} personas, or omit personas to auto-generate; got {len(pers)}")
    jobs = list(tasks or [])
    if jobs and len(jobs) != TASK_COUNT:
        _reject(f"Need exactly {TASK_COUNT} tasks, or omit tasks to auto-generate; got {len(jobs)}")


def _persona_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(p) for p in (plan.get("personas") or []) if isinstance(p, dict)]


def _task_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    specs = plan.get("task_specs")
    if isinstance(specs, list) and specs:
        return [dict(t) if isinstance(t, dict) else {"prompt": str(t)} for t in specs]
    prompts = plan.get("tasks") or []
    return [{"prompt": str(p)} for p in prompts if str(p).strip()]


async def ensure_full_study_inputs(
    product_url: str,
    competitors: list[str] | None,
    personas: list[Any] | None,
    tasks: list[Any] | None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return exactly 2 competitors, 6 personas, 6 tasks; fill gaps via compare_plan_from_url."""
    validate_supplied_counts(competitors, personas, tasks)
    comps = [c.strip() for c in (competitors or []) if str(c).strip()]
    pers: list[dict[str, Any]] = []
    for p in personas or []:
        if isinstance(p, dict):
            pers.append(dict(p))
        else:
            pers.append({"bio": str(p)})
    jobs: list[dict[str, Any]] = []
    for t in tasks or []:
        if isinstance(t, dict):
            jobs.append(dict(t))
        else:
            jobs.append({"prompt": str(t)})

    need_plan = len(comps) < RIVAL_COUNT or len(pers) < PERSONA_COUNT or len(jobs) < TASK_COUNT
    plan: dict[str, Any] | None = None
    if need_plan:
        plan = await compare_plan_from_url(product_url)
        if not plan or plan.get("mode") != "compare":
            _reject("Could not build a full 3-product × 6-persona × 6-task study plan")
        if len(comps) < RIVAL_COUNT:
            comps = [str(c).strip() for c in (plan.get("competitors") or []) if str(c).strip()]
        if len(pers) < PERSONA_COUNT:
            pers = _persona_rows(plan)
        if len(jobs) < TASK_COUNT:
            jobs = _task_rows(plan)

    if len(comps) != RIVAL_COUNT or len(pers) != PERSONA_COUNT or len(jobs) != TASK_COUNT:
        _reject(
            f"Incomplete study plan (need {RIVAL_COUNT} competitors, {PERSONA_COUNT} personas, "
            f"{TASK_COUNT} tasks; got {len(comps)}, {len(pers)}, {len(jobs)})"
        )
    return comps, pers, jobs


def assert_study_state(study: Any) -> None:
    """After website planning, the study must match the e2e matrix."""
    comps = list(getattr(study, "competitors", None) or [])
    personas = list(getattr(study, "personas", None) or [])
    specs = list(getattr(study, "task_specs", None) or [])
    if specs:
        n_tasks = len(specs)
    else:
        tasks = list(getattr(study, "tasks", None) or [])
        if tasks and all("__" in str(t.get("id") or "") for t in tasks):
            n_tasks = len({str(t.get("id") or "").split("__", 1)[0] for t in tasks})
        else:
            n_tasks = len(tasks)
    if len(comps) != RIVAL_COUNT or len(personas) != PERSONA_COUNT or n_tasks != TASK_COUNT:
        _reject(
            f"Study must have {RIVAL_COUNT} competitors, {PERSONA_COUNT} personas, and "
            f"{TASK_COUNT} tasks before agents run (got {len(comps)}, {len(personas)}, {n_tasks})"
        )
