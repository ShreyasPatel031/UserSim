"""Arm 3 — execute short async Python against the live page (code-as-action).

Literature: Webwright (86.7% OM2W WebJudge) and browser-use's own OM2W writeup both
identify moving filter/date/form work into compact programs as the largest harness win.
This action is the minimal slice: one `run_page_code` tool alongside click/type.
"""

from __future__ import annotations

import ast
import asyncio
import os
import textwrap
import traceback

from pydantic import BaseModel, Field

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.tools.service import Tools

from capability.page_helper import PageHelper

_CODE_TIMEOUT_S = float(os.environ.get("BROWSER_USE_CODE_TIMEOUT_S", "15"))
_RESULT_MAX = int(os.environ.get("BROWSER_USE_CODE_RESULT_MAX", "8000"))
_BANNED_NAMES = frozenset(
    {
        "__import__",
        "open",
        "exec",
        "eval",
        "compile",
        "os",
        "sys",
        "subprocess",
        "pathlib",
        "socket",
        "requests",
        "httpx",
        "urllib",
    }
)


def code_actions_enabled() -> bool:
    return os.environ.get("BROWSER_USE_CODE_ACTIONS", "").lower() in {"1", "true", "yes"}


class RunPageCodeAction(BaseModel):
    code: str = Field(
        description=(
            "Async Python using the `page` helper (page.fill, page.click, page.select_option, "
            "page.set_date, page.eval_js, page.url). Assign your return value to `result`. "
            "Use for multi-field forms, date ranges, filter sets, or structured extraction. "
            "Do not import modules. Example:\n"
            "await page.fill('#q', 'wireless keyboard')\n"
            "result = await page.text_content('.results-count')"
        )
    )


def _validate_code(code: str) -> None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("imports are not allowed in run_page_code")
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            raise ValueError(f"{node.id} is not allowed in run_page_code")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("dunder attribute access is not allowed")


async def _run_snippet(code: str, page: PageHelper) -> Any:
    _validate_code(code)
    body = textwrap.indent(code.strip(), "    ")
    src = f"async def __run_page_code_snippet():\n{body}\n    return locals().get('result')"
    namespace: dict = {"page": page, "asyncio": asyncio}
    exec(src, namespace)  # noqa: S102 — sandboxed namespace, ephemeral VM
    return await asyncio.wait_for(namespace["__run_page_code_snippet"](), timeout=_CODE_TIMEOUT_S)


def register_code_actions(tools: Tools, *, allowed_domains: list[str] | None) -> None:
    @tools.registry.action(
        (
            "Execute a short async Python snippet against the CURRENT browser page via the "
            "`page` helper. Prefer this over long click chains for: multi-field forms, date "
            "ranges, applying several filters, or extracting structured lists from the DOM. "
            "Assign the return value to `result`. Errors are returned verbatim — fix and retry. "
            "Do not use for a single click; use click(index) instead."
        ),
        param_model=RunPageCodeAction,
        terminates_sequence=True,
    )
    async def run_page_code(params: RunPageCodeAction, browser_session: BrowserSession):
        page = PageHelper(browser_session, allowed_domains)
        try:
            value = await _run_snippet(params.code, page)
            text = repr(value) if value is not None else "None"
            if len(text) > _RESULT_MAX:
                text = text[:_RESULT_MAX] + f"... [truncated at {_RESULT_MAX} chars]"
            memory = f"run_page_code ok: {text[:500]}"
            return ActionResult(
                extracted_content=text,
                long_term_memory=memory,
                include_extracted_content_only_once=True,
            )
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc(limit=6)
            msg = f"run_page_code failed: {exc}\n{tb}"[:4000]
            return ActionResult(error=msg, long_term_memory=msg[:500])
