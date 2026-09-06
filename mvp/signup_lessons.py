"""Signup failure-mode lessons — data-driven tips kept out of the task prompt.

Curated modes live in ``mvp/signup_failure_modes.json``. The signup agent
pulls a short tip list via ``get_signup_tips`` when stuck; the full catalog is
never dumped into ``task=``. Raw run notes append to ``observations`` for later
curation into ``modes``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "mvp" / "signup_failure_modes.json"
_LOCK = threading.Lock()


def lessons_path() -> Path:
    override = (os.environ.get("MVP_SIGNUP_FAILURE_MODES") or "").strip()
    return Path(override) if override else DEFAULT_PATH


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    p = path or lessons_path()
    if not p.is_file():
        return {"version": 1, "modes": [], "observations": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"version": 1, "modes": [], "observations": []}
    data.setdefault("version", 1)
    data.setdefault("modes", [])
    data.setdefault("observations", [])
    return data


def save_catalog(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or lessons_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    blob = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with _LOCK:
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(p)


def _norm_host(host: str | None) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _host_matches(mode_hosts: list[str], host: str) -> bool:
    """Empty hosts = global. Otherwise match exact or parent/child domain."""
    if not mode_hosts:
        return True
    if not host:
        return False
    for mh in mode_hosts:
        m = _norm_host(mh)
        if not m:
            continue
        if host == m or host.endswith("." + m) or m.endswith("." + host):
            return True
    return False


def _score_mode(mode: dict[str, Any], *, host: str, query: str) -> int:
    if (mode.get("status") or "active") != "active":
        return -1
    mode_hosts = [str(x) for x in (mode.get("hosts") or []) if x]
    if not _host_matches(mode_hosts, host):
        return -1
    score = 1  # global / host-matched baseline
    if mode_hosts:
        score += 2  # prefer host-specific tips when present
    q = (query or "").strip().lower()
    if not q:
        return score
    hay = " ".join(
        [
            str(mode.get("id") or ""),
            str(mode.get("category") or ""),
            str(mode.get("tip") or ""),
            " ".join(str(s) for s in (mode.get("symptoms") or [])),
        ]
    ).lower()
    tokens = [t for t in q.replace(",", " ").split() if len(t) > 2]
    hits = sum(1 for t in tokens if t in hay)
    if hits == 0 and q not in hay:
        # Query given but no overlap — still allow host-specific, demote globals
        return score if mode_hosts else 0
    return score + hits * 3


def select_modes(
    *,
    host: str | None = None,
    query: str = "",
    limit: int = 5,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    catalog = load_catalog(path)
    host_n = _norm_host(host)
    limit = max(1, min(int(limit or 5), 8))
    scored: list[tuple[int, dict[str, Any]]] = []
    for mode in catalog.get("modes") or []:
        if not isinstance(mode, dict):
            continue
        s = _score_mode(mode, host=host_n, query=query)
        if s < 0:
            continue
        if query.strip() and s == 0:
            continue
        scored.append((s, mode))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("id") or "")))
    # With empty query, return a small global starter set (not the whole catalog).
    if not query.strip():
        # Prefer host-specific first, then a few high-value globals.
        preferred_ids = {
            "submit_noop_or_disabled",
            "captcha_wait_loop",
            "invented_otp",
            "email_wait_without_mark",
            "sso_only_or_sso_trap",
        }
        out: list[dict[str, Any]] = []
        for s, m in scored:
            hosts = m.get("hosts") or []
            if hosts and _host_matches([str(h) for h in hosts], host_n):
                out.append(m)
        for s, m in scored:
            if m in out:
                continue
            if (m.get("id") or "") in preferred_ids:
                out.append(m)
            if len(out) >= limit:
                break
        if len(out) < limit:
            for s, m in scored:
                if m not in out:
                    out.append(m)
                if len(out) >= limit:
                    break
        return out[:limit]
    return [m for _, m in scored[:limit]]


def format_tips(modes: list[dict[str, Any]]) -> str:
    if not modes:
        return (
            "No matching signup tips. Describe the blocker in one short phrase "
            "(e.g. 'submit does nothing', 'captcha', 'email already used') and call again."
        )
    lines = ["Signup tips (apply only what matches the current page):"]
    for m in modes:
        mid = m.get("id") or "unknown"
        tip = (m.get("tip") or "").strip()
        if not tip:
            continue
        lines.append(f"- [{mid}] {tip}")
    return "\n".join(lines)


def lookup_tips(
    *,
    host: str | None = None,
    query: str = "",
    limit: int = 5,
    path: Path | None = None,
) -> str:
    return format_tips(select_modes(host=host, query=query, limit=limit, path=path))


# Align with browser-use ActionLoopDetector nudge thresholds (views.py).
LOOP_STAGNATION_THRESHOLD = 5
LOOP_REPETITION_THRESHOLD = 5
LOOP_STAGNATION_ESCALATE = 8
LOOP_REPETITION_ESCALATE = 8


def loop_detector_signal(loop_detector: Any) -> dict[str, int]:
    """Pull repetition/stagnation counts from a browser-use ActionLoopDetector."""
    return {
        "repetition": int(getattr(loop_detector, "max_repetition_count", 0) or 0),
        "stagnation": int(getattr(loop_detector, "consecutive_stagnant_pages", 0) or 0),
    }


def should_inject_loop_tips(
    *,
    repetition: int,
    stagnation: int,
    inject_count: int,
    max_injects: int = 2,
) -> bool:
    """True when loop signals cross a threshold we have not yet answered."""
    if inject_count >= max_injects:
        return False
    if inject_count == 0:
        return (
            stagnation >= LOOP_STAGNATION_THRESHOLD
            or repetition >= LOOP_REPETITION_THRESHOLD
        )
    # Second inject only after a harder stall.
    return (
        stagnation >= LOOP_STAGNATION_ESCALATE
        or repetition >= LOOP_REPETITION_ESCALATE
    )


def loop_tips_followup(
    *,
    host: str | None,
    repetition: int = 0,
    stagnation: int = 0,
    inject_count: int = 0,
    path: Path | None = None,
) -> str:
    """Compact follow-up task text to inject when the agent is looping."""
    # Prefer submit/form tips on stagnation (Buffer-style); broader on pure repetition.
    query = (
        "submit does nothing sign up click validation disabled"
        if stagnation >= LOOP_STAGNATION_THRESHOLD
        else "repeated action failure form captcha sso"
    )
    tips = lookup_tips(host=host, query=query, limit=4, path=path)
    escalate = inject_count >= 1
    header = (
        "AUTO TIP (loop/stagnation detected — apply now, do not ignore):\n"
        f"signals: stagnation={stagnation} repetition={repetition}\n"
    )
    footer = (
        "\nIf these tips do not unblock the page in 1–2 actions, call "
        "note_signup_failure then report_blocked(unknown) — do not keep clicking "
        "the same control."
        if escalate
        else "\nApply the matching tip on the next action. Do not spam the same click."
    )
    return header + tips + footer


def record_observation(
    *,
    host: str,
    symptom: str,
    detail: str = "",
    mode_id: str | None = None,
    source: str = "run",
    path: Path | None = None,
) -> dict[str, Any]:
    """Append a raw observation for later curation into ``modes``."""
    symptom = (symptom or "").strip()
    if not symptom:
        raise ValueError("symptom required")
    obs = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": _norm_host(host),
        "symptom": symptom[:300],
        "detail": (detail or "")[:500],
        "mode_id": (mode_id or "").strip() or None,
        "source": (source or "run")[:64],
    }
    with _LOCK:
        catalog = load_catalog(path)
        observations = list(catalog.get("observations") or [])
        observations.append(obs)
        # Cap growth so the file stays editable.
        catalog["observations"] = observations[-500:]
        save_catalog(catalog, path)
    return obs
