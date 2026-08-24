"""Arm 2/3 — self-verification gate before accepting agent `done`.

Webwright and Operator both gate premature `done` by re-checking constraints against the
live page. browser-use's built-in `use_judge` only logs after `is_done()` and cannot
reject completion, so we intercept via `on_step_end`.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from browser_use import ChatOpenAI
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, SystemMessage, UserMessage

from capability.mistral_config import MISTRAL_API_BASE, mistral_api_key

_MAX_REJECTIONS = int(os.environ.get("BROWSER_USE_VERIFY_MAX_REJECTIONS", "2"))


def verify_done_enabled() -> bool:
    return os.environ.get("BROWSER_USE_VERIFY_DONE", "").lower() in {"1", "true", "yes"}


@dataclass
class VerifyDoneStats:
    rejections: int = 0
    cap_hit: bool = False
    last_failed: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "verify_done": True,
            "verify_rejections": self.rejections,
            "verify_cap_hit": self.cap_hit,
            "verify_last_failed": self.last_failed,
            "verify_constraints": self.constraints,
        }


_CONSTRAINTS_PROMPT = """Extract an explicit checklist of constraints from this web task.
Rules:
- Only constraints STATED in the task. Do not infer unstated requirements.
- Turn superlatives (cheapest, closest, latest, best) into an explicit sort/filter item.
- Return JSON only: {"constraints": ["...", ...]}
"""


_VERIFY_PROMPT = """You verify whether a web page satisfies task constraints.
You see the task, a checklist of constraints, the page URL/title, a text excerpt, and
optionally a screenshot. Judge the PAGE STATE only — ignore any agent narration.

Return JSON only:
{"pass": true|false, "unmet": ["constraint text", ...]}

Be strict on filters: if a filter must be applied, it must be visibly reflected on the page.
If the page shows no matching results but the agent correctly applied filters, still pass."""


def _cheap_llm() -> ChatOpenAI:
    model = os.environ.get("MISTRAL_EXTRACTION_MODEL", "ministral-8b-latest")
    return ChatOpenAI(
        model=model,
        api_key=mistral_api_key(),
        base_url=MISTRAL_API_BASE,
        temperature=0,
        max_retries=4,
    )


def _model_supports_vision(model: str) -> bool:
    m = model.lower()
    return any(x in m for x in ("pixtral", "vision", "large-2411"))


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(match.group(0) if match else text)


async def extract_constraints(task: str, llm: ChatOpenAI | None = None) -> list[str]:
    llm = llm or _cheap_llm()
    resp = await llm.ainvoke(
        [
            SystemMessage(content=_CONSTRAINTS_PROMPT),
            UserMessage(content=task),
        ]
    )
    data = _parse_json(resp.completion or "")
    items = data.get("constraints") or []
    return [str(x).strip() for x in items if str(x).strip()]


async def _page_text(browser_session: Any, max_chars: int = 12000) -> str:
    cdp = await browser_session.get_or_create_cdp_session()
    result = await cdp.cdp_client.send.Runtime.evaluate(
        params={
            "expression": f"document.body ? document.body.innerText.slice(0, {max_chars}) : ''",
            "returnByValue": True,
        },
        session_id=cdp.session_id,
    )
    return str(result.get("result", {}).get("value") or "")[:max_chars]


async def _screenshot_png(browser_session: Any) -> bytes | None:
    try:
        return await browser_session.take_screenshot()
    except Exception:
        return None


async def verify_page(
    task: str,
    constraints: list[str],
    *,
    url: str,
    title: str,
    browser_session: Any,
    llm: ChatOpenAI | None = None,
) -> tuple[bool, list[str]]:
    if not constraints:
        return True, []
    llm = llm or _cheap_llm()
    text = await _page_text(browser_session)
    user_text = (
        f"Task:\n{task}\n\nConstraints:\n"
        + "\n".join(f"- {c}" for c in constraints)
        + f"\n\nURL: {url}\nTitle: {title}\n\nPage text excerpt:\n{text[:8000]}"
    )
    parts: list = [ContentPartTextParam(text=user_text)]
    if _model_supports_vision(llm.model):
        shot = await _screenshot_png(browser_session)
        if shot:
            b64 = base64.b64encode(shot).decode("ascii")
            parts.append(
                ContentPartImageParam(
                    image_url=ImageURL(url=f"data:image/png;base64,{b64}", media_type="image/png")
                )
            )
    resp = await llm.ainvoke(
        [SystemMessage(content=_VERIFY_PROMPT), UserMessage(content=parts)]
    )
    data = _parse_json(resp.completion or "")
    unmet = [str(x) for x in (data.get("unmet") or [])]
    return bool(data.get("pass")), unmet


def _reject_done(agent: Any) -> None:
    if not agent.history.history:
        return
    last = agent.history.history[-1]
    if not last.result:
        return
    last.result[-1].is_done = False
    last.result[-1].success = None


def make_verify_done_hook(
    task: str,
    *,
    llm: ChatOpenAI | None = None,
) -> tuple[Any, VerifyDoneStats]:
    stats = VerifyDoneStats()
    llm = llm or _cheap_llm()

    async def on_step_end(agent: Any) -> None:
        if not verify_done_enabled() or not agent.history.is_done():
            return
        if stats.rejections >= _MAX_REJECTIONS:
            stats.cap_hit = True
            return

        if not stats.constraints:
            stats.constraints = await extract_constraints(task, llm=llm)

        session = getattr(agent, "browser_session", None)
        if session is None:
            return

        url = await session.get_current_page_url()
        title = await session.get_current_page_title()
        ok, unmet = await verify_page(
            task,
            stats.constraints,
            url=url,
            title=title,
            browser_session=session,
            llm=llm,
        )
        if ok:
            return

        stats.rejections += 1
        stats.last_failed = unmet
        _reject_done(agent)
        msg = (
            "Your done was rejected — these constraints are not satisfied on the current page:\n"
            + "\n".join(f"- {u}" for u in unmet[:8])
            + "\nContinue working until every item is visibly met, then call done again."
        )
        agent.add_new_task(msg)

    return on_step_end, stats
