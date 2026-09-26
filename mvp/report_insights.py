"""Evidence-backed report claims.

A strength or weakness is included only when it cites a real agent step that
has a screenshot. Generic "the page loaded" notes are not claims. When two
sites succeed at the same rate, they are ordered by steps, then time, then
friction.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import Any

# Observations that do not say anything about the product.
_GENERIC = (
    "page loaded",
    "loaded quickly",
    "loaded without",
    "without any obvious",
    "without any apparent",
    "easy to access",
    "navigating to the homepage",
    "navigating to the landing",
    "navigating to the website",
    "the site loaded",
    "homepage loaded",
    "landing page loaded",
    "clear landing page",
    "presented a clear landing",
    "no obvious issues",
    "no apparent issues",
)

# Words that make a note specific enough to cite.
_CONCRETE = (
    "clean",
    "modern",
    "professional",
    "clutter",
    "confus",
    "pricing",
    "sign up",
    "signup",
    "sign-up",
    "navigation",
    "menu",
    "error",
    "blank",
    "slow",
    "captcha",
    "login",
    "search",
    "couldn't",
    "could not",
    "can't",
    "cannot",
    "hard to find",
    "hard to use",
    "hard to see",
    "unclear",
    "broken",
    "missing",
    "paywall",
    "modal",
    "popup",
    "cookie",
    "form",
    "button",
    "canvas",
    "drawing",
    "sketch",
    "whiteboard",
)


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _parse_ts(value: object) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _mentions(text: str, bit: str) -> bool:
    if " " in bit or "'" in bit:
        return bit in text
    return re.search(rf"\b{re.escape(bit)}\b", text) is not None


_NEGATIVE_RE = re.compile(
    r"couldn'?t|could not|can'?t|cannot|hard to|confus|unclear|no clear|"
    r"didn'?t|did not|no immediate|no path|stuck|difficult|where to start|"
    r"can(?:no|')t even|not seeing|haven'?t found|no information|can'?t tell|"
    r"not found|no obvious path",
    re.I,
)
_HEDGE_RE = re.compile(
    r"too early|haven'?t seen|not sure|need to find|how easy|looking for|just starting",
    re.I,
)
_POSITIVE_RE = re.compile(
    r"\b(clean|modern|professional|easy|clear|simple|fast|intuitive|obvious|helpful)\b",
    re.I,
)


def _sentiment(text: str) -> str:
    """pos, neg, or neutral. A complaint is never a strength.

    Hedged lines ("too early to tell", "how easy is it") are not claims.
    """
    complaint = bool(re.search(r"couldn'?t|could not|can'?t|cannot|no clear|no immediate", text, re.I))
    if _HEDGE_RE.search(text) and not complaint:
        return "neutral"
    if _NEGATIVE_RE.search(text):
        return "neg"
    if _POSITIVE_RE.search(text):
        return "pos"
    return "neutral"


def _is_generic(text: str) -> bool:
    """True when the note does not name a specific product observation."""
    low = text.lower().strip()
    if not low or len(low) < 12:
        return True
    if any(_mentions(low, bit) for bit in _CONCRETE):
        return False
    # A full sentence that is not a "page loaded" note is specific enough to cite.
    if len(low) >= 40 and not any(phrase in low for phrase in _GENERIC):
        return False
    return True


def _runs(study: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in (study.get("agent_results") or []) if isinstance(r, dict)]


def _shots(run: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for step in run.get("trace") or []:
        if isinstance(step, dict) and step.get("screenshot_url") and isinstance(step.get("step"), int):
            out.append(step)
    return out


def _evidence(run: dict[str, Any], *, detail: str, prefer_friction: bool = False) -> dict[str, Any] | None:
    shots = _shots(run)
    if not shots:
        return None
    chosen = None
    if prefer_friction:
        for step in shots:
            if str(step.get("outcome") or "") == "friction":
                chosen = step
                break
    if chosen is None:
        chosen = shots[-1]
    shot = str(chosen.get("screenshot_url") or "")
    if not shot:
        return None
    # Reject a citation whose screenshot is not actually on this run.
    if shot not in {str(s.get("screenshot_url") or "") for s in shots}:
        return None
    return {
        "agent_id": str(run.get("agent_id") or ""),
        "persona_name": str(run.get("persona_name") or "Simulated user"),
        "task_title": str(run.get("task_title") or ""),
        "step": chosen.get("step"),
        "screenshot_url": shot,
        "step_url": str(chosen.get("url") or ""),
        "final_url": str(run.get("final_url") or chosen.get("url") or ""),
        "action": str(chosen.get("action") or "")[:180],
        "detail": (detail or str(chosen.get("action") or ""))[:220],
    }


def _stuck_on_open(run: dict[str, Any], start_host: str) -> bool:
    steps = int(run.get("num_steps") or len(run.get("trace") or []) or 0)
    final = _host(str(run.get("final_url") or ""))
    if steps > 2:
        return False
    if not final:
        return True
    return final == start_host or start_host.endswith(final) or final.endswith(start_host)


_INTERACT = (
    "click",
    "input",
    "input_text",
    "type",
    "send_keys",
    "go_to_url",
    "search",
    "scroll",
    "select",
    "drag",
    "press_and_hold",
)


def _page_key(url: str | None) -> tuple[str, str, str]:
    if not url:
        return ("", "", "")
    try:
        parsed = urlparse(url)
    except Exception:
        return ("", url, "")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = (parsed.path or "/").rstrip("/") or "/"
    return (host, path, parsed.query or "")


def _action_name(step: dict[str, Any]) -> str:
    label = str(step.get("action") or "").lower()
    return label.split("—")[0].split(":")[0].strip()


def _canvas_dark(raw: str) -> int | None:
    """Sum of non-white samples. None when the signature is missing or tainted."""
    if not raw or "taint" in raw:
        return None
    total = 0
    found = False
    for part in raw.split(";"):
        if "dark=" not in part:
            continue
        found = True
        num = part.split("dark=", 1)[1].split("/", 1)[0]
        if num.lstrip("-").isdigit():
            total += int(num)
    return total if found else None


def _canvas_changed(a: str, b: str) -> bool:
    """A stroke adds non-white pixels. A cursor blink does not.

    The page read scans full rows and columns and hashes where the ink is
    (':h=' in the signature), so a thin pen stroke that adds only a few dark
    samples still counts when the ink moved.
    """
    da, db = _canvas_dark(a), _canvas_dark(b)
    if da is None or db is None:
        return False
    if abs(da - db) >= 8:
        return True
    ha, hb = re.findall(r":h=([0-9a-z]+)", a), re.findall(r":h=([0-9a-z]+)", b)
    return bool(ha and hb and len(ha) == len(hb) and ha != hb and db > 0)


def _text_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _text_changed(a: str, b: str) -> bool:
    ta, tb = _text_tokens(a), _text_tokens(b)
    if len(ta) < 8 or len(tb) < 8:
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        # The first accessibility read is often just the document title.
        # A later read of the real page is a DOM change.
        if len(short) <= 40 and len(long) - len(short) >= 80:
            return True
        return False
    union = len(ta | tb) or 1
    delta = len(ta ^ tb)
    return delta >= 12 and (len(ta & tb) / union) < 0.82


def changed_page_state(run: dict[str, Any], start_url: str) -> bool:
    """URL change, or a meaningful DOM-text or canvas-pixel change.

    Highlight overlays are not part of the signature. A same-URL canvas
    (Excalidraw) counts when the drawing surface actually changes.
    """
    if left_start(run, start_url):
        return True
    steps = [
        step
        for step in (run.get("trace") or [])
        if isinstance(step, dict) and isinstance(step.get("state_sig"), dict)
    ]
    sigs = [step["state_sig"] for step in steps]
    if len(sigs) < 2:
        return False
    # Canvas apps mount their canvas after the first read; judge ink against
    # the first signature that has one.
    base = sigs[0]
    ink_base = next((sig for sig in sigs if "dark=" in str(sig.get("canvas") or "")), base)
    for step, sig in zip(steps[1:], sigs[1:]):
        # A drag that added vector shapes (SVG canvases such as tldraw leave the
        # pixel sample unchanged) changed the drawing surface.
        if str(step.get("action") or "").strip().lower() == "drag" and int(sig.get("shapes") or 0) > int(base.get("shapes") or 0):
            return True
        if _canvas_changed(str(ink_base.get("canvas") or ""), str(sig.get("canvas") or "")):
            return True
        if _text_changed(str(base.get("text") or ""), str(sig.get("text") or "")):
            return True
    return False


def left_start(run: dict[str, Any], start_url: str) -> bool:
    """True when any recorded URL is a different page than the one the run opened."""
    start = run.get("site_url") or start_url
    start_key = _page_key(str(start or ""))
    urls = [run.get("final_url")]
    urls.extend(step.get("url") for step in (run.get("trace") or []) if isinstance(step, dict))
    for url in urls:
        key = _page_key(str(url or ""))
        if key != ("", "", "") and key != start_key:
            return True
    return False


def left_first_screen(run: dict[str, Any], start_url: str) -> bool:
    """True when the run left the opening screen.

    A URL change, a meaningful DOM change, or a canvas stroke counts.
    Waiting, or calling done, on the untouched landing page does not.
    """
    return changed_page_state(run, start_url)


def product_task_passed(run: dict[str, Any], start_url: str) -> bool:
    """Product task success that rejects first-screen stalls.

    Homepage-only runs fail even if the model calls done.
    """
    if not left_first_screen(run, start_url):
        return False
    return task_succeeded(run, start_url)


def product_completion_gate(
    runs: list[dict[str, Any]],
    start_url: str,
) -> dict[str, Any]:
    """At least half of the product runs must leave the first screen and finish.

    A 24-agent matrix has 8 product runs, so the bar is 4/8.
    """
    product = [
        run
        for run in runs
        if isinstance(run, dict) and str(run.get("site_key") or "product") == "product"
    ]
    passed: list[str] = []
    first_screen: list[str] = []
    for run in product:
        aid = str(run.get("agent_id") or run.get("task_id") or "")
        start = str(run.get("site_url") or start_url or "")
        if product_task_passed(run, start):
            passed.append(aid)
        elif not left_first_screen(run, start):
            first_screen.append(aid)
    n = len(product)
    k = len(passed)
    required = (n + 1) // 2 if n else 0
    if n >= 8:
        required = max(required, 4)
    ok = n > 0 and k >= required
    return {
        "product_n": n,
        "success_n": k,
        "success_rate": round(100 * k / n) if n else 0,
        "required_n": required,
        "required_rate": 0.5,
        "first_screen_failures": first_screen,
        "passed_ids": passed,
        "pass": ok,
    }


def task_succeeded(run: dict[str, Any], start_url: str) -> bool:
    """Final-state success: the run interacted and the page state changed, or typed.

    Describing the homepage, waiting, or writing a note is not success.
    Page state changes on a URL change or a meaningful DOM or canvas change.
    """
    failed = run.get("failed_step")
    if isinstance(failed, dict) and str(failed.get("phase") or "").strip():
        # The step loop only writes phase "done" after the page itself showed
        # the goal (never a docs page, never an account wall).
        return str(failed.get("phase")) == "done"
    steps = [step for step in (run.get("trace") or []) if isinstance(step, dict)]
    names = [_action_name(step) for step in steps]
    interacted = any(name.startswith(_INTERACT) or name in _INTERACT for name in names)
    typed = any(name in {"input", "input_text", "type", "send_keys"} for name in names)
    if typed or (interacted and changed_page_state(run, start_url)):
        return True
    # Single-page apps (the canvas stays on one URL). A done call after a
    # click counts only when it names a control, not the landing page.
    done = " ".join(str(step.get("action") or "") for step in steps if _action_name(step) == "done")
    if interacted and done and not _is_generic(done):
        return True
    return False


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 3)


def _step_latencies(runs: list[dict[str, Any]]) -> list[float]:
    vals: list[float] = []
    for run in runs:
        for step in run.get("trace") or []:
            if not isinstance(step, dict) or step.get("step") in (None, 0):
                continue
            raw = step.get("step_latency_s")
            if isinstance(raw, (int, float)) and raw >= 0:
                vals.append(float(raw))
    return vals


def _latency_block(runs: list[dict[str, Any]]) -> dict[str, Any]:
    lat = _step_latencies(runs)
    first = [
        float(r["first_action_s"])
        for r in runs
        if isinstance(r.get("first_action_s"), (int, float))
    ]
    models = [str(r.get("model")) for r in runs if r.get("model")]
    providers = [str(r.get("model_provider")) for r in runs if r.get("model_provider")]
    return {
        "step_latency_p50": _percentile(lat, 0.50),
        "step_latency_p95": _percentile(lat, 0.95),
        "first_action_p50": _percentile(first, 0.50),
        "model": models[0] if models else None,
        "model_provider": providers[0] if providers else None,
    }


def work_metrics(runs: list[dict[str, Any]], start_url: str) -> dict[str, Any]:
    empty_latency = {
        "step_latency_p50": None,
        "step_latency_p95": None,
        "first_action_p50": None,
        "model": None,
        "model_provider": None,
    }
    if not runs:
        return {
            "n": 0,
            "median_steps": None,
            "left_start_pct": 0,
            "changed_page_pct": 0,
            "task_success_rate": 0,
            "task_success_n": 0,
            "left_start_n": 0,
            "changed_page_n": 0,
            **empty_latency,
        }
    steps = [float(run_steps(r)) for r in runs]
    left_n = sum(1 for r in runs if left_start(r, start_url))
    changed_n = sum(1 for r in runs if changed_page_state(r, start_url))
    ok_n = sum(1 for r in runs if task_succeeded(r, start_url))
    return {
        "n": len(runs),
        "median_steps": _median(steps),
        "left_start_n": left_n,
        "left_start_pct": round(100 * left_n / len(runs)),
        "changed_page_n": changed_n,
        "changed_page_pct": round(100 * changed_n / len(runs)),
        "task_success_n": ok_n,
        "task_success_rate": round(100 * ok_n / len(runs)),
        **_latency_block(runs),
    }


def _durations(study: dict[str, Any]) -> dict[str, float]:
    starts: dict[str, float] = {}
    dones: dict[str, float] = {}
    # Per-agent clocks first. The activity log is capped and drops early rows.
    timed: dict[str, float] = {}
    for run in study.get("agent_results") or []:
        if not isinstance(run, dict):
            continue
        aid = str(run.get("agent_id") or "")
        a = run.get("page_open_at_ts") or run.get("created_at_ts")
        b = run.get("finished_at_ts")
        if aid and isinstance(a, (int, float)) and isinstance(b, (int, float)) and b >= a:
            timed[aid] = float(b) - float(a)
    for row in study.get("activity_log") or []:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("agent_id") or "")
        if not aid:
            continue
        ts = _parse_ts(row.get("at"))
        if ts is None:
            continue
        kind = row.get("kind")
        if kind == "agent_start":
            starts.setdefault(aid, ts)
        elif kind == "agent_done":
            dones[aid] = ts
    out: dict[str, float] = {}
    for aid, done in dones.items():
        start = starts.get(aid)
        if start is not None and done >= start:
            out[aid] = done - start
    out.update(timed)
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


_CAPTCHA_RE = re.compile(
    r"\bcaptcha\b|turnstile|hcaptcha|recaptcha|arkose|perimeterx|px-captcha",
    re.I,
)
_TIMEOUT_RE = re.compile(
    r"\btimed?\s*out\b|\btimeout\b|agent wall|deadline exceeded",
    re.I,
)
_SITE_CLASS = ("site-0", "site-1", "site-2", "site-3")


def _note_ok(text: str) -> bool:
    """A product claim must be specific and must not describe a UserSim failure."""
    if _is_generic(text):
        return False
    try:
        from mvp.competitor_urls import is_harness_text

        if is_harness_text(text):
            return False
    except Exception:
        pass
    if _CAPTCHA_RE.search(text) or _TIMEOUT_RE.search(text):
        return False
    return True


_SIGNUP_FAIL_RE = re.compile(
    r"(sign[ -]?up|signup|account creation|create (an )?account|verification|email|inbox|captcha)",
    re.I,
)
_FAIL_WORD_RE = re.compile(
    r"(reject|error|fail|not (be )?completed|incomplete|prevent|unable|could ?n[o']t|blocked|timed? ?out|"
    r"not received|never (arrived|came)|did ?n[o']t (arrive|receive))",
    re.I,
)


def _signup_harness_note(run: dict[str, Any], text: str) -> bool:
    """A note that only restates UserSim's own failed live sign-up is not product friction.

    The account wall itself is still reported from the trace (the path needs an
    account); what our throwaway inbox or captcha solver could not do is a run issue.
    """
    su = run.get("signup") if isinstance(run.get("signup"), dict) else None
    failed = run.get("failed_step") if isinstance(run.get("failed_step"), dict) else {}
    signup_failed = (su is not None and not su.get("ok")) or str(failed.get("reason") or "").startswith(
        "blocked at signup"
    )
    if re.search(r"\b[a-z]+_[a-z_]+\b", text):  # raw status codes like email_rejected
        return True
    return bool(signup_failed and _SIGNUP_FAIL_RE.search(text) and _FAIL_WORD_RE.search(text))


def _failure_blob(result: dict[str, Any]) -> str:
    parts = [
        str(result.get("browser_error") or ""),
        str(result.get("mode") or ""),
        " ".join(str(x) for x in (result.get("friction_points") or [])),
    ]
    for step in result.get("trace") or []:
        if isinstance(step, dict):
            parts.append(str(step.get("action") or ""))
            parts.append(str(step.get("observation") or ""))
    return " ".join(parts)


def _usersim_failure(result: dict[str, Any], start_url: str) -> dict[str, str] | None:
    """Captcha and timeout stops are UserSim failures, even on the right site.

    A run that still completed the task is kept. The captcha sentence is
    dropped later so it cannot become a product weakness.
    """
    if task_succeeded(result, start_url):
        return None
    blob = _failure_blob(result)
    target = str(result.get("site_url") or start_url or "")
    final = str(result.get("final_url") or "")
    failed0 = result.get("failed_step") if isinstance(result.get("failed_step"), dict) else {}
    walled0 = str(result.get("stop_reason") or "") == "needs_account" or str(failed0.get("phase") or "") == "needs_account"
    if _CAPTCHA_RE.search(blob) and not walled0:
        # A captcha behind an account wall is the wall's signup being blocked;
        # the wall row says "blocked at signup: captcha".
        return {
            "kind": "captcha",
            "reason": "Run stopped on a captcha. That is a UserSim limitation, not product friction.",
            "target_url": target,
            "final_url": final,
        }
    failed = result.get("failed_step") if isinstance(result.get("failed_step"), dict) else {}
    walled = str(result.get("stop_reason") or "") == "needs_account" or str(failed.get("phase") or "") == "needs_account"
    if _TIMEOUT_RE.search(blob) and not walled:
        # An account wall is a product fact even when the live signup behind
        # it ran out of time; the report shows that signup on the wall row.
        return {
            "kind": "timeout",
            "reason": "Run timed out before a product conclusion. That is infrastructure, not product friction.",
            "target_url": target,
            "final_url": final,
        }
    return None


def _issue_row(result: dict[str, Any]) -> dict[str, Any]:
    issue = dict(result.get("run_issue") or {})
    ev = _evidence(result, detail=str(issue.get("reason") or ""))
    issue["agent_id"] = str((ev or {}).get("agent_id") or result.get("agent_id") or "")
    issue["persona_name"] = str(result.get("persona_name") or "")
    issue["task_title"] = str(result.get("task_title") or "")
    issue["task_id"] = str(result.get("task_id") or "")
    issue["persona_id"] = str(result.get("persona_id") or "")
    issue["site_key"] = str(result.get("site_key") or "")
    if ev:
        issue["step"] = ev.get("step")
        issue["screenshot_url"] = ev.get("screenshot_url")
    return issue


def _split_runs(study: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop harness failures. Return included runs and run-issue rows."""
    from mvp.competitor_urls import annotate_run_issues, insight_view

    copied = [dict(r) for r in _runs(study)]
    annotate_run_issues(copied)
    issues: list[dict[str, Any]] = []
    for result in copied:
        if result.get("exclude_from_insights") and isinstance(result.get("run_issue"), dict):
            issues.append(_issue_row(result))
            continue
        start = str(result.get("site_url") or study.get("url") or "")
        extra = _usersim_failure(result, start)
        if extra:
            result["run_issue"] = extra
            result["exclude_from_insights"] = True
            issues.append(_issue_row(result))
    included = [insight_view(r) for r in copied if not r.get("exclude_from_insights")]
    return included, issues


def _pretty_host(url: str) -> str:
    host = _host(url)
    if not host:
        return "Site"
    parts = [p for p in host.split(".") if p]
    base = parts[0] if parts else host
    if base in {"app", "www", "docs", "m"} and len(parts) >= 2:
        base = parts[-2]
    if base and len(base) <= 3 and base == parts[-2] and len(parts) >= 2:
        base = f"{base}.{parts[-1]}"  # cal.com reads as "Cal.com", not "Cal"
    return base[:1].upper() + base[1:] if base else "Site"


def _site_label(run: dict[str, Any], study: dict[str, Any]) -> str:
    key = str(run.get("site_key") or "product")
    if key == "product":
        return _pretty_host(str(study.get("url") or run.get("site_url") or ""))
    label = str(run.get("site_label") or "").strip()
    if label and not label.startswith("http") and label.lower() != "product":
        return label
    return _pretty_host(str(run.get("site_url") or ""))


def _persona_key(run: dict[str, Any]) -> str:
    return str(run.get("persona_id") or run.get("persona_name") or "persona")


_VS_SUFFIX = re.compile(r"\s*\(vs\s+https?://[^)]+\)\s*$", re.I)


def _task_title(run: dict[str, Any]) -> str:
    raw = _VS_SUFFIX.sub("", str(run.get("task_title") or "")).strip()
    return " ".join(raw.split())


def _task_key(run: dict[str, Any]) -> str:
    """Group the same goal across sites. Expanded task ids are unique per site."""
    title = _task_title(run).lower()
    if title:
        return title[:120]
    raw = str(run.get("task_id") or "task")
    return raw.split("__")[0]


def _claim(text: str, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    cited = [e for e in evidence if e.get("agent_id") and e.get("screenshot_url")]
    if not text or not cited:
        return None
    return {"claim": text, "evidence": cited[:3]}


_AUTH_PATH_RE = re.compile(r"/(?:login|log-in|signin|sign-in|signup|sign-up|register|join|auth)\b", re.I)


def _short_page(url: str) -> str:
    host, path, _query = _page_key(url)
    if not host:
        return url[:80]
    return (host + ("" if path == "/" else path))[:90]


_ID_SEG_RE = re.compile(
    r"^(?:\d+|[0-9a-f]{8,}|[0-9a-f-]{20,}|(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9-]{6,})$",
    re.I,
)


def _page_shape(url: str) -> str:
    """The page with per-account path segments (workspace slugs, ids) folded to '…'.

    linear.app/riveralabse671/team/RIV/active and linear.app/riveralabs0764/team/RIV/active
    are the same page for a report; each fresh signup gets its own workspace slug.
    """
    page = _short_page(url)
    host, _, path = page.partition("/")
    if not path:
        return page
    segs = ["\u2026" if _ID_SEG_RE.match(seg) else seg for seg in path.split("/")]
    return host + "/" + "/".join(segs)


def _chain_item(action: str) -> str:
    """One readable step for a click chain, cut on a word boundary, never an email."""
    text = " ".join(str(action or "").split())
    if text.startswith("signed up as"):
        m = re.search(r" in (\d+(?:\.\d+)?)s", text)
        return f"live sign-up ({float(m.group(1)):.0f}s)" if m else "live sign-up"
    text = text.removeprefix("click ")
    text = re.sub(r"^(type '[^']*') into .*$", r"\1", text)
    if len(text) > 32:
        text = text[:32].rsplit(" ", 1)[0] + "\u2026"
    return text


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:\u2014-") + "\u2026"


def _step_ax(step: dict[str, Any]) -> str:
    for key in ("accessibility_tree", "ax_tree"):
        text = str(step.get(key) or "").strip()
        if text:
            return text[:1500]
    return ""


def _trace_evidence(run: dict[str, Any], step: dict[str, Any], detail: str) -> dict[str, Any] | None:
    """Cite one real trace step plus this run's uploaded final screenshot."""
    shot = str(run.get("final_screenshot_url") or run.get("final_screenshot") or "").strip()
    if not shot or not isinstance(step.get("step"), int):
        return None
    step_url = str(step.get("url") or "").strip()
    ax = _step_ax(step)
    if not step_url and not ax:
        return None
    return {
        "agent_id": str(run.get("agent_id") or ""),
        "persona_name": str(run.get("persona_name") or "Simulated user"),
        "task_title": _task_title(run),
        "step": int(step["step"]),
        "step_url": step_url,
        "url": step_url,
        "accessibility_tree": ax,
        "screenshot_url": shot,
        "final_screenshot": shot,
        "final_screenshot_url": shot,
        "final_url": str(run.get("final_url") or step_url),
        "action": str(step.get("action") or "")[:180],
        "detail": detail[:220],
    }


_DISMISS_RE = re.compile(r"^press\s+(?:escape|esc|tab)\b", re.I)


def _key_step(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The step that did the work: the last one that is not a dismissal key press."""
    for step in reversed(steps):
        if not _DISMISS_RE.search(" ".join(str(step.get("action") or "").split())):
            return step
    return steps[-1]


def run_steps(run: dict[str, Any]) -> int:
    """Actions a run took. The one step count every chart and claim uses.

    Trace step 0 is the page opening, not an action; num_steps counts it.
    """
    trace = [s for s in (run.get("trace") or []) if isinstance(s, dict)]
    if trace:
        return len(_acted_steps(run))
    return max(0, int(run.get("num_steps") or 0) - 1)


def _acted_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for s in (run.get("trace") or [])
        if isinstance(s, dict) and isinstance(s.get("step"), int) and int(s["step"]) >= 1
    ]


def _run_done(run: dict[str, Any]) -> bool:
    failed = run.get("failed_step") if isinstance(run.get("failed_step"), dict) else {}
    return str(failed.get("phase") or "") == "done" or str(run.get("stop_reason") or "") == "done"


def trace_claims(
    product: list[dict[str, Any]],
    product_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strengths and weaknesses read straight from product traces.

    Only runs that left the page they opened on are cited. Each claim names
    the task, the action and the page it produced, and cites the step plus
    the run's final screenshot. Nothing is written that a step does not show.
    """
    strong: dict[str, list[dict[str, Any]]] = {}
    strong_label: dict[str, str] = {}
    weak: dict[str, list[dict[str, Any]]] = {}
    weak_label: dict[str, str] = {}
    long_paths: dict[str, list[dict[str, Any]]] = {}
    long_label: dict[str, str] = {}
    long_runs: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]], str]]] = {}
    totals: dict[str, int] = {}
    for run in product:
        totals[_task_title(run).lower()] = totals.get(_task_title(run).lower(), 0) + 1
    for run in product:
        start = str(run.get("site_url") or product_url or "")
        steps = _acted_steps(run)
        if not steps or not changed_page_state(run, start):
            continue
        title = _task_title(run) or "Task"
        final_url = str(run.get("final_url") or steps[-1].get("url") or "")
        final_page = _page_shape(final_url)
        moved = [s for s in steps if s.get("changed") is True]
        if _run_done(run) and not _AUTH_PATH_RE.search(final_url):
            key_step = _key_step(moved or steps)
            action = " ".join(str(key_step.get("action") or "").split())[:80]
            count = run_steps(run)
            # A same-page app (a canvas editor) is never "reached" by its last
            # key press: say it was finished there, with the step that did it.
            verb = "reached" if left_start(run, start) else "finished the task on"
            text = f"{title}: \u201c{action}\u201d {verb} {final_page} in {count} step{'s' if count != 1 else ''}"
            key = f"{title.lower()}|{final_page}"
            ev = _trace_evidence(run, key_step, text)
            if ev:
                strong.setdefault(key, []).append(ev)
                strong_label.setdefault(
                    key,
                    f"{title}: agents reached {final_page} by \u201c{action}\u201d"
                    if left_start(run, start)
                    else f"{title}: agents finished it on {final_page} with \u201c{action}\u201d",
                )
            if len(steps) >= 3:
                # A finished path that still took several clicks is friction the
                # trace shows directly: list the clicks, cite the first one.
                key3 = f"{title.lower()}|long|{final_page}"
                long_runs.setdefault(key3, []).append((run, steps, final_page))
            continue
        # Not done. Say where the path ended and why, from the trace itself.
        stop = str(run.get("stop_reason") or "")
        failed = run.get("failed_step") if isinstance(run.get("failed_step"), dict) else {}
        reason = str(failed.get("reason") or stop or "goal not shown")
        if stop == "needs_account" or _AUTH_PATH_RE.search(final_url):
            key = f"{title.lower()}|account"
            label = (
                f"{title}: the path needs an account \u2014 agents hit a sign-up or sign-in wall "
                f"at {final_page} before they could finish"
            )
            if reason.startswith("blocked at signup"):
                why = reason.removeprefix("blocked at signup").lstrip(": ").strip() or "it did not finish"
                key = f"{title.lower()}|account|{reason}"
                label = (
                    f"{title}: the path needs an account (wall at {final_page}); UserSim's live sign-up "
                    f"could not get past it ({why})"
                )
        else:
            key = f"{title.lower()}|{final_page}"
            label = (
                f"{title}: after {len(steps)} steps agents ended on {final_page} "
                f"without reaching the goal ({reason})"
            )
        ev = _trace_evidence(run, steps[-1], label)
        if ev:
            weak.setdefault(key, []).append(ev)
            weak_label.setdefault(key, label)
        for step in steps:
            if step.get("changed") is False:
                action = " ".join(str(step.get("action") or "").split())[:80]
                page = _page_shape(str(step.get("url") or final_url))
                k2 = f"nochange|{action.lower()}|{page}"
                lab = f"\u201c{action}\u201d changed nothing on {page}"
                ev2 = _trace_evidence(run, step, lab)
                if ev2:
                    weak.setdefault(k2, []).append(ev2)
                    weak_label.setdefault(k2, lab)
                break

    for key3, group in long_runs.items():
        # Same counter and rounding as the median-steps chart (run_steps,
        # toFixed(0)); the chain shown is the run closest to that median.
        med = _median([float(run_steps(r)) for r, _, _ in group]) or 0.0
        n_steps = int(med + 0.5)
        rep, rep_steps, page3 = min(group, key=lambda g: abs(run_steps(g[0]) - med))
        items = [_chain_item(s.get("action")) for s in rep_steps]
        chain = " \u2192 ".join(items[:6]) + (" \u2192 \u2026" if len(items) > 6 else "")
        signed = any(str(s.get("decision_source") or "") == "signup" for s in rep_steps)
        median_word = "a median of " if len(group) > 1 and any(run_steps(r) != n_steps for r, _, _ in group) else ""
        lab3 = (
            f"{_task_title(rep) or "Task"}: it took {median_word}{n_steps} steps"
            f"{' including a live sign-up' if signed else ''} ({chain}) "
            f"{'to reach' if left_start(rep, str(rep.get('site_url') or product_url or '')) else 'to finish on'} {page3}"
        )
        long_label[key3] = lab3
        for r, st, _ in [(rep, rep_steps, page3)] + [g for g in group if g[0] is not rep]:
            ev3 = _trace_evidence(r, st[0], lab3)
            if ev3:
                long_paths.setdefault(key3, []).append(ev3)

    def _rank(groups: dict[str, list[dict[str, Any]]], labels: dict[str, str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key, evs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            title = key.split("|", 1)[0]
            n = totals.get(title) or len(evs)
            text = labels[key]
            if not key.startswith("nochange|"):
                text = f"{text} ({len(evs)} of {n} runs)"
            else:
                text = f"{text} ({len(evs)} run{'s' if len(evs) != 1 else ''})"
            claim = _claim(text, evs)
            if claim:
                claim["source"] = "trace"
                out.append(claim)
        return out

    return _rank(strong, strong_label), _rank(weak, weak_label) + _rank(long_paths, long_label)


def build_report_insights(study: dict[str, Any]) -> dict[str, Any]:
    runs, run_issues = _split_runs(study)
    product_url = str(study.get("url") or "")
    host = _host(product_url) or "this product"
    product_name = _pretty_host(product_url)
    product = [r for r in runs if str(r.get("site_key") or "product") == "product"]
    if not product and not run_issues:
        product = [r for r in runs if _host(str(r.get("site_url") or "")) == host]
    start_host = _host(product_url)

    strengths: list[dict[str, Any]] = []
    weaknesses: list[dict[str, Any]] = []

    # Concrete likes. Complaints are weaknesses even when they were stored as a quote.
    look_words = ("clean", "modern", "professional")
    look_evs: list[dict[str, Any]] = []
    like_groups: dict[str, list[dict[str, Any]]] = {}
    like_label: dict[str, str] = {}
    friction_groups: dict[str, list[dict[str, Any]]] = {}
    friction_label: dict[str, str] = {}
    for run in product:
        notes = list(run.get("what_was_easy") or [])
        quote = str(run.get("quote") or "").strip()
        if quote:
            notes.append(quote)
        for note in notes:
            text = str(note).strip()
            if not _note_ok(text):
                continue
            if _sentiment(text) == "neg":
                if _signup_harness_note(run, text):
                    continue
                key = " ".join(text.lower().replace("_", " ").split())[:80]
                ev = _evidence(run, detail=text, prefer_friction=True)
                if not ev:
                    continue
                friction_groups.setdefault(key, []).append(ev)
                friction_label.setdefault(key, text)
                continue
            if _sentiment(text) != "pos":
                continue
            ev = _evidence(run, detail=text)
            if not ev:
                continue
            low = text.lower()
            themes = [bit for bit in _CONCRETE if _mentions(low, bit)]
            if themes and all(bit in look_words for bit in themes):
                if not any(e["agent_id"] == ev["agent_id"] for e in look_evs):
                    look_evs.append(ev)
                continue
            key = " ".join(text.lower().split())[:80]
            like_groups.setdefault(key, []).append(ev)
            like_label.setdefault(key, text)
    if look_evs:
        claim = _claim(
            "Agents called the first screen clean and modern.",
            look_evs,
        )
        if claim:
            strengths.append(claim)
    for key, evs in sorted(like_groups.items(), key=lambda kv: -len(kv[1])):
        claim = _claim(like_label[key], evs)
        if claim:
            strengths.append(claim)
        if len(strengths) >= 3:
            break

    for run in product:
        for note in run.get("friction_points") or []:
            text = str(note).strip()
            if not _note_ok(text) or _signup_harness_note(run, text):
                continue
            key = " ".join(text.lower().replace("_", " ").split())[:80]
            ev = _evidence(run, detail=text, prefer_friction=True)
            if not ev:
                continue
            friction_groups.setdefault(key, []).append(ev)
            friction_label.setdefault(key, text)
    for key, evs in sorted(friction_groups.items(), key=lambda kv: -len(kv[1])):
        claim = _claim(friction_label[key], evs)
        if claim:
            weaknesses.append(claim)
        if len(weaknesses) >= 3:
            break

    # Trace-backed claims first: they cite a step past the opening page.
    t_strengths, t_weaknesses = trace_claims(product, product_url)
    have = {c["claim"] for c in strengths}
    def _norm(text: str) -> str:
        text = re.sub(r"https?://(www\.)?", "", str(text or "").lower())
        text = re.sub(r"\(\d+ (of \d+ )?runs?\)", "", text)
        return re.sub(r"[^a-z0-9]+", "", text)

    def _novel(c: dict[str, Any], base: list[dict[str, Any]]) -> bool:
        n = _norm(c["claim"])
        return bool(n) and not any(n in _norm(t["claim"]) or _norm(t["claim"]) in n for t in base)

    strengths = (t_strengths + [c for c in strengths if _novel(c, t_strengths)])[:3]
    weaknesses = (t_weaknesses + [c for c in weaknesses if _novel(c, t_weaknesses)])[:3]
    del have

    # Stuck means the run never left the page it opened on. A pricing page
    # reached in one click is not stuck, even on the same host.
    stuck = [
        r for r in product
        if not changed_page_state(r, str(r.get("site_url") or product_url or ""))
        and _stuck_on_open(r, start_host)
    ]
    stuck_ratio = (len(stuck) / len(product)) if product else 0.0
    if product and stuck_ratio >= 0.75:
        evs = []
        for run in stuck:
            ev = _evidence(run, detail=f"Ended on {run.get('final_url') or 'the opening URL'} after {run_steps(run)} step{'s' if run_steps(run) != 1 else ''}.")
            if ev:
                evs.append(ev)
        if len(stuck) == len(product):
            stuck_text = (
                f"No product run got past the first screen ({len(stuck)} of {len(product)} "
                "stopped on the homepage), so feature-level weaknesses are not in these traces."
            )
        else:
            stuck_text = (
                f"{len(stuck)} of {len(product)} product runs stopped on the first screen, "
                "so feature-level weaknesses are thin in these traces."
            )
        claim = _claim(stuck_text, evs)
        if claim and not any("first screen" in w["claim"] for w in weaknesses):
            weaknesses.insert(0, claim)
            weaknesses = weaknesses[:3]

    thin = (not strengths and not any("friction" in w["claim"].lower() for w in weaknesses)) or stuck_ratio >= 0.75
    if not product and run_issues:
        headline = (
            f"No usable product runs for {product_name}. "
            f"{len(run_issues)} run(s) failed inside UserSim and are listed as run issues, not product friction."
        )
        thin = True
    elif not product:
        headline = f"No product-site runs for {host}, so there is nothing to claim."
        thin = True
    elif stuck_ratio >= 0.75 and not strengths:
        headline = (
            f"Evidence is thin for {host}: {len(stuck)} of {len(product)} product runs "
            "stopped on the first screen."
        )
    elif stuck_ratio >= 0.75 and strengths:
        headline = (
            f"{host} only shows a first-screen impression. "
            f"{len(stuck)} of {len(product)} product runs never left the homepage."
        )
    elif strengths and weaknesses:
        headline = f"{host}: {_clip(strengths[0]['claim'], 150)}"
    elif strengths:
        headline = f"{host}: {_clip(strengths[0]['claim'], 150)}"
    elif weaknesses:
        headline = f"{host}: {_clip(weaknesses[0]['claim'], 150)}"
    else:
        headline = f"Evidence is thin for {host}: the traces do not support a specific strength or weakness."
        thin = True

    evidence_note = None
    if thin:
        evidence_note = (
            "Evidence is thin. Claims below are only what a trace step actually shows. "
            "Nothing else is filled in."
        )
    if run_issues:
        extra = (
            f"{len(run_issues)} run(s) failed inside UserSim "
            "(wrong site, captcha, timeout, or infrastructure) and are not product friction."
        )
        evidence_note = f"{evidence_note} {extra}".strip() if evidence_note else extra

    comparisons, tie_note = _comparisons(study, runs)
    product_metrics = work_metrics(product, product_url)
    layout = _layout(study, runs, comparisons, product_name, thin, run_issues)
    out = {
        "headline": headline[:240],
        "evidence_thin": bool(thin),
        "evidence_note": evidence_note,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "comparisons": comparisons,
        "tie_note": tie_note,
        "work_metrics": product_metrics,
        "run_issues": run_issues,
        "product_name": product_name,
        **layout,
    }
    out["verdict"] = verdict(out, study)
    out["signups"] = signup_summary(runs, study)
    # A task where a competitor did better is a product weakness. Cite the
    # product runs of that task so the claim points at real steps.
    if len(out["weaknesses"]) < 3:
        have_titles = {c["claim"].split(":", 1)[0].strip().lower() for c in out["weaknesses"]}
        for line in out["verdict"].get("trails") or []:
            title = line.split(":", 1)[0].strip()
            if title.lower() in have_titles:
                continue
            evs = []
            for run in product:
                if (_task_title(run) or "").strip().lower() != title.lower():
                    continue
                steps = _acted_steps(run)
                if not steps:
                    continue
                ev = _trace_evidence(run, steps[-1], line)
                if ev:
                    evs.append(ev)
            claim = _claim(line, evs)
            if claim:
                claim["source"] = "comparison"
                out["weaknesses"].append(claim)
            if len(out["weaknesses"]) >= 3:
                break
    stored = (study.get("summary") or {}) if isinstance(study.get("summary"), dict) else {}
    if stored.get("verdict_summary"):
        out["verdict"]["summary"] = drop_harness_sentences(str(stored["verdict_summary"]))
    return out


def _layout(
    study: dict[str, Any],
    runs: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    product_name: str,
    thin: bool,
    run_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Numbers the Bland-style report draws. Every figure comes from included runs."""
    durations = _durations(study)
    ordered = sorted(
        comparisons,
        key=lambda row: (0 if row.get("site_key") == "product" else 1, str(row.get("site_key"))),
    )
    labels = {str(row.get("site_key")): str(row.get("site_label")) for row in ordered}
    by_site: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_site.setdefault(str(run.get("site_key") or "product"), []).append(run)

    sites: list[dict[str, Any]] = []
    for i, row in enumerate(ordered):
        key = str(row.get("site_key"))
        group = by_site.get(key) or []
        success_steps: list[float] = []
        for run in group:
            start = str(run.get("site_url") or study.get("url") or "")
            if task_succeeded(run, start):
                success_steps.append(float(run_steps(run)))
        sites.append(
            {
                "site_key": key,
                "site_label": labels.get(key) or key,
                "css": _SITE_CLASS[i % len(_SITE_CLASS)],
                "n": row.get("n") or 0,
                "ok": row.get("ok") or 0,
                "success_pct": int(round(float(row.get("success_rate") or 0) * 100)),
                "median_steps": row.get("median_steps"),
                "median_success_steps": _median(success_steps),
                "median_time_s": row.get("median_time_s"),
            }
        )

    task_slots: dict[str, dict[str, Any]] = {}
    persona_slots: dict[str, dict[str, Any]] = {}
    for run in runs:
        sk = str(run.get("site_key") or "product")
        tk = _task_key(run)
        pk = _persona_key(run)
        start = str(run.get("site_url") or study.get("url") or "")
        ok = task_succeeded(run, start)
        steps = float(run_steps(run))
        task = task_slots.setdefault(
            tk,
            {
                "task_id": tk,
                "title": _task_title(run) or tk,
                "prompt": str(run.get("task_prompt") or ""),
                "sites": {},
            },
        )
        cell = task["sites"].setdefault(
            sk, {"n": 0, "ok": 0, "steps": [], "all_steps": [], "times": []}
        )
        cell["n"] += 1
        cell["all_steps"].append(steps)
        elapsed = durations.get(str(run.get("agent_id") or ""))
        if elapsed is not None:
            cell["times"].append(elapsed)
        if ok:
            cell["ok"] += 1
            cell["steps"].append(steps)
        persona = persona_slots.setdefault(
            pk,
            {
                "persona_id": pk,
                "persona_name": str(run.get("persona_name") or pk),
                "bio": str(run.get("persona_bio") or ""),
                "goals": {},
            },
        )
        goal = persona["goals"].setdefault(
            tk,
            {
                "task_id": tk,
                "title": _task_title(run) or tk,
                "prompt": str(run.get("task_prompt") or ""),
                "success": {},
                "steps": {},
            },
        )
        goal["success"][sk] = bool(goal["success"].get(sk)) or ok
        if ok:
            goal["steps"].setdefault(sk, []).append(steps)

    by_task = []
    for task in task_slots.values():
        sites_out = {}
        for sk, cell in task["sites"].items():
            all_steps = cell.get("all_steps") or []
            times = cell.get("times") or []
            time_med = _median(times)
            sites_out[sk] = {
                "n": cell["n"],
                "ok": cell["ok"],
                "median_steps": _median(cell["steps"]) if cell["steps"] else None,
                "median_all_steps": _median(all_steps) if all_steps else None,
                "median_time_s": round(time_med, 1) if time_med is not None else None,
            }
        by_task.append(
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "prompt": task["prompt"],
                "sites": sites_out,
            }
        )

    completed_goals = {site["site_key"]: 0 for site in sites}
    by_persona = []
    for persona in persona_slots.values():
        goals = []
        for goal in persona["goals"].values():
            succeeded = [sk for sk, ok in goal["success"].items() if ok]
            if len(succeeded) == 1:
                pick = succeeded[0]
                reason = f"Only {labels.get(pick, pick)} completed this task."
            elif len(succeeded) > 1:
                pick = None
                bits = []
                for sk in succeeded:
                    med = _median(goal["steps"].get(sk) or [])
                    bit = labels.get(sk, sk)
                    if med is not None:
                        bit += f" ({med:.0f} steps)"
                    bits.append(bit)
                reason = "Completed on " + ", ".join(bits) + ". No single pick."
            else:
                pick = None
                reason = "No included run completed this task."
            for sk in succeeded:
                completed_goals[sk] = completed_goals.get(sk, 0) + 1
            goals.append(
                {
                    "task_id": goal["task_id"],
                    "title": goal["title"],
                    "prompt": goal["prompt"],
                    "success": goal["success"],
                    "pick": pick,
                    "pick_reason": reason,
                }
            )
        wins = {}
        for site in sites:
            wins[site["site_key"]] = sum(1 for g in goals if g["success"].get(site["site_key"]))
        top = None
        if wins:
            best = max(wins.values())
            leaders = [sk for sk, n in wins.items() if n == best and n > 0]
            if len(leaders) == 1:
                top = leaders[0]
        by_persona.append(
            {
                "persona_id": persona["persona_id"],
                "persona_name": persona["persona_name"],
                "bio": persona["bio"],
                "goals": goals,
                "completed": wins,
                "top_site": top,
            }
        )

    for site in sites:
        site["goals_completed"] = completed_goals.get(site["site_key"], 0)

    n_personas = len(by_persona)
    n_tasks = len(by_task)
    n_goals = sum(len(p["goals"]) for p in by_persona)
    names = ", ".join(site["site_label"] for site in sites) or product_name
    metric = (
        "Task success means the page itself showed the finished goal (a docs or help page "
        "about the task does not count, and a sign-up wall is a miss). Steps and time come from the traces. "
        "A site is a pick on a goal only when it is the only one that completed that goal."
    )
    if run_issues:
        metric += (
            f" {len(run_issues)} run(s) failed inside UserSim and are excluded from these rates."
        )
    if thin:
        metric += " Evidence is thin, so only screenshot-backed claims are shown."
    return {
        "sites": sites,
        "by_task": by_task,
        "by_persona": by_persona,
        "n_runs": len(runs),
        "n_goals": n_goals,
        "n_personas": n_personas,
        "n_tasks": n_tasks,
        "n_sites": len(sites),
        "metric_note": metric,
        "lede": f"Task success and step traces across {names} — then drill into the screenshots.",
    }


def _comparisons(
    study: dict[str, Any], runs: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    durations = _durations(study)
    by_site: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        key = str(run.get("site_key") or "product")
        by_site.setdefault(key, []).append(run)
    rows = []
    for key, group in by_site.items():
        site_start = str(group[0].get("site_url") or study.get("url") or "")
        ok = sum(1 for r in group if task_succeeded(r, site_start))
        left_n = sum(1 for r in group if left_start(r, site_start))
        changed_n = sum(1 for r in group if changed_page_state(r, site_start))
        steps = [float(run_steps(r)) for r in group]
        latency = _latency_block(group)
        times = [durations[str(r.get("agent_id"))] for r in group if str(r.get("agent_id")) in durations]
        friction = sum(len(r.get("friction_points") or []) for r in group)
        label = _site_label(group[0], study)
        rows.append(
            {
                "site_key": key,
                "site_label": label,
                "n": len(group),
                "ok": ok,
                "success_rate": round(ok / len(group), 3) if group else 0,
                "left_start_pct": round(100 * left_n / len(group)) if group else 0,
                "changed_page_pct": round(100 * changed_n / len(group)) if group else 0,
                "step_latency_p50": latency["step_latency_p50"],
                "step_latency_p95": latency["step_latency_p95"],
                "model": latency["model"],
                "model_provider": latency["model_provider"],
                "median_steps": _median(steps),
                "median_time_s": round(_median(times), 1) if _median(times) is not None else None,
                "friction_n": friction,
            }
        )
    rows.sort(key=lambda r: (-r["success_rate"], r["median_steps"] or 0, r["median_time_s"] or 1e9, r["friction_n"]))

    # Exact success-rate ties among sites that actually ran.
    ranked = [r for r in rows if r["n"] >= 2]
    tie_note = None
    if len(ranked) >= 2:
        top = ranked[0]["success_rate"]
        tied = [r for r in ranked if r["success_rate"] == top]
        if len(tied) >= 2:
            ordered = sorted(
                tied,
                key=lambda r: (r["median_steps"] or 0, r["median_time_s"] if r["median_time_s"] is not None else 1e9, r["friction_n"]),
            )
            names = ", ".join(
                f"{r['site_label']} ({r['median_steps']:.0f} steps"
                + (f", {r['median_time_s']:.0f}s" if r["median_time_s"] is not None else "")
                + f", {r['friction_n']} friction)"
                for r in ordered
            )
            pct = int(round(top * 100))
            tie_note = (
                f"Task success ties at {pct}%. Ordered by fewer steps, then less time, then less friction: {names}."
            )
    return rows, tie_note


def apply_insights(study: Any) -> dict[str, Any]:
    """Write insights onto a StudyState summary. Returns the insights dict."""
    payload = {
        "url": getattr(study, "url", None),
        "agent_results": getattr(study, "agent_results", None) or [],
        "activity_log": getattr(study, "activity_log", None) or [],
        "summary": getattr(study, "summary", None) or {},
        "segment": getattr(study, "segment", None) or getattr(study, "target_segment", None) or "",
    }
    insights = build_report_insights(payload)
    summary = dict(getattr(study, "summary", None) or {})
    summary["insights"] = insights
    if insights.get("headline"):
        summary["headline"] = insights["headline"]
    study.summary = summary
    return insights


def _fmt_rate(ok: int, n: int) -> str:
    return f"{ok}/{n}"


def verdict(insights: dict[str, Any], study: dict[str, Any]) -> dict[str, Any]:
    """What the product is good for and where it trails, from per-task numbers.

    Each line compares the product with the competitors on one task: finished
    runs first, then median steps, then median time. Account walls are named.
    """
    sites = insights.get("sites") or []
    labels = {str(s.get("site_key")): str(s.get("site_label")) for s in sites}
    product_label = labels.get("product") or _pretty_host(str(study.get("url") or ""))
    good: list[str] = []
    trails: list[str] = []
    walls: dict[str, set[str]] = {}
    for run in _runs(study):
        stop = str(run.get("stop_reason") or "")
        failed = run.get("failed_step") if isinstance(run.get("failed_step"), dict) else {}
        if stop == "needs_account" or str(failed.get("phase") or "") == "needs_account":
            walls.setdefault(_task_title(run) or "task", set()).add(str(run.get("site_key") or "product"))
    for task in insights.get("by_task") or []:
        title = str(task.get("title") or "task")
        cells = task.get("sites") or {}
        mine = cells.get("product") or {}
        if not mine.get("n"):
            continue
        rate = (mine.get("ok") or 0) / max(1, mine.get("n") or 1)
        others = {k: v for k, v in cells.items() if k != "product" and v.get("n")}
        better = []
        worse = []
        for key, cell in others.items():
            orate = (cell.get("ok") or 0) / max(1, cell.get("n") or 1)
            name = labels.get(key) or key
            if orate > rate:
                better.append(f"{name} ({_fmt_rate(cell.get('ok') or 0, cell.get('n') or 0)} finished)")
            elif orate < rate:
                worse.append(f"{name} ({_fmt_rate(cell.get('ok') or 0, cell.get('n') or 0)} finished)")
            elif rate > 0:
                ms, os_ = mine.get("median_steps"), cell.get("median_steps")
                mt, ot = mine.get("median_time_s"), cell.get("median_time_s")
                def _st(v: float) -> str:
                    return f"{v:.0f} step{'s' if round(v) != 1 else ''}"

                if ms is not None and os_ is not None and os_ + 1 <= ms:
                    better.append(f"{name} ({_st(os_)} vs {product_label}'s {ms:.0f})")
                elif ms is not None and os_ is not None and ms + 1 <= os_:
                    worse.append(f"{name} ({_st(os_)} vs {product_label}'s {ms:.0f})")
                elif mt is not None and ot is not None and ot * 1.5 < mt:
                    better.append(f"{name} ({ot:.0f}s vs {product_label}'s {mt:.0f}s)")
                elif mt is not None and ot is not None and mt * 1.5 < ot:
                    worse.append(f"{name} ({ot:.0f}s vs {product_label}'s {mt:.0f}s)")
        mine_txt = _fmt_rate(mine.get("ok") or 0, mine.get("n") or 0)
        steps = mine.get("median_steps")
        how = f" in a median {steps:.0f} step{'s' if steps != 1 else ''}" if steps else ""
        if rate > 0 and not better:
            tail = f", ahead of {', '.join(worse)}" if worse else ", level with the competitors"
            good.append(f"{title}: {mine_txt} runs finished on {product_label}{how}{tail}.")
        elif better:
            wall = " Agents hit a sign-up wall first." if "product" in walls.get(title, set()) else ""
            trails.append(
                f"{title}: {product_label} finished {mine_txt} runs; {', '.join(better)} did better.{wall}"
            )
        elif rate == 0:
            wall = " because it needs an account" if "product" in walls.get(title, set()) else ""
            trails.append(f"{title}: no {product_label} run finished{wall} (no competitor finished it either)."
                          if not others or all(not (c.get("ok")) for c in others.values())
                          else f"{title}: no {product_label} run finished{wall}.")
    return {"good_for": good[:4], "trails": trails[:4], "summary": None}


async def write_verdict_summary(study: dict[str, Any], insights: dict[str, Any]) -> str:
    """Three to five plain sentences from the report's own numbers and claims.

    The model only rewrites facts given to it; it is told not to add any.
    """
    from capability.gemini_config import gemini_chat

    facts = {
        "product": insights.get("product_name"),
        "segment": study.get("segment") or study.get("target_segment") or "",
        "good_for": (insights.get("verdict") or {}).get("good_for") or [],
        "trails": (insights.get("verdict") or {}).get("trails") or [],
        "strengths": [c.get("claim") for c in insights.get("strengths") or []][:3],
        "weaknesses": [c.get("claim") for c in insights.get("weaknesses") or []][:3],
        "live_signups": (insights.get("signups") or {}).get("sites") or [],
        "sites": [
            {k: s.get(k) for k in ("site_label", "ok", "n", "median_steps", "median_time_s")}
            for s in insights.get("sites") or []
        ],
    }
    prompt = (
        "Write a short verdict for a product team from a simulated user study. "
        "Use only these facts; do not invent features, numbers, or sites. "
        "3 to 5 plain sentences: what the product is good for, where it trails its competitors, "
        "and the single most useful fix. No markdown, no bullet points. "
        "live_signups are UserSim's own test accounts: a captcha, a rejected throwaway email, a "
        "verification email that never arrived, or a signup error there is a limit of the test "
        "harness, not a product problem, so never describe it as a product flaw or recommend fixing "
        "it. That a task needs an account at all is a product fact and may be mentioned. "
        "Name the specific competitor for every comparison. No opinions, industry norms, or "
        "claims about typical users that are not in the facts.\n"
        f"Facts: {json.dumps(facts, ensure_ascii=False)[:5000]}"
    )
    raw = await gemini_chat(
        [{"role": "user", "content": prompt}],
        model=os.environ.get("MVP_VERDICT_MODEL") or "gemini-2.5-flash",
        temperature=0.2,
        json_mode=False,
        max_retries=2,
    )
    return drop_harness_sentences(" ".join(str(raw or "").split())[:1200])


_HARNESS_RE = re.compile(
    r"throwaway|disposable|temporary e-?mail|captcha|verification (e-?mail|code)|test account|usersim",
    re.I,
)


def drop_harness_sentences(text: str) -> str:
    """Remove sentences about UserSim's own signup limits; they are not product findings."""
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    kept = [p for p in parts if p and not _HARNESS_RE.search(p)]
    return " ".join(kept)


def _signup_cause(label: str) -> str:
    """'blocked at signup: captcha' -> 'captcha'; 'signup did not finish (site_error)' -> 'site error'."""
    text = re.sub(r"^blocked at sign-?up:?\s*", "", str(label or "").strip(), flags=re.I)
    m = re.match(r"^sign-?up did not finish \((.+)\)$", text, flags=re.I)
    if m:
        text = m.group(1)
    if re.match(r"^\w*Timeout\w*\(.*\)$|^timed? ?out$", text, flags=re.I):
        return "timeout"
    if re.match(r"^\w+(Error|Exception)\(.*\)$", text):
        return "browser error"
    if text.lower() == "error":
        return "signup error"
    return text.replace("_", " ").strip() or "unknown"


def signup_summary(runs: list[dict[str, Any]], study: dict[str, Any]) -> dict[str, Any]:
    """Live account creation during the study, per site: tried, finished, median seconds."""
    rows: dict[str, dict[str, Any]] = {}
    for run in runs:
        info = run.get("signup") if isinstance(run.get("signup"), dict) else None
        if not info:
            continue
        label = _site_label(run, study)
        row = rows.setdefault(label, {"site": label, "tried": 0, "ok": 0, "seconds": [], "reasons": {}})
        row["tried"] += 1
        if info.get("ok"):
            row["ok"] += 1
            if isinstance(info.get("seconds"), (int, float)):
                row["seconds"].append(float(info["seconds"]))
        else:
            from mvp.a11y_agent import signup_block_label

            reason = _signup_cause(signup_block_label(str(info.get("reason") or "unknown")))
            row["reasons"][reason] = row["reasons"].get(reason, 0) + 1
    out = []
    for row in rows.values():
        med = _median(row.pop("seconds"))
        row["median_s"] = round(med, 1) if med is not None else None
        out.append(row)
    return {"sites": out, "tried": sum(r["tried"] for r in out), "ok": sum(r["ok"] for r in out)}
