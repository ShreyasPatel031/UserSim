"""Same-page signup for a study agent that is already in a browser.

``signup_in_session`` never opens a second Browserbase session. The caller
passes the Playwright page it already has. Each call uses a fresh email alias,
types it (no Google SSO), reads the verification code or magic link from
Gmail, and clicks through onboarding until the product workspace is usable.

Hard stop is 90 seconds. CapSolver is not called here — the live balance floor
is enforced elsewhere, and this path relies on the page the caller already has
(Browserbase's own solver if that session was created with solve_captchas).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

from mvp.identity import (
    _base_identity_fields,
    _generate_password,
    email_for_host,
    host_for_url,
)

DEFAULT_TIMEOUT_S = 90.0

# Product the integration e2e actually hits tonight.
START_URLS: dict[str, str] = {
    "linear.app": "https://linear.app/signup",
    "trello.com": "https://trello.com/signup",
    "asana.com": "https://asana.com/create-account",
    "miro.com": "https://miro.com/signup/",
    "tldraw.com": "https://www.tldraw.com/",
}

# Where a finished account should land. Anonymous marketing/canvas is not enough.
WORKSPACE_URL = re.compile(
    r"("
    r"linear\.app/(?!signup|login|auth)[^/?#]+/.+"
    r"|trello\.com/(u/|b/|w/)"
    r"|app\.asana\.com/(?!-/login|-/signup|0/login)"
    r"|miro\.com/app/(dashboard|board)"
    r"|tldraw\.com/.*"
    r")",
    re.I,
)

_OAUTH = re.compile(
    r"\b(google|microsoft|apple|slack|saml|sso|office\s*365|github|facebook|passkey)\b",
    re.I,
)
# Exact button labels, best first. "Continue with email" is a submit only once the
# email box is already on screen (tldraw). It is not a substitute for "Continue".
_SUBMIT_RANK: tuple[re.Pattern[str], ...] = (
    re.compile(r"^try for free$", re.I),
    re.compile(r"^take me to my (canvas|board)$", re.I),
    re.compile(r"^sign up$", re.I),
    re.compile(r"^continue$", re.I),
    re.compile(r"^verify( email)?$", re.I),
    re.compile(r"^next$", re.I),
    re.compile(r"^get started$", re.I),
    re.compile(r"^create( workspace| account)?$", re.I),
    re.compile(r"^join$", re.I),
    re.compile(r"^submit$", re.I),
    re.compile(r"^continue with email$", re.I),
)
_EMAIL_PATH = re.compile(r"^continue with email$|^sign up with email$", re.I)
_SKIP = re.compile(
    r"^(skip( for now| to web app)?|not now|no thanks|maybe later|do this later|"
    r"i['’]ll do this later|got it)$",
    re.I,
)
_CODE_HINT = re.compile(
    r"check your (email|inbox)|enter (the |your )?(verification )?code|"
    r"we (emailed|sent) you|code we sent|sent you a (link|code)|"
    r"click the link we|confirm your email",
    re.I,
)
_PHONE_HINT = re.compile(
    r"\b(enter your phone|verify your phone|sms code|text message code)\b", re.I
)
_WORK_REJECT = re.compile(
    r"personal email|use (a |your )?work email to|business email address|"
    r"could not reach the email|email is not accepted",
    re.I,
)


def start_url_for(site_url: str) -> str:
    host = host_for_url(site_url or "")
    if host in START_URLS:
        return START_URLS[host]
    if host.endswith(".tldraw.com"):
        return START_URLS["tldraw.com"]
    return site_url if "://" in (site_url or "") else f"https://{host}"


def fresh_alias(host: str, persona: dict[str, Any] | None, *, tag: str) -> dict[str, str]:
    """Build a never-reused mailbox. Does not write secrets/identities.json."""
    base = _base_identity_fields()
    persona = persona or {}
    username = str(persona.get("email") or persona.get("username") or base.get("username") or "")
    if "@" not in username:
        raise RuntimeError("persona.email or the credential vault must be a base email")
    name = str(persona.get("full_name") or persona.get("name") or base.get("full_name") or "Shreyas Patel")
    company = str(persona.get("company") or base.get("company") or "UserSim")
    dotted = host in {"miro.com"}
    email = email_for_host(username, host, tag=tag, force_dotted=dotted)
    return {
        "email": email,
        "password": _generate_password(),
        "full_name": name,
        "company": company[:48] or "UserSim",
        "alias_tag": re.sub(r"[^a-z0-9]", "", tag.lower())[:32],
        "host": host,
    }


def _body_hint(body: str) -> str:
    text = re.sub(r"\S+@\S+", "<email>", body or "")
    text = re.sub(r"\b\d{4,8}\b", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "hint:" + text[:140]


def _safe_step(text: str) -> str:
    """Drop anything that looks like a mailbox or a long secret."""
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", text)
    text = re.sub(r"(?i)(password|passwd)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    return text[:180]


def _public_result(
    *,
    ok: bool,
    reason: str,
    email: str,
    started: float,
    steps: list[str],
    alias_tag: str = "",
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "reason": reason,
        "email": email,
        "elapsed_s": round(time.time() - started, 1),
        "steps": [_safe_step(s) for s in steps][-24:],
        "alias_tag": alias_tag,
    }


_SNAPSHOT_JS = r"""
() => {
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textOf = (el) => ((el.innerText || el.getAttribute('aria-label') || el.getAttribute('value') || '') + '')
    .replace(/\s+/g, ' ').trim().slice(0, 80);
  const buttons = [...document.querySelectorAll('button, [role="button"], a, input[type="submit"]')]
    .filter(vis)
    .map(textOf)
    .filter(Boolean)
    .slice(0, 40);
  const fields = [...document.querySelectorAll('input, textarea')]
    .filter(vis)
    .map(el => ({
      type: (el.getAttribute('type') || 'text').toLowerCase(),
      name: el.getAttribute('name') || '',
      id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      maxLength: el.maxLength > 0 ? el.maxLength : 0,
      valueLen: (el.value || '').length,
    }));
  const captcha = !!document.querySelector(
    'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], iframe[src*="turnstile"], .g-recaptcha, [data-sitekey]'
  );
  const body = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 1500);
  return {href: location.href, title: document.title, buttons, fields, captcha, body};
}
"""


async def _snap(page: Any) -> dict[str, Any]:
    try:
        data = await page.evaluate(_SNAPSHOT_JS)
    except Exception:
        data = {"href": "", "title": "", "buttons": [], "fields": [], "captcha": False, "body": ""}
    if not isinstance(data, dict):
        data = {"href": "", "buttons": [], "fields": [], "captcha": False, "body": ""}
    data.setdefault("buttons", [])
    data.setdefault("fields", [])
    data.setdefault("body", "")
    return data


def _field_kind(field: dict[str, Any]) -> str:
    blob = " ".join(
        str(field.get(k) or "")
        for k in ("type", "name", "id", "placeholder", "autocomplete")
    ).lower()
    if field.get("type") == "hidden":
        return "hidden"
    if "email" in blob:
        return "email"
    if field.get("type") == "password" or "password" in blob:
        return "password"
    if field.get("type") == "tel" or "phone" in blob:
        return "phone"
    if any(tok in blob for tok in ("otp", "code", "one-time", "onetime")):
        return "code"
    if field.get("maxLength") in (1, 4, 6, 8) and field.get("type") in {"text", "tel", "number"}:
        return "code"
    if any(tok in blob for tok in ("name", "fullname", "full_name", "display")):
        return "name"
    if any(tok in blob for tok in ("workspace", "company", "organization", "team")):
        return "workspace"
    return "other"


async def _fill_kind(page: Any, kind: str, value: str) -> bool:
    """Type into the first visible field of ``kind``."""
    script = """
    (kind) => {
      const vis = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      document.querySelectorAll('[data-sis-target]').forEach(el => el.removeAttribute('data-sis-target'));
      const fields = [...document.querySelectorAll('input, textarea')].filter(vis);
      const blob = (el) => [el.type, el.name, el.id, el.placeholder, el.getAttribute('autocomplete'), el.getAttribute('aria-label')]
        .filter(Boolean).join(' ').toLowerCase();
      const match = (el) => {
        const b = blob(el);
        const t = (el.getAttribute('type') || 'text').toLowerCase();
        if (t === 'hidden') return false;
        if (kind === 'email') return t === 'email' || b.includes('email');
        if (kind === 'password') return t === 'password' || b.includes('password');
        if (kind === 'name') return /name|fullname|display/.test(b) && !/user.?name|email/.test(b);
        if (kind === 'workspace') return /workspace|company|organization|team name/.test(b);
        if (kind === 'code') {
          return /otp|code|one-time|onetime/.test(b) || ((el.maxLength === 1 || el.maxLength === 6) && /text|tel|number/.test(t));
        }
        return false;
      };
      const el = fields.find(match);
      if (!el) return '';
      el.setAttribute('data-sis-target', '1');
      const proto = Object.getPrototypeOf(el);
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) desc.set.call(el, '');
      el.focus();
      return 'ok';
    }
    """
    try:
        found = await page.evaluate(script, kind)
    except Exception:
        found = ""
    if found != "ok":
        return False
    loc = page.locator("[data-sis-target='1']").first
    try:
        await loc.click(timeout=2500)
        await loc.press_sequentially(value, delay=12)
        typed = await loc.input_value()
        if typed != value:
            await loc.fill(value)
            await page.evaluate(
                """(value) => {
                  const el = document.querySelector('[data-sis-target="1"]');
                  if (!el) return;
                  const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
                  if (desc && desc.set) desc.set.call(el, value);
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                value,
            )
        return True
    except Exception:
        return False


_LABELS_JS = """
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  return [...document.querySelectorAll('button, [role="button"], input[type="submit"]')]
    .filter(vis)
    .map(el => ((el.innerText || el.getAttribute('aria-label') || el.getAttribute('value') || '') + '').replace(/\\s+/g, ' ').trim())
    .filter(t => t && t.length < 80);
}
"""


async def _labels(page: Any) -> list[str]:
    try:
        labels = await page.evaluate(_LABELS_JS)
    except Exception:
        return []
    return [str(label) for label in labels or []]


async def _click_label(page: Any, label: str) -> bool:
    try:
        await page.get_by_role("button", name=label, exact=True).first.click(timeout=3000)
        return True
    except Exception:
        try:
            await page.get_by_text(label, exact=True).first.click(timeout=3000)
            return True
        except Exception:
            return False


async def _click_button(page: Any, pattern: re.Pattern[str], *, avoid_oauth: bool = True) -> str | None:
    for label in await _labels(page):
        if avoid_oauth and _OAUTH.search(label) and not _EMAIL_PATH.search(label):
            continue
        if pattern.search(label) and await _click_label(page, label):
            return label
    return None


async def _click_ranked_submit(page: Any, *, allow_email_path: bool = True) -> str | None:
    labels = await _labels(page)
    for pattern in _SUBMIT_RANK:
        for label in labels:
            if not allow_email_path and _EMAIL_PATH.search(label):
                continue
            if _OAUTH.search(label) and not _EMAIL_PATH.search(label):
                continue
            if pattern.search(label) and await _click_label(page, label):
                return label
    return None


async def _enter_code(page: Any, code: str) -> bool:
    boxes = page.locator("input[maxlength='1']")
    try:
        n = await boxes.count()
    except Exception:
        n = 0
    if n >= 4 and len(code) >= n:
        for i, ch in enumerate(code[:n]):
            try:
                await boxes.nth(i).fill(ch)
            except Exception:
                return False
        return True
    return await _fill_kind(page, "code", code)


def _mail_hosts(host: str) -> list[str]:
    hosts = [host]
    if host == "trello.com":
        hosts.append("id.atlassian.com")
    return hosts


async def _poll_mail(alias: str, host: str, newer_than: float, timeout_s: float) -> tuple[str, str] | None:
    from mvp.email_codes import latest_signup_code, latest_signup_link

    deadline = time.time() + max(0.5, timeout_s)

    def _once() -> tuple[str, str] | None:
        for h in _mail_hosts(host):
            code = latest_signup_code(alias, host=h, newer_than=newer_than)
            if code:
                return ("code", code)
        for h in _mail_hosts(host):
            link = latest_signup_link(alias, host=h, newer_than=newer_than)
            if link:
                return ("link", link)
        return None

    while time.time() < deadline:
        found = await asyncio.to_thread(_once)
        if found:
            return found
        await asyncio.sleep(2.0)
    return None


def _workspace_ready(host: str, snap: dict[str, Any]) -> bool:
    href = str(snap.get("href") or "")
    body = str(snap.get("body") or "")
    path = urlparse(href).path or ""
    low = body.lower()
    if host == "tldraw.com":
        # The anonymous canvas is the default. Require the sign-in affordance to be gone
        # and an account control to be present.
        buttons = " ".join(snap.get("buttons") or []).lower()
        if "sign in" in buttons:
            return False
        return "account" in buttons or "log out" in low or "sign out" in low
    if host == "linear.app":
        if re.search(r"/signup|/login", path):
            return False
        return bool(re.search(r"linear\.app/[^/]+/", href)) and any(
            tok in low for tok in ("inbox", "my issues", "new issue", "workspace")
        )
    if host == "trello.com":
        return bool(re.search(r"trello\.com/(u/|b/|w/)", href)) and "sign up" not in low[:80]
    if host == "asana.com":
        if "app.asana.com" not in href:
            return False
        if re.search(r"/-/(login|signup)", href):
            return False
        return any(tok in low for tok in ("home", "my tasks", "inbox", "project"))
    if host == "miro.com":
        return "miro.com/app/" in href and any(
            tok in low for tok in ("board", "dashboard", "create new", "untitled")
        )
    return bool(WORKSPACE_URL.search(href))


async def _clear_and_open(page: Any, url: str) -> None:
    try:
        await page.context.clear_cookies()
    except Exception:
        pass
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.evaluate(
            "() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }"
        )
    except Exception:
        pass
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(600)


async def _drive(page: Any, ident: dict[str, str], deadline: float, steps: list[str]) -> str:
    host = ident["host"]
    email_at: float | None = None
    emailed = False
    mail_used = False
    captcha_waited = False
    stuck = 0
    last_sig = ""
    while time.time() < deadline:
        snap = await _snap(page)
        href = str(snap.get("href") or "")
        buttons = list(snap.get("buttons") or [])
        fields = list(snap.get("fields") or [])
        kinds = [_field_kind(f) for f in fields]
        sig = f"{urlparse(href).path}|{','.join(kinds)}|{buttons[:6]}"
        if sig == last_sig:
            stuck += 1
        else:
            stuck = 0
            last_sig = sig
        steps.append(_safe_step(f"{urlparse(href).path or '/'} kinds={kinds[:6]}"))
        if _workspace_ready(host, snap):
            return "signed_up"
        body = str(snap.get("body") or "")
        if stuck == 2:
            steps.append(_body_hint(body))
        if "/auth/error" in href:
            steps.append(_body_hint(body))
            return "auth_error"
        if host == "tldraw.com" and emailed and "email" not in kinds and "code" not in kinds:
            # The share dialog posts to Clerk sign-in. Unknown emails are rejected
            # and the dialog closes; there is no email sign-up control on the canvas.
            return "sign_in_only"
        if emailed and _WORK_REJECT.search(body) and "email" in kinds and "password" not in kinds:
            if stuck >= 2:
                steps.append(_body_hint(body))
                return "work_email_rejected"
        if _PHONE_HINT.search(body) and "phone" in kinds and "email" not in kinds:
            return "phone_required"

        # Cookie banners sit on top of Miro/Asana submit buttons.
        if not emailed:
            banner = await _click_button(
                page,
                re.compile(r"^(reject all|accept all cookies|accept all)$", re.I),
                avoid_oauth=True,
            )
            if banner:
                steps.append(f"click:{banner}")
                await page.wait_for_timeout(300)
                continue

        # Prefer the email path over Google on the first screen (Linear, tldraw).
        if not emailed and "email" not in kinds:
            label = await _click_button(page, _EMAIL_PATH)
            if label:
                steps.append(f"click:{label}")
                await page.wait_for_timeout(400)
                continue
            if host == "tldraw.com":
                label = await _click_button(
                    page, re.compile(r"^sign in", re.I), avoid_oauth=True
                )
                if label:
                    steps.append(f"click:{label}")
                    await page.wait_for_timeout(400)
                    continue

        if "email" in kinds and not emailed:
            if not await _fill_kind(page, "email", ident["email"]):
                return "email_field_missing"
            steps.append("typed:email")
            email_at = time.time()
            # "Continue with email" is the reveal button. Clicking it again makes
            # Linear answer "trying to login too fast". Enter submits the field.
            label = await _click_ranked_submit(page, allow_email_path=False)
            if not label:
                try:
                    await page.locator("[data-sis-target='1']").press("Enter")
                    label = "Enter"
                except Exception:
                    label = None
            if not label:
                try:
                    await page.keyboard.press("Enter")
                    label = "Enter"
                except Exception:
                    return "submit_missing"
            steps.append(f"click:{label}")
            emailed = True
            await page.wait_for_timeout(800)
            continue

        visible_challenge = bool(snap.get("captcha")) and bool(
            re.search(r"i['’]m not a robot|verify you are human|complete the captcha", body, re.I)
        )
        if visible_challenge and emailed and not captcha_waited:
            captcha_waited = True
            steps.append("wait:captcha")
            await page.wait_for_timeout(8000)
            continue
        if visible_challenge and captcha_waited and stuck >= 3:
            return "captcha_unsolved"

        needs_mail = emailed and not mail_used and (
            "code" in kinds
            or (
                "email" not in kinds
                and "password" not in kinds
                and (
                    bool(_CODE_HINT.search(body))
                    or host == "miro.com"
                )
            )
        )
        if needs_mail and email_at is not None:
            left = max(1.0, deadline - time.time() - 8.0)
            found = await _poll_mail(ident["email"], host, email_at - 5, min(35.0, left))
            if not found:
                return "email_timeout"
            kind, payload = found
            steps.append(f"mail:{kind}")
            mail_used = True
            if kind == "link":
                await page.goto(payload, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(700)
                continue
            if not await _enter_code(page, payload):
                return "code_field_missing"
            steps.append("typed:code")
            label = await _click_ranked_submit(page)
            if label:
                steps.append(f"click:{label}")
            else:
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
            await page.wait_for_timeout(700)
            continue

        if "password" in kinds:
            if not await _fill_kind(page, "password", ident["password"]):
                steps.append("fill_failed:password")
                if stuck >= 3:
                    steps.append(_body_hint(body))
                    return "password_field_missing"
                await page.wait_for_timeout(400)
                continue
            steps.append("typed:password")
            if "name" in kinds:
                await _fill_kind(page, "name", ident["full_name"])
                steps.append("typed:name")
            try:
                await page.evaluate(
                    """() => {
                      document.querySelectorAll('input[type=checkbox]').forEach(el => {
                        if (!el.checked) el.click();
                      });
                    }"""
                )
            except Exception:
                pass
            label = await _click_ranked_submit(page)
            if label:
                steps.append(f"click:{label}")
            else:
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
            await page.wait_for_timeout(700)
            continue

        if "name" in kinds or "workspace" in kinds:
            if "name" in kinds:
                await _fill_kind(page, "name", ident["full_name"])
                steps.append("typed:name")
            if "workspace" in kinds:
                await _fill_kind(page, "workspace", ident["company"])
                steps.append("typed:workspace")
            label = await _click_ranked_submit(page) or await _click_button(page, _SKIP)
            if label:
                steps.append(f"click:{label}")
                await page.wait_for_timeout(500)
                continue

        label = await _click_button(page, _SKIP)
        if label:
            steps.append(f"click:{label}")
            await page.wait_for_timeout(400)
            continue

        if emailed and stuck >= 3 and "email" in kinds and snap.get("captcha"):
            return "captcha_unsolved"
        if stuck >= 4:
            return "stuck"
        await page.wait_for_timeout(500)
    return "timeout"


async def signup_in_session(
    page: Any,
    site_url: str,
    persona: dict[str, Any] | None = None,
    *,
    timeout_s: float | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Sign up on ``site_url`` using the caller's existing Playwright ``page``.

    Returns ``{ok, reason, email, elapsed_s, steps}``. ``steps`` never contains
    the mailbox or the password. ``email`` is the fresh alias that was used.
    """
    started = time.time()
    host = host_for_url(site_url or "")
    if host.endswith(".tldraw.com"):
        host = "tldraw.com"
    limit = float(timeout_s if timeout_s is not None else os.environ.get("MVP_SIGNUP_IN_SESSION_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    limit = max(5.0, min(90.0, limit))
    steps: list[str] = []
    alias_tag = tag or f"{host.split('.')[0][:12]}{os.urandom(3).hex()}"
    try:
        ident = fresh_alias(host, persona, tag=alias_tag)
    except Exception as exc:
        return _public_result(
            ok=False,
            reason="identity_error",
            email="",
            started=started,
            steps=[type(exc).__name__],
        )
    email = ident["email"]
    try:
        await asyncio.wait_for(
            _clear_and_open(page, start_url_for(site_url)),
            timeout=max(1.0, limit - (time.time() - started)),
        )
        steps.append(f"open:{host}")
        reason = await asyncio.wait_for(
            _drive(page, ident, started + limit, steps),
            timeout=max(1.0, limit - (time.time() - started)),
        )
    except asyncio.TimeoutError:
        reason = "timeout"
    except Exception as exc:
        reason = "error"
        steps.append(type(exc).__name__)
    ok = reason == "signed_up"
    return _public_result(
        ok=ok,
        reason=reason,
        email=email,
        started=started,
        steps=steps,
        alias_tag=ident["alias_tag"],
    )
