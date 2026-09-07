"""CAPTCHA solving stack for product signup.

Layers (cheapest first):

1. Settle / click — wait for invisible scoring, click Cloudflare checkbox.
2. Browserbase native — listen for ``browserbase-solving-started/finished``
   console events (solveCaptchas is on by default for BB sessions).
3. Open-source local solvers — optional ``captcha-solver-ai`` (reCAPTCHA image
   grids) and ``ddddocr`` (simple distorted-text captchas).
4. Solver API — CapSolver or 2Captcha for sitekey-based reCAPTCHA / hCaptcha /
   Turnstile. Returns a token the agent injects into the page.
5. Human push — ntfy + desktop notification; wait for ``secrets/captcha_done.txt``.

Env:
  MVP_CAPTCHA_SOLVER=1          # enable browser-use captcha_solver flag
  MVP_CAPTCHA_API=capsolver|2captcha
  MVP_CAPTCHA_API_KEY=...
  MVP_CAPTCHA_OSS=1             # try local OSS solvers (default on)
  MVP_CAPTCHA_BB_WAIT_S=45      # max wait for Browserbase native solver
  MVP_CAPTCHA_HUMAN_TIMEOUT_S=300
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx

from mvp.notify import push

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
DONE_FILE = SECRETS / "captcha_done.txt"

# Console lines Browserbase emits while its built-in solver runs.
_BB_SOLVING_STARTED = "browserbase-solving-started"
_BB_SOLVING_FINISHED = "browserbase-solving-finished"


def captcha_solver_enabled() -> bool:
    return os.environ.get("MVP_CAPTCHA_SOLVER", "").lower() in {"1", "true", "yes"}


def _api_name() -> str:
    return (os.environ.get("MVP_CAPTCHA_API") or "capsolver").strip().lower()


def _api_key() -> str:
    key = (os.environ.get("MVP_CAPTCHA_API_KEY") or "").strip()
    if key:
        return key
    try:
        from mvp.credentials import _load_vault

        vault = _load_vault()
        captcha = vault.get("captcha") or {}
        return (captcha.get("api_key") or "").strip()
    except Exception:
        return ""


def browserbase_captcha_kwargs() -> dict[str, Any]:
    """Extra kwargs for Browserbase session create when captcha solving is on.

    Do NOT enable ``advanced_stealth`` by default — Browserbase returns 403
    ("Verified mode is only available on the Enterprise plan") on Hobby/Startup.
    """
    if not captcha_solver_enabled():
        return {}
    return {
        "solve_captchas": True,
        "advanced_stealth": False,
    }


async def detect_sitekey(page: Any) -> dict[str, Any] | None:
    """Scrape a visible captcha sitekey + type from the current page DOM."""
    script = """
    (() => {
      const out = {type: null, sitekey: null, action: null};
      const g = document.querySelector('[data-sitekey], .g-recaptcha, .h-captcha, .cf-turnstile');
      if (g) {
        out.sitekey = g.getAttribute('data-sitekey') || g.dataset.sitekey || null;
        const cls = (g.className || '') + ' ' + (g.id || '');
        if (/turnstile|cf-/i.test(cls) || g.tagName === 'DIV' && g.classList.contains('cf-turnstile'))
          out.type = 'turnstile';
        else if (/h-?captcha/i.test(cls)) out.type = 'hcaptcha';
        else out.type = 'recaptcha';
        out.action = g.getAttribute('data-action') || null;
      }
      if (!out.sitekey) {
        const scripts = [...document.scripts].map(s => s.src || '');
        for (const src of scripts) {
          const m = src.match(/[?&](?:render|sitekey)=([A-Za-z0-9_-]{20,})/);
          if (m) { out.sitekey = m[1]; out.type = /hcaptcha/i.test(src) ? 'hcaptcha'
            : /turnstile|challenges\\.cloudflare/i.test(src) ? 'turnstile' : 'recaptcha'; break; }
        }
      }
      if (!out.sitekey && window.grecaptcha) out.type = out.type || 'recaptcha';
      return out.sitekey ? out : null;
    })()
    """
    try:
        return await page.evaluate(script)
    except Exception:
        return None


def solve_sitekey(
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str = "recaptcha",
    action: str | None = None,
    timeout_s: float = 180.0,
) -> str | None:
    """Return a solver token for the given sitekey, or None on failure."""
    key = _api_key()
    if not key:
        return None
    api = _api_name()
    if api in {"capsolver", "cap-solver"}:
        return _capsolver_solve(
            key,
            sitekey=sitekey,
            page_url=page_url,
            captcha_type=captcha_type,
            action=action,
            timeout_s=timeout_s,
        )
    if api in {"2captcha", "twocaptcha", "anti-captcha", "anticaptcha"}:
        return _twocaptcha_solve(
            key,
            sitekey=sitekey,
            page_url=page_url,
            captcha_type=captcha_type,
            action=action,
            timeout_s=timeout_s,
        )
    return None


def _capsolver_solve(
    key: str,
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str,
    action: str | None,
    timeout_s: float,
) -> str | None:
    type_map = {
        "recaptcha": "ReCaptchaV2TaskProxyLess",
        "recaptcha_v2": "ReCaptchaV2TaskProxyLess",
        "recaptcha_v3": "ReCaptchaV3TaskProxyLess",
        "hcaptcha": "HCaptchaTaskProxyLess",
        "turnstile": "AntiTurnstileTaskProxyLess",
    }
    task_type = type_map.get((captcha_type or "recaptcha").lower(), "ReCaptchaV2TaskProxyLess")
    task: dict[str, Any] = {
        "type": task_type,
        "websiteURL": page_url,
        "websiteKey": sitekey,
    }
    if action and "V3" in task_type:
        task["pageAction"] = action
    try:
        create = httpx.post(
            "https://api.capsolver.com/createTask",
            json={"clientKey": key, "task": task},
            timeout=30.0,
        ).json()
    except Exception:
        return None
    task_id = create.get("taskId")
    if not task_id:
        return None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        try:
            result = httpx.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": key, "taskId": task_id},
                timeout=30.0,
            ).json()
        except Exception:
            continue
        if result.get("status") == "ready":
            sol = result.get("solution") or {}
            return sol.get("gRecaptchaResponse") or sol.get("token") or sol.get("response")
        if result.get("status") == "failed" or result.get("errorId"):
            return None
    return None


def _twocaptcha_solve(
    key: str,
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str,
    action: str | None,
    timeout_s: float,
) -> str | None:
    method = "userrecaptcha"
    extra: dict[str, Any] = {}
    ct = (captcha_type or "recaptcha").lower()
    if ct == "hcaptcha":
        method = "hcaptcha"
    elif ct == "turnstile":
        method = "turnstile"
    elif "v3" in ct:
        extra["version"] = "v3"
        if action:
            extra["action"] = action
    try:
        create = httpx.post(
            "https://2captcha.com/in.php",
            data={
                "key": key,
                "method": method,
                "googlekey": sitekey,
                "sitekey": sitekey,
                "pageurl": page_url,
                "json": 1,
                **extra,
            },
            timeout=30.0,
        ).json()
    except Exception:
        return None
    if create.get("status") != 1:
        return None
    req_id = create.get("request")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(5)
        try:
            poll = httpx.get(
                "https://2captcha.com/res.php",
                params={"key": key, "action": "get", "id": req_id, "json": 1},
                timeout=30.0,
            ).json()
        except Exception:
            continue
        if poll.get("status") == 1:
            return str(poll.get("request") or "") or None
        if poll.get("request") not in {"CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"}:
            return None
    return None


def request_human_solve(page_url: str) -> None:
    """Ping the owner and clear any stale done marker."""
    try:
        if DONE_FILE.is_file():
            DONE_FILE.unlink()
    except Exception:
        pass
    push(
        "UserSim CAPTCHA",
        f"Solve the captcha in the signup Chrome window, then touch {DONE_FILE.name}.\n{page_url}",
    )


def wait_for_human_solve(*, timeout_s: float | None = None) -> bool:
    """Wait for the owner to clear a captcha, or fail fast in unattended mode."""
    allow_human = os.environ.get("MVP_CAPTCHA_ALLOW_HUMAN", "").lower() in {
        "1",
        "true",
        "yes",
    }
    # Batch / headless runs cannot rely on a human watching the window.
    unattended = os.environ.get("SIGNUP_HEADLESS", "1").lower() in {"1", "true", "yes"}
    if unattended and not allow_human:
        return False
    timeout_s = timeout_s if timeout_s is not None else float(
        os.environ.get("MVP_CAPTCHA_HUMAN_TIMEOUT_S", "300")
    )
    if not _api_key():
        timeout_s = min(timeout_s, float(os.environ.get("MVP_CAPTCHA_NOAPI_TIMEOUT_S", "20")))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if DONE_FILE.is_file():
            try:
                DONE_FILE.unlink()
            except Exception:
                pass
            return True
        time.sleep(2)
    return False


async def _try_click_cloudflare_checkbox(page: Any) -> bool:
    """Best-effort click on Cloudflare Turnstile / challenge checkbox.

    Many challenges are literally a checkbox in a cross-origin iframe; Playwright
    can still hit the iframe body / checkbox in headed mode sometimes. This is
    free and should run before paid solvers.
    """
    # 1) Same-origin / shadow widget hosts
    try:
        clicked = await page.evaluate(
            """() => {
              const hosts = [
                ...document.querySelectorAll(
                  'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile, #cf-turnstile'
                ),
              ];
              for (const h of hosts) {
                try { h.scrollIntoView({block:'center'}); } catch (e) {}
              }
              // Visible checkbox-looking controls outside iframes
              const btns = [...document.querySelectorAll(
                'input[type="checkbox"], label, div[role="checkbox"], button'
              )];
              for (const b of btns) {
                const t = ((b.innerText || b.getAttribute('aria-label') || '') + '').toLowerCase();
                if (/human|verify|not a robot|cloudflare|turnstile|captcha/.test(t)) {
                  b.click();
                  return true;
                }
              }
              return false;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(2500)
            return True
    except Exception:
        pass

    # 2) Frame walk — click body / checkbox inside challenge iframes
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if "cloudflare" not in url and "turnstile" not in url and "challenge" not in url:
                continue
            for sel in (
                "input[type=checkbox]",
                "label",
                ".ctp-checkbox-label",
                "#challenge-stage",
                "body",
            ):
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    await loc.click(timeout=2000, force=True)
                    await page.wait_for_timeout(3000)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


async def _challenge_visible(page: Any) -> bool:
    """Is a captcha / interstitial still on screen?"""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText || '').toLowerCase();
                  if (/verify you are human|checking your browser|just a moment|are you a robot|complete the security check|press and hold/.test(t))
                    return true;
                  const f = document.querySelector(
                    'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"],' +
                    'iframe[src*="recaptcha/api2/bframe"], iframe[title*="challenge"],' +
                    '.cf-turnstile, #cf-turnstile'
                  );
                  if (!f) return false;
                  // An invisible/0-size recaptcha bframe is not actually blocking.
                  const r = f.getBoundingClientRect ? f.getBoundingClientRect() : null;
                  if (r && (r.width < 20 || r.height < 20)) return false;
                  return true;
                }"""
            )
        )
    except Exception:
        return False


async def wait_for_challenge_to_clear(page: Any, timeout_s: float | None = None) -> bool:
    """Poll until the challenge disappears.

    Invisible reCAPTCHA and Cloudflare Turnstile usually pass on their own in a
    real headed browser, but only after a few seconds of scoring. Reporting
    captcha_unsolved on the first look throws away most of those wins.
    """
    import asyncio as _asyncio

    if timeout_s is None:
        timeout_s = float(os.environ.get("MVP_CAPTCHA_SETTLE_S", "35"))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not await _challenge_visible(page):
            return True
        await _asyncio.sleep(2.5)
    return not await _challenge_visible(page)


def _oss_enabled() -> bool:
    raw = os.environ.get("MVP_CAPTCHA_OSS", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


async def page_looks_captcha_blocked(page: Any) -> dict[str, Any]:
    """Fast signal for the agent: is a captcha / bot-check blocking the page?"""
    if await _recaptcha_solved(page):
        return {
            "blocked": False,
            "challenge_visible": False,
            "widget_present": True,
            "sitekey": None,
            "type": None,
            "action": "continue",
            "solved": True,
        }
    visible = await _challenge_visible(page)
    info = await detect_sitekey(page)
    widget = False
    try:
        widget = bool(
            await page.evaluate(
                """() => !!document.querySelector(
                  'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"],' +
                  'iframe[src*="challenges.cloudflare.com"], .g-recaptcha, .h-captcha, .cf-turnstile'
                )"""
            )
        )
    except Exception:
        pass
    text_block = False
    try:
        text_block = bool(
            await page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText || '').toLowerCase();
                  return /verify you are human|checking your browser|just a moment|complete the security check|press and hold|are you a robot/.test(t);
                }"""
            )
        )
    except Exception:
        pass
    # A marketing page that merely mentions captchas is not blocking. Require a
    # live challenge, sitekey widget, or interstitial copy.
    blocked = bool(visible or (info and info.get("sitekey")) or text_block or (widget and visible))
    if widget and not blocked:
        # Widget present but not yet challenged — agent should still be ready.
        action = "ready_call_solve_captcha_if_stuck"
    else:
        action = "call_solve_captcha" if blocked else "continue"
    return {
        "blocked": blocked,
        "challenge_visible": visible,
        "widget_present": widget,
        "sitekey": (info or {}).get("sitekey"),
        "type": (info or {}).get("type"),
        "action": action,
    }


async def wait_for_browserbase_solver(page: Any, timeout_s: float | None = None) -> bool:
    """Wait for Browserbase's native solver console events, then settle.

    See https://www.browserbase.com/blog/what-is-a-captcha-solver — sessions emit
    ``browserbase-solving-started`` / ``browserbase-solving-finished``. Racing
    ahead while solving is in flight is a common false failure.
    """
    if timeout_s is None:
        timeout_s = float(os.environ.get("MVP_CAPTCHA_BB_WAIT_S", "45"))
    state = {"started": False, "finished": False}

    def _on_console(msg: Any) -> None:
        try:
            text = msg.text if callable(getattr(msg, "text", None)) else getattr(msg, "text", "")
            if callable(text):
                text = text()
            text = str(text or "")
        except Exception:
            return
        if _BB_SOLVING_STARTED in text:
            state["started"] = True
        if _BB_SOLVING_FINISHED in text:
            state["finished"] = True

    try:
        page.on("console", _on_console)
    except Exception:
        # No console hook — fall through to settle polling only.
        return await wait_for_challenge_to_clear(page, timeout_s=min(timeout_s, 20.0))

    deadline = time.time() + timeout_s
    try:
        # Nudge BB / the widget by focusing the challenge area.
        try:
            await page.evaluate(
                """() => {
                  const f = document.querySelector(
                    'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, .cf-turnstile'
                  );
                  if (f) try { f.scrollIntoView({block:'center'}); } catch (e) {}
                }"""
            )
        except Exception:
            pass

        while time.time() < deadline:
            if state["finished"]:
                await asyncio.sleep(1.5)
                if not await _challenge_visible(page):
                    return True
            if not await _challenge_visible(page) and not state["started"]:
                return True
            await asyncio.sleep(1.0)
        return not await _challenge_visible(page)
    finally:
        try:
            page.remove_listener("console", _on_console)
        except Exception:
            pass


async def _try_oss_image_solver(page: Any) -> dict[str, Any] | None:
    """Optional local reCAPTCHA image-grid solver (captcha-solver-ai)."""
    if not _oss_enabled():
        return None
    try:
        from captcha_solver import CaptchaSolver  # type: ignore
    except Exception as exc:
        return {"ok": False, "method": "oss_image", "detail": f"import_failed:{exc}"}
    try:
        solver = CaptchaSolver()
        solved = await solver.solve_on_page(page, max_rounds=5)
        if solved and not await _challenge_visible(page):
            return {"ok": True, "method": "oss_image", "detail": "captcha_solver_ai"}
        if solved:
            return {"ok": True, "method": "oss_image", "detail": "captcha_solver_ai_claimed"}
        return {"ok": False, "method": "oss_image", "detail": "unsolved"}
    except Exception as exc:
        return {"ok": False, "method": "oss_image", "detail": f"{type(exc).__name__}:{exc}"[:200]}


async def _try_oss_text_ocr(page: Any) -> dict[str, Any] | None:
    """Optional ddddocr pass for simple same-origin text/image captchas."""
    if not _oss_enabled():
        return None
    try:
        import ddddocr  # type: ignore
    except Exception as exc:
        return {"ok": False, "method": "oss_ocr", "detail": f"import_failed:{exc}"}

    try:
        targets = await page.evaluate(
            """() => {
              const out = [];
              for (const img of document.querySelectorAll('img[src], img[data-src]')) {
                const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
                const alt = (img.getAttribute('alt') || img.getAttribute('title') || '').toLowerCase();
                const cls = (img.className || '').toLowerCase();
                const id = (img.id || '').toLowerCase();
                const hint = alt + ' ' + cls + ' ' + id + ' ' + src.toLowerCase();
                if (!/captcha|verify|code|challenge|secure/.test(hint)) continue;
                const r = img.getBoundingClientRect();
                if (r.width < 40 || r.height < 15 || r.width > 600) continue;
                out.push({src, w: r.width, h: r.height});
              }
              return out.slice(0, 3);
            }"""
        )
    except Exception as exc:
        return {"ok": False, "method": "oss_ocr", "detail": f"detect_failed:{exc}"}

    if not targets:
        return None

    ocr = ddddocr.DdddOcr(show_ad=False)
    for item in targets:
        src = item.get("src") or ""
        try:
            if src.startswith("data:"):
                import base64
                import re as _re

                m = _re.search(r"base64,(.+)", src)
                if not m:
                    continue
                raw = base64.b64decode(m.group(1))
            elif src.startswith("http"):
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(src)
                    raw = resp.content
            else:
                # Relative / blob — screenshot the element instead.
                loc = page.locator(f'img[src="{src}"]').first
                raw = await loc.screenshot(type="png")
            text = (ocr.classification(raw) or "").strip()
            if not text or len(text) < 3:
                continue
            # Fill the nearest empty input near a captcha-ish label.
            filled = await page.evaluate(
                """(code) => {
                  const inputs = [...document.querySelectorAll('input[type=text], input:not([type])')];
                  for (const inp of inputs) {
                    const name = ((inp.name||'') + ' ' + (inp.id||'') + ' ' + (inp.placeholder||'')).toLowerCase();
                    if (/captcha|verify|code|challenge/.test(name) || !inp.value) {
                      inp.focus();
                      inp.value = code;
                      inp.dispatchEvent(new Event('input', {bubbles:true}));
                      inp.dispatchEvent(new Event('change', {bubbles:true}));
                      return true;
                    }
                  }
                  return false;
                }""",
                text,
            )
            if filled:
                return {"ok": True, "method": "oss_ocr", "detail": f"ddddocr:{text[:12]}"}
        except Exception:
            continue
    return {"ok": False, "method": "oss_ocr", "detail": "no_text_captcha"}


async def _recaptcha_solved(page: Any) -> bool:
    """True when a response token is present or the checkbox is checked."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const t = document.querySelector(
                    '#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[name="h-captcha-response"], input[name="cf-turnstile-response"]'
                  );
                  if (t && (t.value || '').length > 20) return true;
                  return false;
                }"""
            )
        )
    except Exception:
        return False


async def _click_recaptcha_checkbox(page: Any) -> bool:
    """Click the reCAPTCHA v2 anchor checkbox when present."""
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if "recaptcha/api2/anchor" not in url and "recaptcha/enterprise/anchor" not in url:
                continue
            for sel in ("#recaptcha-anchor", ".recaptcha-checkbox-border", "[role=checkbox]"):
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    await loc.click(timeout=3000, force=True)
                    await page.wait_for_timeout(2000)
                    return True
                except Exception:
                    continue
    except Exception:
        pass
    try:
        frame = page.frame_locator('iframe[src*="recaptcha"][src*="anchor"]').first
        await frame.locator("#recaptcha-anchor").first.click(timeout=4000)
        await page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


async def solve_captcha_on_page(page: Any) -> dict[str, Any]:
    """Full stack: settle → BB wait → click → OSS → solver API → human.

    Returns ``{ok, method, detail}``.
    """
    if await _recaptcha_solved(page):
        return {"ok": True, "method": "already_solved", "detail": "token_present"}

    # Click the checkbox first so Browserbase / Google scoring can engage.
    clicked = await _click_recaptcha_checkbox(page)
    if clicked and await _recaptcha_solved(page):
        return {"ok": True, "method": "checkbox", "detail": "anchor_checked"}

    # Browserbase native solver (console events) — free when session has solveCaptchas.
    if await wait_for_browserbase_solver(page):
        if await _recaptcha_solved(page) or not await _challenge_visible(page):
            # Prefer token proof; accept cleared challenge only if widget no longer blocks.
            if await _recaptcha_solved(page):
                return {"ok": True, "method": "browserbase", "detail": "token_after_bb"}
            if not await _challenge_visible(page) and clicked:
                # Checkbox-only pass (no image grid). Confirm with a short settle.
                await asyncio.sleep(1.5)
                if await _recaptcha_solved(page) or not await _challenge_visible(page):
                    return {
                        "ok": True,
                        "method": "browserbase",
                        "detail": "challenge_cleared",
                    }

    # Cheapest remaining: give an interstitial a few seconds to vanish.
    if await wait_for_challenge_to_clear(page, timeout_s=8.0):
        if await _recaptcha_solved(page):
            return {"ok": True, "method": "self_cleared", "detail": "token_present"}
        blocked_info = await page_looks_captcha_blocked(page)
        if not blocked_info.get("blocked") and not blocked_info.get("widget_present"):
            return {"ok": True, "method": "self_cleared", "detail": "challenge_passed"}

    if await _recaptcha_solved(page):
        return {"ok": True, "method": "self_cleared", "detail": "token_present"}

    # Free next: just click the Cloudflare / Turnstile checkbox when present.
    if await _try_click_cloudflare_checkbox(page):
        if await wait_for_challenge_to_clear(page):
            return {"ok": True, "method": "click", "detail": "cloudflare_checkbox"}

    # Open-source local solvers (optional deps).
    oss_img = await _try_oss_image_solver(page)
    if oss_img and oss_img.get("ok"):
        if await _recaptcha_solved(page) or not await _challenge_visible(page):
            return oss_img
    oss_ocr = await _try_oss_text_ocr(page)
    if oss_ocr and oss_ocr.get("ok"):
        return oss_ocr

    page_url = getattr(page, "url", "") or ""
    info = await detect_sitekey(page)
    if info and info.get("sitekey"):
        token = await asyncio.to_thread(
            solve_sitekey,
            sitekey=info["sitekey"],
            page_url=page_url,
            captcha_type=info.get("type") or "recaptcha",
            action=info.get("action"),
        )
        if token:
            injected = await _inject_token(page, token, info.get("type") or "recaptcha")
            if injected:
                if await wait_for_challenge_to_clear(page, timeout_s=15.0) or await _recaptcha_solved(
                    page
                ):
                    return {"ok": True, "method": "solver_api", "detail": info.get("type")}
                return {"ok": True, "method": "solver_api", "detail": f"{info.get('type')}_injected"}
            return {"ok": False, "method": "solver_api", "detail": "inject_failed", "token": token}

    # Human fallback.
    await asyncio.to_thread(request_human_solve, page_url)
    ok = await asyncio.to_thread(wait_for_human_solve)
    detail = "solved" if ok else "timeout"
    if oss_img and not oss_img.get("ok"):
        detail = f"{detail};oss_image={oss_img.get('detail')}"
    if oss_ocr and not oss_ocr.get("ok"):
        detail = f"{detail};oss_ocr={oss_ocr.get('detail')}"
    return {
        "ok": ok,
        "method": "human",
        "detail": detail,
    }


async def _inject_token(page: Any, token: str, captcha_type: str) -> bool:
    script = """
    (token) => {
      const set = (sel) => {
        const el = document.querySelector(sel);
        if (el) { el.value = token; el.innerHTML = token; el.dispatchEvent(new Event('input', {bubbles:true})); }
      };
      set('textarea[name="g-recaptcha-response"]');
      set('textarea[name="h-captcha-response"]');
      set('input[name="cf-turnstile-response"]');
      set('#g-recaptcha-response');
      try {
        if (window.grecaptcha && window.___grecaptcha_cfg) {
          // best-effort callback fire
          const clients = window.___grecaptcha_cfg.clients || {};
          for (const c of Object.values(clients)) {
            try {
              const cb = c?.O?.O?.callback || c?.callback;
              if (typeof cb === 'function') cb(token);
              if (typeof cb === 'string' && typeof window[cb] === 'function') window[cb](token);
            } catch (e) {}
          }
        }
      } catch (e) {}
      try {
        if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
          /* token already set on input */
        }
      } catch (e) {}
      return true;
    }
    """
    try:
        await page.evaluate(script, token)
        return True
    except Exception:
        return False


def status() -> dict[str, Any]:
    oss: dict[str, bool] = {"enabled": _oss_enabled()}
    try:
        import captcha_solver  # noqa: F401

        oss["captcha_solver_ai"] = True
    except Exception:
        oss["captcha_solver_ai"] = False
    try:
        import ddddocr  # noqa: F401

        oss["ddddocr"] = True
    except Exception:
        oss["ddddocr"] = False
    return {
        "captcha_solver_enabled": captcha_solver_enabled(),
        "api": _api_name(),
        "api_key_set": bool(_api_key()),
        "oss": oss,
    }
