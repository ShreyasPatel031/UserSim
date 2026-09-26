"""CAPTCHA solving stack for product signup.

Layers (cheapest first):

1. Settle / click — wait for invisible scoring, click Cloudflare checkbox.
2. Browserbase native — listen for ``browserbase-solving-started/finished``
   console events (solveCaptchas is on by default for BB sessions).
3. Open-source local solvers — optional ``captcha-solver-ai`` (reCAPTCHA image
   grids), reCAPTCHA audio + free STT (speech_recognition / vosk), and
   ``ddddocr`` (simple distorted-text captchas).
4. Solver API — CapSolver, 2Captcha, or Anti-Captcha for sitekey-based
   reCAPTCHA (including Enterprise), hCaptcha, Turnstile, and Arkose.
   Returns a token the agent injects into the page.
5. Human push — ntfy + desktop notification; wait for ``secrets/captcha_done.txt``.

Env:
  MVP_CAPTCHA_SOLVER=1          # enable browser-use captcha_solver flag
  MVP_CAPTCHA_API=capsolver|2captcha|anti-captcha
  MVP_CAPTCHA_API_KEY=...
  MVP_CAPTCHA_OSS=1             # try local OSS solvers (default on)
  MVP_CAPTCHA_AUDIO=1           # try reCAPTCHA audio + free STT (default on)
  MVP_CAPTCHA_BB_WAIT_S=45      # max wait for Browserbase native solver
  MVP_CAPTCHA_HUMAN_TIMEOUT_S=300
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


# Known product sitekeys when the DOM hides them (invisible widgets).
# Bland's React Turnstile does not put the key on .cf-turnstile; the widget
# calls onSuccess(token) instead of a hidden g-recaptcha field.
_KNOWN_SITEKEYS: dict[str, dict[str, str]] = {
    "supabase.com": {
        "type": "hcaptcha",
        "sitekey": "4ca1fdb9-c9c9-4495-ba50-c85fc0e7ec1f",
    },
    "bland.ai": {
        "type": "turnstile",
        "sitekey": "0x4AAAAAAA-wFNpU7mZhDp4F",
        "callback": "onSuccess",
        "token_field": 'input[name="cf-turnstile-response"]',
    },
}

_TURNSTILE_KEY_RE = re.compile(r"\b(0x4[A-Za-z0-9_-]{10,})\b")
_ARKOSE_URL_RE = re.compile(
    r"https?://[^\"'\s>]*arkoselabs\.com/(?:v2|fc)/([A-Za-z0-9-]{8,})/",
    re.I,
)
_WIDGET_SELECTOR = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
    "iframe[src*='challenges.cloudflare.com'], iframe[src*='newassets.hcaptcha'], "
    "iframe[src*='arkoselabs'], iframe[src*='funcaptcha'], "
    ".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], "
    "[data-captcha-sitekey], [data-captcha-provider], [data-pkey], "
    ".funcaptcha, #funcaptcha, input[name='captcha']"
)

_CAPSOLVER_TYPES = {
    "recaptcha": "ReCaptchaV2TaskProxyLess",
    "recaptcha_v2": "ReCaptchaV2TaskProxyLess",
    "recaptcha_v3": "ReCaptchaV3TaskProxyLess",
    "recaptcha_enterprise": "ReCaptchaV2EnterpriseTaskProxyLess",
    "recaptcha_v2_enterprise": "ReCaptchaV2EnterpriseTaskProxyLess",
    "recaptcha_v3_enterprise": "ReCaptchaV3EnterpriseTaskProxyLess",
    "hcaptcha": "HCaptchaTaskProxyLess",
    "turnstile": "AntiTurnstileTaskProxyLess",
    "cloudflare_challenge": "AntiCloudflareTask",
    "geetest": "GeeTestTaskProxyLess",
    "geetest_v4": "GeeTestTaskProxyLess",
    "image_text": "ImageToTextTask",
    "recaptcha_classification": "ReCaptchaV2Classification",
    "arkose": "FunCaptchaTaskProxyLess",
    "funcaptcha": "FunCaptchaTaskProxyLess",
    "arkoselabs": "FunCaptchaTaskProxyLess",
}

_ANTICAPTCHA_TYPES = {
    "recaptcha": "RecaptchaV2TaskProxyless",
    "recaptcha_v2": "RecaptchaV2TaskProxyless",
    "recaptcha_v3": "RecaptchaV3TaskProxyless",
    "recaptcha_enterprise": "RecaptchaV2EnterpriseTaskProxyless",
    "recaptcha_v2_enterprise": "RecaptchaV2EnterpriseTaskProxyless",
    "recaptcha_v3_enterprise": "RecaptchaV3EnterpriseTaskProxyless",
    "hcaptcha": "HCaptchaTaskProxyless",
    "turnstile": "TurnstileTaskProxyless",
    "arkose": "FunCaptchaTaskProxyless",
    "funcaptcha": "FunCaptchaTaskProxyless",
    "arkoselabs": "FunCaptchaTaskProxyless",
}


def _norm_captcha_type(captcha_type: str | None) -> str:
    return (captcha_type or "recaptcha").strip().lower().replace("-", "_").replace(" ", "_")


def capsolver_task_type(captcha_type: str | None) -> str | None:
    return _CAPSOLVER_TYPES.get(_norm_captcha_type(captcha_type))


def anticaptcha_task_type(captcha_type: str | None) -> str | None:
    return _ANTICAPTCHA_TYPES.get(_norm_captcha_type(captcha_type))


def twocaptcha_params(
    captcha_type: str | None,
    *,
    sitekey: str,
    page_url: str,
    action: str | None,
) -> dict[str, Any] | None:
    """2Captcha in.php fields. None when this provider has no mapping."""
    ct = _norm_captcha_type(captcha_type)
    if ct == "hcaptcha":
        return {"method": "hcaptcha", "sitekey": sitekey, "pageurl": page_url, "json": 1}
    if ct == "turnstile":
        return {"method": "turnstile", "sitekey": sitekey, "pageurl": page_url, "json": 1}
    if ct in {"arkose", "funcaptcha", "arkoselabs"}:
        return {"method": "funcaptcha", "publickey": sitekey, "pageurl": page_url, "json": 1}
    if ct in {"recaptcha", "recaptcha_v2", "recaptcha_v3", "recaptcha_enterprise", "recaptcha_v2_enterprise", "recaptcha_v3_enterprise"}:
        params: dict[str, Any] = {
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        }
        if "v3" in ct:
            params["version"] = "v3"
            if action:
                params["action"] = action
        if "enterprise" in ct:
            params["enterprise"] = 1
        return params
    return None


def _solver_task(
    task_type: str,
    *,
    sitekey: str,
    page_url: str,
    action: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task: dict[str, Any] = {"type": task_type, "websiteURL": page_url}
    fields = extra or {}
    if "FunCaptcha" in task_type:
        # CapSolver and Anti-Captcha both want the Arkose public key here.
        if sitekey:
            task["websitePublicKey"] = sitekey
    elif "GeeTest" in task_type:
        if fields.get("gt"):
            task["gt"] = fields["gt"]
        if fields.get("challenge"):
            task["challenge"] = fields["challenge"]
        captcha_id = fields.get("captchaId") or fields.get("captcha_id") or ""
        if captcha_id:
            task["captchaId"] = captcha_id
        elif sitekey and not fields.get("gt"):
            task["captchaId"] = sitekey
    elif sitekey and "Image" not in task_type and "Classification" not in task_type:
        task["websiteKey"] = sitekey
    if action and "V3" in task_type:
        task["pageAction"] = action
    for key, value in fields.items():
        if value is None or key in {"type", "clientKey", "captcha_id"}:
            continue
        if key not in task:
            task[key] = value
    return task


def _host_matches(page_url: str, needle: str) -> bool:
    host = (urlparse(page_url or "").hostname or "").lower()
    return host == needle or host.endswith("." + needle)


class _TagGrabber(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag.lower(), {(k or "").lower(): (v or "") for k, v in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _info_from_provider(provider: str, sitekey: str, attrs: dict[str, str]) -> dict[str, Any]:
    action = (attrs.get("data-action") or attrs.get("data-captcha-action") or "").strip() or None
    p = provider.replace("-", "_")
    if "enterprise" in p and "v3" in p:
        ctype = "recaptcha_v3_enterprise"
    elif "enterprise" in p:
        ctype = "recaptcha_enterprise"
    elif "v3" in p and "recaptcha" in p:
        ctype = "recaptcha_v3"
    elif "hcaptcha" in p:
        ctype = "hcaptcha"
    elif "arkose" in p or "funcaptcha" in p:
        ctype = "arkose"
    elif "turnstile" in p:
        ctype = "turnstile"
    elif "recaptcha" in p:
        ctype = "recaptcha"
    else:
        ctype = p or "recaptcha"
    info: dict[str, Any] = {
        "type": ctype,
        "sitekey": sitekey or None,
        "action": action,
        "token_field": None,
    }
    if ctype.startswith("recaptcha"):
        info["token_field"] = 'input[name="captcha"]'
    elif ctype == "turnstile":
        info["token_field"] = 'input[name="cf-turnstile-response"]'
        info["callback"] = attrs.get("data-callback") or "onSuccess"
    return info


def _known_sitekey(page_url: str) -> dict[str, Any] | None:
    for host, known in _KNOWN_SITEKEYS.items():
        if _host_matches(page_url, host):
            return dict(known)
    return None


def detect_captcha_in_html(html: str, page_url: str = "") -> dict[str, Any] | None:
    """Find a captcha type + sitekey in saved (or live) page HTML.

    Covers the widgets ``detect_sitekey`` used to miss: Auth0 reCAPTCHA
    Enterprise (``data-captcha-provider`` / ``data-captcha-sitekey``, token in
    ``input[name=captcha]``), Arkose/FunCaptcha (``data-pkey``), and Cloudflare
    Turnstile keys that only appear inside a React bundle (``0x4...``).
    """
    raw = html or ""
    parser = _TagGrabber()
    try:
        parser.feed(raw)
    except Exception:
        pass
    tags = parser.tags

    for _tag, attrs in tags:
        provider = (attrs.get("data-captcha-provider") or "").strip().lower()
        if not provider:
            continue
        sitekey = (attrs.get("data-captcha-sitekey") or attrs.get("data-sitekey") or "").strip()
        info = _info_from_provider(provider, sitekey, attrs)
        if info.get("sitekey"):
            return info

    arkose_key = ""
    for _tag, attrs in tags:
        pkey = (attrs.get("data-pkey") or "").strip()
        blob = f"{attrs.get('class', '')} {attrs.get('id', '')}"
        src = attrs.get("src") or ""
        if pkey and re.search(r"arkose|funcaptcha|pkey", blob + " " + src, re.I):
            arkose_key = pkey
            break
        if pkey and (re.search(r"arkose|funcaptcha", blob, re.I) or "arkoselabs" in src.lower()):
            arkose_key = pkey
            break
        if re.search(r"arkoselabs|funcaptcha", src, re.I):
            found = _ARKOSE_URL_RE.search(src)
            if found:
                arkose_key = found.group(1)
                break
        if pkey and re.search(r"arkose|funcaptcha", blob, re.I):
            arkose_key = pkey
            break
    if not arkose_key:
        # A bare data-pkey is Arkose's public key (FunCaptcha).
        for _tag, attrs in tags:
            if attrs.get("data-pkey"):
                arkose_key = attrs["data-pkey"].strip()
                break
    if not arkose_key:
        found = _ARKOSE_URL_RE.search(raw)
        if found:
            arkose_key = found.group(1)
    if arkose_key:
        return {"type": "arkose", "sitekey": arkose_key, "action": None, "token_field": None}

    turnstile_key = ""
    callback = None
    for _tag, attrs in tags:
        blob = f"{attrs.get('class', '')} {attrs.get('id', '')}"
        src = attrs.get("src") or ""
        key = (attrs.get("data-sitekey") or attrs.get("data-captcha-sitekey") or "").strip()
        looks_turnstile = (
            "cf-turnstile" in blob
            or bool(re.search(r"turnstile|challenges\.cloudflare", src, re.I))
            or key.startswith("0x4")
        )
        if not looks_turnstile:
            continue
        callback = attrs.get("data-callback") or callback
        if key:
            turnstile_key = key
            break
    if not turnstile_key:
        found = _TURNSTILE_KEY_RE.search(raw)
        if found:
            turnstile_key = found.group(1)
    if turnstile_key:
        return {
            "type": "turnstile",
            "sitekey": turnstile_key,
            "action": None,
            "token_field": 'input[name="cf-turnstile-response"]',
            "callback": callback or "onSuccess",
        }

    for _tag, attrs in tags:
        blob = f"{attrs.get('class', '')} {attrs.get('id', '')}"
        src = (attrs.get("src") or "")
        key = (attrs.get("data-sitekey") or "").strip()
        if re.search(r"h-?captcha", blob, re.I) or "hcaptcha" in src.lower():
            if not key:
                m = re.search(r"sitekey=([0-9a-f-]{36})", src, re.I)
                key = m.group(1) if m else ""
            if key:
                return {"type": "hcaptcha", "sitekey": key, "action": attrs.get("data-action") or None, "token_field": None}
        if "g-recaptcha" in blob or "recaptcha" in src.lower():
            enterprise = "enterprise" in src.lower() or "enterprise" in blob.lower()
            v3 = "render=" in src.lower() or (attrs.get("data-size") or "").lower() == "invisible" and bool(attrs.get("data-action"))
            if not key:
                m = re.search(r"[?&](?:render|sitekey)=([A-Za-z0-9_-]{20,})", src)
                key = m.group(1) if m else ""
            if key:
                if enterprise and v3:
                    ctype = "recaptcha_v3_enterprise"
                elif enterprise:
                    ctype = "recaptcha_enterprise"
                elif v3 and "render=" in src.lower():
                    ctype = "recaptcha_v3"
                else:
                    ctype = "recaptcha"
                return {
                    "type": ctype,
                    "sitekey": key,
                    "action": attrs.get("data-action") or None,
                    "token_field": 'textarea[name="g-recaptcha-response"]',
                }
        if key and not key.startswith("0x4"):
            ctype = "hcaptcha" if re.fullmatch(r"[0-9a-f-]{36}", key, re.I) else "recaptcha"
            return {"type": ctype, "sitekey": key, "action": attrs.get("data-action") or None, "token_field": None}

    known = _known_sitekey(page_url)
    if known and known.get("sitekey"):
        known.setdefault("action", None)
        return known
    return None


async def detect_sitekey(page: Any) -> dict[str, Any] | None:
    """Scrape a visible captcha sitekey + type from the current page DOM."""
    html = ""
    url = ""
    try:
        content = getattr(page, "content", None)
        if callable(content):
            html = await content()
    except Exception:
        html = ""
    try:
        url = getattr(page, "url", "") or ""
    except Exception:
        url = ""
    if html:
        parsed = detect_captcha_in_html(str(html), page_url=str(url or ""))
        if parsed and parsed.get("sitekey"):
            return parsed
    script = """
    (() => {
      const out = {type: null, sitekey: null, action: null, token_field: null, callback: null};
      const ent = document.querySelector('[data-captcha-provider], [data-captcha-sitekey]');
      if (ent) {
        const provider = (ent.getAttribute('data-captcha-provider') || '').toLowerCase();
        out.sitekey = ent.getAttribute('data-captcha-sitekey') || ent.getAttribute('data-sitekey');
        if (provider.includes('enterprise') && provider.includes('v3')) out.type = 'recaptcha_v3_enterprise';
        else if (provider.includes('enterprise')) out.type = 'recaptcha_enterprise';
        else if (provider.includes('hcaptcha')) out.type = 'hcaptcha';
        else if (provider.includes('arkose') || provider.includes('funcaptcha')) out.type = 'arkose';
        else if (provider.includes('turnstile')) out.type = 'turnstile';
        else if (provider.includes('v3')) out.type = 'recaptcha_v3';
        else out.type = 'recaptcha';
        out.action = ent.getAttribute('data-action') || ent.getAttribute('data-captcha-action');
        if ((out.type || '').indexOf('recaptcha') === 0) out.token_field = 'input[name="captcha"]';
      }
      if (!out.sitekey) {
        const ark = document.querySelector('[data-pkey]');
        if (ark) {
          out.sitekey = ark.getAttribute('data-pkey');
          out.type = 'arkose';
        }
      }
      const g = document.querySelector('[data-sitekey], .g-recaptcha, .h-captcha, .cf-turnstile, [data-captcha-sitekey]');
      if (g && !out.sitekey) {
        out.sitekey = g.getAttribute('data-sitekey') || g.dataset.sitekey || null;
        const cls = (g.className || '') + ' ' + (g.id || '');
        if (/turnstile|cf-/i.test(cls) || g.tagName === 'DIV' && g.classList.contains('cf-turnstile'))
          out.type = 'turnstile';
        else if (/h-?captcha/i.test(cls)) out.type = 'hcaptcha';
        else out.type = 'recaptcha';
        out.action = g.getAttribute('data-action') || null;
      }
      // Invisible hCaptcha / Turnstile often only expose the key on iframe src.
      if (!out.sitekey) {
        for (const f of document.querySelectorAll('iframe[src]')) {
          const src = f.src || '';
          let m = src.match(/[?&#]sitekey=([^&?#]+)/i);
          if (!m) m = src.match(/sitekey=([0-9a-f-]{36})/i);
          if (m) {
            out.sitekey = decodeURIComponent(m[1]);
            if (/hcaptcha/i.test(src)) out.type = 'hcaptcha';
            else if (/turnstile|challenges\\.cloudflare/i.test(src)) out.type = 'turnstile';
            else out.type = 'recaptcha';
            break;
          }
        }
      }
      if (!out.sitekey) {
        const scripts = [...document.scripts].map(s => s.src || '');
        for (const src of scripts) {
          const m = src.match(/[?&](?:render|sitekey)=([A-Za-z0-9_-]{20,})/);
          if (m) { out.sitekey = m[1]; out.type = /hcaptcha/i.test(src) ? 'hcaptcha'
            : /turnstile|challenges\\.cloudflare/i.test(src) ? 'turnstile' : 'recaptcha'; break; }
        }
      }
      if (!out.sitekey) {
        const html = (document.documentElement && document.documentElement.innerHTML) || '';
        const m = html.match(/\\b(0x4[A-Za-z0-9_-]{10,})\\b/);
        if (m) {
          out.sitekey = m[1];
          out.type = 'turnstile';
          out.callback = 'onSuccess';
          out.token_field = 'input[name="cf-turnstile-response"]';
        }
      }
      if (!out.sitekey && window.grecaptcha) out.type = out.type || 'recaptcha';
      if (!out.sitekey && window.hcaptcha) out.type = out.type || 'hcaptcha';
      if (!out.sitekey && window.turnstile) out.type = out.type || 'turnstile';
      return out.sitekey ? out : (out.type ? out : null);
    })()
    """
    try:
        info = await page.evaluate(script)
    except Exception:
        info = None
    if info and info.get("sitekey"):
        return info
    try:
        url = (getattr(page, "url", "") or "").lower()
    except Exception:
        url = ""
    known = _known_sitekey(str(url or ""))
    if known and known.get("sitekey"):
        if info and info.get("type") and not known.get("type"):
            known["type"] = info["type"]
        return known
    return info


def solve_sitekey(
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str = "recaptcha",
    action: str | None = None,
    timeout_s: float = 180.0,
    blocking: bool = False,
    extra: dict[str, Any] | None = None,
    task_type_override: str | None = None,
) -> str | None:
    """Return a solver token for the given sitekey, or None on failure.

    CapSolver is research-only: ``blocking`` must be true (the page detector
    already confirmed a captcha is in the way) and the spend gate must allow
    the host. Other providers still require ``MVP_CAPTCHA_API_KEY``.
    """
    api = _api_name()
    if api in {"capsolver", "cap-solver"}:
        return _capsolver_solve(
            "",
            sitekey=sitekey,
            page_url=page_url,
            captcha_type=captcha_type,
            action=action,
            timeout_s=timeout_s,
            blocking=blocking,
            extra=extra,
            task_type_override=task_type_override,
        )
    key = _api_key()
    if not key:
        return None
    if api in {"2captcha", "twocaptcha", "2-captcha"}:
        return _twocaptcha_solve(
            key,
            sitekey=sitekey,
            page_url=page_url,
            captcha_type=captcha_type,
            action=action,
            timeout_s=timeout_s,
        )
    if api in {"anti-captcha", "anticaptcha", "anti_captcha"}:
        return _anticaptcha_solve(
            key,
            sitekey=sitekey,
            page_url=page_url,
            captcha_type=captcha_type,
            action=action,
            timeout_s=timeout_s,
        )
    return None


def _solution_value(sol: Any) -> str | None:
    """Pull a token or recognition result out of a CapSolver solution object."""
    if not isinstance(sol, dict):
        return None
    gee_keys = ("lot_number", "pass_token", "gen_time", "captcha_output", "captcha_id")
    if any(sol.get(key) for key in gee_keys):
        import json as _json

        payload = {key: sol.get(key) for key in gee_keys if sol.get(key)}
        if sol.get("token"):
            payload["token"] = sol.get("token")
        return _json.dumps(payload)
    for key in ("gRecaptchaResponse", "token", "response", "text", "captcha_voucher"):
        value = sol.get(key)
        if value:
            return str(value)
    if any(sol.get(key) not in (None, "", [], {}) for key in ("objects", "answers", "type", "box")):
        import json as _json

        return _json.dumps({k: sol.get(k) for k in ("objects", "answers", "type", "box", "text") if k in sol})
    return None


def _capsolver_solve(
    key: str,
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str,
    action: str | None,
    timeout_s: float,
    blocking: bool = False,
    extra: dict[str, Any] | None = None,
    task_type_override: str | None = None,
) -> str | None:
    """One createTask, then poll that task. No retry loop.

    ``key`` is ignored. The research token is read from ``CAPSOLVER_API_KEY``
    inside the spend gate, and only after a blocking captcha and a priced task
    type have both been confirmed. Image recognition tasks often return
    ``status=ready`` on the create response and are not polled.
    """
    del key  # vault / caller keys must not reach CapSolver
    from mvp import captcha_spend as spend

    task_type = task_type_override or capsolver_task_type(captcha_type) or ""
    site = spend.current_site() or ""
    if not blocking:
        spend.record_skip(
            site=site,
            captcha_type=captcha_type,
            task_type=task_type,
            reason="not_blocking",
        )
        return None
    reason = spend.refusal_reason(task_type, site=site or None)
    if reason:
        spend.record_skip(
            site=site,
            captcha_type=captcha_type,
            task_type=task_type,
            reason=reason,
        )
        return None
    token = spend.capsolver_key()
    if not token:
        spend.record_skip(
            site=site,
            captcha_type=captcha_type,
            task_type=task_type,
            reason="no_key",
        )
        return None

    balance_before = spend.get_balance(token)
    floor = spend.claim_spend(task_type, balance_before)
    if floor:
        spend.record_skip(
            site=site,
            captcha_type=captcha_type,
            task_type=task_type,
            reason=floor,
        )
        return None
    task = _solver_task(
        task_type, sitekey=sitekey, page_url=page_url, action=action, extra=extra
    )
    task_id = None
    solved = False
    solution: str | None = None
    note = ""
    try:
        try:
            create = httpx.post(
                "https://api.capsolver.com/createTask",
                json={"clientKey": token, "task": task},
                timeout=30.0,
            ).json()
        except Exception:
            spend.record_task(
                site=site,
                captcha_type=captcha_type,
                task_type=task_type,
                task_id=None,
                solved=False,
                cost=0.0,
                balance_before=balance_before,
                balance_after=balance_before,
                note="create_error",
            )
            return None
        if not isinstance(create, dict):
            create = {}
        if create.get("errorId") and not create.get("taskId") and not create.get("solution"):
            balance_after = spend.get_balance(token)
            err = str(create.get("errorCode") or create.get("errorDescription") or "create_rejected")
            spend.record_task(
                site=site,
                captcha_type=captcha_type,
                task_type=task_type,
                task_id=None,
                solved=False,
                cost=0.0,
                balance_before=balance_before,
                balance_after=balance_after,
                note=err[:160],
            )
            return None
        immediate = _solution_value(create.get("solution"))
        if immediate and (create.get("status") in {None, "ready"} or create.get("solution")):
            solution = immediate
            solved = True
            task_id = create.get("taskId") or "sync"
            note = "sync_ready"
        else:
            task_id = create.get("taskId")
            if not task_id:
                balance_after = spend.get_balance(token)
                spend.record_task(
                    site=site,
                    captcha_type=captcha_type,
                    task_type=task_type,
                    task_id=None,
                    solved=False,
                    cost=0.0,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    note="no_task_id",
                )
                return None

            deadline = time.time() + timeout_s
            while time.time() < deadline:
                try:
                    result = httpx.post(
                        "https://api.capsolver.com/getTaskResult",
                        json={"clientKey": token, "taskId": task_id},
                        timeout=30.0,
                    ).json()
                except Exception:
                    time.sleep(3)
                    continue
                if not isinstance(result, dict):
                    time.sleep(3)
                    continue
                if result.get("status") == "ready":
                    solution = _solution_value(result.get("solution") or {})
                    solved = bool(solution)
                    note = "" if solved else "ready_without_token"
                    break
                if result.get("status") == "failed" or result.get("errorId"):
                    note = str(result.get("errorCode") or "task_failed")[:160]
                    break
                time.sleep(3)
            else:
                note = "poll_timeout"

        balance_after = spend.get_balance(token)
        list_price = spend.task_price(task_type) or spend.PRICED_TASKS_USD.get(task_type, 0.0)
        if balance_before is not None and balance_after is not None:
            delta = round(max(0.0, float(balance_before) - float(balance_after)), 6)
        else:
            delta = None
        # Book the published price when the balance call hasn't moved yet so a
        # burst of solves cannot walk past the cap. A rejected task with no
        # debit stays at zero (recorded on the early-return paths above).
        # Book the published price on a successful task. A shared balance
        # delta across concurrent solves is not this task's cost. Unsolved
        # tasks that were still charged book at most the list price.
        if solved:
            cost = list_price
        elif delta is None or delta == 0:
            cost = 0.0
        else:
            cost = min(list_price, delta)
        spend.record_task(
            site=site,
            captcha_type=captcha_type,
            task_type=task_type,
            task_id=None if task_id is None else str(task_id),
            solved=solved,
            cost=cost,
            balance_before=balance_before,
            balance_after=balance_after,
            note=note,
        )
        return solution if solved else None
    finally:
        spend.release_spend(task_type)


def _twocaptcha_solve(
    key: str,
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str,
    action: str | None,
    timeout_s: float,
) -> str | None:
    params = twocaptcha_params(
        captcha_type, sitekey=sitekey, page_url=page_url, action=action
    )
    if not params:
        return None
    try:
        create = httpx.post(
            "https://2captcha.com/in.php",
            data={"key": key, **params},
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


def _anticaptcha_solve(
    key: str,
    *,
    sitekey: str,
    page_url: str,
    captcha_type: str,
    action: str | None,
    timeout_s: float,
) -> str | None:
    """Anti-Captcha createTask/getTaskResult. Not the 2Captcha in.php API."""
    task_type = anticaptcha_task_type(captcha_type)
    if not task_type:
        return None
    task = _solver_task(task_type, sitekey=sitekey, page_url=page_url, action=action)
    try:
        create = httpx.post(
            "https://api.anti-captcha.com/createTask",
            json={"clientKey": key, "task": task},
            timeout=30.0,
        ).json()
    except Exception:
        return None
    if create.get("errorId"):
        return None
    task_id = create.get("taskId")
    if not task_id:
        return None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        try:
            result = httpx.post(
                "https://api.anti-captcha.com/getTaskResult",
                json={"clientKey": key, "taskId": task_id},
                timeout=30.0,
            ).json()
        except Exception:
            continue
        if result.get("errorId"):
            return None
        if result.get("status") == "ready":
            sol = result.get("solution") or {}
            return sol.get("gRecaptchaResponse") or sol.get("token") or sol.get("response")
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
                  'iframe[src*="challenges.cloudflare.com"], iframe[src*="newassets.hcaptcha"],' +
                  'iframe[src*="arkoselabs"], iframe[src*="funcaptcha"],' +
                  '.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey],' +
                  '[data-captcha-sitekey], [data-captcha-provider], [data-pkey], .funcaptcha'
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
                  return /verify you are human|checking your browser|just a moment|complete the security check|press and hold|are you a robot|invalid or missing captcha|missing captcha token|captcha token|failed to sign up:.*captcha|hcaptcha|complete the captcha|trouble verifying recaptcha|recaptcha verification|slide right to secure/.test(t);
                }"""
            )
        )
    except Exception:
        pass
    # Signup submit stuck disabled often means an invisible Turnstile/hCaptcha
    # scored the session as bot — treat as blocked so solve_captcha runs.
    submit_disabled = False
    try:
        submit_disabled = bool(
            await page.evaluate(
                """() => {
                  const btns = [...document.querySelectorAll('button[type=submit], button')];
                  for (const b of btns) {
                    const label = ((b.innerText || b.textContent || b.getAttribute('aria-label') || '') + '').toLowerCase().trim();
                    const isSubmit = (b.getAttribute('type') || '').toLowerCase() === 'submit';
                    // Any disabled primary submit counts — label optional for type=submit.
                    const labelMatch = /sign\\s*up|create\\s*account|register|continue|join/.test(label);
                    if (!isSubmit && !labelMatch) continue;
                    if (isSubmit || labelMatch) {
                      if (b.disabled || b.getAttribute('aria-disabled') === 'true') return true;
                      const style = window.getComputedStyle(b);
                      if (style && (style.pointerEvents === 'none' || Number(style.opacity) < 0.4)) return true;
                    }
                  }
                  return false;
                }"""
            )
        )
    except Exception:
        pass
    # A marketing page that merely mentions captchas is not blocking. Require a
    # live challenge, sitekey widget, interstitial copy, or disabled signup CTA
    # while a widget/sitekey is present.
    # Disabled signup CTA alone is enough — invisible Turnstile/hCaptcha often
    # leave no visible challenge but keep the button dead.
    # Supabase also surfaces "Invalid or missing captcha token" in-page.
    blocked = bool(
        visible
        or (info and info.get("sitekey"))
        or text_block
        or (widget and visible)
        or submit_disabled
    )
    if widget and not blocked:
        action = "ready_call_solve_captcha_if_stuck"
    else:
        action = "call_solve_captcha" if blocked else "continue"
    return {
        "blocked": blocked,
        "challenge_visible": visible,
        "widget_present": widget,
        "submit_disabled": submit_disabled,
        "text_block": text_block,
        "sitekey": (info or {}).get("sitekey"),
        "type": (info or {}).get("type"),
        "action": action,
    }


async def _captcha_widget_present(page: Any) -> bool:
    """True when a captcha iframe/widget is in the DOM (incl. invisible)."""
    try:
        return bool(
            await page.evaluate(
                """() => !!document.querySelector(
                  'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"],' +
                  'iframe[src*="challenges.cloudflare.com"], iframe[src*="newassets.hcaptcha"],' +
                  'iframe[src*="arkoselabs"], iframe[src*="funcaptcha"],' +
                  '.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey],' +
                  '[data-captcha-sitekey], [data-captcha-provider], [data-pkey], .funcaptcha'
                )"""
            )
        )
    except Exception:
        return False


async def wait_for_browserbase_solver(page: Any, timeout_s: float | None = None) -> bool:
    """Wait for Browserbase's native solver console events, then settle.

    See https://www.browserbase.com/blog/what-is-a-captcha-solver — sessions emit
    ``browserbase-solving-started`` / ``browserbase-solving-finished``. Racing
    ahead while solving is in flight is a common false failure.

    Invisible hCaptcha/Turnstile often have **no visible challenge UI**. Do not
    treat "challenge not visible" as success while a widget/sitekey is present
    and no response token has been written yet — that was aborting the BB wait
    on Supabase in ~1s.
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

    widget = await _captcha_widget_present(page)
    try:
        page.on("console", _on_console)
    except Exception:
        # No console hook — fall through to settle polling only.
        if widget:
            # Still wait for a token when the widget is invisible.
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                if await _recaptcha_solved(page):
                    return True
                await asyncio.sleep(1.0)
            return await _recaptcha_solved(page)
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
            if await _recaptcha_solved(page):
                return True
            if state["finished"]:
                await asyncio.sleep(1.5)
                if await _recaptcha_solved(page):
                    return True
                # Finished with no token is only OK when no widget remains.
                if not await _captcha_widget_present(page) and not await _challenge_visible(page):
                    return True
            # Early exit only when there was never a widget and nothing visible.
            if (
                not widget
                and not state["started"]
                and not await _challenge_visible(page)
                and not await _captcha_widget_present(page)
            ):
                return True
            await asyncio.sleep(1.0)
        return await _recaptcha_solved(page) or (
            not await _captcha_widget_present(page) and not await _challenge_visible(page)
        )
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


def _audio_enabled() -> bool:
    raw = os.environ.get("MVP_CAPTCHA_AUDIO", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _transcribe_recaptcha_audio(audio_bytes: bytes) -> str | None:
    """Free/local STT for reCAPTCHA audio challenge clips.

    Prefer ``speech_recognition`` + Google Web Speech (no API key) or Sphinx;
    fall back to ``vosk`` if installed. Returns digits/words or None.
    """
    import io
    import re as _re
    import tempfile

    # Normalize to WAV when possible (reCAPTCHA serves mp3).
    wav_bytes = audio_bytes
    try:
        from pydub import AudioSegment  # type: ignore

        seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        wav_bytes = buf.getvalue()
    except Exception:
        pass

    # 1) speech_recognition (Google free web API, then Sphinx)
    try:
        import speech_recognition as sr  # type: ignore

        recog = sr.Recognizer()
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            tmp.write(wav_bytes)
            tmp.flush()
            with sr.AudioFile(tmp.name) as source:
                audio = recog.record(source)
        for method in ("recognize_google", "recognize_sphinx"):
            fn = getattr(recog, method, None)
            if not fn:
                continue
            try:
                text = (fn(audio) or "").strip().lower()
            except Exception:
                continue
            if text:
                digits = "".join(_re.findall(r"[0-9]", text))
                return digits or _re.sub(r"[^a-z0-9 ]", "", text).strip() or None
    except Exception:
        pass

    # 2) vosk offline
    try:
        import json as _json
        import wave
        from pathlib import Path as _Path

        import vosk  # type: ignore

        model_path = os.environ.get("VOSK_MODEL_PATH") or ""
        if not model_path:
            for cand in (
                "/opt/vosk-model-small-en-us",
                str(_Path.home() / "vosk-model-small-en-us-0.15"),
                "/usr/share/vosk/model",
            ):
                if _Path(cand).is_dir():
                    model_path = cand
                    break
        if not model_path:
            return None
        model = vosk.Model(model_path)
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            tmp.write(wav_bytes)
            tmp.flush()
            wf = wave.open(tmp.name, "rb")
            rec = vosk.KaldiRecognizer(model, wf.getframerate())
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
            result = _json.loads(rec.FinalResult() or "{}")
        text = (result.get("text") or "").strip().lower()
        if text:
            digits = "".join(_re.findall(r"[0-9]", text))
            return digits or text
    except Exception:
        pass
    return None


async def _try_oss_recaptcha_audio(page: Any) -> dict[str, Any] | None:
    """Switch reCAPTCHA to audio challenge and solve via free STT.

    Works on classic v2 image grids that expose the audio button. Enterprise /
    hCaptcha often block this path — then we return ok=False with detail.
    """
    if not _oss_enabled() or not _audio_enabled():
        return None

    bframe = None
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if "recaptcha" in url and ("bframe" in url or "/fc/" in url or "enterprise" in url):
                # Prefer the challenge bframe over the anchor.
                if "anchor" in url:
                    continue
                bframe = frame
                if "bframe" in url:
                    break
    except Exception:
        bframe = None

    if bframe is None:
        try:
            # Trigger challenge if only the checkbox is showing.
            await _click_recaptcha_checkbox(page)
            await page.wait_for_timeout(1500)
            for frame in page.frames:
                url = (frame.url or "").lower()
                if "recaptcha" in url and "bframe" in url:
                    bframe = frame
                    break
        except Exception:
            pass

    if bframe is None:
        return None

    # Click the audio button.
    clicked_audio = False
    for sel in (
        "#recaptcha-audio-button",
        "button#recaptcha-audio-button",
        "#audio-button",
        "button[title*=\"audio\" i]",
        "button[aria-label*=\"audio\" i]",
    ):
        try:
            loc = bframe.locator(sel).first
            if await loc.count() == 0:
                continue
            await loc.click(timeout=4000)
            clicked_audio = True
            await page.wait_for_timeout(2000)
            break
        except Exception:
            continue
    if not clicked_audio:
        return {"ok": False, "method": "oss_audio", "detail": "no_audio_button"}

    # Fetch audio bytes from the challenge frame.
    audio_bytes: bytes | None = None
    try:
        src = await bframe.evaluate(
            """() => {
              const a = document.querySelector('#audio-source, audio, a.rc-audiochallenge-tdownload-link, a[href*="audio"]');
              if (!a) return null;
              return a.src || a.href || a.getAttribute('href') || null;
            }"""
        )
        if src:
            if str(src).startswith("data:"):
                import base64
                import re as _re

                m = _re.search(r"base64,(.+)", str(src))
                if m:
                    audio_bytes = base64.b64decode(m.group(1))
            else:
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    resp = await client.get(str(src))
                    if resp.status_code == 200 and resp.content:
                        audio_bytes = resp.content
    except Exception as exc:
        return {"ok": False, "method": "oss_audio", "detail": f"fetch_failed:{exc}"[:160]}

    if not audio_bytes:
        return {"ok": False, "method": "oss_audio", "detail": "no_audio_bytes"}

    text = await asyncio.to_thread(_transcribe_recaptcha_audio, audio_bytes)
    if not text:
        return {"ok": False, "method": "oss_audio", "detail": "stt_failed"}

    # Type answer and verify.
    try:
        inp = bframe.locator("#audio-response, input#audio-response, input[name=audio-response]").first
        await inp.fill(text, timeout=5000)
        for sel in ("#recaptcha-verify-button", "button#recaptcha-verify-button", "#verify-button"):
            try:
                btn = bframe.locator(sel).first
                if await btn.count():
                    await btn.click(timeout=4000)
                    break
            except Exception:
                continue
        await page.wait_for_timeout(2500)
    except Exception as exc:
        return {"ok": False, "method": "oss_audio", "detail": f"submit_failed:{exc}"[:160]}

    if await _recaptcha_solved(page) or not await _challenge_visible(page):
        return {"ok": True, "method": "oss_audio", "detail": f"stt:{text[:24]}"}
    return {"ok": False, "method": "oss_audio", "detail": f"rejected:{text[:24]}"}


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
                    '#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[name="h-captcha-response"], input[name="cf-turnstile-response"], input[name="captcha"], textarea[name="captcha"]'
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


async def _arm_hcaptcha_execute(page: Any) -> bool:
    """Trigger invisible hCaptcha via ``hcaptcha.execute()`` when present.

    Supabase (and similar) keep Sign up disabled until a token lands. Clicking a
    disabled CTA does nothing — execute() arms Browserbase / the challenge UI.
    """
    try:
        armed = await page.evaluate(
            """() => {
              try {
                if (!window.hcaptcha || typeof window.hcaptcha.execute !== 'function') return false;
                // Prefer explicit widget ids from .h-captcha nodes.
                const nodes = [...document.querySelectorAll('.h-captcha, [data-sitekey]')];
                let ran = false;
                for (const n of nodes) {
                  const id = n.getAttribute('data-hcaptcha-widget-id')
                    || n.getAttribute('data-widget-id');
                  try {
                    if (id) { window.hcaptcha.execute(id); ran = true; }
                    else { window.hcaptcha.execute(); ran = true; }
                  } catch (e) {}
                }
                if (!ran) {
                  try { window.hcaptcha.execute(); ran = true; } catch (e) {}
                }
                return ran;
              } catch (e) { return false; }
            }"""
        )
        if armed:
            await page.wait_for_timeout(2000)
        return bool(armed)
    except Exception:
        return False


async def _click_hcaptcha_checkbox(page: Any) -> bool:
    """Click an hCaptcha checkbox (visible or invisible host) when present."""
    try:
        for frame in page.frames:
            url = (frame.url or "").lower()
            if "hcaptcha" not in url:
                continue
            if "challenge" in url and "checkbox" not in url:
                continue
            for sel in (
                "#checkbox",
                "[role=checkbox]",
                "#anchor-state",
                ".check",
                "div#checkbox",
            ):
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
        frame = page.frame_locator('iframe[src*="hcaptcha"]').first
        await frame.locator("#checkbox, [role=checkbox]").first.click(timeout=4000, force=True)
        await page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


async def _trigger_signup_submit(page: Any) -> bool:
    """Click email Sign up / Create account to engage invisible captchas.

    Avoid SSO buttons (Continue with GitHub/Google) — those match a naive
    ``continue`` regex and yank the session off the email signup form.
    """
    try:
        clicked = await page.evaluate(
            """() => {
              const btns = [...document.querySelectorAll('button[type=submit], button')];
              const scored = [];
              for (const b of btns) {
                const label = ((b.innerText || b.getAttribute('aria-label') || '') + '').toLowerCase().trim();
                if (!label) continue;
                if (/github|google|gitlab|sso|saml|chatgpt|apple|azure|microsoft|bitbucket/.test(label)) continue;
                let score = 0;
                if (b.type === 'submit') score += 5;
                if (/^sign\\s*up$/.test(label) || label === 'create account' || label === 'register') score += 10;
                if (/sign\\s*up|create\\s*account|register|join/.test(label)) score += 3;
                // Do NOT match bare 'continue' — that hits OAuth CTAs.
                if (score > 0) scored.push({b, score, label});
              }
              scored.sort((a,b) => b.score - a.score);
              if (!scored.length) return false;
              const b = scored[0].b;
              try { b.scrollIntoView({block:'center'}); } catch (e) {}
              b.click();
              return scored[0].label;
            }"""
        )
        if clicked:
            await page.wait_for_timeout(2500)
        return bool(clicked)
    except Exception:
        return False


def _maybe_apply_signup_solver_policy() -> dict[str, Any]:
    """Return the published per-type method, if signup should follow it.

    The fresh-score runner unsets ``CAPSOLVER_API_KEY`` before it calls signup,
    so a policy cannot spend during an honest rescore. Paid tasks still have
    to be endorsed by the policy (or the host allowlist / experiment flag)
    and the $1 balance floor still applies.
    """
    from mvp.captcha_spend import load_method_policy

    policy = load_method_policy()
    if not policy.get("apply_to_signup"):
        return {}
    return policy


async def human_drag(page: Any) -> dict[str, Any]:
    """Drag a slider handle with a short eased path. No paid API call."""
    import random

    found = None
    try:
        found = await page.evaluate(
            """() => {
              const sels = [
                '.geetest_slider_button', '.geetest_btn',
                '[class*="slider-button"]', '[class*="slide-btn"]',
                '[class*="slider"] button', '[role="slider"]',
                '.arrow-handle', '[class*="handle"]'
              ];
              for (const s of sels) {
                const el = document.querySelector(s);
                if (!el) continue;
                const r = el.getBoundingClientRect();
                if (r.width >= 8 && r.height >= 8 && r.width < 220 && r.bottom > 0) {
                  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                }
              }
              return null;
            }"""
        )
    except Exception:
        found = None
    if not found:
        return {"ok": False, "detail": "no_handle"}
    x = float(found["x"])
    y = float(found["y"])
    distance = 160 + random.randint(-15, 50)
    try:
        await page.mouse.move(x, y)
        await page.mouse.down()
        steps = 22
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)
            await page.mouse.move(x + distance * ease, y + random.uniform(-1.4, 1.4))
            await page.wait_for_timeout(random.randint(10, 26))
        await page.mouse.up()
        await page.wait_for_timeout(1200)
    except Exception:
        return {"ok": False, "detail": "drag_error"}
    cleared = not await _challenge_visible(page)
    return {"ok": cleared, "detail": "dragged", "cleared": cleared}


async def solve_image_challenge(page: Any, *, method: str = "image_to_text") -> dict[str, Any]:
    """Send the visible challenge image to a priced recognition task.

    ImageToText is the general fallback. ReCaptchaV2Classification is used
    only when the on-page prompt matches CapSolver's question list.
    """
    import base64

    selectors = (
        "iframe[src*='hcaptcha']",
        "iframe[src*='bframe']",
        "img[src*='captcha' i]",
        "img[alt*='captcha' i]",
    )
    png = b""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            png = await loc.screenshot(type="png", timeout=4000)
            if png:
                break
        except Exception:
            continue
    if not png:
        try:
            png = await page.screenshot(type="png")
        except Exception:
            png = b""
    if not png:
        return {"ok": False, "detail": "no_image"}
    shot = base64.b64encode(png).decode()
    page_url = getattr(page, "url", "") or ""
    extra: dict[str, Any] = {"body": shot, "module": "common"}
    task_type = "ImageToTextTask"
    captcha_type = "image_text"
    if method == "recaptcha_classification":
        question = ""
        try:
            question = await page.evaluate(
                "() => ((document.body && document.body.innerText) || '').slice(0, 400)"
            )
        except Exception:
            question = ""
        qid = None
        low = (question or "").lower()
        for needle, code in (
            ("traffic light", "/m/015qff"),
            ("crosswalk", "/m/014xcs"),
            ("fire hydrant", "/m/01pns0"),
            ("bicycle", "/m/0199g"),
            ("bus", "/m/01bjv"),
            ("car", "/m/0k4j"),
            ("motorcycle", "/m/04_sv"),
            ("stair", "/m/01lynh"),
        ):
            if needle in low:
                qid = code
                break
        if not qid:
            return {"ok": False, "detail": "question_unmapped"}
        extra = {"image": shot, "question": qid}
        task_type = "ReCaptchaV2Classification"
        captcha_type = "recaptcha_classification"
    token = await asyncio.to_thread(
        _capsolver_solve,
        "",
        sitekey="",
        page_url=page_url,
        captcha_type=captcha_type,
        action=None,
        timeout_s=60,
        blocking=True,
        extra=extra,
        task_type_override=task_type,
    )
    if not token:
        return {"ok": False, "detail": "no_token"}
    try:
        await page.evaluate(
            """(text) => {
              const el = document.querySelector('input[name*=captcha i], input[id*=captcha i], input[type=text]');
              if (!el || text.startsWith('{')) return false;
              el.focus();
              el.value = text;
              el.dispatchEvent(new Event('input', {bubbles:true}));
              return true;
            }""",
            token,
        )
    except Exception:
        pass
    cleared = not await _challenge_visible(page)
    return {"ok": bool(token), "detail": task_type, "cleared": cleared, "token": True}


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

    # hCaptcha (Supabase invisible + challenge iframe).
    hc_clicked = await _click_hcaptcha_checkbox(page)
    if not hc_clicked:
        # Invisible hCaptcha often only arms after the signup CTA is pressed.
        await _trigger_signup_submit(page)
        hc_clicked = await _click_hcaptcha_checkbox(page)
    # Force-arm invisible widgets — disabled Sign up never reaches hcaptcha.
    hc_armed = await _arm_hcaptcha_execute(page)

    # Longer BB wait when an hCaptcha iframe is present.
    info_early = await detect_sitekey(page)
    is_hcaptcha = bool(
        (info_early or {}).get("type") == "hcaptcha"
        or hc_clicked
        or hc_armed
        or await page.evaluate(
            """() => !!document.querySelector('iframe[src*="hcaptcha"], .h-captcha')"""
        )
    )
    bb_timeout = float(os.environ.get("MVP_CAPTCHA_BB_WAIT_S", "45"))
    if is_hcaptcha:
        bb_timeout = max(bb_timeout, float(os.environ.get("MVP_CAPTCHA_HCAPTCHA_BB_WAIT_S", "90")))

    # Browserbase native solver (console events) — free when session has solveCaptchas.
    if await wait_for_browserbase_solver(page, timeout_s=bb_timeout):
        if await _recaptcha_solved(page):
            # Token present is necessary but not sufficient — Loom often keeps
            # showing a reCAPTCHA error until a fresh solve lands. Only accept
            # early if the signup CTA is no longer disabled.
            still_blocked = await page_looks_captcha_blocked(page)
            if not still_blocked.get("submit_disabled") and not still_blocked.get("blocked"):
                return {"ok": True, "method": "browserbase", "detail": "token_after_bb"}
            # Fall through to OSS / API for a stronger solve.
        # Challenge UI gone with no token is only OK for non-recaptcha interstitials.
        elif not await _challenge_visible(page):
            info = info_early or await detect_sitekey(page)
            url = (getattr(page, "url", "") or "").lower()
            left_for_oauth = any(
                x in url
                for x in ("github.com", "accounts.google", "login.microsoft", "apple.com")
            )
            captcha_type = (info or {}).get("type") or ""
            widget_still = await _captcha_widget_present(page)
            if (
                not left_for_oauth
                and captcha_type not in {"recaptcha", "recaptcha_v2", "hcaptcha"}
                and not widget_still
                and not await _recaptcha_solved(page)
            ):
                blocked = await page_looks_captcha_blocked(page)
                if not blocked.get("widget_present") and not blocked.get("blocked"):
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

    # Prefer audio STT before image-grid guessing — more reliable for v2.
    oss_audio = await _try_oss_recaptcha_audio(page)
    if oss_audio and oss_audio.get("ok") and await _recaptcha_solved(page):
        return oss_audio

    # Open-source local image solver (optional deps).
    oss_img = await _try_oss_image_solver(page)
    if oss_img and oss_img.get("ok"):
        if await _recaptcha_solved(page) or not await _challenge_visible(page):
            return oss_img

    # Retry audio once more after image attempts (new challenge round).
    if not (oss_audio and oss_audio.get("ok")):
        oss_audio = await _try_oss_recaptcha_audio(page)
        if oss_audio and oss_audio.get("ok") and await _recaptcha_solved(page):
            return oss_audio

    oss_ocr = await _try_oss_text_ocr(page)
    if oss_ocr and oss_ocr.get("ok"):
        return oss_ocr

    page_url = getattr(page, "url", "") or ""
    info = await detect_sitekey(page)
    blocked_info = await page_looks_captcha_blocked(page)
    policy = _maybe_apply_signup_solver_policy()
    spec: dict[str, Any] = {}
    if policy and info:
        spec = ((policy.get("types") or {}).get(info.get("type") or "") or {})
    # A sitekey or a disabled button alone is not enough. CapSolver runs only
    # when a challenge, widget, or captcha error is actually on the page.
    solver_key = ""
    if info:
        solver_key = str(info.get("sitekey") or info.get("captchaId") or info.get("gt") or "")
    captcha_blocking = bool(solver_key) and not blocked_info.get("solved") and bool(
        blocked_info.get("challenge_visible")
        or blocked_info.get("widget_present")
        or blocked_info.get("text_block")
    )
    # A published policy limits paid solves to types that actually cleared.
    if policy:
        if spec.get("method") not in {"capsolver", "capsolver_v2_enterprise"}:
            captcha_blocking = False
    # Paid CapSolver only after the detector says this page is actually stuck.
    if info and solver_key and captcha_blocking:
        extra = {
            k: info.get(k)
            for k in ("gt", "challenge", "captchaId")
            if info.get(k)
        }
        captcha_type = spec.get("captcha_type") or info.get("type") or blocked_info.get("type") or "recaptcha"
        token = await asyncio.to_thread(
            solve_sitekey,
            sitekey=solver_key,
            page_url=page_url,
            captcha_type=captcha_type,
            action=info.get("action"),
            blocking=True,
            extra=extra or None,
            task_type_override=spec.get("task"),
        )
        if token:
            injected = await _inject_token(page, token, info.get("type") or "recaptcha")
            if injected:
                cleared = await wait_for_challenge_to_clear(page, timeout_s=15.0)
                still = await page_looks_captcha_blocked(page)
                widget_gone = (
                    cleared
                    and not still.get("challenge_visible")
                    and not still.get("text_block")
                    and not still.get("widget_present")
                )
                if widget_gone or (
                    await _recaptcha_solved(page) and not still.get("challenge_visible")
                ):
                    return {"ok": True, "method": "solver_api", "detail": info.get("type")}
                return {
                    "ok": False,
                    "method": "solver_api",
                    "detail": f"{info.get('type')}_token_widget_remained",
                    "token": token,
                }
            return {"ok": False, "method": "solver_api", "detail": "inject_failed", "token": token}

    if spec.get("method") in {"image_to_text", "recaptcha_classification"}:
        image_result = await solve_image_challenge(page, method=str(spec.get("method")))
        if image_result.get("cleared") or (
            image_result.get("ok") and not await _challenge_visible(page)
        ):
            return {"ok": True, "method": spec.get("method"), "detail": image_result.get("detail")}

    drag_type = ((info or {}).get("type") or "")
    want_drag = spec.get("method") == "mouse_drag" or (
        not policy
        and drag_type in {"arkose", "funcaptcha", "slider", "geetest", "geetest_v4", "datadome"}
    )
    if want_drag:
        dragged = await human_drag(page)
        if dragged.get("ok") and not await _challenge_visible(page):
            return {"ok": True, "method": "mouse_drag", "detail": drag_type}

    # Human fallback — re-check first; Browserbase often finishes a few seconds late.
    if await _recaptcha_solved(page):
        return {"ok": True, "method": "browserbase", "detail": "token_late"}
    # Fail fast with an actionable reason when we have a sitekey but no solver API key.
    if info and info.get("sitekey") and not _api_key():
        return {
            "ok": False,
            "method": "need_solver_api",
            "detail": (
                f"hcaptcha/recaptcha sitekey={info.get('sitekey')} type={info.get('type')} "
                "— Browserbase+OSS could not produce a token; set MVP_CAPTCHA_API_KEY "
                "(CapSolver/2Captcha) or Browserbase Verified"
            ),
        }
    # Unattended seed runs must not burn the human timeout after we already know
    # a paid solver is required — ALLOW_HUMAN=0 → need_solver_api immediately
    # when a widget/challenge is still visible.
    allow_human = (os.environ.get("MVP_CAPTCHA_ALLOW_HUMAN") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not allow_human and (
        await _challenge_visible(page)
        or await _captcha_widget_present(page)
        or (info and info.get("sitekey"))
    ):
        return {
            "ok": False,
            "method": "need_solver_api",
            "detail": (
                f"human_disabled;sitekey={((info or {}).get('sitekey') or 'unknown')} "
                f"type={((info or {}).get('type') or 'unknown')}"
            ),
        }
    await asyncio.to_thread(request_human_solve, page_url)
    ok = await asyncio.to_thread(wait_for_human_solve)
    if not ok and await _recaptcha_solved(page):
        return {"ok": True, "method": "browserbase", "detail": "token_during_human_wait"}
    detail = "solved" if ok else "timeout"
    if oss_img and not oss_img.get("ok"):
        detail = f"{detail};oss_image={oss_img.get('detail')}"
    if oss_audio and not oss_audio.get("ok"):
        detail = f"{detail};oss_audio={oss_audio.get('detail')}"
    if oss_ocr and not oss_ocr.get("ok"):
        detail = f"{detail};oss_ocr={oss_ocr.get('detail')}"
    # Explicit failure when a widget is still present without a token.
    if not ok and await _challenge_visible(page) and not await _recaptcha_solved(page):
        return {
            "ok": False,
            "method": "unsolved",
            "detail": detail,
        }
    return {
        "ok": ok,
        "method": "human",
        "detail": detail,
    }


async def _inject_token(page: Any, token: str, captcha_type: str) -> bool:
    script = """
    (token) => {
      let gee = null;
      try { if (token && token.charAt(0) === '{') gee = JSON.parse(token); } catch (e) {}
      if (gee && (gee.pass_token || gee.lot_number || gee.captcha_output)) {
        const form = document.querySelector('form') || document.body;
        for (const name of ['lot_number', 'pass_token', 'gen_time', 'captcha_output', 'captcha_id']) {
          if (!gee[name]) continue;
          let el = form.querySelector('input[name="' + name + '"]');
          if (!el) {
            el = document.createElement('input');
            el.type = 'hidden';
            el.name = name;
            form.appendChild(el);
          }
          el.value = String(gee[name]);
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
        }
        for (const name of ['geetestCallback', 'captchaCallback', 'onGeetestSuccess']) {
          if (typeof window[name] === 'function') {
            try { window[name](gee); } catch (e) {}
          }
        }
      }
      const tokenValue = (gee && gee.token) ? String(gee.token) : token;
      const set = (sel) => {
        const nodes = document.querySelectorAll(sel);
        nodes.forEach((el) => {
          const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const desc = Object.getOwnPropertyDescriptor(proto, 'value');
          if (desc && desc.set) desc.set.call(el, tokenValue);
          else el.value = tokenValue;
          el.innerHTML = tokenValue;
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
        });
      };
      set('textarea[name="g-recaptcha-response"]');
      set('textarea[name="h-captcha-response"]');
      set('input[name="cf-turnstile-response"]');
      set('#g-recaptcha-response');
      // Auth0 Universal Login (Retell) posts the enterprise token in this field.
      set('input[name="captcha"]');
      set('textarea[name="captcha"]');
      set('#captcha');
      const callNamed = (name) => {
        if (name && typeof window[name] === 'function') {
          try { window[name](tokenValue); } catch (e) {}
        }
      };
      document.querySelectorAll('[data-callback]').forEach((n) => callNamed(n.getAttribute('data-callback')));
      callNamed('onTurnstileSuccess');
      callNamed('onloadTurnstileCallback');
      // Bland's React Cloudflare Turnstile stores the token handler on props.onSuccess.
      const callReact = (props) => {
        if (!props) return false;
        for (const name of ['onSuccess', 'onVerify']) {
          if (typeof props[name] === 'function') {
            try { props[name](tokenValue); return true; } catch (e) {}
          }
        }
        return false;
      };
      const nodes = document.querySelectorAll('div, form, span');
      for (const el of nodes) {
        let keys;
        try { keys = Object.keys(el); } catch (e) { continue; }
        for (const k of keys) {
          if (k.indexOf('__reactProps') === 0 && callReact(el[k])) break;
          if (k.indexOf('__reactFiber') === 0 || k.indexOf('__reactInternalInstance') === 0) {
            let fiber = el[k];
            for (let i = 0; i < 15 && fiber; i++) {
              if (callReact(fiber.memoizedProps) || callReact(fiber.pendingProps)) break;
              fiber = fiber.return;
            }
          }
        }
      }
      try {
        if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
          const seen = new Set();
          const walk = (obj, depth) => {
            if (!obj || depth > 6 || typeof obj !== 'object') return;
            if (seen.has(obj)) return;
            seen.add(obj);
            if (typeof obj.callback === 'function') {
              try { obj.callback(tokenValue); } catch (e) {}
            }
            let keys;
            try { keys = Object.keys(obj); } catch (e) { return; }
            for (const k of keys) {
              try { walk(obj[k], depth + 1); } catch (e) {}
            }
          };
          walk(window.___grecaptcha_cfg.clients, 0);
        }
      } catch (e) {}
      try {
        if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
          /* token already set on input */
        }
      } catch (e) {}
      try {
        if (window.hcaptcha) {
          // Fire data-callback / registered widget callbacks so React enables Sign up.
          const nodes = [...document.querySelectorAll('.h-captcha, [data-sitekey], [data-callback]')];
          for (const n of nodes) {
            const cbName = n.getAttribute('data-callback');
            if (cbName && typeof window[cbName] === 'function') {
              try { window[cbName](tokenValue); } catch (e) {}
            }
          }
          try {
            if (typeof window.hcaptcha.getResponse === 'function') {
              /* response fields already set above */
            }
          } catch (e) {}
        }
      } catch (e) {}
      return true;
    }
    """
    try:
        await page.evaluate(script, token)
        # After token inject, re-enable / click Sign up so the form submits.
        try:
            await page.evaluate(
                """() => {
                  const btns = [...document.querySelectorAll('button[type=submit], button')];
                  for (const b of btns) {
                    const label = ((b.innerText || '') + '').toLowerCase().trim();
                    if (/github|google|gitlab|sso|chatgpt|apple/.test(label)) continue;
                    if (!(/sign\\s*up|create\\s*account|register/.test(label) || b.type === 'submit')) continue;
                    b.disabled = false;
                    b.removeAttribute('disabled');
                    b.setAttribute('aria-disabled', 'false');
                    try { b.click(); } catch (e) {}
                    return true;
                  }
                  return false;
                }"""
            )
        except Exception:
            pass
        return True
    except Exception:
        return False


def status() -> dict[str, Any]:
    oss: dict[str, bool] = {"enabled": _oss_enabled(), "audio_enabled": _audio_enabled()}
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
    try:
        import speech_recognition  # noqa: F401

        oss["speech_recognition"] = True
    except Exception:
        oss["speech_recognition"] = False
    try:
        import vosk  # noqa: F401

        oss["vosk"] = True
    except Exception:
        oss["vosk"] = False
    return {
        "captcha_solver_enabled": captcha_solver_enabled(),
        "api": _api_name(),
        "api_key_set": bool(_api_key()),
        "oss": oss,
    }
