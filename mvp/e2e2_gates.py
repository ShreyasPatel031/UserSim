"""Strict e2e pass gates.

Startup gates stay: agent count, first real screenshot within 5s, and a vision
YES that the screenshot is the real product. The old 360s elapsed ceiling is a
study-level budget of 8 minutes. There is no per-agent limit on how long a
study may run. An agent that makes no progress for several steps is flagged
stuck; it is not timed out. Time to first action is separate: from each
agent's first real screenshot until a click, type, or scroll shows up in the
live study. That passes only when the median is <= 5s and the max is <= 10s
at 24 agents. The harness aborts once that max is clearly blown.

Task completion comes only from an independent vision judge. The judge sees the
final screenshot plus the final URL and DOM and writes a verdict with a reason.
Agent summaries, quotes, and task_succeeded notes are not a pass signal.
A study passes only when those verdicts clear the product bar and the report
checks pass. Competitor runs are reported separately.
Browserbase and concurrency losses count against the run. They are not dropped.
"""

from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urlsplit

from mvp.report_insights import (
    _canvas_changed,
    _page_key,
    _text_changed,
    changed_page_state,
)

PASS_AGENT_BAR = 24
PRODUCT_SUCCESS_MIN = 0.50
RUN_ISSUE_MAX = 0.25
# Confirmed maxima for this strict matrix, in seconds:
#   saved-study wall (created→updated): Linear 352, Excalidraw 349, MDN 358
#   measured 24-agent e2e2 elapsed: Etsy 378 (highest in results/e2e2_*)
#   harness baseline cited for the old gate: YouTube ~408
#   live runs on this branch: Linear 303, Excalidraw 314
# Per-agent durations in those studies peaked near 248s. That is not a timeout.
OBSERVED_STUDY_MAX_S = 408.0
DEFAULT_STUDY_BUDGET_S = 480.0  # 8 minutes, above the confirmed max
DEFAULT_MAX_ELAPSED_S = DEFAULT_STUDY_BUDGET_S
DEFAULT_FIRST_SHOT_S = 5.0
# Consecutive trace steps with the same URL, DOM text, and canvas.
# A single opening frame is a product miss, not a stuck agent.
STUCK_STEPS = 3

FAILURE_INFRASTRUCTURE = "our infrastructure"
FAILURE_MODEL_TIMEOUT = "model timeout"
FAILURE_STUCK = "stuck"
FAILURE_PRODUCT = "product"
FAILURE_NO_FIRST_ACTION = "no_first_action"
FAILURE_TYPES = (
    FAILURE_INFRASTRUCTURE,
    FAILURE_MODEL_TIMEOUT,
    FAILURE_STUCK,
    FAILURE_PRODUCT,
    FAILURE_NO_FIRST_ACTION,
)
# Legacy fleet check (half by 60s, every agent by 90s). The live abort is
# time_to_first_action; --first-action-s only loosens that tighter ceiling.
DEFAULT_FIRST_ACTION_S = 60.0
DEFAULT_FIRST_ACTION_FRAC = 0.5
FIRST_ACTION_ALL_EXTRA_S = 30.0
# Screenshot → click/type/scroll visible in the live study. Pass at 24 agents.
DEFAULT_TTFA_MEDIAN_S = 5.0
DEFAULT_TTFA_MAX_S = 10.0
# Early abort once this wait is clearly past the max. --first-action-s overrides it.
DEFAULT_TTFA_ABORT_S = DEFAULT_TTFA_MAX_S
_CLICK_TYPE_SCROLL = frozenset(
    {"click", "type", "input", "input_text", "send_keys", "scroll"}
)
# Abort when Browserbase session drops are strictly over this share of agents.
INFRA_DROP_MAX = 0.25

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

_TIMEOUT_RE = re.compile(
    r"\btimed?\s*out\b|\btimeout\b|agent wall|deadline exceeded",
    re.I,
)

_CDP_RE = re.compile(r"root cdp client not initialized", re.I)
_BB_DROP_RE = re.compile(
    r"root cdp client not initialized|"
    r"session (?:dropped|closed|expired|disconnected)|"
    r"browser(?:base)? session (?:dropped|closed|lost)|"
    r"target closed|"
    r"websocket[^.]{0,40}clos|"
    r"browser disconnected|"
    r"cdp client",
    re.I,
)

_INFRA_KINDS = {"infrastructure", "navigation", "captcha"}


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


def _harness_blob(run: dict[str, Any]) -> str:
    """Harness and trace text. Agent summaries and quotes are not included."""
    issue = run.get("run_issue") if isinstance(run.get("run_issue"), dict) else {}
    parts = [
        str(run.get("browser_error") or ""),
        str(run.get("last_action") or ""),
        str(run.get("error") or ""),
        str(run.get("mode") or ""),
        str(issue.get("kind") or ""),
        str(issue.get("reason") or ""),
    ]
    for step in run.get("trace") or []:
        if isinstance(step, dict):
            parts.append(str(step.get("action") or ""))
    return " ".join(parts)


def is_model_timeout(run: dict[str, Any]) -> bool:
    """The model or agent wall stopped the run. Not a Browserbase loss."""
    if is_browserbase_or_concurrency_loss(run):
        return False
    return bool(_TIMEOUT_RE.search(_harness_blob(run)))


def is_infrastructure_failure(run: dict[str, Any]) -> bool:
    """Our harness failed the run: Browserbase, navigation, captcha, browser error."""
    if is_browserbase_or_concurrency_loss(run):
        return True
    if is_model_timeout(run):
        return False
    issue = run.get("run_issue") if isinstance(run.get("run_issue"), dict) else {}
    kind = str(issue.get("kind") or "").lower()
    if kind in _INFRA_KINDS:
        return True
    return bool(str(run.get("browser_error") or "").strip())


def _step_progressed(prev: dict[str, Any], cur: dict[str, Any]) -> bool:
    """True when the URL, DOM text, or canvas changed between two trace steps."""
    prev_key = _page_key(str(prev.get("url") or ""))
    cur_key = _page_key(str(cur.get("url") or ""))
    if prev_key != ("", "", "") and cur_key != ("", "", "") and prev_key != cur_key:
        return True
    prev_sig = prev.get("state_sig") if isinstance(prev.get("state_sig"), dict) else {}
    cur_sig = cur.get("state_sig") if isinstance(cur.get("state_sig"), dict) else {}
    if _canvas_changed(str(prev_sig.get("canvas") or ""), str(cur_sig.get("canvas") or "")):
        return True
    if _text_changed(str(prev_sig.get("text") or ""), str(cur_sig.get("text") or "")):
        return True
    return False


def _action_key(step: dict[str, Any]) -> str:
    return " ".join(str(step.get("action") or "").split()).lower()


def stuck_no_progress(run: dict[str, Any], *, steps: int = STUCK_STEPS) -> bool:
    """True when the same action is repeated `steps` times with no URL/DOM change.

    Opening the page is not that action. A run that only captured the opening
    frame has not repeated an action, so it is not stuck.
    """
    trace = [
        step
        for step in (run.get("trace") or [])
        if isinstance(step, dict) and isinstance(step.get("step"), int)
    ]
    trace.sort(key=lambda step: int(step["step"]))
    streak = 0
    prev: dict[str, Any] | None = None
    prev_key = ""
    for step in trace:
        key = _action_key(step)
        if not key or key.startswith("opened"):
            streak = 0
            prev = step
            prev_key = ""
            continue
        same = (
            prev is not None
            and key == prev_key
            and not _step_progressed(prev, step)
        )
        streak = streak + 1 if same else 1
        prev = step
        prev_key = key
        if streak >= steps:
            return True
    return False


def action_verb(text: object) -> str:
    """Leading action name, so 'click — index=4' and 'Opened https://…' both parse."""
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    head = raw.split("—", 1)[0]
    head = head.split(" - ", 1)[0]
    head = head.split(":", 1)[0]
    return " ".join(head.split())


def is_click_type_scroll(text: object) -> bool:
    """A real UI action. Opening the page, search, and go_to_url do not count."""
    for part in re.split(r"[;\n]", str(text or "")):
        verb = action_verb(part)
        if not verb:
            continue
        if verb in _CLICK_TYPE_SCROLL:
            return True
        if any(verb.startswith(name + " ") for name in _CLICK_TYPE_SCROLL):
            return True
    return False


def has_click_type_scroll(run: dict[str, Any]) -> bool:
    """True once a click, type, or scroll is in the trace or the live last action."""
    for step in run.get("trace") or []:
        if isinstance(step, dict) and is_click_type_scroll(step.get("action")):
            return True
    return is_click_type_scroll(run.get("last_action"))


def note_visible_actions(
    runs: list[dict[str, Any]],
    seen_at: dict[str, float],
    now: float,
) -> None:
    """Stamp the poll time when a click/type/scroll first shows up in the study JSON.

    That JSON is what the live UI renders. The stamp is not an agent-side clock.
    """
    for run in runs:
        if not isinstance(run, dict):
            continue
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        if not aid or aid in seen_at:
            continue
        if has_click_type_scroll(run):
            seen_at[aid] = float(now)


def _screenshot_epoch(run: dict[str, Any]) -> float | None:
    for key in ("first_screenshot_at_ts", "first_screenshot_at"):
        value = run.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def assess_time_to_first_action(
    runs: list[dict[str, Any]],
    *,
    now: float,
    action_seen_at: dict[str, float] | None = None,
    median_s: float = DEFAULT_TTFA_MEDIAN_S,
    max_s: float = DEFAULT_TTFA_MAX_S,
    abort_after_s: float | None = None,
    expected: int = PASS_AGENT_BAR,
) -> dict[str, Any]:
    """Time from each agent's first real screenshot to a click/type/scroll in the live UI.

    `action_seen_at` is the harness poll time when that action showed up in the
    study payload. The pass bar is median <= 5s and max <= 10s at 24 agents.
    Abort when any agent with a screenshot still has no such action after
    `abort_after_s` (default 10s, the max, so the threshold is clearly blown).
    A higher `abort_after_s` only delays the abort; it does not loosen the pass bar.
    """
    if action_seen_at is None:
        action_seen_at = {}
    note_visible_actions(runs, action_seen_at, now)
    ceiling = float(max_s if abort_after_s is None else abort_after_s)
    need = int(expected) if int(expected) > 0 else PASS_AGENT_BAR
    agents = [run for run in runs if isinstance(run, dict)]
    latencies: list[float] = []
    per_agent: list[dict[str, Any]] = []
    blown: list[dict[str, Any]] = []
    idle: list[dict[str, Any]] = []
    for run in agents:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        shot = _screenshot_epoch(run)
        acted = has_click_type_scroll(run)
        appeared = action_seen_at.get(aid) if aid else None
        latency = None
        waited = None
        if shot is not None and acted and appeared is not None:
            latency = max(0.0, float(appeared) - float(shot))
            latencies.append(latency)
        elif shot is not None and not acted:
            waited = float(now) - float(shot)
            idle.append(run)
            if waited > ceiling:
                blown.append(run)
        elif not acted:
            idle.append(run)
        per_agent.append(
            {
                "agent_id": aid,
                "screenshot_at": shot,
                "action_seen_at": appeared,
                "latency_s": None if latency is None else round(latency, 3),
                "waited_s": None if waited is None else round(waited, 3),
            }
        )
    median = _median(latencies)
    maximum = max(latencies) if latencies else None
    abort = bool(blown)
    complete = len(agents) >= need and len(latencies) == len(agents) and len(latencies) >= need
    ok = (
        not abort
        and complete
        and median is not None
        and maximum is not None
        and median <= float(median_s)
        and maximum <= float(max_s)
    )
    reason = ""
    if abort:
        waits = ", ".join(
            f"{str(run.get('agent_id') or '')}="
            f"{max(0.0, float(now) - float(_screenshot_epoch(run) or now)):.1f}s"
            for run in blown[:8]
        )
        reason = (
            f"FAIL time_to_first_action: {len(blown)}/{len(agents)} agents had no "
            f"click/type/scroll {ceiling:.0f}s after their first real screenshot "
            f"({waits})"
        )
        seen = "; ".join(last_seen_text(run) for run in blown[:8])
        if seen:
            reason = f"{reason}. {seen}"
    median_out = None if median is None else round(median, 3)
    max_out = None if maximum is None else round(maximum, 3)
    return {
        "measured": True,
        "ok": ok,
        "abort": abort,
        "type": FAILURE_NO_FIRST_ACTION if abort else "",
        "median_s": median_out,
        "max_s": max_out,
        "n": len(latencies),
        "agents": len(agents),
        "expected": need,
        "acted": len(latencies),
        "median_limit_s": float(median_s),
        "max_limit_s": float(max_s),
        "abort_after_s": ceiling,
        "missing_ids": [str(run.get("agent_id") or "") for run in idle],
        "ids": [str(run.get("agent_id") or "") for run in blown],
        "reason": reason,
        "detail": reason,
        "per_agent": per_agent,
    }


def has_real_action(run: dict[str, Any]) -> bool:
    """A numbered step at or after 1 whose action is not just opening the page."""
    for step in run.get("trace") or []:
        if not isinstance(step, dict):
            continue
        try:
            number = int(step.get("step"))
        except (TypeError, ValueError):
            continue
        if number < 1:
            continue
        action = str(step.get("action") or "").strip()
        if not action or action.lower().startswith("opened"):
            continue
        return True
    return False


def last_seen_text(run: dict[str, Any]) -> str:
    """Phase and error the harness last observed for this agent."""
    aid = str(run.get("agent_id") or run.get("task_id") or "")
    phase = str(run.get("phase") or run.get("status") or "")
    error = str(run.get("error") or run.get("browser_error") or "")
    last = str(run.get("last_action") or "")
    return (
        f"{aid} phase={phase[:80]} error={error[:120]} last_action={last[:80]}"
    )


def _agent_text(run: dict[str, Any]) -> str:
    issue = run.get("run_issue") if isinstance(run.get("run_issue"), dict) else {}
    return " ".join(
        [
            str(run.get("browser_error") or ""),
            str(run.get("last_action") or ""),
            str(run.get("error") or ""),
            str(run.get("phase") or ""),
            str(run.get("status") or ""),
            str(issue.get("kind") or ""),
            str(issue.get("reason") or ""),
        ]
    )


def is_cdp_failure(run: dict[str, Any]) -> bool:
    return bool(_CDP_RE.search(_agent_text(run)))


def is_browserbase_session_drop(run: dict[str, Any]) -> bool:
    return bool(_BB_DROP_RE.search(_agent_text(run)))


def assess_first_action(
    runs: list[dict[str, Any]],
    *,
    since_s: float,
    first_action_s: float = DEFAULT_FIRST_ACTION_S,
    frac: float = DEFAULT_FIRST_ACTION_FRAC,
) -> dict[str, Any]:
    """Abort when agents open the page and then sit.

    At `first_action_s` (default 60s after the first task) fewer than `frac`
    of agents with a real action aborts. At `first_action_s` + 30s (default
    90s) any agent still without one aborts.
    """
    agents = [run for run in runs if isinstance(run, dict)]
    acted = [run for run in agents if has_real_action(run)]
    missing = [run for run in agents if not has_real_action(run)]
    total = len(agents)
    acted_n = len(acted)
    share = (acted_n / total) if total else 1.0
    all_by = float(first_action_s) + FIRST_ACTION_ALL_EXTRA_S
    abort = False
    reason = ""
    if total and since_s >= float(first_action_s) and share < float(frac):
        abort = True
        reason = (
            f"FAIL first_action: {acted_n}/{total} agents had a real action "
            f"by {since_s:.0f}s (need >= {float(frac):.0%} by {float(first_action_s):.0f}s)"
        )
    elif total and since_s >= all_by and missing:
        abort = True
        reason = (
            f"FAIL first_action: {len(missing)}/{total} agents still have no real action "
            f"at {since_s:.0f}s (every agent must act by {all_by:.0f}s)"
        )
    seen = "; ".join(last_seen_text(run) for run in missing)
    if abort and seen:
        reason = f"{reason}. {seen}"
    return {
        "measured": True,
        "ok": not abort,
        "abort": abort,
        "type": FAILURE_NO_FIRST_ACTION if abort else "",
        "acted": acted_n,
        "agents": total,
        "since_s": round(float(since_s), 1),
        "first_action_s": float(first_action_s),
        "frac": float(frac),
        "all_by_s": all_by,
        "missing_ids": [str(run.get("agent_id") or "") for run in missing],
        "reason": reason,
        "detail": seen[:1500],
    }


def assess_infrastructure_abort(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Abort on a CDP init failure, or when session drops pass 25% of agents."""
    agents = [run for run in runs if isinstance(run, dict)]
    total = len(agents)
    cdp = [run for run in agents if is_cdp_failure(run)]
    drops = [run for run in agents if is_browserbase_session_drop(run)]
    abort = False
    reason = ""
    flagged = cdp
    if cdp:
        abort = True
        reason = (
            f"FAIL our infrastructure: Root CDP client not initialized "
            f"on {len(cdp)}/{total} agents"
        )
    elif total and (len(drops) / total) > INFRA_DROP_MAX:
        abort = True
        flagged = drops
        reason = (
            f"FAIL our infrastructure: Browserbase session drops "
            f"{len(drops)}/{total} (over {INFRA_DROP_MAX:.0%})"
        )
    if abort:
        reason = f"{reason}. " + "; ".join(last_seen_text(run) for run in flagged)
    return {
        "abort": abort,
        "type": FAILURE_INFRASTRUCTURE if abort else "",
        "reason": reason,
        "ids": [str(run.get("agent_id") or "") for run in flagged],
        "cdp_n": len(cdp),
        "drop_n": len(drops),
        "agents": total,
    }


def assess_stuck_abort(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Abort when an agent repeats one action with no URL or DOM change."""
    agents = [run for run in runs if isinstance(run, dict)]
    stuck = [run for run in agents if stuck_no_progress(run)]
    if not stuck:
        return {"abort": False, "type": "", "reason": "", "ids": []}
    reason = (
        f"FAIL stuck: {len(stuck)} agent(s) repeated the same action "
        f"{STUCK_STEPS} times with no URL/DOM change. "
        + "; ".join(last_seen_text(run) for run in stuck)
    )
    return {
        "abort": True,
        "type": FAILURE_STUCK,
        "reason": reason,
        "ids": [str(run.get("agent_id") or "") for run in stuck],
    }


def final_url_of(run: dict[str, Any]) -> str:
    url = str(run.get("final_url") or "").strip()
    if url:
        return url
    for step in reversed(run.get("trace") or []):
        if isinstance(step, dict) and str(step.get("url") or "").strip():
            return str(step.get("url") or "").strip()
    return ""


def final_dom_of(run: dict[str, Any], *, limit: int = 1500) -> str:
    """Last DOM text signature on the trace. Empty when the run never recorded one."""
    for step in reversed(run.get("trace") or []):
        if not isinstance(step, dict):
            continue
        sig = step.get("state_sig")
        if isinstance(sig, dict) and str(sig.get("text") or "").strip():
            return str(sig.get("text") or "").strip()[:limit]
    return ""


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


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def coerce_verdict(raw: object) -> dict[str, Any]:
    """Normalize a judge payload. Missing and non-dict values are a NO."""
    if isinstance(raw, dict):
        opening = _as_bool(raw.get("still_on_opening_screen"))
        reached = _as_bool(raw.get("goal_reached")) and not opening
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            reason = "Goal reached." if reached else "Goal not reached."
        return {
            "goal_reached": reached,
            "still_on_opening_screen": opening,
            "reason": reason,
        }
    if raw is True:
        return {
            "goal_reached": True,
            "still_on_opening_screen": False,
            "reason": "Judge verdict: goal reached.",
        }
    if raw is False:
        return {
            "goal_reached": False,
            "still_on_opening_screen": False,
            "reason": "Judge verdict: goal not reached.",
        }
    return {
        "goal_reached": False,
        "still_on_opening_screen": False,
        "reason": "No independent judge verdict.",
    }


def verdict_reached(raw: object) -> bool:
    return bool(coerce_verdict(raw).get("goal_reached"))


def product_run_succeeded(
    run: dict[str, Any],
    start_url: str,
    *,
    vision_goal: object = None,
) -> bool:
    """Success is an independent judge YES.

    Infrastructure losses and model timeouts are not success. Agent summaries
    are not read. `start_url` is unused; the judge already saw the final URL.
    """
    del start_url
    if is_infrastructure_failure(run) or is_model_timeout(run):
        return False
    return verdict_reached(vision_goal)


def failure_type_for(run: dict[str, Any], verdict: object) -> str:
    """Bucket for a run that did not succeed. Priority is fixed."""
    if is_infrastructure_failure(run):
        return FAILURE_INFRASTRUCTURE
    if is_model_timeout(run):
        return FAILURE_MODEL_TIMEOUT
    if not verdict_reached(verdict) and stuck_no_progress(run):
        return FAILURE_STUCK
    return FAILURE_PRODUCT


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


def judge_goal_screenshot(
    png: bytes,
    *,
    task: str,
    start_url: str,
    final_url: str = "",
    dom: str = "",
) -> dict[str, Any]:
    """Independent vision judge.

    Decides whether the final screenshot, final URL, and DOM text show that
    the task goal was reached. The coding agent's own summary is not an input.
    """
    from mvp.e2e_ui_run import gemini_vision_json

    dom_text = (dom or "").strip()
    if len(dom_text) > 1500:
        dom_text = dom_text[:1500]
    prompt = f"""You are an independent QA vision judge. You do not work for the agent that browsed this page. Judge only the final screenshot, the final URL, and the DOM text below, against the task goal.

Task goal: {task or "unknown"}
Page the run opened on: {start_url or "unknown"}
Final URL: {final_url or "unknown"}
Final DOM text (may be truncated):
{dom_text or "(no DOM text recorded)"}

PASS goal_reached=true only when the screenshot and the final URL/DOM together show the goal was actually reached (for example the requested issue form or created issue, a drawing on the canvas, an export/share dialog, or the specific destination the task asked for).

FAIL goal_reached=false when:
- This is still the opening screen, marketing homepage, or unchanged first canvas
- The final URL and DOM are still the page the run opened on, and the screenshot does not show the goal
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
        return coerce_verdict(
            {
                "goal_reached": False,
                "still_on_opening_screen": True,
                "reason": f"PNG too small ({len(png)} bytes)",
            }
        )
    result = gemini_vision_json(prompt, png)
    return coerce_verdict(result)


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
    max_elapsed = float(
        startup.get("study_budget_s")
        or startup.get("max_elapsed_s")
        or DEFAULT_STUDY_BUDGET_S
    )
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
            "study_budget",
            "Study budget",
            "not recorded" if elapsed is None else f"{elapsed}s",
            f"<= {max_elapsed:.0f}s for the whole study (observed max {OBSERVED_STUDY_MAX_S:.0f}s)",
            elapsed is not None and float(elapsed) <= max_elapsed,
            (
                "No per-agent time limit. "
                f"Stuck means the same action repeated {STUCK_STEPS} times with no URL or DOM change. "
                "Confirmed maxima: saved-study wall 358s, measured e2e2 elapsed 378s, "
                f"YouTube baseline {OBSERVED_STUDY_MAX_S:.0f}s."
            ),
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
    check = startup.get("first_action_check")
    action_s = float(startup.get("first_action_s") or DEFAULT_FIRST_ACTION_S)
    action_frac = float(startup.get("first_action_frac") or DEFAULT_FIRST_ACTION_FRAC)
    all_by = action_s + FIRST_ACTION_ALL_EXTRA_S
    if isinstance(check, dict) and check.get("measured"):
        gates.append(
            _gate(
                "first_action",
                "First real action",
                f"{check.get('acted')}/{check.get('agents')} by {check.get('since_s')}s",
                (
                    f">= {action_frac:.0%} of agents by {action_s:.0f}s "
                    f"and every agent by {all_by:.0f}s"
                ),
                bool(check.get("ok")),
                str(check.get("detail") or check.get("reason") or ""),
            )
        )
    else:
        gates.append(
            _gate(
                "first_action",
                "First real action",
                "not measured",
                "live abort is time_to_first_action",
                True,
                "The 60s/90s fleet check is not the live abort.",
            )
        )
    ttfa = startup.get("time_to_first_action_check")
    median_lim = float(startup.get("ttfa_median_s") or DEFAULT_TTFA_MEDIAN_S)
    max_lim = float(startup.get("ttfa_max_s") or DEFAULT_TTFA_MAX_S)
    ttfa_need = int(startup.get("expected") or bar)
    if isinstance(ttfa, dict) and ttfa.get("measured"):
        med = ttfa.get("median_s")
        mx = ttfa.get("max_s")
        got = ttfa.get("n")
        med_txt = "n/a" if med is None else f"{med}s"
        max_txt = "n/a" if mx is None else f"{mx}s"
        gates.append(
            _gate(
                "time_to_first_action",
                "Time to first action",
                f"median={med_txt} max={max_txt} n={got}/{ttfa_need}",
                (
                    f"median <= {median_lim:.0f}s and max <= {max_lim:.0f}s "
                    f"at {ttfa_need} agents"
                ),
                bool(ttfa.get("ok")),
                str(ttfa.get("detail") or ttfa.get("reason") or ""),
            )
        )
    else:
        gates.append(
            _gate(
                "time_to_first_action",
                "Time to first action",
                "not measured",
                (
                    f"median <= {median_lim:.0f}s and max <= {max_lim:.0f}s "
                    f"at {ttfa_need} agents"
                ),
                True,
                (
                    "Live poll did not record screenshot → click/type/scroll "
                    "visible in the study."
                ),
            )
        )
    return gates


def _competitor_scores(
    study: dict[str, Any],
    runs: list[dict[str, Any]],
    verdicts: dict[str, object],
) -> list[dict[str, Any]]:
    """Judge verdicts, reported separately. Not a product pass gate."""
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
            if product_run_succeeded(
                run,
                _start_url(run, study),
                vision_goal=verdicts.get(str(run.get("agent_id") or "")),
            )
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


def _origin(report_url: str) -> str:
    if not report_url:
        return ""
    parts = urlsplit(report_url)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return ""


def _absolute_url(base: str, url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if not base:
        return text
    return base.rstrip("/") + (text if text.startswith("/") else "/" + text)


def _shot_step(run: dict[str, Any]) -> dict[str, Any] | None:
    return _final_shot(run)


def build_early_failures(
    study: dict[str, Any],
    runs: list[dict[str, Any]],
    early: dict[str, Any],
    *,
    base_url: str = "",
) -> dict[str, Any]:
    """Failure file for an early abort. Every listed run shares the abort type."""
    kind = str(early.get("type") or FAILURE_PRODUCT)
    wanted = set(early.get("ids") or early.get("missing_ids") or [])
    study_id = str(study.get("id") or "")
    failed: list[dict[str, Any]] = []
    for run in runs:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        if not aid:
            continue
        if wanted and aid not in wanted:
            continue
        if kind == FAILURE_NO_FIRST_ACTION and has_click_type_scroll(run):
            continue
        shot = _shot_step(run)
        step_n = shot.get("step") if shot else None
        shot_url = str((shot or {}).get("screenshot_url") or "")
        step_q = int(step_n) if isinstance(step_n, int) else 0
        if study_id:
            trace = f"{base_url}/report?study={study_id}&agent={aid}&step={step_q}"
        else:
            trace = f"{base_url}/report?agent={aid}&step={step_q}"
        failed.append(
            {
                "agent_id": aid,
                "site_key": str(run.get("site_key") or ""),
                "task": str(run.get("task_prompt") or run.get("task_title") or ""),
                "type": kind,
                "judge_reason": last_seen_text(run),
                "phase": str(run.get("phase") or run.get("status") or ""),
                "error": str(run.get("error") or run.get("browser_error") or ""),
                "goal_reached": False,
                "trace_link": trace,
                "final_screenshot": _absolute_url(base_url, shot_url),
                "final_url": final_url_of(run),
                "step": step_n if isinstance(step_n, int) else None,
            }
        )
    counts: dict[str, int] = {name: 0 for name in FAILURE_TYPES}
    for row in failed:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    return {
        "study_id": study_id,
        "product_url": _product_url(study),
        "abort": kind,
        "reason": str(early.get("reason") or ""),
        "types": list(FAILURE_TYPES),
        "counts": counts,
        "failed_runs": failed,
    }


def build_failure_report(
    study: dict[str, Any],
    runs: list[dict[str, Any]],
    verdicts: dict[str, object],
    *,
    base_url: str = "",
) -> dict[str, Any]:
    """Every run the judge (or a harness failure) did not pass.

    Types are mutually exclusive: our infrastructure, model timeout, stuck, product.
    """
    study_id = str(study.get("id") or "")
    failed: list[dict[str, Any]] = []
    for run in runs:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        if not aid:
            continue
        raw = verdicts.get(aid)
        verdict = coerce_verdict(raw)
        if product_run_succeeded(run, _start_url(run, study), vision_goal=raw):
            continue
        shot = _shot_step(run)
        step_n = shot.get("step") if shot else None
        shot_url = str((shot or {}).get("screenshot_url") or "")
        step_q = int(step_n) if isinstance(step_n, int) else 0
        if study_id:
            trace = f"{base_url}/report?study={study_id}&agent={aid}&step={step_q}"
        else:
            trace = f"{base_url}/report?agent={aid}&step={step_q}"
        kind = failure_type_for(run, raw)
        failed.append(
            {
                "agent_id": aid,
                "site_key": str(run.get("site_key") or ""),
                "task": str(run.get("task_prompt") or run.get("task_title") or ""),
                "type": kind,
                "judge_reason": str(verdict.get("reason") or ""),
                "goal_reached": False,
                "trace_link": trace,
                "final_screenshot": _absolute_url(base_url, shot_url),
                "final_url": final_url_of(run),
                "step": step_n if isinstance(step_n, int) else None,
            }
        )
    counts: dict[str, int] = {name: 0 for name in FAILURE_TYPES}
    for row in failed:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    return {
        "study_id": study_id,
        "product_url": _product_url(study),
        "types": list(FAILURE_TYPES),
        "counts": counts,
        "failed_runs": failed,
    }


def evaluate_strict_gates(
    study: dict[str, Any],
    *,
    startup: dict[str, Any] | None = None,
    vision_goal: dict[str, object] | None = None,
    screenshot_loads: Callable[[str], bool] | None = None,
    report_html: str | None = None,
    report_url: str | None = None,
    abort_reason: str | None = None,
) -> dict[str, Any]:
    """Return gates, judge-backed scores, and pass=True only when every gate passes.

    `vision_goal` maps agent id → judge verdict (dict with goal_reached, reason)
    or a bool. Agent summary fields are ignored.
    """
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
        if product_run_succeeded(run, start, vision_goal=vision_goal.get(aid)):
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
                    f"judge_yes={success_n} "
                    f"structural_past_first_screen={len(structural_ids)} "
                    f"first_screen_or_opening={len(first_screen_ids)} "
                    f"opening_frame={len(opening_ids)} "
                    f"stuck={sum(1 for r in product if stuck_no_progress(r))} "
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

    competitors = _competitor_scores(study, runs, vision_goal)
    base_url = str(startup.get("base") or _origin(str(report_url or "")))
    failures = build_failure_report(study, runs, vision_goal, base_url=base_url)
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
        "verdicts": {aid: coerce_verdict(vision_goal.get(aid)) for aid in runs_by_id},
        "failures": failures,
    }


def render_markdown(
    result: dict[str, Any],
    *,
    study_id: str = "",
    product_url: str = "",
    failure_file: str = "",
) -> str:
    """Human summary. Every gate is a row with value, threshold, and PASS/FAIL."""
    failures = result.get("failures") if isinstance(result.get("failures"), dict) else {}
    counts = failures.get("counts") if isinstance(failures.get("counts"), dict) else {}
    lines = [
        "# Strict e2e gates",
        "",
        f"- study: {study_id or '(none)'}",
        f"- product: {product_url or '(none)'}",
        f"- pass: {str(bool(result.get('pass'))).lower()}",
        f"- failure file: {failure_file or '(not written)'}",
        (
            "- failed runs: "
            + ", ".join(f"{name}={counts.get(name, 0)}" for name in FAILURE_TYPES)
        ),
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
