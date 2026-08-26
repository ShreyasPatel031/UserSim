"""Arm 1 widget primitives — registered when BROWSER_USE_WIDGET_TOOLS=1.

Implemented by the Arm 1 agent. Arm 3 imports this module only for the shared registry.
"""

from __future__ import annotations

import os

from browser_use.tools.service import Tools


def widget_tools_enabled() -> bool:
    return os.environ.get("BROWSER_USE_WIDGET_TOOLS", "").lower() in {"1", "true", "yes"}


def register_widget_actions(tools: Tools, *, allowed_domains: list[str] | None) -> None:
  # Arm 1: select_option, set_date, assert_filter_applied, loop breaker hooks.
    _ = tools, allowed_domains
    raise NotImplementedError(
        "BROWSER_USE_WIDGET_TOOLS=1 but widget primitives are not implemented yet (Arm 1)."
    )
