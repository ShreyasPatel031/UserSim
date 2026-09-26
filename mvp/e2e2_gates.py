"""Strict e2e pass gates.

Startup gates (agent count, first real screenshot, vision YES, elapsed) stay.
They are not sufficient. A study passes only when every gate below passes.

Product task completion is judged on the final state of each product run:
the URL, DOM, or canvas moved toward the goal, and a vision judge confirmed
the final screenshot shows the goal. A run that never leaves the first screen
or ends on the opening frame is a failure. It stays in the denominator.
Competitor runs are reported separately and do not count toward that gate.
Browserbase and concurrency losses count against the run. They are not dropped.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from mvp.report_insights import changed_page_state

PASS_AGENT_BAR = 24
PRODUCT_SUCCESS_MIN = 0.50
RUN_ISSUE_MAX = 0.25
DEFAULT_MAX_ELAPSED_S = 360.0
DEFAULT_FIRST_SHOT_S = 5.0

# Bland-style /report shell (same layout as /blandai).
_REPORT_MARKERS = (
    'data-tab="analytics"',
    'data-tab="traces"',
    'id="analytics-root"',
    'id="tab-traces"',
    "Overview",
    "Trace drill-down",
)

_HOMEPAGE_EXCUSE_RE = re.compile(
    r"first screen|home\s*page|homepage|landing page|"
    r"did(?:n'?t| not) leave|never left|did(?:n'?t| not) get past|"
    r"no product run got past|stopped on the (?:first|home)|"
    r"opening frame|opening screen|never left the homepage",
    re.I,
)

_BB_LOSS_RE = re.compile(
    r"browserbase|concurrency cap|too many requests|\b429\b|"
    r"rate limit|create timeout|browser slot|waiting for a browser",
    re.I,
)


def _gate(
    gate_id: str,
    name: str,
    value: object,
    threshold: str,
    ok: bool,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "name": name,
        "value": value,
        "threshold": threshold,
        "pass": bool(ok),
        "detail": detail,
    }


def iter_runs(study: dict[str, Any]) -> list[dict[str, Any]]:
    """Agent rows from the study. Later agent_results overwrite live sessions."""
    by_id: dict[str, dict[str, Any]] = {}
    live = study.get("live_sessions") or {}
    items = list(live.values()) if isinstance(live, dict) else list(live or [])
    for row in items:
        if isinstance(row, dict):
            aid = str(row.get("agent_id") or row.get("task_id") or "")
            if aid:
                by_id[aid] = dict(row)
    for row in study.get("agent_results") or []:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("agent_id") or row.get("task_id") or "")
        if not aid:
            continue
        by_id[aid] = {**by_id.get(aid, {}), **row}
    return list(by_id.values())


def _product_url(study: dict[str, Any]) -> str:
    return str(study.get("url") or "")


def is_product_run(run: dict[str, Any]) -> bool:
    return str(run.get("site_key") or "product") == "product"


def _start_url(run: dict[str, Any], study: dict[str, Any]) -> str:
    return str(run.get("site_url") or _product_url(study) or "")


def _final_shot(run: dict[str, Any]) -> dict[str, Any] | None:
    last = None
    for step in run.get("trace") or []:
        if isinstance(step, dict) and step.get("screenshot_url") and isinstance(step.get("step"), int):
            last = step
    return last


def ended_on_opening_frame(run: dict[str, Any]) -> bool:
    """Final screenshot is missing, a placeholder, or the opening frame (step 0)."""
    final = _final_shot(run)
    if final is None:
        return True
    if final.get("opening_placeholder") or final.get("opening_blankish"):
        return True
    try:
        step_n = int(final.get("step") or 0)
    except (TypeError, ValueError):
        step_n = 0
    return step_n <= 0


def never_left_first_screen(run: dict[str, Any], start_url: str) -> bool:
    """No URL, DOM-text, or canvas change away from the page the run opened."""
    return not changed_page_state(run, start_url)


def beyond_first_screen(run: dict[str, Any], start_url: str) -> bool:
    """The run left the opening state and did not finish on the opening frame."""
    if ended_on_opening_frame(run):
        return False
    if never_left_first_screen(run, start_url):
        return False
    return True


def is_browserbase_or_concurrency_loss(run: dict[str, Any]) -> bool:
    """Infrastructure loss. Do not match ordinary mode=browser or session URLs."""
    issue = run.get("run_issue") if isinstance(run.get("run_issue"), dict) else {}
    blob = " ".join(
        [
            str(run.get("browser_error") or ""),
            str(issue.get("kind") or ""),
            str(issue.get("reason") or ""),
            str(run.get("last_action") or ""),
            str(run.get("error") or ""),
        ]
    )
    return bool(_BB_LOSS_RE.search(blob))


def is_homepage_excuse(text: str) -> bool:
    return bool(_HOMEPAGE_EXCUSE_RE.search(text or ""))


def _insights(study: dict[str, Any]) -> dict[str, Any]:
    summary = study.get("summary") if isinstance(study.get("summary"), dict) else {}
    insights = summary.get("insights") if isinstance(summary.get("insights"), dict) else {}
    return insights


def _run_issues(study: dict[str, Any]) -> list[dict[str, Any]]:
    insights = _insights(study)
    rows = insights.get("run_issues")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return []


def _task_titles(study: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for task in study.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        raw = str(task.get("title") or task.get("prompt") or "").strip()
        if "(vs " in raw:
            continue
        if not raw or raw in seen:
            continue
        seen.add(raw)
        titles.append(raw)
    return titles


def product_run_succeeded(
    run: dict[str, Any],
    start_url: str,
    *,
    vision_goal: bool,
) -> bool:
    """Final-state success. Opening-frame and first-screen runs never pass."""
    if is_browserbase_or_concurrency_loss(run):
        return False
    if not beyond_first_screen(run, start_url):
        return False
    return bool(vision_goal)


def _screenshot_ok(url: str, loader: Callable[[str], bool] | None) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    if loader is None:
        return False
    try:
        return bool(loader(text))
    except Exception:
        return False


def _evidence_ok(
    evidence: dict[str, Any],
    runs_by_id: dict[str, dict[str, Any]],
    study: dict[str, Any],
    loader: Callable[[str], bool] | None,
) -> bool:
    aid = str(evidence.get("agent_id") or "")
    if not aid or not isinstance(evidence.get("step"), int):
        return False
    if not _screenshot_ok(str(evidence.get("screenshot_url") or ""), loader):
        return False
    run = runs_by_id.get(aid)
    if not run:
        return False
    return beyond_first_screen(run, _start_url(run, study))


def _qualifying_claims(
    claims: list[Any],
    runs_by_id: dict[str, dict[str, Any]],
    study: dict[str, Any],
    loader: Callable[[str], bool] | None,
) -> list[dict[str, Any]]:
    out = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        evidence = [e for e in (claim.get("evidence") or []) if isinstance(e, dict)]
        if any(_evidence_ok(ev, runs_by_id, study, loader) for ev in evidence):
            out.append(claim)
    return out


def judge_goal_screenshot(png: bytes, *, task: str, start_url: str) -> dict[str, Any]:
    """Vision judge: does this final screenshot show the task goal was reached?"""
    from mvp.e2e_ui_run import gemini_vision_json

    prompt = f"""You are a strict QA vision judge for the FINAL screenshot of a browser agent.

Task goal: {task or "unknown"}
Page the run opened on: {start_url or "unknown"}

PASS goal_reached=true only when the pixels show the goal was actually reached
(for example the requested issue form or created issue, a drawing on the canvas,
an export/share dialog, or the specific destination the task asked for).

FAIL goal_reached=false when:
- This is still the opening screen, marketing homepage, or unchanged first canvas
- The agent only scrolled or hovered the page it opened on
- You cannot tell the goal was reached

Return JSON only:
{{
  "goal_reached": true/false,
  "still_on_opening_screen": true/false,
  "reason": "one short sentence"
}}
"""
    if len(png) < 2000:
        return {
            "goal_reached": False,
            "still_on_opening_screen": True,
            "reason": f"PNG too small ({len(png)} bytes)",
        }
    result = gemini_vision_json(prompt, png)
    result["goal_reached"] = bool(result.get("goal_reached")) and not bool(
        result.get("still_on_opening_screen")
    )
    return result


def _startup_gates(
    study: dict[str, Any],
    runs: list[dict[str, Any]],
    startup: dict[str, Any],
    abort_reason: str | None,
) -> list[dict[str, Any]]:
    expected = int(startup.get("expected") or PASS_AGENT_BAR)
    bar = int(startup.get("pass_agent_bar") or PASS_AGENT_BAR)
    min_personas = int(startup.get("min_personas") or 4)
    min_tasks = int(startup.get("min_tasks") or 2)
    min_sites = int(startup.get("min_sites") or 3)
    max_elapsed = float(startup.get("max_elapsed_s") or DEFAULT_MAX_ELAPSED_S)
    first_shot_s = float(startup.get("first_shot_s") or DEFAULT_FIRST_SHOT_S)

    agents = len(runs)
    personas = int(startup["personas"]) if "personas" in startup else len(study.get("personas") or [])
    if "task_bases" in startup:
        task_bases = int(startup["task_bases"])
    else:
        task_bases = len(_task_titles(study))
    if "sites" in startup:
        sites = int(startup["sites"])
    else:
        keys = {str(r.get("site_key") or "product") for r in runs}
        sites = max(len(keys), 1 + len(study.get("competitors") or []))
    yeses = startup.get("yeses")
    elapsed = startup.get("elapsed_s")
    missing = startup.get("missing_shot")
    max_gap = startup.get("max_creation_to_shot_s")
    slow = int(startup.get("slow_agents") or 0)
    vision_nos = int(startup.get("vision_nos") or 0)
    status = str(startup.get("status") or study.get("status") or "")
    has_summary = bool(startup["has_summary"]) if "has_summary" in startup else bool(study.get("summary"))

    gates = [
        _gate(
            "full_matrix",
            "Full 24-agent matrix",
            expected,
            f">= {bar} (smaller runs are smoke-only)",
            expected >= bar and agents >= bar,
            f"agents={agents}",
        ),
        _gate(
            "agent_count",
            "Agent count",
            agents,
            f">= {max(expected, bar)}",
            agents >= max(expected, bar),
        ),
        _gate(
            "persona_count",
            "Persona count",
            personas,
            f">= {min_personas}",
            personas >= min_personas,
        ),
        _gate(
            "task_count",
            "Task count",
            task_bases,
            f">= {min_tasks}",
            task_bases >= min_tasks,
        ),
        _gate(
            "site_count",
            "Site count",
            sites,
            f">= {min_sites}",
            sites >= min_sites,
        ),
        _gate(
            "vision_yes",
            "First real screenshot is the product",
            "not recorded" if yeses is None else f"{yeses}/{expected}",
            f"{expected}/{expected} vision YES",
            yeses is not None and int(yeses) >= expected and vision_nos == 0,
            f"vision_nos={vision_nos}",
        ),
        _gate(
            "study_complete",
            "Study completed with a summary",
            status if not abort_reason else f"{status or 'running'} aborted",
            "status=complete, summary present, no harness abort",
            status == "complete" and has_summary and not abort_reason,
            abort_reason or "",
        ),
        _gate(
            "elapsed",
            "Elapsed time",
            "not recorded" if elapsed is None else f"{elapsed}s",
            f"<= {max_elapsed:.0f}s",
            elapsed is not None and float(elapsed) <= max_elapsed,
        ),
        _gate(
            "first_screenshot",
            "Every agent has a first real screenshot",
            "not recorded" if missing is None else f"missing={missing}",
            "missing=0",
            missing is not None and int(missing) == 0,
        ),
        _gate(
            "first_screenshot_latency",
            "Creation to first real screenshot",
            "not recorded" if max_gap is None else f"max={max_gap}s slow={slow}",
            f"<= {first_shot_s:.0f}s for every agent",
            max_gap is not None and float(max_gap) <= first_shot_s and slow == 0,
        ),
    ]
    return gates


def _competitor_scores(
    study: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Past-first-screen counts. Not a product gate and not vision-confirmed."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        if is_product_run(run):
            continue
        key = str(run.get("site_key") or "competitor")
        groups.setdefault(key, []).append(run)
    rows = []
    for key, group in sorted(groups.items()):
        ok = sum(
            1
            for run in group
            if beyond_first_screen(run, _start_url(run, study))
            and not is_browserbase_or_concurrency_loss(run)
        )
        label = str(group[0].get("site_label") or group[0].get("site_url") or key)
        rows.append(
            {
                "site_key": key,
                "site_label": label,
                "success_n": ok,
                "n": len(group),
                "value": f"{ok}/{len(group)}",
            }
        )
    return rows


def evaluate_strict_gates(
    study: dict[str, Any],
    *,
    startup: dict[str, Any] | None = None,
    vision_goal: dict[str, bool] | None = None,
    screenshot_loads: Callable[[str], bool] | None = None,
    report_html: str | None = None,
    report_url: str | None = None,
    abort_reason: str | None = None,
) -> dict[str, Any]:
    """Return gates, competitor scores, and pass=True only when every gate passes."""
    startup = dict(startup or {})
    vision_goal = dict(vision_goal or {})
    runs = iter_runs(study)
    runs_by_id = {str(r.get("agent_id") or r.get("task_id") or ""): r for r in runs}
    product = [r for r in runs if is_product_run(r)]
    insights = _insights(study)
    issues = _run_issues(study)

    success_ids: list[str] = []
    first_screen_ids: list[str] = []
    opening_ids: list[str] = []
    structural_ids: list[str] = []
    for run in product:
        aid = str(run.get("agent_id") or "")
        start = _start_url(run, study)
        if ended_on_opening_frame(run):
            opening_ids.append(aid)
        if never_left_first_screen(run, start) or ended_on_opening_frame(run):
            first_screen_ids.append(aid)
        if beyond_first_screen(run, start):
            structural_ids.append(aid)
        if product_run_succeeded(run, start, vision_goal=bool(vision_goal.get(aid))):
            success_ids.append(aid)

    product_n = len(product)
    success_n = len(success_ids)
    need_n = (product_n + 1) // 2 if product_n else 1
    # At least 50%, so 4/8 passes. Odd counts round up the minimum count.
    rate_ok = product_n > 0 and (success_n * 2) >= product_n
    rate_value = f"{success_n}/{product_n}" if product_n else "0/0"
    rate_pct = round(100 * success_n / product_n) if product_n else 0

    bb_losses = [r for r in runs if is_browserbase_or_concurrency_loss(r)]
    bb_ids = {str(r.get("agent_id") or "") for r in bb_losses if r.get("agent_id")}
    issue_ids = {str(row.get("agent_id") or "") for row in issues if row.get("agent_id")}
    # A Browserbase/concurrency loss that the report omitted is a silent exclusion.
    silent_bb = sorted(aid for aid in bb_ids if aid not in issue_ids)
    bb_marked_success = sorted(aid for aid in bb_ids if aid in success_ids)
    product_ids = {str(r.get("agent_id") or "") for r in product}
    opening_excluded = [aid for aid in opening_ids if aid and aid not in product_ids]
    infra_ok = not silent_bb and not bb_marked_success

    by_task = [row for row in (insights.get("by_task") or []) if isinstance(row, dict)]
    study_tasks = _task_titles(study)
    missing_rates: list[str] = []
    if not by_task:
        missing_rates.append("no by_task rows")
    seen_titles = set()
    for row in by_task:
        title = str(row.get("title") or row.get("task_id") or "")
        seen_titles.add(title.lower())
        cell = (row.get("sites") or {}).get("product") if isinstance(row.get("sites"), dict) else None
        if not isinstance(cell, dict) or "n" not in cell or "ok" not in cell:
            missing_rates.append(title or "(untitled task)")
            continue
        try:
            n = int(cell["n"])
            ok = int(cell["ok"])
        except (TypeError, ValueError):
            missing_rates.append(title or "(untitled task)")
            continue
        if n <= 0:
            missing_rates.append(f"{title}: n=0")
        elif ok > n:
            missing_rates.append(f"{title}: ok>n")
    for title in study_tasks:
        if title.lower() not in seen_titles and not any(title.lower() in s for s in seen_titles):
            missing_rates.append(f"missing task {title}")

    strengths = [c for c in (insights.get("strengths") or []) if isinstance(c, dict)]
    weaknesses = [c for c in (insights.get("weaknesses") or []) if isinstance(c, dict)]
    good_strengths = _qualifying_claims(strengths, runs_by_id, study, screenshot_loads)
    good_weaknesses = _qualifying_claims(weaknesses, runs_by_id, study, screenshot_loads)
    real_weaknesses = [
        c for c in good_weaknesses if not is_homepage_excuse(str(c.get("claim") or ""))
    ]
    top_weak = str((weaknesses[0].get("claim") if weaknesses else "") or "")
    solely_homepage = (not real_weaknesses) or (
        bool(weaknesses) and is_homepage_excuse(top_weak) and len(real_weaknesses) == 0
    )

    study_id = str(study.get("id") or startup.get("study_id") or "")
    html = report_html or ""
    missing_markers = [m for m in _REPORT_MARKERS if m not in html]
    url_ok = bool(report_url) and (not study_id or study_id in str(report_url))
    report_ok = bool(html) and not missing_markers and url_ok

    # Listed run issues, plus any Browserbase loss the report failed to list.
    issue_count = len(issues) + len(silent_bb)
    run_n = len(runs)
    issue_ok = run_n > 0 and (issue_count * 4) <= run_n
    issue_pct = round(100 * issue_count / run_n) if run_n else 100

    separate_ok = isinstance(insights.get("run_issues"), list)
    harness_in_weakness = [
        str(c.get("claim") or "")[:80]
        for c in weaknesses
        if is_homepage_excuse(str(c.get("claim") or "")) is False
        and _BB_LOSS_RE.search(str(c.get("claim") or ""))
    ]
    if harness_in_weakness:
        separate_ok = False

    gates = _startup_gates(study, runs, startup, abort_reason)
    gates.extend(
        [
            _gate(
                "product_task_completion",
                "Product task completion",
                f"{rate_value} ({rate_pct}%)",
                f">= {PRODUCT_SUCCESS_MIN:.0%} of product runs (>= {need_n}/{product_n or '?'})",
                rate_ok,
                (
                    f"structural_past_first_screen={len(structural_ids)} "
                    f"vision_confirmed={success_n} "
                    f"first_screen_or_opening={len(first_screen_ids)} "
                    f"opening_frame={len(opening_ids)} "
                    f"bb_losses_in_product={sum(1 for r in product if is_browserbase_or_concurrency_loss(r))}"
                ),
            ),
            _gate(
                "report_page",
                "Bland-style report page",
                report_url or "missing",
                "/report?study=<id> shell with overview and trace tabs",
                report_ok,
                "missing markers: " + ", ".join(missing_markers) if missing_markers else "",
            ),
            _gate(
                "task_completion_rates",
                "Every task has a completion rate",
                f"{len(by_task)} tasks" if not missing_rates else "missing " + "; ".join(missing_rates[:4]),
                "each task has a product ok/n rate",
                not missing_rates,
            ),
            _gate(
                "product_strength",
                "Product strength from a run past the first screen",
                f"{len(good_strengths)}/{len(strengths)}",
                ">= 1 strength with agent, step, and a screenshot URL that loads",
                len(good_strengths) >= 1,
            ),
            _gate(
                "product_weakness",
                "Product weakness from a run past the first screen",
                f"{len(good_weaknesses)}/{len(weaknesses)}",
                ">= 1 weakness with agent, step, and a screenshot URL that loads",
                len(good_weaknesses) >= 1,
            ),
            _gate(
                "top_weakness_not_homepage_only",
                "Top weakness is not only the homepage stall",
                (top_weak[:140] or "(none)"),
                "at least one weakness is a real product issue from a run past the first screen",
                not solely_homepage and len(real_weaknesses) >= 1,
                f"real_weaknesses={len(real_weaknesses)}",
            ),
            _gate(
                "run_issues_separate",
                "Run issues listed separately from product friction",
                f"{len(issues)} listed",
                "insights.run_issues is its own list; harness errors are not product weaknesses",
                separate_ok,
                "; ".join(harness_in_weakness),
            ),
            _gate(
                "run_issue_rate",
                "Run issue share",
                f"{issue_count}/{run_n} ({issue_pct}%)" if run_n else "0/0",
                f"<= {RUN_ISSUE_MAX:.0%} of runs",
                issue_ok,
            ),
            _gate(
                "infra_honesty",
                "Browserbase and concurrency losses count against the run",
                f"losses={len(bb_losses)} silent={len(silent_bb)} counted_as_success={len(bb_marked_success)}",
                "0 silently excluded, 0 counted as task success",
                infra_ok,
                ", ".join(silent_bb[:8]),
            ),
            _gate(
                "first_screen_not_excluded",
                "First-screen and opening-frame runs stay in the product denominator",
                f"opening_or_first_screen={len(first_screen_ids)} product_n={product_n} excluded=0",
                "excluded=0 (a stuck run is a failure, not a drop)",
                product_n >= len(set(first_screen_ids)) and not opening_excluded,
                f"excluded={len(opening_excluded)}",
            ),
        ]
    )

    competitors = _competitor_scores(study, runs)
    fail_reasons = [
        f"{g['id']}: value={g['value']} threshold={g['threshold']}"
        + (f" ({g['detail']})" if g.get("detail") else "")
        for g in gates
        if not g["pass"]
    ]
    return {
        "pass": not fail_reasons,
        "gates": gates,
        "fail_reasons": fail_reasons,
        "product_task_success": {
            "success_n": success_n,
            "n": product_n,
            "value": rate_value,
            "success_ids": success_ids,
            "structural_ids": structural_ids,
            "first_screen_ids": first_screen_ids,
        },
        "competitor_task_success": competitors,
        "run_issues": issues,
        "browserbase_concurrency_losses": [
            str(r.get("agent_id") or "") for r in bb_losses
        ],
    }


def render_markdown(result: dict[str, Any], *, study_id: str = "", product_url: str = "") -> str:
    """Human summary. Every gate is a row with value, threshold, and PASS/FAIL."""
    lines = [
        "# Strict e2e gates",
        "",
        f"- study: {study_id or '(none)'}",
        f"- product: {product_url or '(none)'}",
        f"- pass: {str(bool(result.get('pass'))).lower()}",
        "",
        "| Gate | Value | Threshold | Result |",
        "| --- | --- | --- | --- |",
    ]
    for gate in result.get("gates") or []:
        mark = "PASS" if gate.get("pass") else "FAIL"
        value = str(gate.get("value")).replace("|", "/")
        threshold = str(gate.get("threshold")).replace("|", "/")
        lines.append(
            f"| {gate.get('name')} (`{gate.get('id')}`) | {value} | {threshold} | {mark} |"
        )
    lines.append("")
    lines.append("## Competitor task completion")
    lines.append("")
    lines.append("Reported separately. These runs do not count toward the product gate.")
    lines.append("")
    comps = result.get("competitor_task_success") or []
    if not comps:
        lines.append("- (none)")
    else:
        for row in comps:
            lines.append(
                f"- {row.get('site_label')} ({row.get('site_key')}): {row.get('value')}"
            )
    product = result.get("product_task_success") or {}
    lines.extend(
        [
            "",
            "## Product task completion",
            "",
            f"- confirmed: {product.get('value')}",
            f"- past the first screen (structural): {len(product.get('structural_ids') or [])}",
            f"- first screen or opening frame: {len(product.get('first_screen_ids') or [])}",
            "",
        ]
    )
    if result.get("fail_reasons"):
        lines.append("## Failed gates")
        lines.append("")
        for reason in result["fail_reasons"]:
            lines.append(f"- {reason}")
        lines.append("")
    return "\n".join(lines)
