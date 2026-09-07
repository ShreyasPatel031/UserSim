"""Optional harness tool registry for OM2W experiment arms.

Arm 1 adds widget primitives here (`BROWSER_USE_WIDGET_TOOLS=1`).
Arm 3 adds code execution here (`BROWSER_USE_CODE_ACTIONS=1`).
"""

from __future__ import annotations

import os

from browser_use.tools.service import Tools

from capability.code_actions import code_actions_enabled, register_code_actions
from capability.widget_primitives import register_widget_actions, widget_tools_enabled


def build_harness_tools(*, allowed_domains: list[str] | None) -> Tools | None:
    """Return a Tools registry with arm-specific actions, or None if all flags are off."""
    if not code_actions_enabled() and not widget_tools_enabled():
        return None

    tools = Tools()
    if widget_tools_enabled():
        register_widget_actions(tools, allowed_domains=allowed_domains)
    if code_actions_enabled():
        register_code_actions(tools, allowed_domains=allowed_domains)
    return tools


def harness_tools_flags() -> dict:
    from capability.verify_done import verify_done_enabled

    return {
        "widget_tools": widget_tools_enabled(),
        "code_actions": code_actions_enabled(),
        "verify_done": verify_done_enabled(),
        "code_action_timeout_s": int(os.environ.get("BROWSER_USE_CODE_TIMEOUT_S", "15")),
        "code_result_max_chars": int(os.environ.get("BROWSER_USE_CODE_RESULT_MAX", "8000")),
        "verify_max_rejections": int(os.environ.get("BROWSER_USE_VERIFY_MAX_REJECTIONS", "2")),
    }
