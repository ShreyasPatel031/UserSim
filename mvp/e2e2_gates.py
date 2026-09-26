"""Strict e2e pass gates.

Startup gates stay: agent count, and each agent opening the assigned site
within 5s, confirmed by URL and the accessibility tree. Vision runs only on
the one final screenshot. The old 360s elapsed ceiling is a study-level
budget of 8 minutes. There is no per-agent limit on how long a study may run.
An agent that makes no progress for several steps is flagged stuck; it is not
timed out. Time to first action starts when the study records browser-session
ready or page open, until a click, type, or scroll shows up in the live
study. That passes only when the median is <= 5s and the max is <= 10s at 24
agents. The harness aborts once that max is clearly blown.
Two headline clocks sit in front of that: time_to_first_value is the Run
click until the first click, type, or scroll is visible in the live UI
(pass <= 10s), and total_time is the Run click until the report is ready
(pass within the 8-minute study budget).

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

# A full matrix is 24 agents at once. An 8-wide or serialized browser cap
# does not pass, even if the eight that ran were fast.
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
# URL submit → first click/type/scroll visible in the live UI.
DEFAULT_TIME_TO_FIRST_VALUE_S = 10.0
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


def _numbered_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [
        step
        for step in (run.get("trace") or [])
        if isinstance(step, dict) and isinstance(step.get("step"), int)
    ]
    steps.sort(key=lambda step: int(step["step"]))
    return steps


def ended_on_opening_frame(run: dict[str, Any]) -> bool:
    """The run never recorded a step after the page open.

    A single final screenshot is not, by itself, an opening frame. Per-step
    screenshots are not required. A placeholder or blank opening shot still is.
    """
    for step in _numbered_steps(run):
        if step.get("opening_placeholder") or step.get("opening_blankish"):
            if int(step["step"]) == 0 and len(_numbered_steps(run)) == 1:
                return True
    if not _numbered_steps(run):
        return True
    return int(_numbered_steps(run)[-1]["step"]) <= 0


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


# Page open is the start when the study stored it. Otherwise session ready.
_PAGE_OPEN_TS_KEYS = (
    "page_open_at_ts",
    "page_opened_at_ts",
    "page_open_at",
    "opened_at_ts",
)
_SESSION_READY_TS_KEYS = (
    "browser_ready_at_ts",
    "browser_session_ready_at_ts",
    "session_ready_at_ts",
    "browser_ready_at",
    "session_ready_at",
)
_AX_KEYS = (
    "ax_tree",
    "accessibility_tree",
    "ax",
    "accessibility",
    "ax_text",
)
# Epoch of the first click/type/scroll written onto the live session.
# `first_action_s` is a monotonic duration inside the agent and is not a stamp.
_FIRST_ACTION_TS_KEYS = (
    "first_action_at_ts",
    "first_action_at",
)
# Per-agent phase durations, milliseconds. Seconds under `timing.<phase>_s` adapt.
_PHASE_MS_KEYS = (
    "session_ready",
    "page_open",
    "first_action",
    "final_screenshot",
)


def missing_field(name: str) -> str:
    """Loud failure text. A gate that needed `name` and did not find it."""
    return f"missing field {name}"


def _epoch(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _clock_sources(run: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [run]
    steps = [step for step in (run.get("trace") or []) if isinstance(step, dict)]
    steps.sort(key=lambda step: int(step["step"]) if isinstance(step.get("step"), int) else 0)
    if steps:
        sources.append(steps[0])
    return sources


def _first_recorded_epoch(
    sources: list[dict[str, Any]], keys: tuple[str, ...]
) -> tuple[float | None, str]:
    for source in sources:
        for key in keys:
            stamp = _epoch(source.get(key))
            if stamp is not None:
                return stamp, key
    return None, ""


def first_action_epoch(run: dict[str, Any]) -> tuple[float | None, str]:
    """Epoch when the first click/type/scroll was written. Not `first_action_s`."""
    sources: list[dict[str, Any]] = [run]
    for step in run.get("trace") or []:
        if isinstance(step, dict) and is_click_type_scroll(step.get("action")):
            sources.append(step)
            break
    return _first_recorded_epoch(sources, _FIRST_ACTION_TS_KEYS)


def _phase_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def phase_ms_of(run: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """Milliseconds per phase. Accepts `phase_ms` or `timing.<phase>_ms` / `_s`."""
    raw = run.get("phase_ms") if isinstance(run.get("phase_ms"), dict) else {}
    timing = run.get("timing") if isinstance(run.get("timing"), dict) else {}
    found: dict[str, float] = {}
    missing: list[str] = []
    for key in _PHASE_MS_KEYS:
        number = _phase_number(raw.get(key))
        if number is None:
            number = _phase_number(raw.get(f"{key}_ms"))
        if number is None:
            number = _phase_number(timing.get(f"{key}_ms"))
        if number is None:
            seconds = _phase_number(timing.get(f"{key}_s"))
            if seconds is not None:
                number = seconds * 1000.0
        if number is None:
            missing.append(f"phase_ms.{key}")
        else:
            found[key] = number
    if not raw and not timing and missing:
        return {}, ["phase_ms"]
    return found, missing


def failed_step_fields(run: dict[str, Any]) -> tuple[str, str]:
    """Phase and reason of the step that failed.

    Contract is `failed_step.phase` and `failed_step.reason`. A last trace step
    with those keys, or `run_issue.kind` / `run_issue.reason`, is the same pair.
    """
    blob = run.get("failed_step") if isinstance(run.get("failed_step"), dict) else {}
    phase = str(blob.get("phase") or "").strip()
    reason = str(blob.get("reason") or "").strip()
    numbered = _numbered_steps(run)
    last = numbered[-1] if numbered else {}
    if not phase:
        phase = str(last.get("phase") or "").strip()
    if not reason:
        reason = str(last.get("reason") or "").strip()
    issue = run.get("run_issue") if isinstance(run.get("run_issue"), dict) else {}
    if not phase:
        phase = str(issue.get("phase") or issue.get("kind") or "").strip()
    if not reason:
        reason = str(issue.get("reason") or "").strip()
    if not phase:
        phase = missing_field("failed_step_phase")
    if not reason:
        reason = missing_field("failed_step_reason")
    return phase, reason


def action_clock_start(run: dict[str, Any]) -> tuple[float | None, str]:
    """When this agent could act: page open if recorded, else browser session ready.

    Screenshot timestamps are not a start. The study JSON supplies whichever
    of those two events it recorded.
    """
    sources = _clock_sources(run)
    opened, key = _first_recorded_epoch(sources, _PAGE_OPEN_TS_KEYS)
    if opened is not None:
        return opened, key
    ready, key = _first_recorded_epoch(sources, _SESSION_READY_TS_KEYS)
    if ready is not None:
        return ready, key
    return None, ""


def _host_of(url: object) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    host = (urlsplit(text).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _ax_blob(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)) and value:
        try:
            import json

            return json.dumps(value, default=str)[:2000]
        except Exception:
            return ""
    return ""


def ax_text(obj: object) -> str:
    """Accessibility tree text recorded on a run, step, or evidence row."""
    if not isinstance(obj, dict):
        return ""
    for key in _AX_KEYS:
        text = _ax_blob(obj.get(key))
        if text and text.lower() not in {"{}", "[]", "null", "none"}:
            return text
    sig = obj.get("state_sig")
    if isinstance(sig, dict):
        for key in _AX_KEYS:
            text = _ax_blob(sig.get(key))
            if text and text.lower() not in {"{}", "[]", "null", "none"}:
                return text
    return ""


def run_has_ax(run: dict[str, Any]) -> bool:
    if ax_text(run):
        return True
    for step in run.get("trace") or []:
        if ax_text(step):
            return True
    return False


def opened_url_of(run: dict[str, Any]) -> str:
    """URL the study recorded when the page opened, else the first trace URL."""
    for key in ("page_url", "opened_url", "current_url"):
        text = str(run.get(key) or "").strip()
        if text:
            return text
    steps = [step for step in (run.get("trace") or []) if isinstance(step, dict)]
    steps.sort(key=lambda step: int(step["step"]) if isinstance(step.get("step"), int) else 0)
    for step in steps:
        text = str(step.get("url") or "").strip()
        if text:
            return text
    return str(run.get("final_url") or "").strip()


def opened_on_assigned_site(run: dict[str, Any]) -> bool:
    site = _host_of(run.get("site_url"))
    opened = _host_of(opened_url_of(run))
    return bool(site) and site == opened


def created_epoch(run: dict[str, Any]) -> float | None:
    return _epoch(run.get("created_at_ts")) or _epoch(run.get("created_at"))


def remember_earliest_clocks(
    runs: list[dict[str, Any]],
    latch: dict[str, dict[str, float]],
) -> None:
    """Keep the earliest created and page-open stamps seen on each agent.

    A later poll that moves those stamps forward (both rewritten to the
    response time) must not shrink time_to_first_action or the 5s open gap.
    The action time stays the poll that first showed the click.
    """
    for run in runs:
        if not isinstance(run, dict):
            continue
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        if not aid:
            continue
        slot = latch.setdefault(aid, {})
        created = created_epoch(run)
        if created is not None:
            prev = slot.get("created_at_ts")
            if prev is None or created < prev:
                slot["created_at_ts"] = created
        opened, _key = _first_recorded_epoch(_clock_sources(run), _PAGE_OPEN_TS_KEYS)
        if opened is not None:
            prev_open = slot.get("page_open_at_ts")
            if prev_open is None or opened < prev_open:
                slot["page_open_at_ts"] = opened
        if "created_at_ts" in slot:
            run["created_at_ts"] = slot["created_at_ts"]
        if "page_open_at_ts" in slot:
            run["page_open_at_ts"] = slot["page_open_at_ts"]


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
    """Time from browser-session ready or page open to a click/type/scroll in the live UI.

    The start is whichever of those the study JSON recorded (page open first,
    otherwise session ready). Screenshot time is not the start. `action_seen_at`
    is the harness poll time when that action showed up in the study payload.
    The pass bar is median <= 5s and max <= 10s at 24 agents. Abort when any
    agent whose clock has started still has no such action after `abort_after_s`
    (default 10s). A higher value only delays the abort.
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
    missing_start: list[dict[str, Any]] = []
    for run in agents:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        started, start_key = action_clock_start(run)
        acted = has_click_type_scroll(run)
        appeared = action_seen_at.get(aid) if aid else None
        latency = None
        waited = None
        if started is not None and acted and appeared is not None:
            latency = max(0.0, float(appeared) - float(started))
            latencies.append(latency)
        elif started is not None and not acted:
            waited = float(now) - float(started)
            idle.append(run)
            if waited > ceiling:
                blown.append(run)
        elif not acted:
            idle.append(run)
            created = created_epoch(run)
            age = None if created is None else float(now) - float(created)
            if age is None or age > ceiling:
                missing_start.append(run)
        per_agent.append(
            {
                "agent_id": aid,
                "started_at": started,
                "start": start_key,
                "action_seen_at": appeared,
                "latency_s": None if latency is None else round(latency, 3),
                "waited_s": None if waited is None else round(waited, 3),
            }
        )
    median = _median(latencies)
    maximum = max(latencies) if latencies else None
    abort = bool(blown or missing_start)
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
    missing_fields: list[str] = ["page_open_at_ts"] if missing_start else []
    if missing_start:
        reason = (
            f"{missing_field('page_open_at_ts')}: {len(missing_start)}/{len(agents)} "
            "agents have no page-open or session-ready stamp"
        )
    if blown:
        waits = ", ".join(
            f"{str(run.get('agent_id') or '')}="
            f"{max(0.0, float(now) - float(action_clock_start(run)[0] or now)):.1f}s"
            for run in blown[:8]
        )
        reason = (
            f"FAIL time_to_first_action: {len(blown)}/{len(agents)} agents had no "
            f"click/type/scroll {ceiling:.0f}s after browser session ready or page open "
            f"({waits})"
        )
        seen = "; ".join(last_seen_text(run) for run in blown[:8])
        if seen:
            reason = f"{reason}. {seen}"
        if missing_start and not reason.startswith("missing field"):
            reason = f"{missing_field('page_open_at_ts')}. {reason}"
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
        "ids": [str(run.get("agent_id") or "") for run in (*blown, *missing_start)],
        "missing_fields": missing_fields,
        "reason": reason,
        "detail": reason,
        "per_agent": per_agent,
    }


def assess_recorded_time_to_first_action(
    runs: list[dict[str, Any]],
    *,
    median_s: float = DEFAULT_TTFA_MEDIAN_S,
    max_s: float = DEFAULT_TTFA_MAX_S,
    expected: int = PASS_AGENT_BAR,
) -> dict[str, Any]:
    """Offline clock from page_open_at_ts (or session ready) to first_action_at_ts.

    `first_action_s` is not an epoch and does not satisfy this clock. A missing
    stamp fails the gate; it does not count as unmeasured.
    """
    agents = [run for run in runs if isinstance(run, dict)]
    need = int(expected) if int(expected) > 0 else PASS_AGENT_BAR
    latencies: list[float] = []
    missing_open = False
    missing_action = False
    idle = 0
    for run in agents:
        started, _key = action_clock_start(run)
        if started is None:
            missing_open = True
            continue
        acted = has_click_type_scroll(run)
        acted_at, _stamp = first_action_epoch(run)
        if acted and acted_at is None:
            missing_action = True
            continue
        if acted_at is None:
            idle += 1
            continue
        latencies.append(max(0.0, float(acted_at) - float(started)))
    median = _median(latencies)
    maximum = max(latencies) if latencies else None
    missing_fields: list[str] = []
    if missing_open:
        missing_fields.append("page_open_at_ts")
    if missing_action:
        missing_fields.append("first_action_at_ts")
    complete = (
        not missing_fields
        and len(agents) >= need
        and len(latencies) == len(agents)
        and len(latencies) >= need
    )
    ok = (
        complete
        and median is not None
        and maximum is not None
        and median <= float(median_s)
        and maximum <= float(max_s)
    )
    if missing_fields:
        detail = "; ".join(missing_field(name) for name in missing_fields)
    elif not ok:
        detail = (
            f"median={median} max={maximum} n={len(latencies)}/{need} idle={idle}"
        )
    else:
        detail = ""
    return {
        "measured": True,
        "ok": ok,
        "median_s": None if median is None else round(median, 3),
        "max_s": None if maximum is None else round(maximum, 3),
        "n": len(latencies),
        "agents": len(agents),
        "missing_fields": missing_fields,
        "detail": detail,
        "reason": detail,
    }


def assess_page_opened(
    runs: list[dict[str, Any]],
    *,
    now: float | None = None,
    limit_s: float = DEFAULT_FIRST_SHOT_S,
) -> dict[str, Any]:
    """Every agent opened its assigned site within `limit_s`, confirmed by URL and AX.

    The clock is creation → the page-open timestamp the study recorded. When
    the study only stored browser-session ready, that stamp is the open time
    once URL and the accessibility tree confirm the page. Vision is not used.
    """
    agents = [run for run in runs if isinstance(run, dict)]
    limit = float(limit_s)
    opened_n = 0
    slow: list[str] = []
    wrong: list[str] = []
    missing_ax: list[str] = []
    waiting: list[str] = []
    missing_names: list[str] = []

    def _note(name: str) -> None:
        if name not in missing_names:
            missing_names.append(name)

    for run in agents:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        created = created_epoch(run)
        on_site = opened_on_assigned_site(run)
        has_ax = run_has_ax(run)
        sources = _clock_sources(run)
        open_ts, _key = _first_recorded_epoch(sources, _PAGE_OPEN_TS_KEYS)
        if open_ts is None and on_site and has_ax:
            open_ts, _key = _first_recorded_epoch(sources, _SESSION_READY_TS_KEYS)
        gap = None
        if created is not None and open_ts is not None:
            gap = max(0.0, open_ts - created)
        age = None
        if created is not None and now is not None:
            age = float(now) - created
        past_limit = (gap is not None and gap > limit) or (
            age is not None and age > limit and gap is None
        )
        finished = now is None
        stamp_missing = open_ts is None
        if on_site and has_ax and gap is not None and gap <= limit:
            opened_n += 1
            continue
        if opened_url_of(run) and not on_site:
            wrong.append(aid)
        elif on_site and not has_ax and (past_limit or finished or gap is not None):
            missing_ax.append(aid)
            _note("ax_tree")
            if stamp_missing:
                _note("page_open_at_ts")
        elif gap is not None and gap > limit:
            slow.append(aid)
        elif past_limit or finished:
            slow.append(aid)
            if stamp_missing:
                _note("page_open_at_ts")
            if not has_ax:
                _note("ax_tree")
        else:
            waiting.append(aid)
    abort = bool(wrong or slow or missing_ax)
    ok = bool(agents) and opened_n == len(agents) and not waiting and not abort
    reason = ""
    if abort and missing_names:
        reason = "; ".join(missing_field(name) for name in missing_names)
        reason = f"{reason}: {opened_n}/{len(agents)} agents"
    elif abort:
        parts = []
        if wrong:
            parts.append(f"wrong site={len(wrong)}")
        if missing_ax:
            parts.append(f"no accessibility tree={len(missing_ax)}")
        if slow:
            parts.append(f"opened after {limit:.0f}s={len(slow)}")
        reason = (
            f"FAIL page_opened: {opened_n}/{len(agents)} agents opened the assigned "
            f"site within {limit:.0f}s ({', '.join(parts)})"
        )
    return {
        "measured": True,
        "ok": ok,
        "abort": abort,
        "opened": opened_n,
        "agents": len(agents),
        "slow": len(slow),
        "wrong_site": len(wrong),
        "missing_ax": len(missing_ax),
        "waiting": len(waiting),
        "limit_s": limit,
        "reason": reason,
        "detail": reason,
        "ids": wrong + missing_ax + slow,
        "missing_fields": list(missing_names),
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
    """Last DOM text, or the accessibility tree when that is the page read."""
    for step in reversed(run.get("trace") or []):
        if not isinstance(step, dict):
            continue
        sig = step.get("state_sig")
        if isinstance(sig, dict) and str(sig.get("text") or "").strip():
            return str(sig.get("text") or "").strip()[:limit]
    text = ax_text(run)
    if text:
        return text[:limit]
    for step in reversed(run.get("trace") or []):
        text = ax_text(step)
        if text:
            return text[:limit]
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


def _cited_step(run: dict[str, Any], step_n: int) -> dict[str, Any] | None:
    for step in _numbered_steps(run):
        if int(step["step"]) == step_n:
            return step
    return None


def _final_screenshot_url(run: dict[str, Any], evidence: dict[str, Any]) -> str:
    """The one final screenshot. A per-step shot still counts for older reports."""
    for source in (evidence, run):
        for key in ("final_screenshot", "final_screenshot_url", "screenshot_url"):
            text = str(source.get(key) or "").strip()
            if text:
                return text
    shot = _final_shot(run)
    return str((shot or {}).get("screenshot_url") or "").strip()


def _evidence_ok(
    evidence: dict[str, Any],
    runs_by_id: dict[str, dict[str, Any]],
    study: dict[str, Any],
    loader: Callable[[str], bool] | None,
) -> bool:
    """A strength or weakness cites a step's URL or AX tree, plus the final screenshot."""
    aid = str(evidence.get("agent_id") or "")
    if not aid or not isinstance(evidence.get("step"), int):
        return False
    run = runs_by_id.get(aid)
    if not run or not beyond_first_screen(run, _start_url(run, study)):
        return False
    cited = _cited_step(run, int(evidence["step"])) or {}
    step_url = str(
        evidence.get("step_url") or evidence.get("url") or cited.get("url") or ""
    ).strip()
    ax = ax_text(evidence) or ax_text(cited)
    if not step_url and not ax:
        return False
    return _screenshot_ok(_final_screenshot_url(run, evidence), loader)


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


def _headline_gates(startup: dict[str, Any]) -> list[dict[str, Any]]:
    """The two clocks the summary leads with. Per-agent time_to_first_action stays separate."""
    value_limit = float(
        startup.get("time_to_first_value_max_s") or DEFAULT_TIME_TO_FIRST_VALUE_S
    )
    budget = float(
        startup.get("study_budget_s")
        or startup.get("max_elapsed_s")
        or DEFAULT_STUDY_BUDGET_S
    )
    raw_value = startup.get("time_to_first_value_s")
    if raw_value is None:
        value_ok = False
        value_text = "not recorded"
    else:
        seconds = float(raw_value)
        value_ok = seconds <= value_limit
        value_text = f"{seconds}s"
    agent = str(startup.get("time_to_first_value_agent") or "")
    raw_total = startup.get("total_time_s")
    ready = startup.get("report_ready")
    if raw_total is None:
        total_ok = False
        total_text = "not ready"
    else:
        total_s = float(raw_total)
        ready_ok = ready is not False
        total_ok = ready_ok and total_s <= budget
        total_text = f"{total_s}s" if ready_ok else f"{total_s}s, report not ready"
    return [
        _gate(
            "time_to_first_value",
            "Time to first value",
            value_text,
            (
                f"<= {value_limit:.0f}s from URL submit until the first "
                "click, type, or scroll is visible in the live UI"
            ),
            value_ok,
            f"agent={agent}" if agent else "",
        ),
        _gate(
            "total_time",
            "Total time",
            total_text,
            f"<= {budget:.0f}s from URL submit until the report is ready",
            total_ok,
            "8-minute study budget.",
        ),
    ]


def _page_opened_gate(
    runs: list[dict[str, Any]],
    startup: dict[str, Any],
    limit_s: float,
) -> dict[str, Any]:
    check = startup.get("page_open_check")
    if not (isinstance(check, dict) and check.get("measured")):
        check = assess_page_opened(runs, limit_s=limit_s)
    opened = check.get("opened")
    agents = check.get("agents")
    missing = [str(name) for name in (check.get("missing_fields") or [])]
    if missing and not check.get("ok"):
        value = "; ".join(missing_field(name) for name in missing)
    else:
        value = f"{opened}/{agents} within {limit_s:.0f}s"
    return _gate(
        "page_opened",
        "Page opened on the assigned site",
        value,
        (
            f"<= {limit_s:.0f}s from agent creation, URL host matches the assigned "
            "site, accessibility tree present"
        ),
        bool(check.get("ok")),
        str(check.get("detail") or check.get("reason") or ""),
    )


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
    elapsed = startup.get("elapsed_s")
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
        _page_opened_gate(runs, startup, first_shot_s),
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
    if not (isinstance(ttfa, dict) and ttfa.get("measured")):
        ttfa = assess_recorded_time_to_first_action(
            runs,
            median_s=median_lim,
            max_s=max_lim,
            expected=ttfa_need,
        )
    med = ttfa.get("median_s")
    mx = ttfa.get("max_s")
    got = ttfa.get("n")
    missing = [str(name) for name in (ttfa.get("missing_fields") or [])]
    starts = [
        str(row.get("start") or "")
        for row in (ttfa.get("per_agent") or [])
        if isinstance(row, dict)
    ]
    if not missing and starts and not any(starts) and not ttfa.get("ok"):
        missing = ["page_open_at_ts"]
    if missing and not ttfa.get("ok"):
        value = "; ".join(missing_field(name) for name in missing)
    else:
        med_txt = "n/a" if med is None else f"{med}s"
        max_txt = "n/a" if mx is None else f"{mx}s"
        value = f"median={med_txt} max={max_txt} n={got}/{ttfa_need}"
    gates.append(
        _gate(
            "time_to_first_action",
            "Time to first action",
            value,
            (
                f"median <= {median_lim:.0f}s and max <= {max_lim:.0f}s "
                f"at {ttfa_need} agents"
            ),
            bool(ttfa.get("ok")),
            str(ttfa.get("detail") or ttfa.get("reason") or ""),
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


def _failure_contract(run: dict[str, Any], base_url: str, shot_url: str) -> dict[str, Any]:
    phase, reason = failed_step_fields(run)
    found, missing = phase_ms_of(run)
    dedicated = _run_final_screenshot(run)
    url = dedicated or shot_url
    return {
        "failed_step_phase": phase,
        "failed_step_reason": reason,
        "phase_ms": (
            "; ".join(missing_field(name) for name in missing) if missing else found
        ),
        "final_screenshot": (
            _absolute_url(base_url, url) if url else missing_field("final_screenshot_url")
        ),
        "final_url": final_url_of(run) or missing_field("final_url"),
    }


def _phase_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("failed_step_phase") or missing_field("failed_step_phase"))
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"phase": phase, "n": count} for phase, count in ordered]


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
                **_failure_contract(run, base_url, shot_url),
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
        "phase_counts": _phase_counts(failed),
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
                **_failure_contract(run, base_url, shot_url),
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
        "phase_counts": _phase_counts(failed),
        "failed_runs": failed,
    }


def _run_final_screenshot(run: dict[str, Any]) -> str:
    """The async final screenshot. A per-step URL is not this field."""
    for key in ("final_screenshot_url", "final_screenshot"):
        text = str(run.get(key) or "").strip()
        if text:
            return text
    return ""


def _field_contract_gates(
    runs: list[dict[str, Any]],
    vision_goal: dict[str, object],
    study: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fields PR #47 must write. A missing one fails; it is not skipped."""
    agents = [run for run in runs if isinstance(run, dict)]
    phase_names: list[str] = []
    for run in agents:
        _found, missing = phase_ms_of(run)
        for name in missing:
            if name not in phase_names:
                phase_names.append(name)
    if not agents:
        phase_names = ["phase_ms"]
    phase_ok = not phase_names
    phase_value = (
        f"{len(agents)}/{len(agents)}"
        if phase_ok
        else "; ".join(missing_field(name) for name in phase_names)
    )

    shot_missing = [run for run in agents if not _run_final_screenshot(run)]
    shot_ok = bool(agents) and not shot_missing
    shot_value = (
        f"{len(agents) - len(shot_missing)}/{len(agents)}"
        if shot_ok
        else missing_field("final_screenshot_url")
    )

    url_missing = [run for run in agents if not final_url_of(run)]
    dom_missing = [run for run in agents if not final_dom_of(run)]
    judge_names: list[str] = []
    if not agents or url_missing:
        judge_names.append("final_url")
    if not agents or dom_missing:
        judge_names.append("state_sig.text")
    judge_ok = not judge_names
    judge_value = (
        f"{len(agents)}/{len(agents)}"
        if judge_ok
        else "; ".join(missing_field(name) for name in judge_names)
    )

    failed_runs = []
    for run in agents:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        if product_run_succeeded(run, _start_url(run, study), vision_goal=vision_goal.get(aid)):
            continue
        failed_runs.append(run)
    step_names: list[str] = []
    for run in failed_runs:
        phase, reason = failed_step_fields(run)
        if phase.startswith("missing field") and "failed_step_phase" not in step_names:
            step_names.append("failed_step_phase")
        if reason.startswith("missing field") and "failed_step_reason" not in step_names:
            step_names.append("failed_step_reason")
    step_ok = not step_names
    if not agents and not step_names:
        step_names = ["failed_step_phase"]
        step_ok = False
    step_value = (
        f"{len(failed_runs)} failed runs"
        if step_ok
        else "; ".join(missing_field(name) for name in step_names)
    )
    return [
        _gate(
            "phase_ms",
            "Per-phase milliseconds",
            phase_value,
            "each agent has phase_ms.session_ready, page_open, first_action, final_screenshot",
            phase_ok,
            f"missing_agents={len([r for r in agents if phase_ms_of(r)[1]])}" if not phase_ok else "",
        ),
        _gate(
            "final_screenshot",
            "Final screenshot",
            shot_value,
            "each agent has final_screenshot_url (one async capture for the judge)",
            shot_ok,
            "",
        ),
        _gate(
            "judge_inputs",
            "Final URL and page text for the judge",
            judge_value,
            "final_url plus state_sig.text or ax_tree on every agent",
            judge_ok,
            "",
        ),
        _gate(
            "failed_step",
            "Failed-step phase and reason",
            step_value,
            "every failed run has failed_step.phase and failed_step.reason",
            step_ok,
            "",
        ),
    ]


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

    gates = (
        _headline_gates(startup)
        + _startup_gates(study, runs, startup, abort_reason)
        + _field_contract_gates(runs, vision_goal, study)
    )
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
                ">= 1 strength with agent, step, AX or URL, and the final screenshot",
                len(good_strengths) >= 1,
            ),
            _gate(
                "product_weakness",
                "Product weakness from a run past the first screen",
                f"{len(good_weaknesses)}/{len(weaknesses)}",
                ">= 1 weakness with agent, step, AX or URL, and the final screenshot",
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
    by_id = {str(g.get("id")): g for g in (result.get("gates") or []) if isinstance(g, dict)}
    lines = [
        "# Strict e2e gates",
        "",
        "## Headline",
        "",
    ]
    for gate_id in ("time_to_first_value", "total_time"):
        gate = by_id.get(gate_id)
        if not gate:
            continue
        mark = "PASS" if gate.get("pass") else "FAIL"
        lines.append(
            f"- `{gate_id}`: {gate.get('value')} (threshold {gate.get('threshold')}) {mark}"
        )
    lines.extend(
        [
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
    )
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
