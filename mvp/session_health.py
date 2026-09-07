"""Check whether a captured browser profile is still signed in.

Sessions expire, and a stale profile fails silently: agents just see a
signed-out site and the study quietly measures the wrong experience. This runs
a throwaway clone headlessly and asks the page directly, so a stale session can
be re-established by mvp.auto_signin / mvp.auto_signup before agents launch.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from mvp.profile_pool import clone_for_url, discard

# Site-specific "am I signed in" probes, evaluated in the page.
_PROBES = {
    "youtube.com": "(window.ytcfg && ytcfg.get) ? !!ytcfg.get('LOGGED_IN') : "
    "!!document.querySelector('#avatar-btn')",
    "google.com": "!!document.querySelector('a[href*=\"SignOutOptions\"]')",
}

# Generic probe used when no site-specific expression is registered.
_GENERIC_PROBE = """
(() => {
  const body = (document.body && document.body.innerText || '').toLowerCase();
  const hasAccount = !!(
    document.querySelector(
      'a[href*="logout"], a[href*="signout"], a[href*="sign-out"],' +
      'button[aria-label*="Account"], button[aria-label*="account"],' +
      'img[alt*="avatar"], [data-testid*="avatar"], [data-testid*="user-menu"],' +
      '[data-testid*="UserMenu"], [aria-label*="User menu"]'
    )
  );
  const logoutText = /\\blog\\s*out\\b|\\bsign\\s*out\\b|account settings|my account/.test(body);
  const loginForm = !!(
    document.querySelector('input[type="password"], form[action*="login"], form[action*="signin"]')
  );
  const path = (location.pathname || '').toLowerCase();
  const appPath = /dashboard|workspace|inbox|projects|settings|home\\b|app\\b/.test(path);
  if (loginForm && !hasAccount) return false;
  if (hasAccount || logoutText) return true;
  if (appPath && !loginForm) return true;
  return false;
})()
"""


def _probe_for(host: str) -> str:
    for key, expr in _PROBES.items():
        if key in host:
            return expr
    return _GENERIC_PROBE


async def profile_signed_in(url: str, *, timeout_s: float = 45.0) -> bool | None:
    """True/False when a profile exists; None when there is nothing to check."""
    host = (urlparse(url).hostname or "").lower()
    clone = await asyncio.to_thread(clone_for_url, url)
    if not clone:
        # Also treat a site_state JSON with no profile as "nothing to probe".
        return None
    probe = _probe_for(host)

    from browser_use import BrowserSession
    from browser_use.browser.profile import BrowserProfile

    from capability import USER_AGENT, VIEWPORT

    session = None
    try:
        session = BrowserSession(
            browser_profile=BrowserProfile(
                is_local=True,
                headless=True,
                viewport=VIEWPORT,
                user_agent=USER_AGENT,
                disable_security=True,
                user_data_dir=str(clone),
                channel="chrome",
            )
        )
        await asyncio.wait_for(session.start(), timeout=timeout_s)
        cdp = await session.get_or_create_cdp_session()
        await cdp.cdp_client.send.Page.navigate(
            {"url": url}, session_id=cdp.session_id
        )
        await asyncio.sleep(8)
        result = await cdp.cdp_client.send.Runtime.evaluate(
            {"expression": probe, "returnByValue": True}, session_id=cdp.session_id
        )
        return bool(result.get("result", {}).get("value"))
    except Exception:
        return False
    finally:
        if session is not None:
            try:
                await session.kill()
            except Exception:
                pass
        await asyncio.to_thread(discard, clone)


def check(url: str) -> bool | None:
    return asyncio.run(profile_signed_in(url))


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/"
    print(f"{target} signed_in={check(target)}")
