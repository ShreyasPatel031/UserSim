"""Browser Use agent runs for MVP — screenshots with DOM bounding boxes."""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from capability import CAPABLE_AGENT_PREAMBLE, USER_AGENT, VIEWPORT, location_for
from capability.browserbase_client import close_session, create_session
from auth import vertex_credentials
from config import GCP_PROJECT, MODEL

from mvp.paths import MVP_RUNS_DIR

# Enough steps to leave the landing page: land, scroll, open a nav item, read, come back.
MVP_MAX_STEPS = int(os.environ.get("MVP_MAX_BROWSER_STEPS", "12"))
# Backstop only. A step is supposed to decide in a few seconds: the first
# click comes from the opening screenshot, and later DOM captures are capped.
# These ceilings stop a stuck CDP call from cancelling the step before a
# history item exists. They are not what makes the agent fast.
DEFAULT_LLM_TIMEOUT_S = 30
DEFAULT_STEP_TIMEOUT_S = 60
MVP_LLM_TIMEOUT_S = int(os.environ.get("MVP_LLM_TIMEOUT_S", "") or DEFAULT_LLM_TIMEOUT_S)
MVP_STEP_TIMEOUT_S = int(os.environ.get("MVP_STEP_TIMEOUT_S", "") or DEFAULT_STEP_TIMEOUT_S)
MVP_HOLD_S = float(os.environ.get("MVP_PRESS_HOLD_S", "10") or "10")
# Viewport-only DOM, a small element list, and a hard stop so one state
# capture cannot sit on the CDP connection until browser-use's 30s timeout.
DOM_BUDGET_S = float(os.environ.get("MVP_DOM_BUDGET_S", "") or "4")
SHOT_BUDGET_S = float(os.environ.get("MVP_SHOT_BUDGET_S", "") or "5")
# The decision waits this long for a state capture, then continues on the
# screenshot. A stuck CDP call is left running so it cannot hold the step.
STATE_BUDGET_S = float(os.environ.get("MVP_STATE_BUDGET_S", "") or "4")
DOM_ELEMENT_CAP = int(os.environ.get("MVP_DOM_ELEMENT_CAP", "") or "40")
_VISION_IMAGE = (800, 450)

# Measurement only. Each phase prints one JSON line and is copied onto the
# trace step. where/step are task-local so a background DOM capture and the
# vision call do not stamp each other's timings.
_PHASE_WHERE = contextvars.ContextVar("usersim_phase_where", default="loop")
_PHASE_STEP = contextvars.ContextVar("usersim_phase_step", default=None)
_PHASE_LOG = Path("/tmp/usersim_phase/events.jsonl")
_HTTP_STATUS_RE = re.compile(r"\b(408|429|500|502|503|504)\b")


def _http_status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int) and 100 <= val < 600:
            return val
    response = getattr(exc, "response", None)
    if response is not None:
        val = getattr(response, "status_code", None)
        if isinstance(val, int) and 100 <= val < 600:
            return val
    match = _HTTP_STATUS_RE.search(str(exc))
    if match:
        return int(match.group(1))
    return None


class _PhaseClock:
    """Per-agent phase timings. Writes survive a killed run via stdout and jsonl."""

    def __init__(self, agent_id: str, study_id: str) -> None:
        self.agent_id = agent_id
        self.study_id = study_id
        self.events: list[dict[str, Any]] = []
        self.current_step: int | None = None
        self.hook_step: int | None = None

    def event(self, **rec: Any) -> None:
        where = str(rec.pop("where", None) or _PHASE_WHERE.get() or "loop")
        step = rec.get("step")
        if step is None:
            pinned = _PHASE_STEP.get()
            if pinned is not None:
                step = pinned
            else:
                step = self.hook_step if where == "hook" else self.current_step
        row: dict[str, Any] = {
            "t": round(time.time(), 3),
            "agent_id": self.agent_id,
            "study_id": self.study_id,
            "where": where,
            **rec,
            "step": step,
        }
        self.events.append(row)
        line = json.dumps(row, default=str)
        print(f"[phase] {line}", flush=True)
        try:
            _PHASE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _PHASE_LOG.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

    def begin(self, phase: str, **extra: Any) -> float:
        self.event(event="start", phase=phase, **extra)
        return time.monotonic()

    def finish(self, phase: str, started: float, **extra: Any) -> None:
        self.event(
            event="end",
            phase=phase,
            ms=round((time.monotonic() - started) * 1000),
            **extra,
        )

    def note_exception(self, phase: str, exc: BaseException, **extra: Any) -> str:
        text = f"{type(exc).__name__}: {exc}"[:400]
        self.event(
            event="end",
            phase=phase,
            ms=0,
            error=text,
            error_type=type(exc).__name__,
            http_status=_http_status_of(exc),
            **extra,
        )
        return text

    def fields_for(self, step_no: object) -> dict[str, Any]:
        if not isinstance(step_no, int):
            return {}
        phase_ms: dict[str, int] = {}
        llm_status = None
        llm_retries = None
        errors: list[str] = []
        for ev in self.events:
            if ev.get("step") != step_no or ev.get("event") != "end":
                continue
            where = str(ev.get("where") or "loop")
            phase = str(ev.get("phase") or "")
            if not phase:
                continue
            key = phase if where == "loop" else f"{where}_{phase}"
            if isinstance(ev.get("ms"), int):
                phase_ms[key] = int(ev["ms"])
            if phase == "llm" and where == "loop":
                llm_status = ev.get("http_status")
                llm_retries = ev.get("retry_count")
            if ev.get("error"):
                errors.append(f"{key}: {ev.get('error')}")
        out: dict[str, Any] = {}
        if phase_ms:
            out["phase_ms"] = phase_ms
        if llm_status is not None:
            out["llm_http_status"] = llm_status
        if llm_retries is not None:
            out["llm_retry_count"] = llm_retries
        if errors:
            out["swallowed_error"] = " | ".join(errors)[:800]
        return out


def _patch_method(obj: Any, name: str, wrapper: Any) -> bool:
    try:
        setattr(obj, name, wrapper)
        return True
    except Exception:
        try:
            object.__setattr__(obj, name, wrapper)
            return True
        except Exception as exc:
            print(
                f"[phase] could not patch {type(obj).__name__}.{name}: {exc!r}",
                flush=True,
            )
            return False


def _cheap_dom_flags() -> dict[str, Any]:
    """Viewport-only DOM, no highlight pass, almost no idle wait."""
    return {
        "highlight_elements": False,
        "dom_highlight_elements": False,
        "cross_origin_iframes": False,
        "max_iframes": 1,
        "max_iframe_depth": 0,
        "paint_order_filtering": True,
        "minimum_wait_page_load_time": 0.05,
        "wait_for_network_idle_page_load_time": 0.05,
        "wait_between_actions": 0.05,
    }


def _ensure_cheap_dom_service(watchdog: Any, browser_session: Any) -> None:
    """Build the DOM service once, scoped to the viewport and one frame."""
    svc = getattr(watchdog, "_dom_service", None)
    if svc is not None:
        svc.viewport_threshold = 0
        svc.max_iframes = 1
        svc.max_iframe_depth = 0
        svc.cross_origin_iframes = False
        return
    from browser_use.dom.service import DomService

    watchdog._dom_service = DomService(
        browser_session=browser_session,
        logger=getattr(watchdog, "logger", None),
        cross_origin_iframes=False,
        paint_order_filtering=True,
        max_iframes=1,
        max_iframe_depth=0,
        viewport_threshold=0,
    )


def _cap_dom_elements(state: Any, limit: int) -> Any:
    """Keep a short viewport-first element list for the model."""
    if limit <= 0 or state is None:
        return state
    smap = getattr(state, "selector_map", None)
    if not isinstance(smap, dict) or len(smap) <= limit:
        return state
    vw = float(VIEWPORT["width"])
    vh = float(VIEWPORT["height"])

    def _in_view(node: Any) -> bool:
        snap = getattr(node, "snapshot_node", None)
        bounds = getattr(snap, "bounds", None)
        if bounds is None:
            return True
        x = float(getattr(bounds, "x", 0) or 0)
        y = float(getattr(bounds, "y", 0) or 0)
        w = float(getattr(bounds, "width", 0) or 0)
        h = float(getattr(bounds, "height", 0) or 0)
        return x < vw and y < vh and x + w > 0 and y + h > 0

    ranked = sorted(smap.items(), key=lambda item: (0 if _in_view(item[1]) else 1, item[0]))
    keep = {idx for idx, _node in ranked[:limit]}
    for idx in list(smap):
        if idx not in keep:
            smap.pop(idx, None)

    def _walk(node: Any) -> None:
        if node is None:
            return
        idx = getattr(node, "selector_index", None)
        if idx is not None and idx not in keep:
            try:
                node.is_interactive = False
                node.selector_index = None
            except Exception:
                pass
        for child in getattr(node, "children", None) or []:
            _walk(child)

    _walk(getattr(state, "_root", None))
    return state


def _empty_dom_state() -> Any:
    from browser_use.dom.views import SerializedDOMState

    return SerializedDOMState(_root=None, selector_map={})


def _empty_browser_state(reason: str, browser_session: Any = None) -> Any:
    """DOM-less state so the model can still click the last screenshot."""
    from browser_use.browser.views import BrowserStateSummary

    screenshot = None
    url = ""
    title = "Browser state unavailable"
    tabs: list[Any] = []
    if browser_session is not None:
        cached = getattr(browser_session, "_cached_browser_state_summary", None)
        if cached is not None:
            screenshot = getattr(cached, "screenshot", None) or None
            url = str(getattr(cached, "url", "") or "")
            cached_title = getattr(cached, "title", None)
            if cached_title:
                title = str(cached_title)
            tabs = list(getattr(cached, "tabs", None) or [])
        if not screenshot:
            screenshot = getattr(browser_session, "_usersim_fallback_screenshot", None)
    return BrowserStateSummary(
        dom_state=_empty_dom_state(),
        url=url,
        title=title,
        tabs=tabs,
        screenshot=screenshot,
        browser_errors=[reason[:300]],
        state_error=reason[:300],
    )


async def _await_budget(task: asyncio.Task, timeout: float) -> Any:
    """Return the task result, or None once the budget passes.

    The task is left running. Cancelling a CDP call and then waiting for that
    cancel used to hold the step until the 30s browser-state timeout.
    """
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task not in done:
        return None
    if task.cancelled():
        return None
    exc = task.exception()
    if exc is not None:
        if isinstance(exc, asyncio.CancelledError):
            return None
        raise exc
    return task.result()


def _install_session_probes(browser_session: Any, clock: _PhaseClock) -> None:
    """Time DOM extraction, screenshots, and navigation on this session only."""
    if browser_session is None or getattr(browser_session, "_phase_probes", False):
        return
    try:
        object.__setattr__(browser_session, "_phase_probes", True)
    except Exception:
        pass

    orig_state = browser_session.get_browser_state_summary
    try:
        object.__setattr__(browser_session, "_usersim_orig_state", orig_state)
    except Exception:
        pass

    def _remember_inflight(task: asyncio.Task) -> None:
        try:
            object.__setattr__(browser_session, "_usersim_state_inflight", task)
        except Exception:
            pass

    def _clear_inflight(task: asyncio.Task) -> None:
        if not task.done():
            return
        current = getattr(browser_session, "_usersim_state_inflight", None)
        if current is task:
            try:
                object.__setattr__(browser_session, "_usersim_state_inflight", None)
            except Exception:
                pass

    async def state_wrapped(*args: Any, **kwargs: Any) -> Any:
        # One capture per browser. A step that is still extracting is reused
        # instead of starting a second DOM walk on the same CDP connection.
        pending = getattr(browser_session, "_usersim_pending_state", None)
        inflight = getattr(browser_session, "_usersim_state_inflight", None)
        reused = False
        if pending is not None and pending is not asyncio.current_task():
            try:
                object.__setattr__(browser_session, "_usersim_pending_state", None)
            except Exception:
                pass
            task = pending
            reused = True
            _remember_inflight(task)
        elif (
            isinstance(inflight, asyncio.Task)
            and inflight is not asyncio.current_task()
            and not inflight.done()
        ):
            task = inflight
            reused = True
        else:
            # The event handler does the CDP work on another task. Holding the
            # slot here deadlocks that handler, which then returns no state.
            task = asyncio.create_task(orig_state(*args, **kwargs))
            _remember_inflight(task)
        started = clock.begin("state", reused=reused)
        error = None
        error_type = None
        try:
            result = await _await_budget(task, STATE_BUDGET_S)
            if result is None:
                error = f"TimeoutError: state budget {STATE_BUDGET_S:.0f}s"
                error_type = "TimeoutError"
                return _empty_browser_state(error, browser_session)
            state_error = getattr(result, "state_error", None)
            if state_error:
                error = str(state_error)[:400]
                error_type = "state_error"
            return result
        except asyncio.CancelledError:
            if _task_is_cancelling():
                error = "CancelledError: cancelled"
                error_type = "CancelledError"
                raise
            error = "CancelledError: state capture interrupted"
            error_type = "CancelledError"
            return _empty_browser_state(error, browser_session)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:400]
            error_type = type(exc).__name__
            raise
        finally:
            clock.finish(
                "state", started, error=error, error_type=error_type, reused=reused
            )
            _clear_inflight(task)

    _patch_method(browser_session, "get_browser_state_summary", state_wrapped)

    profile = getattr(browser_session, "browser_profile", None)
    if profile is not None:
        for key, value in _cheap_dom_flags().items():
            try:
                setattr(profile, key, value)
            except Exception:
                pass

    watchdog = getattr(browser_session, "_dom_watchdog", None)
    if watchdog is not None:
        orig_dom = watchdog._build_dom_tree_without_highlights

        async def dom_wrapped(*args: Any, **kwargs: Any) -> Any:
            started = clock.begin("dom")
            error = None
            error_type = None
            try:
                async with _CdpSlot():
                    try:
                        _ensure_cheap_dom_service(watchdog, browser_session)
                    except Exception as exc:
                        clock.note_exception("dom_service", exc)
                    result = await asyncio.wait_for(
                        orig_dom(*args, **kwargs), timeout=DOM_BUDGET_S
                    )
                return _cap_dom_elements(result, DOM_ELEMENT_CAP)
            except TimeoutError:
                error = f"TimeoutError: DOM budget {DOM_BUDGET_S:.0f}s"
                error_type = "TimeoutError"
                return _empty_dom_state()
            except asyncio.CancelledError:
                error = "CancelledError: cancelled"
                error_type = "CancelledError"
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:400]
                error_type = type(exc).__name__
                raise
            finally:
                clock.finish("dom", started, error=error, error_type=error_type)

        orig_shot = watchdog._capture_clean_screenshot

        async def shot_wrapped(*args: Any, **kwargs: Any) -> Any:
            started = clock.begin("screenshot")
            error = None
            error_type = None
            try:
                async with _CdpSlot():
                    return await asyncio.wait_for(
                        orig_shot(*args, **kwargs), timeout=SHOT_BUDGET_S
                    )
            except TimeoutError:
                error = f"TimeoutError: screenshot budget {SHOT_BUDGET_S:.0f}s"
                error_type = "TimeoutError"
                return None
            except asyncio.CancelledError:
                error = "CancelledError: cancelled"
                error_type = "CancelledError"
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:400]
                error_type = type(exc).__name__
                raise
            finally:
                clock.finish("screenshot", started, error=error, error_type=error_type)

        _patch_method(watchdog, "_build_dom_tree_without_highlights", dom_wrapped)
        _patch_method(watchdog, "_capture_clean_screenshot", shot_wrapped)

    if hasattr(browser_session, "navigate_to"):
        orig_nav = browser_session.navigate_to

        async def nav_wrapped(*args: Any, **kwargs: Any) -> Any:
            started = clock.begin("navigate")
            error = None
            error_type = None
            try:
                async with _CdpSlot():
                    return await orig_nav(*args, **kwargs)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:400]
                error_type = type(exc).__name__
                raise
            finally:
                clock.finish("navigate", started, error=error, error_type=error_type)

        _patch_method(browser_session, "navigate_to", nav_wrapped)

    if hasattr(browser_session, "take_screenshot"):
        orig_take = browser_session.take_screenshot

        async def take_wrapped(*args: Any, **kwargs: Any) -> Any:
            started = clock.begin("screenshot")
            error = None
            error_type = None
            try:
                async with _CdpSlot():
                    return await orig_take(*args, **kwargs)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:400]
                error_type = type(exc).__name__
                raise
            finally:
                clock.finish("screenshot", started, error=error, error_type=error_type)

        _patch_method(browser_session, "take_screenshot", take_wrapped)


def _wrap_llm_probe(llm: Any, clock: _PhaseClock, attempts: dict[str, Any]) -> None:
    try:
        client = llm.get_client()
        models = client.aio.models
        orig_gen = models.generate_content

        async def gen_wrapped(*args: Any, **kwargs: Any) -> Any:
            attempts["n"] = int(attempts["n"]) + 1
            try:
                return await orig_gen(*args, **kwargs)
            except Exception as exc:
                attempts["statuses"].append(_http_status_of(exc))
                raise

        _patch_method(models, "generate_content", gen_wrapped)
    except Exception as exc:
        clock.note_exception("llm_client", exc)

    orig_invoke = llm.ainvoke

    async def invoke_wrapped(*args: Any, **kwargs: Any) -> Any:
        attempts["n"] = 0
        attempts["statuses"] = []
        started = clock.begin("llm")
        status: int | None = 200
        error = None
        error_type = None
        try:
            return await orig_invoke(*args, **kwargs)
        except asyncio.CancelledError:
            status = None
            error = "CancelledError: cancelled"
            error_type = "CancelledError"
            raise
        except Exception as exc:
            statuses = [s for s in attempts["statuses"] if isinstance(s, int)]
            status = _http_status_of(exc) or (statuses[-1] if statuses else 0)
            error = f"{type(exc).__name__}: {exc}"[:400]
            error_type = type(exc).__name__
            raise
        finally:
            retry_count = max(0, int(attempts["n"]) - 1)
            clock.finish(
                "llm",
                started,
                http_status=status,
                retry_count=retry_count,
                attempt_count=int(attempts["n"]),
                retry_statuses=list(attempts["statuses"]),
                error=error,
                error_type=error_type,
            )

    _patch_method(llm, "ainvoke", invoke_wrapped)


_LLM_PROBES: set[int] = set()


def _install_agent_probes(agent: Any, llm: Any, clock: _PhaseClock) -> None:
    """Time the LLM call (status and retries) and action execution."""
    if id(llm) not in _LLM_PROBES:
        _LLM_PROBES.add(id(llm))
        _wrap_llm_probe(llm, clock, {"n": 0, "statuses": []})
    if agent is None:
        return
    orig_step = agent.step

    async def step_wrapped(step_info: Any = None) -> Any:
        offset = int(getattr(agent, "_usersim_step_offset", 0) or 0)
        step_no = int(getattr(getattr(agent, "state", None), "n_steps", 0) or 0) + offset
        clock.current_step = step_no
        token = _PHASE_STEP.set(step_no)
        started = clock.begin("step", step=step_no)
        error = None
        error_type = None
        try:
            return await orig_step(step_info)
        except asyncio.CancelledError:
            error = "CancelledError: cancelled"
            error_type = "CancelledError"
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:400]
            error_type = type(exc).__name__
            raise
        finally:
            clock.finish("step", started, step=step_no, error=error, error_type=error_type)
            _PHASE_STEP.reset(token)

    _patch_method(agent, "step", step_wrapped)

    orig_exec = agent._execute_actions

    async def exec_wrapped() -> Any:
        # The step rail updates when the action is chosen, before multi_act
        # and the post-step hook finish.
        _schedule_live_action(agent)
        started = clock.begin("action")
        error = None
        error_type = None
        try:
            return await orig_exec()
        except asyncio.CancelledError:
            error = "CancelledError: cancelled"
            error_type = "CancelledError"
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:400]
            error_type = type(exc).__name__
            raise
        finally:
            clock.finish("action", started, error=error, error_type=error_type)

    _patch_method(agent, "_execute_actions", exec_wrapped)

    orig_handle = agent._handle_step_error

    async def handle_wrapped(error: BaseException) -> Any:
        clock.note_exception("step_error", error, where="loop")
        return await orig_handle(error)

    _patch_method(agent, "_handle_step_error", handle_wrapped)


def _task_is_cancelling() -> bool:
    """True when this task itself was cancelled, not a child event timeout."""
    task = asyncio.current_task()
    cancelling = getattr(task, "cancelling", None)
    return bool(cancelling and cancelling())


def _cdp_failure_text(text: str) -> bool:
    return bool(_CDP_ERROR_RE.search(text or ""))


def _step_is_real_action(step: dict[str, Any]) -> bool:
    """A click, type, or scroll. Opening frames and recorded failures are not."""
    if not isinstance(step, dict) or not isinstance(step.get("step"), int):
        return False
    if int(step["step"]) <= 0 or step.get("timing_only") or step.get("failed_step"):
        return False
    action = str(step.get("action") or "")
    lowered = action.lower()
    if not action or lowered.startswith("open") or lowered.startswith("step failed"):
        return False
    return True


def _failure_phase(clock: _PhaseClock | None, step_no: int) -> str:
    """The phase that was in flight when the step died. The wrapper is last."""
    if clock is None:
        return "step"
    specific = ""
    for ev in clock.events:
        if ev.get("event") != "end" or ev.get("step") != step_no or not ev.get("error"):
            continue
        phase = str(ev.get("phase") or "")
        if phase and phase != "step":
            specific = phase
        elif phase == "step" and not specific:
            specific = "step"
    return specific or "step"


def _failure_reason(agent: Any, clock: _PhaseClock | None, step_no: int) -> tuple[str, str]:
    """Exception or timeout text, plus the phase that produced it."""
    texts: list[str] = []
    results = getattr(getattr(agent, "state", None), "last_result", None) or []
    for item in results:
        err = getattr(item, "error", None)
        if err:
            texts.append(str(err).strip())
    phase = _failure_phase(clock, step_no)
    if clock is not None:
        for ev in reversed(clock.events):
            if ev.get("step") != step_no or not ev.get("error"):
                continue
            err = str(ev.get("error") or "").strip()
            if err and err != "null" and err != "CancelledError: cancelled":
                texts.append(err)
                break
    if not texts:
        fails = getattr(getattr(agent, "state", None), "consecutive_failures", None)
        texts.append(
            f"no history item after step {step_no} (consecutive_failures={fails})"
        )
    return texts[0][:400], phase


def _failed_trace_step(
    *,
    step_no: int,
    reason: str,
    phase: str,
    url: str | None = None,
) -> dict[str, Any]:
    """A numbered trace row for a step browser-use did not store.

    The action text stays free of the timeout wording. The classifier reads
    run.error for the type, and failed_step.phase / reason for the contract.
    """
    failed = {"phase": phase, "reason": reason[:400], "step": step_no}
    return {
        "step": step_no,
        "action": "step failed",
        "observation": reason[:800],
        "thought": "",
        "thought_detail": {},
        "url": url,
        "screenshot_url": None,
        "outcome": "fail",
        "phase": phase,
        "reason": reason[:400],
        "error": reason[:400],
        "failed_step": failed,
    }


def _last_failed_step(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    numbered = [
        step
        for step in trace
        if isinstance(step, dict) and isinstance(step.get("step"), int) and int(step["step"]) > 0
    ]
    if not numbered or _step_is_real_action(numbered[-1]):
        return None
    failed = numbered[-1].get("failed_step")
    return failed if isinstance(failed, dict) else None


def _surface_swallowed_failure(
    clock: _PhaseClock | None,
    run_exc: BaseException | None,
    trace: list[dict[str, Any]],
) -> tuple[str, str]:
    """Return (error, browser_error) for a run that never acted.

    failures.json classifies browser_error as our infrastructure and a
    timeout string on error as a model timeout. A finished run stays blank
    so a recovered step is not relabeled.
    """
    acted = any(_step_is_real_action(step) for step in trace if isinstance(step, dict))
    if run_exc is not None:
        text = f"{type(run_exc).__name__}: {run_exc}"[:400]
        if _cdp_failure_text(text):
            return "", text
        return text, ""
    if acted or clock is None:
        return "", ""
    for ev in reversed(clock.events):
        err = str(ev.get("error") or "").strip()
        if not err or err == "null":
            continue
        kind = str(ev.get("error_type") or "Exception")
        text = err if err.startswith(kind) else f"{kind}: {err}"
        text = text[:400]
        if kind == "CancelledError":
            continue
        if _cdp_failure_text(text):
            return "", text
        if kind == "state_error" or "timed out" in text.lower() or "timeout" in text.lower():
            return text, ""
        return text, ""
    return "", ""


def silent_failure_fields(trace: list[dict[str, Any]] | None) -> tuple[str, str]:
    """(error, browser_error) when a budget kill hid a swallowed browser failure.

    An agent that already acted keeps the plain study-budget error.
    """
    notes: list[str] = []
    acted = False
    for step in trace or []:
        if not isinstance(step, dict):
            continue
        if step.get("swallowed_error"):
            notes.append(str(step["swallowed_error"]))
        if step.get("failed_step") and isinstance(step.get("failed_step"), dict):
            notes.append(str((step.get("failed_step") or {}).get("reason") or ""))
        if _step_is_real_action(step):
            acted = True
    if acted or not notes:
        return "study budget", ""
    text = notes[-1][:400]
    if _cdp_failure_text(text):
        return "", text
    return text, ""


def _stamp_phase_trace(
    trace: list[dict[str, Any]],
    clock: _PhaseClock | None,
) -> None:
    if clock is None:
        return
    have = {step.get("step") for step in trace if isinstance(step, dict)}
    for step in trace:
        if not isinstance(step, dict):
            continue
        extra = clock.fields_for(step.get("step"))
        if extra.get("swallowed_error") and step.get("swallowed_error"):
            step["swallowed_error"] = (
                str(step["swallowed_error"]) + " | " + str(extra["swallowed_error"])
            )[:800]
            extra = {k: v for k, v in extra.items() if k != "swallowed_error"}
        if extra.get("phase_ms"):
            merged = dict(step.get("phase_ms") or {})
            merged.update(extra.pop("phase_ms"))
            step["phase_ms"] = merged
        step.update(extra)
        if step.get("step") == 0:
            opening: dict[str, int] = {}
            for ev in clock.events:
                if ev.get("where") != "opening" or ev.get("event") != "end":
                    continue
                if isinstance(ev.get("ms"), int) and ev.get("phase"):
                    opening[f"opening_{ev['phase']}"] = int(ev["ms"])
            if opening:
                merged = dict(step.get("phase_ms") or {})
                merged.update(opening)
                step["phase_ms"] = merged
    # Unnumbered so gate step counters stay on real actions. The row is still
    # on the trace, and the same record is in the phase log if the run is killed.
    seen = {
        ev.get("step")
        for ev in clock.events
        if ev.get("where") == "loop"
        and ev.get("event") == "end"
        and isinstance(ev.get("step"), int)
    }
    for step_no in sorted(n for n in seen if isinstance(n, int)):
        if step_no in have:
            continue
        fields = clock.fields_for(step_no)
        if not fields:
            continue
        trace.append(
            {
                "step": None,
                "timed_step": step_no,
                "timing_only": True,
                "action": "phase timings",
                "observation": str(fields.get("swallowed_error") or ""),
                "thought": "",
                "thought_detail": {},
                "url": None,
                "screenshot_url": None,
                "outcome": "neutral",
                **fields,
            }
        )


def llm_run_concurrency() -> int:
    """How many browser agents may hold a live session at once.

    Eight parallel flash agents leave Linear (8/8). Twenty-four at once time out
    on navigate and never leave the homepage (0/8). Sixteen lets the other
    sixteen agents overlap that work so a 24-agent matrix still finishes inside
    the 360s e2e budget. Navigations stay capped separately.
    """
    raw = (os.environ.get("MVP_LLM_RUN_CONCURRENCY") or "16").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 16


def nav_concurrency() -> int:
    """How many agents may create a session and navigate at once.

    The 24-wide failure was the navigation burst, not the later clicks.
    """
    raw = (os.environ.get("MVP_NAV_CONCURRENCY") or "8").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


_NAV_SEMAPHORE: asyncio.Semaphore | None = None
_CDP_SEMAPHORE: asyncio.Semaphore | None = None
_CDP_DEPTH = contextvars.ContextVar("usersim_cdp_depth", default=0)
_CDP_ERROR_RE = re.compile(
    r"cdp|websocket|target closed|http 410|session (?:not running|closed|dropped)|"
    r"browser closed|connection closed",
    re.I,
)


def cdp_concurrency() -> int:
    """How many DOM/screenshot/navigation CDP calls may run at once.

    One agent captures state in about 1.6s. Six at once stretch that to about
    7s. Twenty-four hit the 30s browser-state timeout (empty DOM, no click).
    The LLM call stays near 2s with HTTP 200 at every level, so the cap is
    only on the CDP phase.
    """
    raw = (os.environ.get("MVP_CDP_CONCURRENCY") or "4").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


def _cdp_semaphore() -> asyncio.Semaphore:
    global _CDP_SEMAPHORE
    if _CDP_SEMAPHORE is None:
        _CDP_SEMAPHORE = asyncio.Semaphore(cdp_concurrency())
    return _CDP_SEMAPHORE


class _CdpSlot:
    """One CDP slot. Nested calls from the same task do not take a second slot."""

    def __init__(self) -> None:
        self._held = False
        self._token: contextvars.Token | None = None

    async def __aenter__(self) -> None:
        if _CDP_DEPTH.get() > 0:
            self._token = _CDP_DEPTH.set(_CDP_DEPTH.get() + 1)
            return
        await _cdp_semaphore().acquire()
        self._held = True
        self._token = _CDP_DEPTH.set(1)

    async def __aexit__(self, *_exc: object) -> None:
        if self._token is not None:
            _CDP_DEPTH.reset(self._token)
        if self._held:
            _cdp_semaphore().release()


def _nav_semaphore() -> asyncio.Semaphore:
    global _NAV_SEMAPHORE
    if _NAV_SEMAPHORE is None:
        _NAV_SEMAPHORE = asyncio.Semaphore(nav_concurrency())
    return _NAV_SEMAPHORE


def _study_bb_owner() -> str:
    from capability.browserbase_client import study_session_owner

    return study_session_owner()


def _png_is_blankish(path: Path) -> bool:
    """True when the shot is basically black / empty (loading splash).

    Align with e2e2 `_png_looks_blank`: small logo-on-black splashes (~32KB)
    are blank; large dark product UIs (Linear, etc.) with real texture are not.
    """
    try:
        if not path.is_file() or path.stat().st_size < 2500:
            return True
        size = path.stat().st_size
    except OSError:
        return True
    try:
        from PIL import Image

        im = Image.open(path).convert("RGB").resize((64, 40))
        pixels = list(im.getdata())
        lums = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels]
        mean = sum(lums) / max(1, len(lums))
        var = sum((x - mean) ** 2 for x in lums) / max(1, len(lums))
        # Small payloads: logo-on-black splash or empty pane.
        if size < 48000:
            if mean < 25.0:
                return True
            if mean < 40.0 and var < 250.0:
                return True
            return False
        # Large payloads: only near-uniform near-black (empty canvas).
        if mean < 12.0 and var < 80.0:
            return True
        return False
    except Exception:
        return size < 48000


def _history_to_actions(history) -> list[dict]:
    actions: list[dict] = []
    try:
        items = list(getattr(history, "history", None) or history or [])
    except Exception:
        items = []
    for i, h in enumerate(items, start=1):
        model_out = getattr(h, "model_output", None)
        result = getattr(h, "result", None)
        url = None
        state = getattr(h, "state", None)
        if state is not None:
            url = getattr(state, "url", None)
        act = None
        if model_out is not None:
            act = getattr(model_out, "action", None) or getattr(model_out, "actions", None)
            if act is not None and not isinstance(act, (str, dict, list)):
                try:
                    act = [
                        a.model_dump() if hasattr(a, "model_dump") else str(a)
                        for a in (act if isinstance(act, list) else [act])
                    ]
                except Exception:
                    act = str(act)
        actions.append(
            {
                "i": i,
                "action": act,
                "result": str(result)[:500] if result is not None else None,
                "url": url,
            }
        )
    return actions


def _action_label(action: Any) -> str:
    """Render a browser-use action as human-readable text, not a pydantic repr."""
    if action is None:
        return "—"
    if isinstance(action, list):
        return "; ".join(_action_label(a) for a in action)

    payload = action
    root = getattr(payload, "root", None)
    if root is not None:
        payload = root
    dumped = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else None
    if isinstance(dumped, dict) and dumped:
        name, args = next(iter(dumped.items()))
        if isinstance(args, dict):
            detail = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", False))
            return (f"{name} — {detail}" if detail else name)[:300]
        return f"{name}: {args}"[:300]
    if isinstance(action, dict) and action:
        name, args = next(iter(action.items()))
        if isinstance(args, dict):
            detail = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", False))
            return (f"{name} — {detail}" if detail else str(name))[:300]
        return f"{name}: {args}"[:300]
    return str(action)[:300]


def _result_text(result: Any) -> str:
    if not result:
        return ""
    items = result if isinstance(result, list) else [result]
    parts: list[str] = []
    for item in items:
        extracted = getattr(item, "extracted_content", None)
        if extracted:
            parts.append(str(extracted)[:400])
            continue
        memory = getattr(item, "long_term_memory", None) or getattr(item, "memory", None)
        if memory:
            parts.append(str(memory)[:400])
            continue
        parts.append(str(item)[:300])
    return " | ".join(parts)


def _browserbase_profile(cdp_url: str):
    from browser_use.browser.profile import BrowserProfile

    from mvp.captcha import captcha_solver_enabled

    return BrowserProfile(
        cdp_url=cdp_url,
        is_local=False,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        disable_security=True,
        enable_default_extensions=False,
        captcha_solver=captcha_solver_enabled(),
        **_cheap_dom_flags(),
    )


def _local_browser_profile(
    *,
    storage_state: Any | None = None,
    headless: bool | None = None,
    user_data_dir: str | None = None,
):
    from browser_use.browser.profile import BrowserProfile

    from mvp.captcha import captcha_solver_enabled

    if headless is None:
        headless = os.environ.get("MVP_BROWSER_HEADLESS", "1").lower() not in {
            "0",
            "false",
            "no",
        }
    kwargs: dict[str, Any] = {
        "is_local": True,
        "headless": headless,
        "viewport": VIEWPORT,
        "user_agent": USER_AGENT,
        "disable_security": True,
        "enable_default_extensions": False,
        "captcha_solver": captcha_solver_enabled(),
        **_cheap_dom_flags(),
    }
    # Default: bundled Chromium. channel=chrome will attach to an already-open
    # Google Chrome (e.g. the UserSim debug window on :9222) and agents get stuck
    # on http://127.0.0.1:8787/live. Opt in with MVP_BROWSER_CHANNEL=chrome.
    channel = os.environ.get("MVP_BROWSER_CHANNEL", "").lower()
    if channel and channel not in {"", "0", "none", "chromium"}:
        kwargs["channel"] = channel
    if user_data_dir:
        # A cloned signed-in profile: the only thing Google accepts.
        kwargs["user_data_dir"] = user_data_dir
    elif storage_state:
        kwargs["storage_state"] = storage_state
        # browser-use warns and fights itself if both storage_state and a temp
        # user_data_dir are set — keep cookies-only for parallel agents.
        kwargs["user_data_dir"] = None
    else:
        # Isolated temp profile so parallel local fallbacks never share cookies
        # or attach to an existing Chrome user-data dir.
        import tempfile

        kwargs["user_data_dir"] = tempfile.mkdtemp(prefix="usersim-local-")
    return BrowserProfile(**kwargs)


def _cdp_cookies(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Convert a Playwright storage_state into CDP Network.setCookies params.

    browser-use 0.13 drives Chrome over CDP, so the profile's ``storage_state``
    is never read — cookies have to be pushed in by hand once the session is up.
    Note this is a fallback: Google binds its session cookies to the profile, so
    only a cloned profile (see mvp.profile_pool) actually signs in there.
    """
    out: list[dict[str, Any]] = []
    for c in (state or {}).get("cookies") or []:
        if not c.get("name"):
            continue
        cookie: dict[str, Any] = {
            "name": c["name"],
            "value": c.get("value") or "",
            "domain": c.get("domain") or "",
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure")),
            "httpOnly": bool(c.get("httpOnly")),
        }
        if c.get("sameSite") in {"Strict", "Lax", "None"}:
            cookie["sameSite"] = c["sameSite"]
        expires = c.get("expires")
        # -1 marks a session cookie; CDP wants the field omitted entirely.
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        out.append(cookie)
    return out


async def _inject_cookies(session: Any, state: dict[str, Any] | None) -> int:
    cookies = _cdp_cookies(state)
    if not cookies:
        return 0
    try:
        cdp = await session.get_or_create_cdp_session()
        await cdp.cdp_client.send.Network.setCookies(
            {"cookies": cookies}, session_id=cdp.session_id
        )
    except Exception:
        return 0
    return len(cookies)


def action_model_name(explicit: str | None = None) -> str:
    """Action-step model.

    The configured flash model is the one that leaves the homepage. Forcing its
    lite sibling (commit 1526a5a restored that downgrade) dropped Linear product
    task success from 8/8 to 1/8 on the same 8-agent harness. Set
    ``MVP_AGENT_ACTION_MODEL`` to pin a different model.
    """
    chosen = (explicit or os.environ.get("MVP_AGENT_ACTION_MODEL") or "").strip()
    if chosen:
        return chosen
    base = (os.environ.get("MVP_BROWSER_MODEL") or os.environ.get("MVP_LLM_MODEL") or MODEL or "").strip()
    return base or MODEL


def _product_session_call_kwargs() -> dict[str, Any]:
    """Signup's richest Browserbase flags. ``create_session`` walks the ladder.

    Proxies + captcha solve, then solve without proxies, then bare.
    ``advanced_stealth`` stays off (Hobby returns 403).
    """
    return {"proxies": True, "solve_captchas": True, "advanced_stealth": False}


_PAGE_STATE_JS = """() => {
  const text = ((document.body && document.body.innerText) || '')
    .replace(/\\s+/g, ' ').trim().slice(0, 2500);
  let canvas = '';
  for (const c of document.querySelectorAll('canvas')) {
    try {
      const w = c.width || 0, h = c.height || 0;
      if (w < 2 || h < 2) continue;
      const ctx = c.getContext('2d');
      if (!ctx) continue;
      const data = ctx.getImageData(0, 0, w, h).data;
      // A thin stroke misses an 8x8 grid. Count non-white pixels on a denser grid.
      const step = Math.max(4, Math.floor(Math.min(w, h) / 48));
      let dark = 0, total = 0;
      for (let y = 0; y < h; y += step) {
        for (let x = 0; x < w; x += step) {
          const i = (y * w + x) * 4;
          if ((data[i] + data[i + 1] + data[i + 2]) < 700) dark++;
          total++;
        }
      }
      canvas += w + 'x' + h + ':dark=' + dark + '/' + total + ';';
    } catch (e) {
      canvas += 'taint;';
    }
  }
  return {text, canvas};
}"""

_CAPTCHA_JS = """() => {
  const text = ((document.body && document.body.innerText) || '').slice(0, 8000);
  const html = ((document.documentElement && document.documentElement.innerHTML) || '').slice(0, 180000);
  const blob = html + '\\n' + text;
  const markers = [];
  if (/press\\s*(?:&|and)\\s*hold/i.test(text) || /press\\s*(?:&|and)\\s*hold/i.test(html))
    markers.push('press-and-hold');
  if (/px-captcha|perimeterx|\\b_px\\b|human challenge/i.test(blob)) markers.push('perimeterx');
  if (/datadome|captcha-delivery\\.com/i.test(blob)) markers.push('datadome');
  if (/challenges\\.cloudflare\\.com|cf-turnstile|just a moment/i.test(blob)) markers.push('turnstile');
  if (/hcaptcha/i.test(blob)) markers.push('hcaptcha');
  if (/recaptcha|g-recaptcha/i.test(blob)) markers.push('recaptcha');
  if (/arkoselabs|funcaptcha/i.test(blob)) markers.push('arkose');
  if (/access denied|are you a robot|verify you are human|bot detection/i.test(text))
    markers.push('bot-wall');
  let box = null;
  const nodes = document.querySelectorAll('button, [role=button], div, span, p, a, iframe, #px-captcha, .px-captcha, [id*="px-captcha"]');
  for (const el of nodes) {
    const t = (el.innerText || el.getAttribute('aria-label') || el.title || '').trim();
    const id = ((el.id || '') + ' ' + (el.className || '') + ' ' + (el.src || '')).toLowerCase();
    const hold = /press\\s*(?:&|and)?\\s*hold/i.test(t) || /\\bhold\\b/i.test(t) && t.length < 48 || id.includes('px-captcha') || id.includes('perimeterx');
    if (!hold) continue;
    if (t.length > 180 && !id.includes('px-captcha')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 12) continue;
    if (r.bottom < 0 || r.top > (window.innerHeight || 800)) continue;
    box = {
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      text: (t || id).slice(0, 80),
    };
    break;
  }
  return {markers, box, title: document.title || '', snippet: text.slice(0, 280)};
}"""


async def _eval_page(session: Any, expression: str) -> Any:
    page = await asyncio.wait_for(session.get_current_page(), timeout=8)
    if page is None:
        return None
    # browser-use Page.evaluate returns a string. Objects arrive as JSON.
    raw = await asyncio.wait_for(page.evaluate(expression), timeout=8)
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return raw


async def _page_state(session: Any) -> dict[str, str] | None:
    try:
        raw = await _eval_page(session, _PAGE_STATE_JS)
    except Exception as exc:  # noqa: BLE001
        print(f"page state capture failed: {exc!r}"[:240], flush=True)
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "text": str(raw.get("text") or "")[:2500],
        "canvas": str(raw.get("canvas") or "")[:4000],
    }


async def _mouse_path(session: Any, points: list[tuple[int, int]], *, hold_s: float = 0.0) -> None:
    """Mouse down, optional hold, stepped move, mouse up. Real CDP events."""
    if not points:
        return
    cdp = await session.get_or_create_cdp_session()
    client = cdp.cdp_client
    sid = cdp.session_id

    async def send(params: dict[str, Any]) -> None:
        await client.send.Input.dispatchMouseEvent(params, session_id=sid)

    x, y = points[0]
    await send({"type": "mouseMoved", "x": x, "y": y})
    await send(
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}
    )
    if hold_s > 0:
        await asyncio.sleep(hold_s)
    for px, py in points[1:]:
        await send(
            {
                "type": "mouseMoved",
                "x": px,
                "y": py,
                "button": "left",
                "buttons": 1,
            }
        )
        await asyncio.sleep(0.02)
    lx, ly = points[-1]
    await send(
        {"type": "mouseReleased", "x": lx, "y": ly, "button": "left", "clickCount": 1}
    )


def _line_points(x0: int, y0: int, x1: int, y1: int, steps: int = 8) -> list[tuple[int, int]]:
    points = []
    steps = max(2, steps)
    for i in range(steps + 1):
        t = i / steps
        points.append((int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))))
    return points


async def _detect_captcha(session: Any) -> dict[str, Any] | None:
    try:
        raw = await _eval_page(session, _CAPTCHA_JS)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    markers = [str(m) for m in (raw.get("markers") or []) if m]
    if not markers and not raw.get("box"):
        return None
    return {
        "markers": markers,
        "box": raw.get("box") if isinstance(raw.get("box"), dict) else None,
        "title": str(raw.get("title") or "")[:120],
        "snippet": str(raw.get("snippet") or "")[:280],
    }


async def _maybe_press_and_hold(session: Any, *, agent_id: str) -> dict[str, Any] | None:
    """Hold a press-and-hold widget with the mouse. No CapSolver."""
    found = await _detect_captcha(session)
    if not found:
        return None
    markers = found.get("markers") or []
    box = found.get("box") or {}
    kind = "press-and-hold" if "press-and-hold" in markers else (markers[0] if markers else "")
    held = False
    if kind == "press-and-hold" and box.get("x") is not None and box.get("y") is not None:
        x, y = int(box["x"]), int(box["y"])
        print(
            f"[{agent_id}] captcha {markers} — holding mouse at ({x},{y}) for {MVP_HOLD_S:.0f}s",
            flush=True,
        )
        try:
            await _mouse_path(session, [(x, y)], hold_s=MVP_HOLD_S)
            held = True
            await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] press-and-hold failed: {exc!r}", flush=True)
    else:
        print(f"[{agent_id}] captcha markers={markers} (no mouse hold)", flush=True)
    return {
        "kind": kind or ",".join(markers),
        "markers": markers,
        "held": held,
        "box": box or None,
        "title": found.get("title") or "",
        "snippet": found.get("snippet") or "",
    }


def _study_tools() -> Any:
    from browser_use import Tools
    from browser_use.agent.views import ActionResult

    tools = Tools(exclude_actions=["write_file", "replace_file"])

    @tools.action(
        "Draw or drag. Mouse down at start_x,start_y, move in a straight line to "
        "end_x,end_y, then mouse up. Selecting a rectangle or line tool does not "
        "place a shape — drag across the canvas. Coordinates are viewport pixels."
    )
    async def drag(start_x: int, start_y: int, end_x: int, end_y: int, browser_session):  # noqa: ANN001
        if browser_session is None:
            return ActionResult(error="No browser session for drag")
        try:
            await _mouse_path(
                browser_session,
                _line_points(int(start_x), int(start_y), int(end_x), int(end_y)),
            )
        except Exception as exc:  # noqa: BLE001
            return ActionResult(error=f"Drag failed: {exc}")
        return ActionResult(
            extracted_content=f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y}).",
            long_term_memory=f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y}).",
        )

    @tools.action(
        "Press and hold the left mouse button at x,y, then release. Use this on a "
        "Press and Hold or PerimeterX check. Do not call an external captcha solver."
    )
    async def press_and_hold(x: int, y: int, browser_session, seconds: int = 10):  # noqa: ANN001
        if browser_session is None:
            return ActionResult(error="No browser session for press_and_hold")
        # PerimeterX ignores a short press. Always hold about 10s.
        hold = 10.0
        try:
            await _mouse_path(browser_session, [(int(x), int(y))], hold_s=hold)
        except Exception as exc:  # noqa: BLE001
            return ActionResult(error=f"Press-and-hold failed: {exc}")
        return ActionResult(
            extracted_content=f"Held the mouse at ({x},{y}) for {hold:.0f}s.",
            long_term_memory=f"Held the mouse at ({x},{y}) for {hold:.0f}s.",
        )

    return tools


def _trace_step_from_history_item(
    h: Any,
    step_no: int,
    *,
    study_id: str,
    agent_id: str,
    screenshot_dir: Path,
) -> dict[str, Any]:
    model_out = getattr(h, "model_output", None)
    state = getattr(h, "state", None)
    url = getattr(state, "url", None) if state else None
    shot_src = getattr(state, "screenshot_path", None) if state else None

    screenshot_name = None
    if (screenshot_dir / f"bbox_{step_no}.png").exists():
        screenshot_name = f"bbox_{step_no}.png"
    elif shot_src and Path(shot_src).exists():
        screenshot_name = f"step_{step_no}.png"
        shutil.copy2(shot_src, screenshot_dir / screenshot_name)

    act_raw = None
    if model_out is not None:
        act_raw = getattr(model_out, "action", None) or getattr(model_out, "actions", None)
    action = _action_label(act_raw)
    observation = _result_text(getattr(h, "result", None))

    thought_fields: dict[str, str] = {}
    if model_out:
        for field in ("thinking", "evaluation_previous_goal", "next_goal", "memory"):
            val = getattr(model_out, field, None)
            if val:
                thought_fields[field] = str(val).strip()
    thought_summary = (
        thought_fields.get("next_goal")
        or thought_fields.get("evaluation_previous_goal")
        or thought_fields.get("thinking")
        or ""
    )

    step_latency_s = None
    meta = getattr(h, "metadata", None)
    if meta is not None:
        try:
            step_latency_s = round(float(meta.duration_seconds), 3)
        except Exception:
            step_latency_s = None

    return {
        "step": step_no,
        "action": action,
        "observation": observation,
        "thought": thought_summary,
        "thought_detail": thought_fields,
        "url": url,
        "screenshot_url": (
            f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{screenshot_name}"
            if screenshot_name
            else None
        ),
        "outcome": "neutral",
        "step_latency_s": step_latency_s,
    }


_INTERACT_ACTIONS = {
    "click",
    "input",
    "input_text",
    "type",
    "send_keys",
    "go_to_url",
    "search",
    "search_page",
    "scroll",
    "select_dropdown",
    "select_dropdown_option",
    "upload_file",
    "drag",
    "press_and_hold",
    "switch_tab",
}
_BLOCKED_MARKERS = (
    "captcha",
    "press & hold",
    "press and hold",
    "verification",
    "access denied",
    "login wall",
    "sign in to continue",
    "sign in required",
)


def _action_name(action: Any) -> str:
    label = _action_label(action).lower()
    return label.split("—")[0].split(":")[0].strip()


def _same_page(url: str | None, start_url: str | None) -> bool:
    if not url or not start_url:
        return True

    def key(raw: str) -> tuple[str, str, str]:
        try:
            parsed = urlparse(raw)
        except Exception:
            return ("", raw, "")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = (parsed.path or "/").rstrip("/") or "/"
        return (host, path, parsed.query or "")

    return key(url) == key(start_url)


def _history_interact_count(agent: Any) -> int:
    history = getattr(agent, "history", None)
    items = list(getattr(history, "history", None) or [])
    count = 0
    for item in items:
        model_out = getattr(item, "model_output", None)
        actions = getattr(model_out, "action", None) if model_out is not None else None
        if actions is None:
            continue
        if not isinstance(actions, list):
            actions = [actions]
        for action in actions:
            if _action_name(action) in _INTERACT_ACTIONS:
                count += 1
    return count


def reject_early_done(agent: Any, start_url: str) -> bool:
    """Undo a done action that only describes the page the agent opened.

    Returns True when the done flag was cleared so the loop keeps going.
    A done call stands when the agent left the start URL, interacted at least
    twice, or the page is clearly blocked.
    """
    history = getattr(agent, "history", None)
    if history is None or not history.is_done():
        return False
    items = list(getattr(history, "history", None) or [])
    if not items:
        return False
    results = list(getattr(items[-1], "result", None) or [])
    if not results:
        return False
    last = results[-1]
    blob = " ".join(
        str(getattr(last, field, "") or "")
        for field in ("extracted_content", "long_term_memory", "error")
    ).lower()
    state = getattr(items[-1], "state", None)
    url = str(getattr(state, "url", None) or start_url)
    blocked = any(marker in blob for marker in _BLOCKED_MARKERS)
    # One click, drag, or typed field is enough. Requiring two made canvas
    # runs call done, get rejected, and spend the rest of the step cap repeating it.
    if blocked or not _same_page(url, start_url) or _history_interact_count(agent) >= 1:
        return False
    # success=True is invalid once is_done is cleared.
    if getattr(last, "success", None) is True:
        last.success = None
    last.is_done = False
    last.error = (
        "Still on the start page without doing the task. Click, type, or open the "
        "section the task asks for. Call done only when that page or state is open, "
        "or when a captcha or login wall blocks you."
    )
    print(f"rejected early done on {url}", flush=True)
    return True


def _remember_step(book: dict[str, Any], step: dict[str, Any]) -> None:
    n = step.get("step")
    if isinstance(n, int):
        book.setdefault("emitted", {})[n] = step


def _schedule_emit(
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
    step: dict[str, Any],
    book: dict[str, Any] | None = None,
) -> None:
    """Hand a trace row to the UI without waiting on persistence."""
    if isinstance(book, dict):
        _remember_step(book, step)
    if on_step is None:
        return
    maybe = on_step(step)
    if asyncio.iscoroutine(maybe):
        task = asyncio.create_task(maybe)
        if isinstance(book, dict):
            book.setdefault("emit_tasks", []).append(task)


def _schedule_live_action(agent: Any) -> None:
    """Push the chosen action onto the step rail before it finishes executing."""
    book = getattr(agent, "_usersim_book", None)
    if not isinstance(book, dict):
        return
    model_out = getattr(getattr(agent, "state", None), "last_model_output", None)
    if model_out is None:
        return
    act = getattr(model_out, "action", None) or getattr(model_out, "actions", None)
    label = _action_label(act)
    if not label or label == "—":
        return
    step_no = int(book.get("step") or 0) + 1
    if book.get("live_emitted") == step_no:
        return
    book["live_emitted"] = step_no
    thought = str(getattr(model_out, "next_goal", None) or getattr(model_out, "thinking", None) or "")
    _schedule_emit(
        book.get("on_step"),
        {
            "step": step_no,
            "action": label,
            "observation": "",
            "thought": thought[:400],
            "thought_detail": {"next_goal": thought[:400]} if thought else {},
            "url": None,
            "screenshot_url": None,
            "outcome": "neutral",
            "live": True,
        },
        book,
    )


def _make_step_hooks(
    screenshot_dir: Path,
    *,
    study_id: str,
    agent_id: str,
    start_url: str = "",
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    page_state: dict[str, Any] | None = None,
):
    """Record the step from the screenshot browser-use already took.

    Nothing here extracts the DOM, draws highlights, or takes another
    screenshot. The UI write is scheduled so tracing does not stall the next
    decision.
    """
    book = page_state if isinstance(page_state, dict) else {}
    book.setdefault("step", 0)
    book["on_step"] = on_step
    state = book

    def _emit(step: dict[str, Any]) -> None:
        _schedule_emit(on_step, step, book)

    async def on_step_start(agent: Any) -> None:
        nxt = state["step"] + 1
        session = getattr(agent, "browser_session", None)
        holds = int(book.get("holds") or 0)
        if session is not None and holds < 1:
            try:
                found = await _maybe_press_and_hold(session, agent_id=agent_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] captcha check failed: {exc!r}", flush=True)
                found = None
            if found:
                book["captcha"] = found
                if found.get("held"):
                    book["holds"] = holds + 1
        # Status pulse only. The numbered row is emitted when the action is chosen.
        _emit(
            {
                "step": None,
                "progress_only": True,
                "action": f"Thinking — step {nxt}",
                "observation": "",
                "thought": f"Deciding what to do next (step {nxt})…",
                "thought_detail": {
                    "thinking": f"Looking at the page and choosing the next action for step {nxt}."
                },
                "url": None,
                "screenshot_url": None,
                "outcome": "neutral",
            }
        )

    async def on_step_end(agent: Any) -> None:
        clock = book.get("phase_clock") if isinstance(book.get("phase_clock"), _PhaseClock) else None
        swallowed: list[str] = []

        def _swallowed(phase: str, exc: BaseException) -> None:
            text = f"{type(exc).__name__}: {exc}"[:400]
            swallowed.append(f"{phase}: {text}")
            print(f"[{agent_id}] swallowed {phase}: {text}", flush=True)
            if clock is not None:
                clock.note_exception(phase, exc, where="hook", step=state["step"] or None)

        try:
            reject_early_done(agent, start_url)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] early-done check failed: {exc!r}", flush=True)
            _swallowed("early_done", exc)
        state["step"] += 1
        step_no = state["step"]
        if book.get("t0") is not None and book.get("first_action_s") is None:
            book["first_action_s"] = round(time.monotonic() - float(book["t0"]), 3)
        session = getattr(agent, "browser_session", None)
        if session is None:
            _emit(
                _failed_trace_step(
                    step_no=step_no,
                    reason="no browser session",
                    phase="action",
                )
            )
            return
        history = getattr(agent, "history", None)
        items = list(getattr(history, "history", None) or [])
        # step() is cancelled on step_timeout before _finalize appends history.
        # Compare to the previous length so a later success is not marked failed.
        prev_len = int(state.get("history_len") or 0)
        if len(items) <= prev_len:
            reason, phase = _failure_reason(agent, clock, step_no)
            print(
                f"[{agent_id}] step {step_no} failed phase={phase}: {reason}"
                + (f" swallowed={swallowed}" if swallowed else ""),
                flush=True,
            )
            step = _failed_trace_step(step_no=step_no, reason=reason, phase=phase)
            if swallowed:
                step["swallowed_error"] = " | ".join(swallowed)[:800]
            if clock is not None:
                extra = clock.fields_for(step_no)
                if extra.get("phase_ms"):
                    step["phase_ms"] = extra["phase_ms"]
                if extra.get("swallowed_error"):
                    prior = str(step.get("swallowed_error") or "")
                    step["swallowed_error"] = (prior + " | " + str(extra["swallowed_error"])).strip(" |")[:800]
            sigs = book.get("sigs") if isinstance(book.get("sigs"), dict) else {}
            if step_no in sigs:
                step["state_sig"] = sigs[step_no]
            _emit(step)
            return
        state["history_len"] = len(items)
        # Reuse the screenshot already stored on the history item.
        latest = items[-1]
        shot = getattr(getattr(latest, "state", None), "screenshot_path", None)
        dest = screenshot_dir / f"bbox_{step_no}.png"
        if shot and Path(shot).is_file() and not dest.is_file():
            try:
                shutil.copy2(shot, dest)
            except Exception as exc:  # noqa: BLE001
                _swallowed("reuse_screenshot", exc)
        step = _trace_step_from_history_item(
            items[-1],
            step_no,
            study_id=study_id,
            agent_id=agent_id,
            screenshot_dir=screenshot_dir,
        )
        if swallowed:
            step["swallowed_error"] = " | ".join(swallowed)[:800]
        if clock is not None:
            extra = clock.fields_for(step_no)
            if extra.get("swallowed_error") and step.get("swallowed_error"):
                step["swallowed_error"] = (
                    str(step["swallowed_error"]) + " | " + str(extra.pop("swallowed_error"))
                )[:800]
            if extra.get("phase_ms"):
                merged = dict(step.get("phase_ms") or {})
                merged.update(extra.pop("phase_ms"))
                step["phase_ms"] = merged
            step.update(extra)
        sigs = book.get("sigs") if isinstance(book.get("sigs"), dict) else {}
        if step_no in sigs:
            step["state_sig"] = sigs[step_no]
        _emit(step)

    return on_step_start, on_step_end


_CONSENT_CLICK_JS = """
() => {
  const texts = [
    'accept all', 'accept all cookies', 'accept cookies', 'i agree', 'agree',
    'allow all', 'got it', 'ok', 'okay', 'continue', 'consent',
  ];
  const nodes = [
    ...document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], a'),
  ];
  for (const el of nodes) {
    const label = ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim().toLowerCase();
    if (!label || label.length > 48) continue;
    if (!texts.some((t) => label === t || label.startsWith(t))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    el.click();
    return label;
  }
  return '';
}
"""


async def _ensure_cdp_connected(browser_session: Any, *, agent_id: str) -> None:
    """Reconnect if the socket died while this agent waited for a run slot.

    browser-use raises 'Root CDP client not initialized' once the websocket
    leaves OPEN. connect() tears down a dead client and opens a new one.
    """
    if browser_session is None:
        return
    try:
        connected = bool(browser_session.is_cdp_connected)
    except Exception:
        connected = False
    if connected:
        return
    print(f"[{agent_id}] CDP down — reconnecting before agent.run", flush=True)
    try:
        await asyncio.wait_for(browser_session.connect(), timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] CDP reconnect failed: {exc!r}", flush=True)


async def _dismiss_consent_banners(browser_session: Any, *, agent_id: str) -> None:
    try:
        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=8)
        if page is None:
            return
        for _ in range(2):
            clicked = await asyncio.wait_for(page.evaluate(_CONSENT_CLICK_JS), timeout=5)
            if not clicked:
                break
            print(f"[{agent_id}] dismissed consent: {clicked!r}", flush=True)
            await asyncio.sleep(0.4)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] consent dismiss skipped: {exc!r}", flush=True)


def parse_vision_action(
    payload: Any,
    *,
    width: int,
    height: int,
    image_w: int = _VISION_IMAGE[0],
    image_h: int = _VISION_IMAGE[1],
) -> dict[str, Any] | None:
    """Turn a vision reply into a viewport click or type.

    The model sees an 800x450 image. Coordinates inside that image are scaled
    up to the screenshot. Coordinates already past the image are viewport pixels.
    """
    data: Any = payload
    if hasattr(payload, "model_dump"):
        data = payload.model_dump()
    elif not isinstance(payload, dict):
        text = str(getattr(payload, "completion", payload) or "")
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind") or data.get("action") or "").strip().lower()
    if kind not in {"click", "type"}:
        return None
    try:
        x = int(float(data.get("x")))
        y = int(float(data.get("y")))
    except (TypeError, ValueError):
        return None
    if image_w > 0 and image_h > 0 and 0 <= x <= image_w and 0 <= y <= image_h and width and height:
        # A point on the resized image. The far edges are still inside the image,
        # so only values past the image are treated as already-viewport pixels.
        if x < image_w and y < image_h:
            x = int(round(x * width / image_w))
            y = int(round(y * height / image_h))
    x = max(1, min(int(width or x), x))
    y = max(1, min(int(height or y), y))
    text = str(data.get("text") or "")[:80]
    if kind == "type" and not text:
        kind = "click"
    return {"kind": kind, "x": x, "y": y, "text": text}


def _vision_jpeg(path: Path) -> tuple[str, int, int]:
    import base64
    import io

    from PIL import Image

    im = Image.open(path)
    src_w, src_h = im.size
    im = im.convert("RGB").resize(_VISION_IMAGE)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=55)
    return base64.b64encode(buf.getvalue()).decode("ascii"), src_w, src_h


async def _cdp_insert_text(session: Any, text: str) -> None:
    cdp = await session.get_or_create_cdp_session()
    await cdp.cdp_client.send.Input.insertText(
        {"text": text},
        session_id=cdp.session_id,
    )


def _start_background_state(browser_session: Any, clock: _PhaseClock, step_no: int) -> None:
    """Load DOM while the vision call runs. The next step reuses this task."""

    async def _load() -> Any:
        token_where = _PHASE_WHERE.set("loop")
        token_step = _PHASE_STEP.set(step_no)
        try:
            # Call the unwrapped capture. The step wrapper only waits for it,
            # so this task is not itself cut off at the state budget.
            fetch = getattr(browser_session, "_usersim_orig_state", None)
            if fetch is None:
                fetch = browser_session.get_browser_state_summary
            return await fetch(include_screenshot=True)
        finally:
            _PHASE_WHERE.reset(token_where)
            _PHASE_STEP.reset(token_step)

    task = asyncio.create_task(_load())
    try:
        object.__setattr__(browser_session, "_usersim_pending_state", task)
        object.__setattr__(browser_session, "_usersim_state_inflight", task)
    except Exception:
        pass
    clock.event(event="start", phase="state", where="background", step=step_no, note="scheduled")


async def _act_from_opening_screenshot(
    browser_session: Any,
    llm: Any,
    *,
    clock: _PhaseClock,
    screenshot_dir: Path,
    study_id: str,
    agent_id: str,
    task_prompt: str,
    url: str,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
    book: dict[str, Any],
) -> dict[str, Any] | None:
    """Click or type from the opening PNG. Does not wait for a DOM extraction."""
    shot = screenshot_dir / "bbox_0.png"
    if not shot.is_file() or shot.stat().st_size < 100:
        return None
    shot_at = book.get("screenshot_mono")
    if not isinstance(shot_at, float):
        shot_at = time.monotonic()
        book["screenshot_mono"] = shot_at
    # The loop's first state capture is this task. Trace step 1 is the click;
    # the capture belongs to the following decision.
    _start_background_state(browser_session, clock, step_no=2)
    step_token = _PHASE_STEP.set(1)
    where_token = _PHASE_WHERE.set("opening")
    clock.current_step = 1
    decision: dict[str, Any] | None = None
    phase = "llm"
    try:
        jpeg, src_w, src_h = _vision_jpeg(shot)
        try:
            object.__setattr__(browser_session, "_usersim_fallback_screenshot", jpeg)
        except Exception:
            pass
        from browser_use.llm.messages import (
            ContentPartImageParam,
            ContentPartTextParam,
            ImageURL,
            SystemMessage,
            UserMessage,
        )
        from pydantic import BaseModel, Field

        class VisionFirstAction(BaseModel):
            kind: str = Field(description="click or type")
            x: int
            y: int
            text: str = ""

        prompt = (
            f"Task: {task_prompt[:400]}\n"
            f"Page: {url}\n"
            "The image is 800 by 450. Pick ONE next action a real user would take "
            "for the task. Return kind=click or kind=type, plus x and y inside the "
            "image. For type, also return the short text to enter. Do not describe the page."
        )
        messages = [
            SystemMessage(content="You choose one browser action from a screenshot."),
            UserMessage(
                content=[
                    ContentPartTextParam(text=prompt),
                    ContentPartImageParam(
                        image_url=ImageURL(
                            url=f"data:image/jpeg;base64,{jpeg}",
                            media_type="image/jpeg",
                            detail="low",
                        )
                    ),
                ]
            ),
        ]
        try:
            result = await asyncio.wait_for(
                llm.ainvoke(messages, output_format=VisionFirstAction),
                timeout=8,
            )
            decision = parse_vision_action(
                getattr(result, "completion", result),
                width=src_w or int(VIEWPORT["width"]),
                height=src_h or int(VIEWPORT["height"]),
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"[:400]
            failed = _failed_trace_step(step_no=1, reason=reason, phase="llm", url=url)
            failed["screenshot_url"] = (
                f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_0.png"
            )
            _schedule_emit(on_step, failed, book)
            book["step"] = 1
            print(f"[{agent_id}] vision first action failed phase=llm: {reason}", flush=True)
            return failed
        if not decision:
            failed = _failed_trace_step(
                step_no=1,
                reason="vision reply had no click or type coordinates",
                phase="llm",
                url=url,
            )
            _schedule_emit(on_step, failed, book)
            book["step"] = 1
            print(f"[{agent_id}] vision first action had no coordinates", flush=True)
            return failed
        phase = "action"
        started = clock.begin("action", where="opening", step=1)
        try:
            await asyncio.wait_for(
                _mouse_path(browser_session, [(decision["x"], decision["y"])]),
                timeout=3,
            )
            if decision["kind"] == "type" and decision.get("text"):
                await asyncio.wait_for(
                    _cdp_insert_text(browser_session, str(decision["text"])),
                    timeout=3,
                )
        except Exception as exc:
            clock.finish(
                "action",
                started,
                where="opening",
                step=1,
                error=f"{type(exc).__name__}: {exc}"[:400],
                error_type=type(exc).__name__,
            )
            failed = _failed_trace_step(
                step_no=1,
                reason=f"{type(exc).__name__}: {exc}"[:400],
                phase="action",
                url=url,
            )
            _schedule_emit(on_step, failed, book)
            book["step"] = 1
            print(f"[{agent_id}] vision click failed: {exc!r}", flush=True)
            return failed
        clock.finish("action", started, where="opening", step=1)
        elapsed_ms = round((time.monotonic() - float(shot_at)) * 1000)
        clock.event(
            event="end",
            phase="first_action",
            where="opening",
            step=1,
            ms=elapsed_ms,
        )
        book["first_action_s"] = round(elapsed_ms / 1000, 3)
        book["vision_action"] = decision
        if decision["kind"] == "type" and decision.get("text"):
            label = f"type — x={decision['x']}, y={decision['y']}, text={decision['text']}"
        else:
            label = f"click — x={decision['x']}, y={decision['y']}"
        step = {
            "step": 1,
            "action": label,
            "observation": "Chosen from the opening screenshot.",
            "thought": "",
            "thought_detail": {},
            "url": url,
            "screenshot_url": f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_0.png",
            "boxes": [],
            "outcome": "neutral",
            "phase_ms": {"first_action": elapsed_ms},
        }
        extra = clock.fields_for(1)
        if extra.get("phase_ms"):
            merged = dict(step["phase_ms"])
            merged.update(extra["phase_ms"])
            step["phase_ms"] = merged
        _schedule_emit(on_step, step, book)
        book["step"] = 1
        print(
            f"[{agent_id}] first action {label} {elapsed_ms}ms after screenshot",
            flush=True,
        )
        return step
    finally:
        _PHASE_STEP.reset(step_token)
        _PHASE_WHERE.reset(where_token)


async def _emit_opening_frame(
    browser_session: Any,
    *,
    screenshot_dir: Path,
    study_id: str,
    agent_id: str,
    url: str,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    shot_name: str = "bbox_0.png",
    book: dict[str, Any] | None = None,
) -> None:
    """Navigate + one viewport screenshot, then return so the first click can start."""
    try:
        await asyncio.wait_for(browser_session.navigate_to(url), timeout=45)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening navigate failed: {exc!r}", flush=True)

    await _dismiss_consent_banners(browser_session, agent_id=agent_id)
    # Wait for real paint — 0.2s was capturing Vimeo/Dailymotion black splashes.
    page = None
    try:
        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=8)
    except Exception as exc:  # noqa: BLE001
        print(f"[{agent_id}] opening get_current_page failed: {exc!r}", flush=True)
    if page is not None:
        try:
            await asyncio.wait_for(page.wait_for_load_state("domcontentloaded"), timeout=8)
        except Exception:
            pass
        try:
            await asyncio.sleep(0.4)
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                page.wait_for_function(
                    "() => document.body && (document.body.innerText || '').trim().length > 40",
                    timeout=2000,
                ),
                timeout=3,
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                page.evaluate("() => window.scrollTo(0, 0)"),
                timeout=5,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] opening scrollTop failed: {exc!r}", flush=True)
        # Cookie / consent banners that cover the page.
        try:
            await asyncio.wait_for(
                page.evaluate(
                    """() => {
                      const labels = ['accept all','accept','agree','got it','i agree','allow all','ok'];
                      const els = [...document.querySelectorAll('button,[role=button],a')];
                      for (const el of els) {
                        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (!t || t.length > 40) continue;
                        if (!labels.some(l => t === l || t.startsWith(l))) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 8 || r.height < 8) continue;
                        el.click();
                        return t;
                      }
                      return '';
                    }"""
                ),
                timeout=5,
            )
        except Exception:
            pass

    shot_path = screenshot_dir / shot_name

    async def _snap_once() -> bool:
        try:
            await asyncio.wait_for(
                browser_session.take_screenshot(path=str(shot_path), full_page=False),
                timeout=20,
            )
            return True
        except TypeError:
            try:
                await asyncio.wait_for(
                    browser_session.take_screenshot(path=str(shot_path)),
                    timeout=20,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] opening screenshot failed: {exc!r}", flush=True)
                return False
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] opening screenshot failed: {exc!r}", flush=True)
            return False

    ok = False
    # Two quick frames. The first real click uses whichever PNG we publish
    # and must not wait on a reload loop.
    for attempt in range(2):
        await asyncio.sleep(0.3 if attempt == 0 else 0.6)
        if not await _snap_once():
            continue
        if isinstance(book, dict) and "screenshot_mono" not in book:
            book["screenshot_mono"] = time.monotonic()
        if not _png_is_blankish(shot_path):
            ok = True
            break
        print(
            f"[{agent_id}] opening frame blankish (attempt {attempt + 1}/2) — one more snap",
            flush=True,
        )

    if not ok:
        if not shot_path.is_file() or shot_path.stat().st_size < 100:
            print(f"[{agent_id}] opening screenshot missing/empty", flush=True)
            return
        if _png_is_blankish(shot_path):
            print(
                f"[{agent_id}] opening frame still blank after extended wait — "
                "publishing best effort so same-site backfill can replace it",
                flush=True,
            )
            # Fall through and publish — backfill_site_opening_shots can replace
            # blank splash from a same-site donor once any agent gets real paint.
        else:
            print(
                f"[{agent_id}] opening frame marginal — publishing best effort",
                flush=True,
            )

    final_url = url
    try:
        got = browser_session.get_current_page_url()
        if asyncio.iscoroutine(got):
            got = await asyncio.wait_for(got, timeout=5)
        if got:
            final_url = got
    except Exception:
        pass
    step = {
        "step": 0,
        "action": f"Opened {final_url}",
        "observation": "Landing page screenshot",
        "thought": "",
        "thought_detail": {},
        "url": final_url,
        "screenshot_url": f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{shot_name}",
        "boxes": [],
        "outcome": "neutral",
        "evidence_label": "Opening frame · before agent steps",
    }
    _schedule_emit(on_step, step, book)
    print(
        f"[{agent_id}] opening frame ready ({shot_path.stat().st_size} bytes) {final_url}",
        flush=True,
    )


def _history_to_trace(
    history,
    *,
    study_id: str,
    agent_id: str,
    screenshot_dir: Path,
) -> list[dict[str, Any]]:
    items = list(getattr(history, "history", None) or [])
    return [
        _trace_step_from_history_item(
            h, i, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
        )
        for i, h in enumerate(items, start=1)
    ]


def _urls_match(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        p = urlparse((u or "").strip())
        host = (p.hostname or "").lower().removeprefix("www.")
        path = (p.path or "/").rstrip("/") or "/"
        return f"{host}{path}"

    return bool(a and b and norm(a) == norm(b))


async def _page_block_reason(browser_session: Any) -> str | None:
    """Return a classify_page_block reason if the open tab is a WAF/deny interstitial."""
    try:
        from capability.site_preflight import classify_page_block

        page = await asyncio.wait_for(browser_session.get_current_page(), timeout=5)
        title = ""
        final_url = ""
        body = ""
        try:
            title = await asyncio.wait_for(page.title(), timeout=3)
        except Exception:
            pass
        try:
            final_url = str(page.url or "")
        except Exception:
            pass
        try:
            body = await asyncio.wait_for(
                page.evaluate(
                    "() => (document.body && (document.body.innerText || '')) "
                    ".slice(0, 4000)"
                ),
                timeout=5,
            )
            body = str(body or "")
        except Exception:
            body = ""
        blocked, reason = classify_page_block(
            final_url=final_url, title=title or "", body=body or ""
        )
        return reason if blocked else None
    except Exception as exc:  # noqa: BLE001
        print(f"[warm] block classify skipped: {exc!r}", flush=True)
        return None


async def warm_opening_session(
    *, study_id: str, url: str, proxies: bool = False
) -> dict[str, Any] | None:
    """Create Browserbase + navigate + screenshot while brief LLMs run.

    Returns a live browser_session already on ``url`` with bbox_0.png written under
    ``MVP_RUNS_DIR / study_id / _warm``. Caller must either hand this to
    ``run_browser_agent(..., warm=...)`` or ``close_warm_opening``.

    If the landing page is a WAF/access-denied interstitial, retries once with
    residential proxies (generic — not site-specific).
    """
    if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
        return None
    run_dir = MVP_RUNS_DIR / study_id / "_warm"
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    bb_session = None
    browser_session = None
    t0 = time.time()
    t_bb_create: float | None = None
    t_navigate_done: float | None = None
    t_paint: float | None = None
    try:
        from browser_use import BrowserSession

        bb_session = await asyncio.to_thread(
            create_session,
            keep_alive=True,
            owner=_study_bb_owner(),
            study_id=study_id,
            **_product_session_call_kwargs(),
        )
        t_bb_create = time.time() - t0
        connect = getattr(bb_session, "connect_url", None)
        if not connect:
            raise RuntimeError("Browserbase session missing connect_url")
        browser_session = BrowserSession(browser_profile=_browserbase_profile(connect))
        await browser_session.start()
        t_nav0 = time.time()
        # YouTube signed-out home is often an empty splash in automation —
        # warm a search-results URL so we get a real product frame for e2e.
        paint_url = url
        try:
            host = (urlparse(url).hostname or "").lower()
            if "youtube.com" in host or "youtu.be" in host:
                from mvp.auth_state import youtube_bootstrap_url

                paint_url = youtube_bootstrap_url("videos to watch", "warm")
                print(f"[warm] YouTube bootstrap paint via {paint_url}", flush=True)
        except Exception as yt_exc:  # noqa: BLE001
            print(f"[warm] YouTube bootstrap skipped: {yt_exc!r}", flush=True)
            paint_url = url
        await _emit_opening_frame(
            browser_session,
            screenshot_dir=screenshot_dir,
            study_id=study_id,
            agent_id="_warm",
            url=paint_url,
            on_step=None,
        )
        t_navigate_done = time.time() - t_nav0
        shot = screenshot_dir / "bbox_0.png"
        if not shot.is_file() or shot.stat().st_size < 100:
            raise RuntimeError("warm opening screenshot missing")
        block_reason = await _page_block_reason(browser_session)
        if block_reason and not proxies:
            print(
                f"[warm] blocked interstitial for {url}: {block_reason} — "
                "retrying with proxies",
                flush=True,
            )
            try:
                await close_warm_opening(
                    {
                        "bb_session": bb_session,
                        "browser_session": browser_session,
                        "owns_session": True,
                    }
                )
            except Exception:
                pass
            bb_session = None
            browser_session = None
            return await warm_opening_session(
                study_id=study_id, url=url, proxies=True
            )
        t_paint = time.time() - t0
        live_view = None
        try:
            from capability.browserbase_client import session_live_view_url

            sid = getattr(bb_session, "id", None)
            if sid:
                live_view = await asyncio.to_thread(session_live_view_url, str(sid))
        except Exception as live_exc:  # noqa: BLE001
            print(f"[warm] live view url failed: {live_exc!r}", flush=True)
        timing = {
            "bb_create_s": round(t_bb_create, 3) if t_bb_create is not None else None,
            "navigate_and_paint_s": round(t_navigate_done, 3)
            if t_navigate_done is not None
            else None,
            "first_paint_total_s": round(t_paint, 3) if t_paint is not None else None,
            "blankish": _png_is_blankish(shot),
            "blocked": bool(block_reason),
            "block_reason": block_reason,
            "proxies": bool(proxies),
        }
        print(
            f"[warm] first pixels ready for {url} "
            f"bb_create={timing['bb_create_s']}s "
            f"nav+paint={timing['navigate_and_paint_s']}s "
            f"total={timing['first_paint_total_s']}s "
            f"blankish={timing['blankish']} blocked={timing['blocked']} "
            f"proxies={timing['proxies']}",
            flush=True,
        )
        return {
            "url": url,
            "bb_session": bb_session,
            "browser_session": browser_session,
            "shot_path": shot,
            "owns_session": True,
            "live_view_url": live_view,
            "browserbase_session_id": getattr(bb_session, "id", None),
            "timing": timing,
            "blocked": bool(block_reason),
            "block_reason": block_reason,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[warm] opening session failed: {exc!r}", flush=True)
        if browser_session is not None:
            try:
                await browser_session.kill()
            except Exception:
                pass
        if bb_session is not None:
            sid = getattr(bb_session, "id", None)
            if sid:
                try:
                    await asyncio.to_thread(close_session, sid)
                except Exception:
                    pass
        return None


async def close_warm_opening(warm: dict[str, Any] | None) -> None:
    if not warm:
        return
    browser_session = warm.get("browser_session")
    bb_session = warm.get("bb_session")
    if browser_session is not None:
        try:
            await browser_session.kill()
        except Exception:
            pass
        warm["browser_session"] = None
    if warm.get("owns_session") and bb_session is not None:
        sid = getattr(bb_session, "id", None)
        if sid:
            try:
                await asyncio.to_thread(close_session, sid)
            except Exception:
                pass
        warm["bb_session"] = None
        warm["owns_session"] = False


async def run_browser_agent(
    *,
    study_id: str,
    agent_id: str,
    url: str,
    task_prompt: str,
    persona: dict[str, Any],
    segment: str,
    model: str | None = None,
    max_steps: int = MVP_MAX_STEPS,
    on_step: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    bb_session: Any | None = None,
    local: bool = False,
    warm: dict[str, Any] | None = None,
    wall_s: float | None = None,
) -> dict[str, Any]:
    """Run Browser Use (Browserbase or local Chromium) and return a bbox screenshot trace.

    First real pixels are emitted as soon as the target URL is open — before the
    LLM agent loop, and (for non-YouTube) before waiting on auth vault I/O.
    If ``warm`` is a matching pre-opened session from ``warm_opening_session``,
    the landing screenshot is published immediately and the LLM continues on it.
    """
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        home = Path("/tmp/usersim-home")
        home.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HOME", str(home))
        os.environ.setdefault("TMPDIR", "/tmp")
        os.environ.setdefault("XDG_CONFIG_HOME", str(home / ".config"))
        os.environ.setdefault("XDG_CACHE_HOME", str(home / ".cache"))
        Path(os.environ["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

    model = action_model_name(model)
    # wall_s is ignored. A hung browser is stopped by the study budget, or by
    # the accessibility loop's stuck detector on the path studies actually run.
    _ = wall_s
    _budget = MVP_STEP_TIMEOUT_S
    os.environ.setdefault("BROWSER_USE_CDP_TIMEOUT_S", str(_budget))
    os.environ.setdefault("BROWSER_USE_ACTION_TIMEOUT_S", str(_budget))

    run_dir = MVP_RUNS_DIR / study_id / agent_id
    screenshot_dir = run_dir / "screenshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    phase_clock = _PhaseClock(agent_id, study_id)
    run_failure: BaseException | None = None

    from mvp.profile_pool import clone_for_url, discard as discard_profile

    from mvp.auth_state import (
        ensure_site_auth,
        storage_state_for_url,
        youtube_bootstrap_url,
        youtube_is_signed_in,
        youtube_needs_content_bootstrap,
    )

    start_url = url
    yt_hint = ""
    host = (urlparse(url).hostname or "").lower()
    is_youtube = "youtube.com" in host or "youtu.be" in host

    force_local = local or os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {
        "1",
        "true",
        "yes",
    }

    use_warm = (
        not force_local
        and isinstance(warm, dict)
        and warm.get("browser_session") is not None
        and _urls_match(str(warm.get("url") or ""), url)
        and warm.get("shot_path")
        and Path(warm["shot_path"]).is_file()
    )

    # YouTube: never block the UI on vault I/O before first pixels.
    # Load disk cookies fast → open browser → screenshot; refresh auth in parallel.
    auth_task: asyncio.Task | None = None
    storage_state: Any = None

    async def _pulse(text: str, *, thinking: bool = False) -> None:
        if on_step is None:
            return
        maybe = on_step(
            {
                "step": None,
                "progress_only": True,
                "action": text,
                "thought": text,
                "thought_detail": {"thinking": text} if thinking else {},
                "observation": "",
                "url": start_url,
                "screenshot_url": None,
                "outcome": "neutral",
            }
        )
        if asyncio.iscoroutine(maybe):
            await maybe

    if is_youtube:
        await _pulse(f"Preparing YouTube session for {url}…")
        # Instant disk cookies so we can open a browser without waiting on sign-in.
        storage_state = storage_state_for_url(url)
        # Background refresh only when auto sign-in/sign-up is enabled.
        if os.environ.get("MVP_AUTO_SIGNUP", "").lower() in {"1", "true", "yes"} or os.environ.get(
            "MVP_AUTO_SIGNIN", ""
        ).lower() in {"1", "true", "yes"}:
            auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))
        if youtube_needs_content_bootstrap(url, storage_state):
            start_url = youtube_bootstrap_url(task_prompt, persona.get("name") or "")
            yt_hint = (
                "YouTube's signed-out home feed is often empty in automation. You were opened on "
                "search results with real videos — use those, refine the query, or open a video. "
                "If you can sign in / avatar is visible, you may also open Home afterward.\n"
            )
            await _pulse(f"Opening search results — {start_url.split('search_query=')[-1][:40]}…")
        elif youtube_is_signed_in(
            storage_state if isinstance(storage_state, dict) else None
        ):
            yt_hint = (
                "You are signed into YouTube (Gmail session cookies loaded). Use the personalized "
                "home feed, subscriptions, and account UI as a real logged-in user would.\n"
            )
            await _pulse("Signed-in cookies ready — opening YouTube…")
        else:
            await _pulse("Opening YouTube…")
    elif not use_warm:
        await _pulse(f"Opening {url}…")
        auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))

    cookie_state = storage_state if isinstance(storage_state, dict) else None
    if storage_state and isinstance(storage_state, dict):
        state_path = run_dir / "storage_state.json"
        state_path.write_text(json.dumps(storage_state))
        storage_state = str(state_path)

    owns_session = False
    session_url: str | None = None
    profile_clone = None
    browser_session = None
    history = None
    backend = "browserbase"
    warm_live_url = None
    warm_bb_id = None
    page_state: dict[str, Any] = {
        "sigs": {},
        "holds": 0,
        "captcha": None,
        "t0": None,
        "first_action_s": None,
        "step": 0,
        "phase_clock": phase_clock,
        "on_step": on_step,
    }

    def _build_llm() -> Any:
        from browser_use import ChatGoogle

        location = os.environ.get("MVP_VERTEX_LOCATION") or location_for(model)
        kwargs: dict[str, Any] = {
            "model": model,
            "vertexai": True,
            "credentials": vertex_credentials(),
            "project": GCP_PROJECT,
            "location": location,
            "temperature": 0,
            # One attempt. A slow call is aborted by http timeout and the next
            # agent step retries, instead of five backoffs eating the wall.
            "max_retries": 1,
            "max_output_tokens": 768,
            "http_options": {"timeout": max(3000, (MVP_LLM_TIMEOUT_S - 2) * 1000)},
        }
        # Gemini 2.5 thinking is what stretched the first call past a minute.
        if "2.5" in model or "gemini-3" in model:
            kwargs["thinking_budget"] = 0
        return ChatGoogle(**kwargs)

    # Overlap client setup with navigation so the vision call can start
    # on the first screenshot.
    llm_task = asyncio.create_task(asyncio.to_thread(_build_llm))

    async def _vision_from_opening() -> Any:
        if page_state.get("vision_started") or browser_session is None:
            return None
        page_state["vision_started"] = True
        try:
            llm_ready = await llm_task
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] LLM client failed: {exc!r}", flush=True)
            failed = _failed_trace_step(
                step_no=1,
                reason=f"{type(exc).__name__}: {exc}"[:400],
                phase="llm",
                url=start_url,
            )
            _schedule_emit(on_step, failed, page_state)
            page_state["step"] = 1
            return None
        _install_agent_probes(None, llm_ready, phase_clock)
        try:
            await _act_from_opening_screenshot(
                browser_session,
                llm_ready,
                clock=phase_clock,
                screenshot_dir=screenshot_dir,
                study_id=study_id,
                agent_id=agent_id,
                task_prompt=task_prompt,
                url=start_url,
                on_step=on_step,
                book=page_state,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] opening vision failed: {exc!r}", flush=True)
            phase_clock.note_exception("llm", exc, where="opening", step=1)
        return llm_ready if page_state.get("vision_started") else None

    if use_warm:
        browser_session = warm["browser_session"]
        bb_session = warm.get("bb_session") or bb_session
        owns_session = bool(warm.get("owns_session", True))
        session_url = getattr(bb_session, "session_url", None) if bb_session else None
        backend = "browserbase"
        warm_live_url = warm.get("live_view_url")
        warm_bb_id = warm.get("browserbase_session_id") or getattr(bb_session, "id", None)
        # Publish warm pixels under this agent id immediately.
        dest = screenshot_dir / "bbox_0.png"
        try:
            if Path(warm["shot_path"]) != dest:
                shutil.copy2(warm["shot_path"], dest)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] warm shot copy failed: {exc!r}", flush=True)
            use_warm = False
            if not is_youtube and auth_task is None:
                auth_task = asyncio.create_task(asyncio.to_thread(ensure_site_auth, url))
        if use_warm:
            step = {
                "step": 0,
                "action": f"Opened {url}",
                "observation": "Landing page screenshot",
                "thought": "",
                "thought_detail": {},
                "url": url,
                "screenshot_url": (
                    f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_0.png"
                ),
                "boxes": [],
                "outcome": "neutral",
                "evidence_label": "Opening frame · before agent steps",
            }
            page_state["screenshot_mono"] = time.monotonic()
            _schedule_emit(on_step, step, page_state)
            await _vision_from_opening()
            # Stash live URL and turn live view ON immediately — page is open.
            if on_step is not None and (warm_live_url or bb_session is not None):
                maybe = on_step(
                    {
                        "step": None,
                        "progress_only": True,
                        "live_active": True,
                        "live_view_url": warm_live_url,
                        "browserbase_session_id": warm_bb_id,
                        "action": "Page open — live browser on",
                        "thought": "Page is open. Starting the simulated user…",
                        "thought_detail": {},
                        "observation": "",
                        "url": url,
                        "screenshot_url": None,
                        "outcome": "neutral",
                    }
                )
                if asyncio.iscoroutine(maybe):
                    await maybe
            print(f"[{agent_id}] warm opening frame published immediately", flush=True)
            # Prevent double-close if caller also holds the warm dict.
            warm["browser_session"] = None
            warm["bb_session"] = None
            warm["owns_session"] = False

    # Only a few navigations at once. The run slot above this stays held so
    # the model loop can overlap once the page is actually open.
    hold_nav = not use_warm
    if hold_nav:
        await _nav_semaphore().acquire()
    try:
        if not use_warm:
            if force_local:
                # A cloned signed-in profile beats cookie injection: Google binds session
                # cookies to the profile, so transplanted cookies report LOGGED_IN=false.
                profile_clone = await asyncio.to_thread(clone_for_url, url)
                if profile_clone:
                    cookie_state = None
                    if auth_task is not None and not auth_task.done():
                        auth_task.cancel()
                        try:
                            await auth_task
                        except Exception:
                            pass
                        auth_task = None
                    start_url = url
                    yt_hint = (
                        "You are signed in on this site. Use the personalized home feed, "
                        "subscriptions, and account UI as a real logged-in user would.\n"
                    )
                profile = _local_browser_profile(
                    storage_state=None
                    if profile_clone
                    else (storage_state if isinstance(storage_state, str) else None),
                    user_data_dir=str(profile_clone) if profile_clone else None,
                )
                backend = "local_playwright"
            else:
                # create_session may contend on a threading lock; off-loop so parallel agents progress.
                owns_session = bb_session is None
                if owns_session:
                    # keep_alive=True so parallel agents don't lose CDP mid-run (410 Gone).
                    bb_session = await asyncio.to_thread(
                        create_session,
                        keep_alive=True,
                        owner=_study_bb_owner(),
                        study_id=study_id,
                        **_product_session_call_kwargs(),
                    )
                    print(
                        f"[{agent_id}] browserbase flags={getattr(bb_session, 'flags', None)}",
                        flush=True,
                    )
                session_url = getattr(bb_session, "session_url", None)
                connect = getattr(bb_session, "connect_url", None)
                if not connect:
                    raise RuntimeError("Browserbase session missing connect_url")
                profile = _browserbase_profile(connect)
                backend = "browserbase"
                await _pulse("Browser ready — loading the page…")

            try:
                from browser_use import BrowserSession

                # Own the session before agent.run so we navigate + show a frame
                # the moment the task URL is known — not after the LLM's first thought.
                browser_session = BrowserSession(browser_profile=profile)
                await browser_session.start()
                _install_session_probes(browser_session, phase_clock)

                _opening_where = _PHASE_WHERE.set("opening")
                try:
                    await _emit_opening_frame(
                        browser_session,
                        screenshot_dir=screenshot_dir,
                        study_id=study_id,
                        agent_id=agent_id,
                        url=start_url,
                        on_step=on_step,
                        book=page_state,
                    )
                finally:
                    _PHASE_WHERE.reset(_opening_where)
                await _vision_from_opening()
                # Flip live view ON immediately — don't wait for LLM / agent.run.
                if on_step is not None and bb_session is not None and not force_local:
                    live_url = None
                    try:
                        from capability.browserbase_client import session_live_view_url

                        sid = getattr(bb_session, "id", None)
                        if sid:
                            live_url = await asyncio.to_thread(session_live_view_url, str(sid))
                    except Exception:
                        live_url = None
                    maybe = on_step(
                        {
                            "step": None,
                            "progress_only": True,
                            "live_active": True,
                            "live_view_url": live_url,
                            "browserbase_session_id": getattr(bb_session, "id", None),
                            "action": "Live browser on",
                            "thought": "Page is open — live view connected.",
                            "thought_detail": {},
                            "observation": "",
                            "url": start_url,
                            "screenshot_url": None,
                            "outcome": "neutral",
                        }
                    )
                    if asyncio.iscoroutine(maybe):
                        await maybe
                await _pulse("First screenshot captured — starting the simulated user…", thinking=True)
            except Exception:
                if browser_session is not None:
                    try:
                        await browser_session.kill()
                    except Exception:
                        pass
                if profile_clone is not None:
                    await asyncio.to_thread(discard_profile, profile_clone)
                if owns_session and bb_session is not None:
                    sid = getattr(bb_session, "id", None)
                    if sid:
                        await asyncio.to_thread(close_session, sid)
                raise
    finally:
        if hold_nav:
            _nav_semaphore().release()

    try:
        # Auth/cookies after the first click. The vision action already ran
        # on the opening screenshot.
        if auth_task is not None:
            try:
                # Cap wait so a slow vault never owns TTFT; skip cookies if late.
                storage_state = await asyncio.wait_for(auth_task, timeout=2.5)
            except asyncio.TimeoutError:
                print(f"[{agent_id}] deferred auth timed out — starting without cookies", flush=True)
                auth_task.cancel()
                try:
                    await auth_task
                except Exception:
                    pass
                storage_state = None
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] deferred auth failed: {exc!r}", flush=True)
                storage_state = None
            cookie_state = storage_state if isinstance(storage_state, dict) else None
            if storage_state and isinstance(storage_state, dict):
                state_path = run_dir / "storage_state.json"
                state_path.write_text(json.dumps(storage_state))
                storage_state = str(state_path)

        if cookie_state and browser_session is not None:
            injected = await _inject_cookies(browser_session, cookie_state)
            print(f"[{agent_id}] injected {injected} cookies via CDP", flush=True)

        from browser_use import Agent

        llm = await llm_task
        _install_agent_probes(None, llm, phase_clock)
        persona_line = f"You are {persona.get('name')}: {persona.get('bio')}"
        stay_put = (
            f"CRITICAL: Stay on {start_url} and its own pages/subdomains only. "
            f"Do not navigate to other products or competitors (especially not YouTube, "
            f"Vimeo, or Dailymotion unless that is exactly this site). "
            f"Evaluate the task using THIS site’s UI, search, and docs.\n"
        )
        agent_task = (
            f"{CAPABLE_AGENT_PREAMBLE}\n\n"
            f"{persona_line}\n"
            f"Customer segment: {segment}\n"
            f"{yt_hint}"
            f"{stay_put}"
            f"You are already on {start_url}. Continue from this page.\n"
            f"Task: {task_prompt}\n"
            f"Behave like this persona would — note confusion, pricing concerns, and UX friction.\n"
            f"Do not judge the site from the landing page alone. The task is not done when you "
            f"can describe the first screen.\n"
            f"Click, type, and open the specific page or control the task names. "
            f"Call done only after that page or state is on screen, or when a captcha, "
            f"login wall, or missing control blocks you. Say which.\n"
            f"On a drawing canvas, clicking a shape tool does not place a shape. "
            f"Select the tool, then use drag (mouse down, move, mouse up) across the canvas.\n"
            f"If the page says Press and Hold, use press_and_hold on that control. "
            f"Do not use an external captcha service.\n"
            f"Do not write todo files. Do not wait if the page is already visible.\n"
        )

        agent = Agent(
            task=agent_task,
            llm=llm,
            browser_session=browser_session,
            browser_profile=None,
            tools=_study_tools(),
            use_vision=True,
            vision_detail_level="low",
            use_thinking=False,
            # flash_mode emits actions the controller drops ("no handler"),
            # so the step fails without a click. Planning stays off so the
            # first action is a click, not a todo file.
            flash_mode=False,
            enable_planning=False,
            use_judge=False,
            # Do not stop the agent because a model call was slow or failed.
            max_failures=10_000,
            llm_timeout=MVP_LLM_TIMEOUT_S,
            step_timeout=MVP_STEP_TIMEOUT_S,
            llm_screenshot_size=(800, 450),
            message_compaction=False,
            max_actions_per_step=2,
            calculate_cost=True,
            file_system_path=str(run_dir),
            save_conversation_path=str(run_dir / "conversation"),
            # We already navigated + screenshotted. Default True makes browser-use
            # re-navigate to the URL in the task text BEFORE the first hooked step —
            # live iframe up, step rail stuck at opening, looks frozen on YouTube.
            directly_open_url=False,
            extend_system_message=(
                "You are a real user in a usability study, not an optimizer. "
                "Prefer obvious UI paths; comment on clarity and trust. "
                "Never claim to see content that is only 'implied' or absent from the "
                "current screenshot/DOM. Stay on the product site you were given. "
                "If a cookie/consent banner blocks the page, Accept all / Agree first, "
                "then continue the task. "
                "Do not call done on the landing page. Do not spend a step writing notes "
                "or waiting. Act on the task. "
                "To draw, call drag with viewport coordinates. A click on the rectangle "
                "tool is not a rectangle. "
                "On a Press and Hold check, call press_and_hold. Never call CapSolver "
                "or another captcha API. "
                "When the DOM has no element index, click or type with coordinate_x "
                "and coordinate_y in viewport pixels."
            ),
        )
        try:
            agent.tools.set_coordinate_clicking(True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{agent_id}] coordinate clicking unavailable: {exc!r}", flush=True)
        try:
            object.__setattr__(agent, "_usersim_book", page_state)
            object.__setattr__(agent, "_usersim_step_offset", int(page_state.get("step") or 0))
        except Exception:
            pass
        decision = page_state.get("vision_action")
        if isinstance(decision, dict):
            try:
                from browser_use.agent.views import ActionResult

                label = (
                    f"typed {decision.get('text')!r} at ({decision.get('x')},{decision.get('y')})"
                    if decision.get("kind") == "type"
                    else f"clicked ({decision.get('x')},{decision.get('y')})"
                )
                agent.state.last_result = [
                    ActionResult(
                        extracted_content=(
                            f"You already {label} using the opening screenshot. "
                            "Continue the task from the current page."
                        ),
                        long_term_memory=f"Already {label} from the opening screenshot.",
                    )
                ]
            except Exception as exc:  # noqa: BLE001
                print(f"[{agent_id}] could not record the opening click: {exc!r}", flush=True)
        if use_warm and browser_session is not None:
            _install_session_probes(browser_session, phase_clock)
        _install_agent_probes(agent, llm, phase_clock)
        # Signal UI: agent loop is starting — replace screenshot with live view now.
        if on_step is not None and bb_session is not None:
            live_url = warm_live_url
            if not live_url:
                try:
                    from capability.browserbase_client import session_live_view_url

                    sid = getattr(bb_session, "id", None)
                    if sid:
                        live_url = await asyncio.to_thread(session_live_view_url, str(sid))
                except Exception:
                    live_url = None
            maybe = on_step(
                {
                    "step": None,
                    "progress_only": True,
                    "live_active": True,
                    "live_view_url": live_url,
                    "browserbase_session_id": getattr(bb_session, "id", None) or warm_bb_id,
                    "action": "Agent started — live browser on",
                    "thought": "I'm on the page now. Looking around before I click…",
                    "thought_detail": {
                        "thinking": "Landing page is open. Reading what's visible and choosing a first action."
                    },
                    "observation": "",
                    "url": start_url,
                    "screenshot_url": None,
                    "outcome": "neutral",
                }
            )
            if asyncio.iscoroutine(maybe):
                await maybe
        if page_state.get("screenshot_mono") is None:
            page_state["screenshot_mono"] = time.monotonic()
        page_state["t0"] = page_state["screenshot_mono"]
        on_step_start, on_step_end = _make_step_hooks(
            screenshot_dir,
            study_id=study_id,
            agent_id=agent_id,
            start_url=start_url,
            on_step=on_step,
            page_state=page_state,
        )
        await _ensure_cdp_connected(browser_session, agent_id=agent_id)
        print(
            f"[{agent_id}] agent.run starting model={model} provider=google-vertex "
            f"llm_timeout={MVP_LLM_TIMEOUT_S}s step_timeout={MVP_STEP_TIMEOUT_S}s "
            f"(warm={use_warm}, max_steps={max_steps}, cdp_budget={_budget}s)",
            flush=True,
        )
        history = None
        run_failure: BaseException | None = None
        try:
            history = await agent.run(
                max_steps=max_steps,
                on_step_start=on_step_start,
                on_step_end=on_step_end,
            )
        except asyncio.CancelledError:
            if _task_is_cancelling():
                raise
            run_failure = RuntimeError("CancelledError: agent run interrupted")
            phase_clock.note_exception("agent_run", run_failure, where="loop")
            print(f"[{agent_id}] agent.run interrupted — returning partial", flush=True)
        except Exception as run_exc:  # noqa: BLE001
            # Prefer partial opening frames over raising into study retry.
            # The exception used to stop here, so failures.json never saw it.
            run_failure = run_exc
            phase_clock.note_exception("agent_run", run_exc, where="loop")
            print(f"[{agent_id}] agent.run failed: {run_exc!r} — returning partial", flush=True)
    finally:
        if browser_session is not None:
            try:
                await asyncio.wait_for(browser_session.kill(), timeout=8)
            except Exception:
                pass
            browser_session = None
        if profile_clone is not None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(discard_profile, profile_clone), timeout=5
                )
            except Exception:
                pass
        if owns_session and bb_session is not None:
            sid = getattr(bb_session, "id", None)
            if sid:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(close_session, sid), timeout=8
                    )
                except Exception:
                    pass

    actions = _history_to_actions(history) if history is not None else []
    emitted = page_state.get("emitted") if isinstance(page_state.get("emitted"), dict) else {}
    if emitted:
        trace = [emitted[k] for k in sorted(emitted) if isinstance(k, int)]
    else:
        trace = (
            _history_to_trace(
                history, study_id=study_id, agent_id=agent_id, screenshot_dir=screenshot_dir
            )
            if history is not None
            else []
        )
    pending_emits = [t for t in (page_state.get("emit_tasks") or []) if asyncio.isfuture(t)]
    if pending_emits:
        await asyncio.wait(pending_emits, timeout=2)
    # Keep the pre-agent landing frame (bbox_0) ahead of LLM steps.
    opening = screenshot_dir / "bbox_0.png"
    if opening.is_file() and opening.stat().st_size > 100:
        open_url = url
        try:
            if history is not None and hasattr(history, "urls"):
                urls0 = history.urls() or []
                if urls0:
                    open_url = urls0[0]
        except Exception:
            pass
        if not any(s.get("step") == 0 for s in trace):
            trace = [
                {
                    "step": 0,
                    "action": f"Opened {open_url}",
                    "observation": "Landing page loaded — agent starting…",
                    "thought": "",
                    "thought_detail": {},
                    "url": open_url,
                    "screenshot_url": (
                        f"/api/studies/{study_id}/agents/{agent_id}/screenshots/bbox_0.png"
                    ),
                    "boxes": [],
                    "outcome": "neutral",
                    "evidence_label": "Opening frame · before agent steps",
                },
                *trace,
            ]

    final_url = ""
    try:
        urls = history.urls() if history is not None and hasattr(history, "urls") else []
        final_url = urls[-1] if urls else ""
    except Exception:
        final_url = actions[-1].get("url") or url if actions else url

    is_done = False
    try:
        is_done = (
            bool(history.is_done()) if history is not None and hasattr(history, "is_done") else False
        )
    except Exception:
        pass

    sigs = page_state.get("sigs") if isinstance(page_state.get("sigs"), dict) else {}
    for step in trace:
        n = step.get("step")
        if isinstance(n, int) and n in sigs and not step.get("state_sig"):
            step["state_sig"] = sigs[n]
    _stamp_phase_trace(trace, phase_clock)
    swallowed_error, swallowed_browser_error = _surface_swallowed_failure(
        phase_clock, run_failure, trace
    )
    ended_failed = _last_failed_step(trace)
    if ended_failed and not swallowed_error and not swallowed_browser_error:
        reason = str(ended_failed.get("reason") or "")
        if _cdp_failure_text(reason):
            swallowed_browser_error = reason[:400]
        else:
            swallowed_error = reason[:400]

    visited_urls: list[str] = []
    for step in trace:
        step_url = step.get("url")
        if step_url and step_url not in visited_urls:
            visited_urls.append(step_url)

    bb_flags = getattr(bb_session, "flags", None) if bb_session is not None else None
    captcha = page_state.get("captcha")
    first_action_s = page_state.get("first_action_s")

    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "study_id": study_id,
                "agent_id": agent_id,
                "task_prompt": task_prompt,
                "persona": persona,
                "actions": actions,
                "trace": trace,
                "final_url": final_url,
                "visited_urls": visited_urls,
                "completed": is_done,
                "backend": backend,
                "browserbase_session_url": session_url,
                "browserbase_flags": bb_flags,
                "model": model,
                "model_provider": "google-vertex",
                "captcha": captcha,
                "first_action_s": first_action_s,
                "phase_events": phase_clock.events,
                "error": swallowed_error,
                "browser_error": swallowed_browser_error,
                "failed_step": ended_failed,
            },
            indent=2,
            default=str,
        )
    )

    return {
        "agent_id": agent_id,
        "persona_id": persona.get("id"),
        "task_id": agent_id,
        "completed": is_done,
        "final_url": final_url,
        "visited_urls": visited_urls,
        "actions": actions,
        "trace": trace,
        "backend": backend,
        "browserbase_session_url": session_url,
        "browserbase_flags": bb_flags,
        "model": model,
        "model_provider": "google-vertex",
        "captcha": captcha,
        "first_action_s": first_action_s,
        "phase_events": phase_clock.events,
        "error": swallowed_error,
        "browser_error": swallowed_browser_error,
        "failed_step": ended_failed,
        "run_dir": str(run_dir),
        "num_steps": len(trace),
    }
