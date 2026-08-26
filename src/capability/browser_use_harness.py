"""Shared browser-use Agent tuning (Stage 1 hill-climb defaults).

Turn off browser-use's internal judge, route page extraction to a cheap model, and
keep navigation on the task's registrable domain.

History is deliberately NOT capped. An earlier revision pinned max_history_items to 6
to stay under Mistral's 8-image request limit, but that limit never applied here:
browser-use builds agent_history_description from item.to_string() (text only) and
sends exactly one screenshot per request ("Use only the current screenshot"). The
max_images=10 cap lives in _judge_and_log, not the agent loop. The cap therefore cost
the agent its memory of steps 2..n-5 for no benefit, and 6 was the library floor
(assert max_history_items > 5). browser-use's own compacted_memory handles growth.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from browser_use import ChatOpenAI

from capability.mistral_config import MISTRAL_API_BASE, mistral_api_key
from capability.code_actions import code_actions_enabled

# Cheap text model for extract / fallback — does not compete with the agent LLM.
DEFAULT_EXTRACTION_MODEL = os.environ.get("MISTRAL_EXTRACTION_MODEL", "ministral-8b-latest")

STAGE1_ENABLED = os.environ.get("BROWSER_USE_STAGE1", "1").lower() not in {"0", "false", "no"}
FAST_BAKEOFF = os.environ.get("BROWSER_USE_FAST", "").lower() in {"1", "true", "yes"}


def browser_use_arm() -> str:
    """Parallel-arm selector (see contributions/mistral-vibe/PARALLEL_ARMS_PLAN.md)."""
    return os.environ.get("BROWSER_USE_ARM", "0").strip() or "0"


def _history_items_setting() -> int | None:
    """None = uncapped text history. Default 6 matches the 12% baseline run.

    browser-use asserts max_history_items > 5, so illegal values are coerced to None.
    Arm 1 sets BROWSER_USE_ARM=1 (or BROWSER_USE_MAX_HISTORY_ITEMS=none).
    """
    arm = browser_use_arm()
    raw = (os.environ.get("BROWSER_USE_MAX_HISTORY_ITEMS") or "").strip().lower()
    if not raw and arm == "1":
        return None
    if not raw:
        return 6
    if raw in {"none", "0", "all", "-1", "uncapped"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return 6
    return value if value > 5 else None


def _actions_per_step_setting() -> int:
    arm = browser_use_arm()
    raw = os.environ.get("BROWSER_USE_MAX_ACTIONS_PER_STEP")
    if raw is not None:
        return int(raw)
    if arm == "2":
        return 4
    return 3 if FAST_BAKEOFF else 2


def _use_allowed_domains() -> bool:
    arm = browser_use_arm()
    if arm == "2":
        return os.environ.get("BROWSER_USE_ALLOWED_DOMAINS", "0").lower() not in {
            "0",
            "false",
            "no",
        }
    return True


STAGE1_MAX_HISTORY_ITEMS = _history_items_setting()
STAGE1_MAX_ACTIONS_PER_STEP = _actions_per_step_setting()
STAGE1_USE_ALLOWED_DOMAINS = _use_allowed_domains()
STAGE1_LLM_MAX_RETRIES = int(os.environ.get("MISTRAL_LLM_MAX_RETRIES", "8"))
# 180s/step lets a single hung page burn 90+ min across 30 steps. Default 90s.
STAGE1_STEP_TIMEOUT = int(os.environ.get("BROWSER_USE_STEP_TIMEOUT", "90"))


def stage1_enabled() -> bool:
    return STAGE1_ENABLED


def allowed_domains_for_start_url(start_url: str) -> list[str]:
    """Allow the task site and its subdomains; block off-site search escapes."""
    host = (urlparse(start_url).hostname or "").lower().strip(".")
    if not host:
        return []
    parts = host.split(".")
    if len(parts) >= 2:
        registrable = ".".join(parts[-2:])
        return [f"*.{registrable}", host]
    return [host]


def mistral_llm(model: str, *, max_retries: int | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        api_key=mistral_api_key(),
        base_url=MISTRAL_API_BASE,
        temperature=0,
        max_retries=max_retries if max_retries is not None else STAGE1_LLM_MAX_RETRIES,
    )


def stage1_llm_stack(agent_model: str) -> tuple[ChatOpenAI, ChatOpenAI | None, ChatOpenAI | None]:
    """Return (agent_llm, page_extraction_llm, fallback_llm)."""
    agent_llm = mistral_llm(agent_model)
    if not stage1_enabled():
        return agent_llm, None, None
    cheap = mistral_llm(DEFAULT_EXTRACTION_MODEL)
    return agent_llm, cheap, cheap


def stage1_agent_kwargs(*, use_vision: bool) -> dict:
    """Extra kwargs for browser_use.Agent when Stage 1 is on."""
    base_message = (
        "You are optimizing for task completion, not human imitation. "
        "Apply all required filters and finish the stated goal."
    )
    if not stage1_enabled():
        return {
            "max_actions_per_step": 3,
            "extend_system_message": base_message,
        }
    kwargs: dict = {
        "use_judge": False,
        "max_actions_per_step": STAGE1_MAX_ACTIONS_PER_STEP,
        "max_history_items": STAGE1_MAX_HISTORY_ITEMS,
        "step_timeout": STAGE1_STEP_TIMEOUT,
        "extend_system_message": (
            f"{base_message} "
            "Stay on the start website — do not use Google, Bing, or DuckDuckGo. "
            "Do not call done until every task constraint is satisfied on the page."
        ),
    }
    if FAST_BAKEOFF:
        kwargs["flash_mode"] = True
    if use_vision:
        # Smaller screenshots in the LLM payload (viewport is still 1280x800).
        kwargs["llm_screenshot_size"] = (960, 600)
    if code_actions_enabled():
        kwargs["extend_system_message"] = (
            f"{kwargs['extend_system_message']} "
            "For multi-field forms, date ranges, filter sets, or structured list extraction, "
            "prefer run_page_code with the page helper over long click chains. "
            "Use click/input for single-element actions only."
        )
    return kwargs


def stage1_profile_kwargs(start_url: str, base: dict) -> dict:
    """Merge allowed_domains into a BrowserProfile kwargs dict."""
    if not stage1_enabled() or not STAGE1_USE_ALLOWED_DOMAINS:
        return base
    domains = allowed_domains_for_start_url(start_url)
    if domains:
        base = {**base, "allowed_domains": domains}
    return base


def stage1_config_snapshot() -> dict:
    from capability.widget_tools import harness_tools_flags

    snap = {
        "arm": browser_use_arm(),
        "stage1": stage1_enabled(),
        "use_judge": False if stage1_enabled() else True,
        "extraction_model": DEFAULT_EXTRACTION_MODEL if stage1_enabled() else None,
        "max_actions_per_step": STAGE1_MAX_ACTIONS_PER_STEP if stage1_enabled() else 3,
        "max_history_items": STAGE1_MAX_HISTORY_ITEMS if stage1_enabled() else None,
        "allowed_domains_enabled": STAGE1_USE_ALLOWED_DOMAINS if stage1_enabled() else None,
        "llm_max_retries": STAGE1_LLM_MAX_RETRIES if stage1_enabled() else 5,
        "fast_bakeoff": FAST_BAKEOFF,
        "step_timeout": STAGE1_STEP_TIMEOUT if stage1_enabled() else None,
    }
    snap.update(harness_tools_flags())
    return snap
