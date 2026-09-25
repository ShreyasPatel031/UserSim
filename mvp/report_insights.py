"""Evidence-backed report claims.

A strength or weakness is included only when it cites a real agent step that
has a screenshot. Generic "the page loaded" notes are not claims. When two
sites succeed at the same rate, they are ordered by steps, then time, then
friction.
"""

from __future__ import annotations

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


def _is_generic(text: str) -> bool:
    """True when the note does not name a specific product observation."""
    low = text.lower().strip()
    if not low:
        return True
    return not any(_mentions(low, bit) for bit in _CONCRETE)


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


def task_succeeded(run: dict[str, Any], start_url: str) -> bool:
    """Final-state success: the run interacted and landed off the start page, or typed.

    Describing the homepage, waiting, or writing a note is not success.
    """
    names = [_action_name(step) for step in (run.get("trace") or []) if isinstance(step, dict)]
    interacted = any(name.startswith(_INTERACT) or name in _INTERACT for name in names)
    typed = any(name in {"input", "input_text", "type", "send_keys"} for name in names)
    if typed:
        return True
    return interacted and left_start(run, start_url)


def work_metrics(runs: list[dict[str, Any]], start_url: str) -> dict[str, Any]:
    if not runs:
        return {
            "n": 0,
            "median_steps": None,
            "left_start_pct": 0,
            "task_success_rate": 0,
            "task_success_n": 0,
            "left_start_n": 0,
        }
    steps = [float(r.get("num_steps") or len(r.get("trace") or []) or 0) for r in runs]
    left_n = sum(1 for r in runs if left_start(r, start_url))
    ok_n = sum(1 for r in runs if task_succeeded(r, start_url))
    return {
        "n": len(runs),
        "median_steps": _median(steps),
        "left_start_n": left_n,
        "left_start_pct": round(100 * left_n / len(runs)),
        "task_success_n": ok_n,
        "task_success_rate": round(100 * ok_n / len(runs)),
    }


def _durations(study: dict[str, Any]) -> dict[str, float]:
    starts: dict[str, float] = {}
    dones: dict[str, float] = {}
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
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _claim(text: str, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    cited = [e for e in evidence if e.get("agent_id") and e.get("screenshot_url")]
    if not text or not cited:
        return None
    return {"claim": text, "evidence": cited[:3]}


def build_report_insights(study: dict[str, Any]) -> dict[str, Any]:
    runs = _runs(study)
    product_url = str(study.get("url") or "")
    host = _host(product_url) or "this product"
    product = [r for r in runs if str(r.get("site_key") or "product") == "product"]
    if not product:
        product = [r for r in runs if _host(str(r.get("site_url") or "")) == host]
    start_host = _host(product_url)

    strengths: list[dict[str, Any]] = []
    weaknesses: list[dict[str, Any]] = []

    # Concrete likes. First-screen look comments collapse into one cited claim.
    look_words = ("clean", "modern", "professional")
    look_evs: list[dict[str, Any]] = []
    like_groups: dict[str, list[dict[str, Any]]] = {}
    like_label: dict[str, str] = {}
    for run in product:
        notes = list(run.get("what_was_easy") or [])
        quote = str(run.get("quote") or "").strip()
        if quote:
            notes.append(quote)
        for note in notes:
            text = str(note).strip()
            if _is_generic(text):
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

    friction_groups: dict[str, list[dict[str, Any]]] = {}
    friction_label: dict[str, str] = {}
    for run in product:
        for note in run.get("friction_points") or []:
            text = str(note).strip()
            if _is_generic(text):
                continue
            key = " ".join(text.lower().split())[:80]
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

    stuck = [r for r in product if _stuck_on_open(r, start_host)]
    stuck_ratio = (len(stuck) / len(product)) if product else 0.0
    if product and stuck_ratio >= 0.75:
        evs = []
        for run in stuck:
            ev = _evidence(run, detail=f"Ended on {run.get('final_url') or 'the opening URL'} after {run.get('num_steps') or 1} step(s).")
            if ev:
                evs.append(ev)
        claim = _claim(
            f"No product run got past the first screen ({len(stuck)} of {len(product)} stopped on the homepage), so feature-level weaknesses are not in these traces.",
            evs,
        )
        if claim and not any("first screen" in w["claim"] for w in weaknesses):
            weaknesses.insert(0, claim)
            weaknesses = weaknesses[:3]

    thin = (not strengths and not any("friction" in w["claim"].lower() for w in weaknesses)) or stuck_ratio >= 0.75
    if not product:
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
        headline = f"{host}: {strengths[0]['claim'][:90]}"
    elif strengths:
        headline = f"{host}: {strengths[0]['claim'][:110]}"
    elif weaknesses:
        headline = f"{host}: {weaknesses[0]['claim'][:110]}"
    else:
        headline = f"Evidence is thin for {host}: the traces do not support a specific strength or weakness."
        thin = True

    evidence_note = None
    if thin:
        evidence_note = (
            "Evidence is thin. Claims below are only what a trace step actually shows. "
            "Nothing else is filled in."
        )

    comparisons, tie_note = _comparisons(study, runs)
    product_metrics = work_metrics(product, product_url)
    return {
        "headline": headline[:240],
        "evidence_thin": bool(thin),
        "evidence_note": evidence_note,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "comparisons": comparisons,
        "tie_note": tie_note,
        "work_metrics": product_metrics,
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
        steps = [float(r.get("num_steps") or len(r.get("trace") or []) or 0) for r in group]
        times = [durations[str(r.get("agent_id"))] for r in group if str(r.get("agent_id")) in durations]
        friction = sum(len(r.get("friction_points") or []) for r in group)
        label = str(group[0].get("site_label") or key)
        if key == "product":
            label = _host(str(study.get("url") or "")) or "Product"
        rows.append(
            {
                "site_key": key,
                "site_label": label,
                "n": len(group),
                "ok": ok,
                "success_rate": round(ok / len(group), 3) if group else 0,
                "left_start_pct": round(100 * left_n / len(group)) if group else 0,
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
    }
    insights = build_report_insights(payload)
    summary = dict(getattr(study, "summary", None) or {})
    summary["insights"] = insights
    if insights.get("headline"):
        summary["headline"] = insights["headline"]
    study.summary = summary
    return insights
