"""CAPTCHA solving stack for product signup.

Layers (cheapest first):

1. Browserbase native — session flags ``solveCaptchas`` / advanced stealth
   (wired in ``capability.browserbase_client``).
2. Solver API — CapSolver or 2Captcha for sitekey-based reCAPTCHA / hCaptcha /
   Turnstile. Returns a token the agent injects into the page.
3. Human push — ntfy + desktop notification; wait for ``secrets/captcha_done.txt``.

Env:
  MVP_CAPTCHA_SOLVER=1          # enable browser-use captcha_solver flag
  MVP_CAPTCHA_API=capsolver|2captcha
  MVP_CAPTCHA_API_KEY=...
  MVP_CAPTCHA_HUMAN_TIMEOUT_S=300
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from mvp.notify import push

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
DONE_FILE = SECRETS / "captcha_done.txt"


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
    """Extra kwargs for Browserbase session create when captcha solving is on."""
    if not captcha_solver_enabled():
        return {}
    # Browserbase API field names have evolved; pass both common shapes.
    return {
        "solve_captchas": True,
        "advanced_stealth": True,
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


async def solve_captcha_on_page(page: Any) -> dict[str, Any]:
    """Full stack: detect sitekey → solver API → inject token → else human.

    Returns ``{ok, method, detail}``.
    """
    page_url = getattr(page, "url", "") or ""
    info = await detect_sitekey(page)
    if info and info.get("sitekey"):
        token = await __import__("asyncio").to_thread(
            solve_sitekey,
            sitekey=info["sitekey"],
            page_url=page_url,
            captcha_type=info.get("type") or "recaptcha",
            action=info.get("action"),
        )
        if token:
            injected = await _inject_token(page, token, info.get("type") or "recaptcha")
            if injected:
                return {"ok": True, "method": "solver_api", "detail": info.get("type")}
            return {"ok": False, "method": "solver_api", "detail": "inject_failed", "token": token}

    # Human fallback.
    await __import__("asyncio").to_thread(request_human_solve, page_url)
    ok = await __import__("asyncio").to_thread(wait_for_human_solve)
    return {
        "ok": ok,
        "method": "human",
        "detail": "solved" if ok else "timeout",
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
    return {
        "captcha_solver_enabled": captcha_solver_enabled(),
        "api": _api_name(),
        "api_key_set": bool(_api_key()),
    }
