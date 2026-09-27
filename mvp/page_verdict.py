"""One task-success number: what each run's final page proves.

The report counted a run as finished when the agent itself stopped with
"done", while the Gemini judge grades the final screenshot. Kolanut study
4d6edbd5 showed 2/8 on the report page and 5/8 from the judge: four agents
had a full outreach draft in the editor but never said done, and one said
done on an Ask Kolanut answer the page did not back up.

After all agents finish, every run's final PNG, final URL and final DOM go
through the judge's own prompt (``e2e2_gates.judge_goal_screenshot``) once.
The verdict is stored on the run as ``page_verdict`` and the report's task
completion reads it, so the page the user opens and the grader look at the
same evidence with the same question. The agent's own claim stays on the run
as ``agent_claimed_done``.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any


def _runs_by_id(study: Any) -> dict[str, dict[str, Any]]:
    """Merged rows the grader reads: live session fields, then agent results on top."""
    rows: dict[str, dict[str, Any]] = {}
    live = getattr(study, "live_sessions", None) or {}
    for row in list(live.values()) if isinstance(live, dict) else list(live or []):
        if isinstance(row, dict) and (row.get("agent_id") or row.get("task_id")):
            rows[str(row.get("agent_id") or row.get("task_id"))] = dict(row)
    for row in getattr(study, "agent_results", None) or []:
        if isinstance(row, dict) and (row.get("agent_id") or row.get("task_id")):
            aid = str(row.get("agent_id") or row.get("task_id"))
            rows[aid] = {**rows.get(aid, {}), **row}
    return rows


def verdict_success(run: dict[str, Any]) -> bool | None:
    """True/False from the stored final-page verdict, None when there is none."""
    verdict = run.get("page_verdict") if isinstance(run, dict) else None
    if isinstance(verdict, dict) and isinstance(verdict.get("goal_reached"), bool):
        return bool(verdict["goal_reached"])
    return None


async def apply_page_verdicts(study: Any, *, timeout_s: float | None = None) -> int:
    """Judge every run's final page once; returns how many verdicts were written."""
    if os.environ.get("MVP_PAGE_VERDICT", "1") == "0":
        return 0
    from mvp.e2e2_gates import coerce_verdict, final_dom_of, final_url_of, judge_goal_screenshot
    from mvp.paths import MVP_RUNS_DIR

    merged = _runs_by_id(study)
    results = [r for r in (getattr(study, "agent_results", None) or []) if isinstance(r, dict)]
    sem = asyncio.Semaphore(int(os.environ.get("MVP_PAGE_VERDICT_CONCURRENCY", "12")))
    budget = float(timeout_s or os.environ.get("MVP_PAGE_VERDICT_TIMEOUT_S", "45"))
    written = 0

    async def one(result: dict[str, Any]) -> None:
        nonlocal written
        aid = str(result.get("agent_id") or result.get("task_id") or "")
        run = merged.get(aid, result)
        task = str(run.get("task_prompt") or run.get("task_title") or "")
        start = str(run.get("site_url") or getattr(study, "url", "") or "")
        path = MVP_RUNS_DIR / str(getattr(study, "id", "")) / aid / "screenshots" / "final.png"
        shot = str(run.get("final_screenshot_url") or run.get("final_screenshot") or "")
        if not shot or not path.is_file():
            verdict = coerce_verdict(
                {"goal_reached": False, "still_on_opening_screen": True, "reason": "no final screenshot"}
            )
        else:
            png = path.read_bytes()
            async with sem:
                try:
                    raw = await asyncio.wait_for(
                        asyncio.to_thread(
                            judge_goal_screenshot,
                            png,
                            task=task,
                            start_url=start,
                            final_url=final_url_of(run),
                            dom=final_dom_of(run),
                        ),
                        timeout=budget,
                    )
                    verdict = coerce_verdict(raw)
                except Exception as exc:  # noqa: BLE001
                    # No verdict: the report falls back to the agent's own stop.
                    print(f"[page_verdict] {aid} judge failed: {exc!r}"[:200], flush=True)
                    return
        verdict["checked_at_ts"] = time.time()
        result.setdefault("agent_claimed_done", bool(result.get("completed")))
        result["page_verdict"] = verdict
        result["completed"] = bool(verdict.get("goal_reached"))
        written += 1

    await asyncio.gather(*(one(r) for r in results))
    print(f"[page_verdict] {written}/{len(results)} final pages judged", flush=True)
    return written
