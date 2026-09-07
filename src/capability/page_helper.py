"""Thin async DOM helper for model-authored page code (Arm 3).

browser-use drives the browser over CDP, not a Playwright Page handle. This wrapper
exposes a small, safe surface the model can call from `run_page_code` snippets.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from browser_use.browser import BrowserSession
from browser_use.utils import match_url_with_domain_pattern


def _js_string(s: str) -> str:
    return json.dumps(s)


class PageHelper:
    """Async page helper exposed to `run_page_code` snippets as `page`."""

    def __init__(self, session: BrowserSession, allowed_domains: list[str] | None) -> None:
        self._session = session
        self._allowed = allowed_domains or []

    async def url(self) -> str:
        return await self._session.get_current_page_url()

    async def title(self) -> str:
        return await self._session.get_current_page_title()

    async def eval_js(self, expression: str) -> Any:
        """Evaluate JavaScript on the current page and return the value."""
        cdp_session = await self._session.get_or_create_cdp_session()
        result = await cdp_session.cdp_client.send.Runtime.evaluate(
            params={"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id=cdp_session.session_id,
        )
        if result.get("exceptionDetails"):
            exc = result["exceptionDetails"]
            raise RuntimeError(exc.get("text") or str(exc))
        value = result.get("result", {}).get("value")
        await self._assert_url_allowed()
        return value

    async def fill(self, selector: str, value: str, *, clear: bool = True) -> str:
        sel, val = _js_string(selector), _js_string(value)
        clear_js = "el.value = '';" if clear else ""
        js = f"""(() => {{
  const el = document.querySelector({sel});
  if (!el) return 'not found: ' + {sel};
  {clear_js}
  el.focus();
  el.value = {val};
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  return 'ok';
}})()"""
        out = await self.eval_js(js)
        return str(out)

    async def click(self, selector: str) -> str:
        sel = _js_string(selector)
        js = f"""(() => {{
  const el = document.querySelector({sel});
  if (!el) return 'not found: ' + {sel};
  el.click();
  return 'ok';
}})()"""
        return str(await self.eval_js(js))

    async def select_option(self, selector: str, value: str) -> str:
        sel, val = _js_string(selector), _js_string(value)
        js = f"""(() => {{
  const el = document.querySelector({sel});
  if (!el) return 'not found: ' + {sel};
  if (el.tagName === 'SELECT') {{
    el.value = {val};
    el.dispatchEvent(new Event('input', {{bubbles: true}}));
    el.dispatchEvent(new Event('change', {{bubbles: true}}));
    return 'ok select';
  }}
  return 'not a select: ' + el.tagName;
}})()"""
        return str(await self.eval_js(js))

    async def set_date(self, selector: str, iso_date: str) -> str:
        return await self.fill(selector, iso_date, clear=True)

    async def text_content(self, selector: str) -> str:
        sel = _js_string(selector)
        js = f"""(() => {{
  const el = document.querySelector({sel});
  return el ? (el.textContent || '').trim() : '';
}})()"""
        return str(await self.eval_js(js))

    async def _assert_url_allowed(self) -> None:
        if not self._allowed:
            return
        current = await self.url()
        host = (urlparse(current).hostname or "").lower()
        if not host:
            return
        if not any(match_url_with_domain_pattern(current, pattern) for pattern in self._allowed):
            raise RuntimeError(f"navigation left allowed domains: {current}")
