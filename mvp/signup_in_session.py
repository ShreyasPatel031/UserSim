"""In-run signup on the agent's own Playwright page.

``signup_in_session(page, site_url, persona)`` is called by the step loop when a
task needs an account (login/signup wall). It drives the SAME page through a
generic, model-guided signup:

  read the page (interactive elements, indexed)  ->  one Gemini call picks a few
  form actions  ->  run them  ->  re-read ...

using a fresh Gmail plus-alias inbox (``mvp.signup_inbox``; Gmail only, no
throwaway inboxes, fails loudly without GMAIL_USER/GMAIL_APP_PASSWORD), reading the emailed code or
magic link, clearing a captcha only when one actually blocks the form, and then
walking onboarding until the signed-in product workspace loads. A reload must
still show the workspace before it counts as ``ok``.

There are no per-site scripts. ``SITE_HINTS`` holds one-line hints at most.
OAuth / SSO buttons (Google, Microsoft, Apple, Slack, GitHub, SAML) are hidden
from the model so it always uses the email path.

Returns ``{ok, reason, email, inbox, elapsed_s, final_url, evidence, steps,
captcha}``. ``steps`` never contains the password.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import string
import time
from typing import Any
from urllib.parse import urljoin, urlparse

DEFAULT_TIMEOUT_S = 240.0

# Small, optional hints only. No selectors, no scripted moves.
SITE_HINTS: dict[str, str] = {}

_OAUTH = re.compile(
    r"\b(google|microsoft|apple|slack|saml|sso|office\s*365|office365|github|gitlab|"
    r"facebook|passkey|okta|atlassian account|chatgpt|single sign)\b",
    re.I,
)
_AUTH_PATH = re.compile(
    r"/(log-?in|sign-?in|sign-?up|register|join|create-account|auth|verify|signup|"
    r"account/create|onboarding|welcome|get-started|invite)(\b|/|$|\?)",
    re.I,
)


_ONBOARDING_PATH = re.compile(
    r"/(welcome|onboarding|setup|get-started|getting-started|account_setup|account-setup|"
    r"invite|join|signup|sign-up|login|verify)(\b|/|$)",
    re.I,
)

_OAUTH_HOST = re.compile(
    r"(^|\.)(accounts\.google\.com|login\.microsoftonline\.com|login\.live\.com|appleid\.apple\.com|"
    r"github\.com|slack\.com|facebook\.com|okta\.com)$",
    re.I,
)

_ERROR_TEXT = re.compile(
    r"unable to verify|please refresh|try again|something went wrong|too many (requests|attempts)|"
    r"too fast|temporarily blocked|not allowed to sign up|invalid email|email (address )?is not valid|"
    r"disposable|use a (work|different) email",
    re.I,
)


_COOKIE = re.compile(
    r"^(reject all( cookies)?|accept all( cookies)?|allow all( cookies)?|accept cookies|"
    r"only necessary|necessary only|reject non-essential|decline all|i accept|agree( and close)?)$",
    re.I,
)

_EMAIL_REJECT = re.compile(
    r"invalid email domain|email domain (is )?not (allowed|supported)|disposable|temporary email|"
    r"couldn['’]t create your account|please try again later|use a (work|business|different) email( address)?( (to|instead))?|"
    r"email (address )?(is )?not (valid|allowed|accepted)|we (can(no|')t|are unable to) (accept|reach)|"
    r"could not reach the email|try again with a different email|"
    r"users? from this domain (is |are )?(blocked|not allowed)|domain (is |are )?blocked",
    re.I,
)


def _host(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _site(url: str) -> str:
    """Registrable-ish domain: last two labels (linear.app, trello.com, notion.so)."""
    parts = _host(url).split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else _host(url)


def _gen_password() -> str:
    core = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
    return f"Us{core}!7q"


def _identity(persona: dict[str, Any] | None, email: str) -> dict[str, str]:
    persona = persona or {}
    raw = str(persona.get("full_name") or persona.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]+ [A-Za-z][A-Za-z'\-]+", raw):
        raw = "Sam Rivera"
    first, last = raw.split(" ", 1)
    role = str(persona.get("role") or persona.get("job") or "Product manager")[:40]
    company = str(persona.get("company") or "Rivera Labs")[:40]
    return {
        "email": email,
        "password": _gen_password(),
        "full_name": raw,
        "first_name": first,
        "last_name": last,
        "company": company,
        "workspace": re.sub(r"[^a-z0-9]", "", company.lower())[:12] + secrets.token_hex(2),
        "role": role,
        "code": "",
    }


# ---------------------------------------------------------------- page read

_SNAPSHOT_JS = r"""
() => {
  const OUT = [];
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') return false;
    // OTP widgets overlay a transparent <input> on drawn boxes: keep inputs.
    if (Number(s.opacity) === 0 && !['INPUT', 'TEXTAREA'].includes(el.tagName)) return false;
    // Honeypots / password-manager decoys: aria-hidden, untabbable, not clickable.
    if (el.closest('[aria-hidden="true"]') && !el.closest('[role="dialog"]')) return false;
    if (el.tabIndex < 0 && s.pointerEvents === 'none') return false;
    return true;
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const labelFor = (el) => {
    let t = el.getAttribute('aria-label') || '';
    if (!t && el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) t = l.innerText;
    }
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    if (!t && el.getAttribute('aria-labelledby')) {
      t = el.getAttribute('aria-labelledby').split(/\s+/).map(id => (document.getElementById(id) || {}).innerText || '').join(' ');
    }
    return clean(t).slice(0, 80);
  };
  document.querySelectorAll('[data-sis-i]').forEach(el => el.removeAttribute('data-sis-i'));
  const sel = 'input, textarea, select, button, a[href], [role="button"], [role="link"], [role="checkbox"], [role="radio"], [role="option"], [role="menuitem"], [role="tab"], [role="combobox"], [role="switch"], [contenteditable="true"], label';
  const seen = new Set();
  let i = 0;
  const walk = (root) => {
    for (const el of root.querySelectorAll(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute('type') || '').toLowerCase();
      if (type === 'hidden') continue;
      const isBox = type === 'checkbox' || type === 'radio';
      // Custom checkboxes hide the input; keep it if its label is visible.
      if (!vis(el) && !(isBox && el.closest('label') && vis(el.closest('label')))) continue;
      if (tag === 'label' && el.querySelector('input,button,select,textarea')) {
        // label wrapping a control: the control is listed on its own
        const inner = el.querySelector('input[type=checkbox],input[type=radio]');
        if (!inner || vis(inner)) continue;
      } else if (tag === 'label') continue;
      const r = el.getBoundingClientRect();
      const role = el.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'select' ? 'select' : ['input','textarea'].includes(tag) ? (isBox ? type : 'textbox') : tag);
      let name = labelFor(el);
      if (!name && !['input','textarea','select'].includes(tag)) name = clean(el.innerText || el.getAttribute('title') || el.getAttribute('value') || (el.querySelector('img[alt]')||{}).alt || '').slice(0, 80);
      if (!name && tag === 'input' && ['submit','button'].includes(type)) name = clean(el.value);
      const item = {i, tag, role, name};
      if (['input','textarea'].includes(tag)) {
        item.type = type || 'text';
        item.placeholder = clean(el.getAttribute('placeholder')).slice(0, 60);
        item.field = [el.getAttribute('name'), el.id, el.getAttribute('autocomplete')].filter(Boolean).join(' ').slice(0, 60);
        if (isBox) item.checked = !!el.checked; else item.filled = (el.value || '').length;
        if (el.maxLength > 0 && el.maxLength < 10) item.maxlength = el.maxLength;
        if (el.required) item.required = true;
      }
      if (tag === 'select') item.options = [...el.options].slice(0, 12).map(o => clean(o.text)).join(' | ');
      if (el.getAttribute('aria-checked')) item.checked = el.getAttribute('aria-checked') === 'true';
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') item.disabled = true;
      if (tag === 'a') item.href = (el.getAttribute('href') || '').slice(0, 90);
      if (r.bottom < 0 || r.top > innerHeight) item.offscreen = true;
      el.setAttribute('data-sis-i', String(i));
      OUT.push(item);
      i += 1;
      if (i >= 140) return;
    }
    for (const el of root.querySelectorAll('*')) { if (el.shadowRoot && i < 140) walk(el.shadowRoot); }
  };
  walk(document);
  const frames = [...document.querySelectorAll('iframe')].filter(vis).map(f => f.src || '').filter(Boolean);
  // Invisible widgets (reCAPTCHA badge, size=invisible) do not block a form.
  const cap = frames.filter(s => !/size=invisible/i.test(s))
    .find(s => /recaptcha|hcaptcha|turnstile|challenges\.cloudflare|arkoselabs|funcaptcha|captcha/i.test(s)) || '';
  const body = clean(document.body ? document.body.innerText : '').slice(0, 2200);
  return {url: location.href, title: document.title, elements: OUT, captcha: cap, body};
}
"""


async def _snapshot(page: Any) -> dict[str, Any]:
    for _ in range(3):
        try:
            data = await asyncio.wait_for(page.evaluate(_SNAPSHOT_JS), timeout=8)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        try:
            await page.wait_for_timeout(700)
        except Exception:
            break
    return {"url": getattr(page, "url", ""), "title": "", "elements": [], "captcha": "", "body": ""}


def _visible_elements(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Drop OAuth/SSO buttons so the model can only take the email path."""
    out = []
    for el in snap.get("elements") or []:
        name = str(el.get("name") or "")
        if el.get("role") in {"button", "link"} and _OAUTH.search(name) and "email" not in name.lower():
            continue
        out.append(el)
    return out


def _fmt_elements(elements: list[dict[str, Any]]) -> str:
    lines = []
    for el in elements[:120]:
        bits = [f"[{el['i']}] {el.get('role')}"]
        if el.get("type") and el.get("type") not in {"text"}:
            bits.append(f"type={el['type']}")
        if el.get("name"):
            bits.append(json.dumps(el["name"]))
        for k in ("placeholder", "field", "options", "href", "maxlength"):
            if el.get(k):
                bits.append(f"{k}={json.dumps(el[k]) if isinstance(el[k], str) else el[k]}")
        if "filled" in el:
            bits.append(f"filled={el['filled']}")
        if "checked" in el:
            bits.append(f"checked={el['checked']}")
        if el.get("disabled"):
            bits.append("disabled")
        if el.get("offscreen"):
            bits.append("offscreen")
        lines.append(" ".join(bits))
    return "\n".join(lines)


def _page_sig(snap: dict[str, Any]) -> str:
    els = snap.get("elements") or []
    return "|".join(
        [
            urlparse(str(snap.get("url") or "")).path,
            str(len(els)),
            ",".join(f"{e.get('role')}:{e.get('name','')[:20]}:{e.get('filled','')}:{e.get('checked','')}" for e in els[:30]),
            str(snap.get("body") or "")[:300],
        ]
    )


def _has_password_or_email_field(snap: dict[str, Any]) -> bool:
    for el in snap.get("elements") or []:
        if el.get("tag") != "input":
            continue
        blob = f"{el.get('type')} {el.get('name')} {el.get('placeholder')} {el.get('field')}".lower()
        if el.get("type") == "password" or "email" in blob:
            return True
    return False


# ---------------------------------------------------------------- model

def _model() -> str:
    return (os.environ.get("MVP_SIGNUP_IN_SESSION_MODEL") or "gemini-2.5-flash").strip()


_RULES = """You are signing up for a NEW account on a website, in a real browser, and must end
inside the signed-in product (its app/workspace/dashboard/editor), ready to use it.
Reply with ONE JSON object only:
{"thought":"short","status":"working|need_email|signed_in|blocked","reason":"",
 "actions":[{"do":"fill|click|check|select|press|goto|scroll|wait","i":0,"value":""}]}

Rules:
- Use the email path. OAuth/SSO buttons are hidden and must not be used.
- Values: write {email} {password} {full_name} {first_name} {last_name} {company}
  {workspace} {role} {code} literally; they are substituted. Other free text is fine
  (onboarding answers, e.g. team size "1-10", use case "project management").
- One screen at a time: fill every field on the CURRENT form (and tick required
  terms/consent checkboxes), then click its submit button, in one actions list
  (max 8). Do not click the same submit twice if the page is still loading: use wait.
- If a sign-in form is shown, look for a "Sign up"/"Create account"/"Get started"
  link; if the site has no signup link on this page, click the header's
  Sign up / Get started / Try free control. "goto" (value=absolute URL) only for a
  same-site signup URL you can see as an href.
- status=need_email when the page says a code or link was emailed and waits for it
  (a code input is visible or "check your email"). Once the code is known it is
  given to you as {code}: fill it into the code box(es) and continue.
- Onboarding after the account exists: answer with short plausible values, choose
  the free plan/"skip"/"not now"/"continue" for invites, integrations, desktop apps,
  and upsells. Pick any template if forced. Keep going until the app itself loads.
  If an onboarding tour stalls, exit it with Close / X / Skip / Escape.
- status=signed_in only when the logged-in app is on screen (workspace, dashboard,
  boards, issues, documents, canvas with an account/avatar control) and no more
  onboarding steps or forms are pending.
- status=blocked with reason in {phone_required, captcha, email_rejected,
  payment_required, account_exists, site_error, no_signup} only when you cannot
  continue by any control on the page. A visible captcha checkbox => reason captcha.
- If the page shows an error such as "unable to verify", "try again", or "refresh",
  that is NOT need_email: reload by goto-ing the current URL once, then retry.
- Never type anything into search boxes. Never log in to an existing account."""


async def _decide(
    *, snap: dict[str, Any], ident: dict[str, str], site_url: str, history: list[str],
    note: str, hint: str, dead_names: set[str] | None = None,
) -> dict[str, Any] | None:
    from capability.gemini_config import extract_json, gemini_chat

    elements = [
        e for e in _visible_elements(snap)
        if not (dead_names and e.get("role") in {"button", "link", "tab", "menuitem"} and str(e.get("name") or "")[:40] in dead_names)
    ]
    known = {k: ("(type {password})" if k == "password" else v) for k, v in ident.items() if v}
    prompt = (
        f"{_RULES}\n\nSite: {site_url}\n"
        + (f"Hint: {hint}\n" if hint else "")
        + f"Identity (use placeholders): {json.dumps(known)}\n"
        f"URL: {snap.get('url')}\nTitle: {snap.get('title')}\n"
        f"Captcha iframe: {snap.get('captcha') or 'none'}\n"
        f"Visible text: {str(snap.get('body') or '')[:1800]}\n"
        f"Elements:\n{_fmt_elements(elements)}\n"
        f"Done so far: {' ; '.join(history[-10:]) or 'nothing'}\n"
        f"{note}\n"
    )
    for attempt in range(3):
        try:
            raw = await asyncio.wait_for(
                gemini_chat([{"role": "user", "content": prompt}], model=_model(), temperature=0.4 * attempt,
                            json_mode=True, max_retries=2),
                timeout=40,
            )
            data = extract_json(raw)
            if isinstance(data, dict):
                return data
        except Exception as exc:  # noqa: BLE001
            print(f"[signup] model call failed: {exc!r}", flush=True)
    return None


_VERIFY = """Is this browser page the SIGNED-IN product application (e.g. a workspace,
dashboard, board, issue list, document editor, or canvas that belongs to a logged-in
user), as opposed to a marketing page, a login/signup/verify form, or an onboarding
step (welcome, profile setup, invite teammates, connect tools, pick a plan, survey)
that still needs answers? Onboarding steps are NOT signed_in. Reply JSON {"signed_in":true|false,
"evidence":"one sentence naming what on the page shows it"}."""


async def _verify_signed_in(snap: dict[str, Any]) -> tuple[bool, str]:
    from capability.gemini_config import extract_json, gemini_chat

    url = str(snap.get("url") or "")
    elements = _visible_elements(snap)
    prompt = (
        f"{_VERIFY}\nURL: {url}\nTitle: {snap.get('title')}\n"
        f"Visible text: {str(snap.get('body') or '')[:1800]}\n"
        f"Elements:\n{_fmt_elements(elements[:80])}\n"
    )
    try:
        raw = await asyncio.wait_for(
            gemini_chat([{"role": "user", "content": prompt}], model=_model(), temperature=0,
                        json_mode=True, max_retries=2),
            timeout=40,
        )
        data = extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        return False, f"verify failed: {exc!r}"[:160]
    return bool(isinstance(data, dict) and data.get("signed_in")), str((data or {}).get("evidence") or "")[:200]


_OTP_JS = r"""
() => {
  const ok = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden' && !el.disabled; };
  const inputs = [...document.querySelectorAll('input')].filter(ok).filter(el => {
    const t = (el.type || 'text').toLowerCase();
    const blob = [el.name, el.id, el.placeholder, el.autocomplete, el.getAttribute('aria-label')].join(' ').toLowerCase();
    return ['text', 'tel', 'number', ''].includes(t) && !/email|search|name|phone/.test(blob);
  });
  const pick = inputs.find(el => (el.autocomplete || '').includes('one-time-code'))
    || inputs.find(el => /otp|code|verif|pin/.test([el.name, el.id, el.placeholder, el.getAttribute('aria-label')].join(' ').toLowerCase()))
    || inputs.find(el => el.maxLength === 1) || inputs.find(el => el.inputMode === 'numeric') || null;
  document.querySelectorAll('[data-sis-otp]').forEach(e => e.removeAttribute('data-sis-otp'));
  if (!pick) return '';
  pick.setAttribute('data-sis-otp', '1');
  return 'ok';
}
"""


async def _type_code(page: Any, code: str) -> bool:
    """Type the emailed code into the page's code box (single or split boxes)."""
    try:
        found = await page.evaluate(_OTP_JS)
    except Exception:
        found = ""
    if found != "ok":
        return False
    loc = page.locator("[data-sis-otp='1']").first
    try:
        await loc.click(timeout=3000, force=True)
        await page.keyboard.type(code, delay=70)
        return True
    except Exception:
        return False


async def _pick_link(mail: dict[str, Any]) -> str:
    """Pick the confirmation/magic link. One cheap model call when there are several."""
    links = list(mail.get("links") or [])
    if len(links) <= 1:
        return links[0]
    from capability.gemini_config import extract_json, gemini_chat

    texts = list(mail.get("link_texts") or [""] * len(links))
    listing = "\n".join(f"{i}: [{texts[i] if i < len(texts) else ''}] {u[:140]}" for i, u in enumerate(links))
    prompt = (
        "A signup verification email arrived. Which link confirms the email / signs the user in "
        "/ continues account setup? Reply JSON {\"i\": n}.\n"
        f"Subject: {mail.get('subject')}\nBody: {str(mail.get('text') or '')[:1200]}\nLinks:\n{listing}"
    )
    try:
        raw = await asyncio.wait_for(
            gemini_chat([{"role": "user", "content": prompt}], model=_model(), temperature=0, json_mode=True, max_retries=2),
            timeout=30,
        )
        i = int(extract_json(raw).get("i"))
        if 0 <= i < len(links):
            return links[i]
    except Exception:
        pass
    return links[0]


# ---------------------------------------------------------------- actions

def _subst(value: str, ident: dict[str, str]) -> str:
    out = str(value or "")
    for key, val in ident.items():
        out = out.replace("{" + key + "}", val or "")
    return out


def _redact(text: str, ident: dict[str, str]) -> str:
    pw = ident.get("password") or ""
    return text.replace(pw, "<password>") if pw else text


async def _do(page: Any, act: dict[str, Any], ident: dict[str, str], elements: dict[int, dict[str, Any]], home_site: str = "") -> str:
    kind = str(act.get("do") or "").lower()
    value = _subst(str(act.get("value") or ""), ident)
    try:
        idx = int(act.get("i")) if act.get("i") is not None and str(act.get("i")).strip() != "" else None
    except (TypeError, ValueError):
        idx = None
    el = elements.get(idx) if idx is not None else None
    loc = page.locator(f"[data-sis-i='{idx}']").first if idx is not None else None
    if kind in {"click", "check", "fill", "select"} and el is None:
        return f"{kind} [{idx}] missing"
    name = str((el or {}).get("name") or "")[:40]
    if kind in {"click", "check"} and el is not None and el.get("role") in {"button", "link"} and _OAUTH.search(name) and "email" not in name.lower():
        return f"refused oauth {name}"
    if kind == "fill":
        if el.get("maxlength") == 1:
            # split OTP boxes: type the whole code starting at the first box
            await loc.click(timeout=3000)
            await page.keyboard.type(value, delay=60)
            return f"typed {len(value)} chars into split boxes"
        try:
            # Type like a person: bot checks score instant fill() as automation.
            await loc.click(timeout=3000)
            await loc.fill("", timeout=2000)
            await page.keyboard.type(value, delay=35 if len(value) < 60 else 5)
        except Exception:
            await loc.fill(value, timeout=4000)
        try:
            got = await loc.input_value(timeout=1500)
            if got != value:
                await loc.click(timeout=2000)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await page.keyboard.type(value, delay=20)
        except Exception:
            pass
        field = name or el.get("placeholder") or el.get("field") or "field"
        shown = act.get("value") if "{" in str(act.get("value") or "") else value[:30]
        return f"fill {field!s:.30} = {shown}"
    if kind == "check":
        try:
            if el.get("checked"):
                return f"already checked {name}"
            try:
                await loc.check(timeout=3000, force=True)
            except Exception:
                await loc.click(timeout=3000, force=True)
        except Exception:
            # hidden input: click its label
            await page.locator(f"label:has([data-sis-i='{idx}'])").first.click(timeout=3000)
        return f"check {name}"
    if kind == "select":
        try:
            await loc.select_option(label=value, timeout=3000)
        except Exception:
            await loc.select_option(value=value, timeout=3000)
        return f"select {name} = {value[:30]}"
    if kind == "click":
        try:
            live = await loc.evaluate(
                "el => ((el.getAttribute('aria-label') || el.innerText || el.value || '') + '').replace(/\\s+/g, ' ').trim().slice(0, 80)",
                timeout=1500,
            )
        except Exception:
            live = None
        want = str(el.get("name") or "")
        words = lambda t: {w for w in re.findall(r"[a-z0-9]{3,}", t.lower())}  # noqa: E731
        if live is not None and want and live and not (words(want) & words(live)) and want[:25].lower() not in live.lower():
            return f"skipped stale [{idx}] (now {live[:30]!r})"
        if live and _OAUTH.search(live) and "email" not in live.lower():
            return f"refused oauth {live[:30]}"
        try:
            await loc.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            await loc.click(timeout=4000)
        except Exception:
            await loc.click(timeout=3000, force=True)
        return f"click {el.get('role')} {name!r}"
    if kind == "press":
        await page.keyboard.press(value or "Enter")
        return f"press {value or 'Enter'}"
    if kind == "goto":
        target = urljoin(page.url, value)
        if _site(target) not in {_site(page.url), home_site} or _OAUTH_HOST.search(_host(target)):
            return f"refused off-site goto {target[:60]}"
        await page.goto(target, wait_until="domcontentloaded", timeout=30000)
        return f"goto {target[:80]}"
    if kind == "scroll":
        await page.mouse.wheel(0, 600)
        return "scroll"
    if kind == "wait":
        await page.wait_for_timeout(2000)
        return "wait"
    return f"unknown action {kind}"


async def _settle(page: Any, ms: int = 900) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    try:
        await page.wait_for_timeout(ms)
    except Exception:
        pass


# ---------------------------------------------------------------- captcha

def _capsolver_key() -> str:
    return (
        os.environ.get("CAPSOLVER_API_KEY")
        or os.environ.get("MVP_CAPTCHA_API_KEY")
        or ""
    ).strip()


async def _recaptcha_anchor_checked(page: Any) -> bool:
    """True when a reCAPTCHA v2 anchor frame shows the checkbox as checked.

    Falls back to the response-token check only when no anchor frame exists.
    """
    anchors = [
        f for f in getattr(page, "frames", []) or []
        if re.search(r"recaptcha/(api2|enterprise)/anchor", (f.url or "").lower())
    ]
    if not anchors:
        from mvp import captcha as cap

        return bool(await cap._recaptcha_solved(page))
    for frame in anchors:
        try:
            if (await frame.locator("#recaptcha-anchor").first.get_attribute("aria-checked", timeout=1500)) == "true":
                return True
        except Exception:
            continue
    return False


async def _captcha_frame_visible(page: Any) -> bool:
    """A visible (non-invisible) captcha/challenge iframe is still on the page."""
    try:
        return bool(await page.evaluate(
            """() => [...document.querySelectorAll('iframe')].some(f => {
                 const r = f.getBoundingClientRect();
                 const s = f.src || '';
                 return r.width > 20 && r.height > 20 && !/size=invisible/i.test(s)
                   && /recaptcha|hcaptcha|turnstile|challenges\\.cloudflare|arkoselabs|funcaptcha|captcha/i.test(s);
               })"""
        ))
    except Exception:
        return False


async def _clear_captcha(page: Any, snap: dict[str, Any], spend: dict[str, Any]) -> dict[str, Any]:
    """Free clicks first; CapSolver only with a key and only under the per-site cap."""
    from mvp import captcha as cap

    out: dict[str, Any] = {"type": snap.get("captcha", "")[:80], "ok": False, "method": ""}
    ctype = str(snap.get("captcha") or "").lower()
    try:
        # Only a checked anchor counts. Calendly (reCAPTCHA Enterprise v2 on
        # recaptcha.net) also carries a filled g-recaptcha-response from an
        # invisible widget, so "token present" said ok while the image
        # challenge was still open, and CapSolver was never reached.
        if await cap._click_recaptcha_checkbox(page) and await _recaptcha_anchor_checked(page):
            out.update(ok=True, method="recaptcha_checkbox")
            return out
    except Exception:
        pass
    if "recaptcha" in str(snap.get("captcha") or "") and os.environ.get("MVP_SIGNUP_AUDIO_CAPTCHA", "1") != "0":
        from mvp.signup_captcha_audio import solve_recaptcha_audio

        try:
            res = await asyncio.wait_for(solve_recaptcha_audio(page), timeout=90)
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "method": "audio", "detail": repr(exc)[:120]}
        out["audio"] = res
        if res.get("ok"):
            out.update(ok=True, method=str(res.get("method")))
            return out
    # The Turnstile helper clicks any control whose text mentions "human" or
    # "verify" and reports True. On a reCAPTCHA/hCaptcha page that is a false
    # "solved", so only use it for Cloudflare widgets and only count it when
    # the challenge iframe is gone afterwards.
    if not ctype or "turnstile" in ctype or "cloudflare" in ctype:
        try:
            if await cap._try_click_cloudflare_checkbox(page):
                await page.wait_for_timeout(4000)
                if not await _captcha_frame_visible(page):
                    out.update(ok=True, method="turnstile_click")
                    return out
        except Exception:
            pass
    if not _capsolver_key():
        out["method"] = "no_capsolver_key"
        return out
    cap_usd = float(os.environ.get("MVP_SIGNUP_CAPTCHA_SITE_CAP_USD", "1.50"))
    if spend.get("usd", 0.0) + 0.003 > cap_usd:
        out["method"] = "site_cap_reached"
        return out
    # The CapSolver spend gate refuses any solve that is not bound to a site and
    # an attempt ("host_not_paid" / "no_signup_attempt"). Bind this in-run
    # signup so a blocking captcha on an allowlisted host can be paid for.
    site = str(spend.get("site") or "")
    if site:
        try:
            from mvp import captcha_spend as cs

            if not spend.get("attempt"):
                spend["attempt"] = cs.begin_inrun_attempt(site)
            else:
                cs.bind_signup(site, int(spend["attempt"]))
        except Exception as exc:  # noqa: BLE001
            out["spend_bind_error"] = repr(exc)[:120]
    os.environ.setdefault("MVP_CAPTCHA_API_KEY", _capsolver_key())
    os.environ["MVP_CAPTCHA_BB_WAIT_S"] = "0"
    os.environ["MVP_CAPTCHA_HCAPTCHA_BB_WAIT_S"] = "0"
    try:
        res = await asyncio.wait_for(cap.solve_captcha_on_page(page), timeout=150)
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "method": "solver_error", "detail": repr(exc)[:120]}
    spend["usd"] = spend.get("usd", 0.0) + (0.003 if "capsolver" in str(res.get("method", "")) or "api" in str(res.get("method", "")) else 0.0)
    spend["calls"] = spend.get("calls", 0) + 1
    out.update(ok=bool(res.get("ok")), method=str(res.get("method") or ""), detail=str(res.get("detail") or "")[:120])
    return out


# ---------------------------------------------------------------- main

def _looks_like_app(snap: dict[str, Any]) -> bool:
    url = str(snap.get("url") or "")
    if _AUTH_PATH.search(urlparse(url).path or ""):
        return False
    return not _has_password_or_email_field(snap)


async def signup_in_session(
    page: Any,
    site_url: str,
    persona: dict[str, Any] | None = None,
    *,
    signup_url: str | None = None,
    timeout_s: float | None = None,
    tag: str | None = None,
    on_step: Any | None = None,
) -> dict[str, Any]:
    """Sign up on ``site_url`` in the caller's ``page`` and leave it signed in.

    ``signup_url``: optional URL of the wall the task loop hit (used as the start
    page). The page is left on the signed-in workspace when ``ok`` is True.
    """
    from mvp.signup_inbox import GmailInboxMissing, create_inbox

    started = time.time()
    limit = float(timeout_s or os.environ.get("MVP_SIGNUP_IN_SESSION_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    deadline = started + limit
    site = _site(site_url)
    tag = tag or re.sub(r"[^a-z0-9]", "", site.split(".")[0])[:10]
    steps: list[str] = []
    history: list[str] = []
    captcha_log: list[dict[str, Any]] = []
    spend: dict[str, Any] = {"usd": 0.0, "calls": 0, "site": site}
    ident: dict[str, str] = {}
    last_snap: dict[str, Any] = {}
    result: dict[str, Any] = {
        "ok": False, "reason": "", "email": "", "inbox": "", "elapsed_s": 0.0,
        "final_url": "", "evidence": "", "steps": steps, "captcha": captcha_log,
    }

    def _finish(ok: bool, reason: str, evidence: str = "") -> dict[str, Any]:
        result.update(
            ok=ok, reason=reason, evidence=evidence,
            elapsed_s=round(time.time() - started, 1),
            final_url=str(getattr(page, "url", "") or ""),
            capsolver_usd=round(spend["usd"], 4), capsolver_calls=spend["calls"],
        )
        result["steps"] = [_redact(s, ident) for s in steps][-60:]
        if last_snap:
            result["last_page"] = {
                "url": last_snap.get("url"), "title": last_snap.get("title"),
                "body": str(last_snap.get("body") or "")[:800],
                "elements": _fmt_elements(_visible_elements(last_snap))[:4000],
            }
        print(f"[signup] {site}: ok={ok} reason={reason} {result['elapsed_s']}s", flush=True)
        return result

    try:
        inbox = await asyncio.to_thread(create_inbox, site, tag)
    except GmailInboxMissing as exc:
        print(f"[signup] ERROR {site}: {exc}", flush=True)
        return _finish(False, "gmail_inbox_missing: set GMAIL_USER and GMAIL_APP_PASSWORD")
    except Exception as exc:  # noqa: BLE001
        return _finish(False, f"inbox_error: {exc!r}"[:120])
    ident = _identity(persona, inbox.address)
    result["email"] = inbox.address
    result["inbox"] = inbox.backend
    email_since = time.time()
    seen_mail: set[str] = set()

    # Popups (a signup link that opens a new tab): pull the URL into our page.
    popups: list[Any] = []

    def _on_popup(p: Any) -> None:
        popups.append(p)

    try:
        page.context.on("page", _on_popup)
    except Exception:
        pass

    # Some sites reject the address only in the API response and leave the form
    # unchanged (ClickUp: 400 {"err":"Users from this domain are blocked."}).
    # Without this the loop only sees "page stopped changing".
    api_rejects: list[str] = []

    async def _check_reject(resp: Any) -> None:
        try:
            req = resp.request
            if req.method not in {"POST", "PUT"} or not (400 <= resp.status < 500):
                return
            if _site(resp.url) != site:
                return
            body = (await resp.text())[:400]
        except Exception:
            return
        m = _EMAIL_REJECT.search(body)
        if m:
            api_rejects.append(m.group(0))

    def _on_response(resp: Any) -> None:
        try:
            asyncio.ensure_future(_check_reject(resp))
        except Exception:
            pass

    try:
        page.on("response", _on_response)
    except Exception:
        pass

    try:
        start = signup_url or ""
        cur = str(getattr(page, "url", "") or "")
        if start:
            await page.goto(start, wait_until="domcontentloaded", timeout=30000)
        elif _site(cur) != site or cur.startswith("about:"):
            await page.goto(site_url, wait_until="domcontentloaded", timeout=30000)
        await _settle(page, 1200)
        steps.append(f"start {page.url[:100]}")

        last_sig = ""
        same = 0
        errors_seen = 0
        dead: list[str] = []
        dead_count: dict[str, int] = {}
        empty_waits = 0
        email_submitted = False
        rejects = 0
        banner_clicks = 0
        verifying = 0
        pending_links: list[str] = []
        pending_wait = 0
        url_changed_at = time.time()
        last_url = ""
        note = ""
        email_waits = 0
        while time.time() < deadline:
            if api_rejects:
                dom = ident["email"].split("@")[1] if "@" in ident.get("email", "") else "?"
                steps.append(f"email rejected by the site API: {api_rejects[0]} ({dom})")
                return _finish(False, f"email_rejected: {api_rejects[0]} ({dom})")
            if popups:
                pop = popups.pop(0)
                try:
                    await pop.wait_for_load_state("domcontentloaded", timeout=8000)
                    purl = pop.url
                    if purl and not purl.startswith("about:") and not _OAUTH.search(_host(purl)):
                        await pop.close()
                        await page.goto(purl, wait_until="domcontentloaded", timeout=30000)
                        steps.append(f"popup moved into page {purl[:80]}")
                        await _settle(page)
                except Exception:
                    pass
            snap = await _snapshot(page)
            last_snap.clear()
            last_snap.update(snap)
            if str(snap.get("url")) != last_url:
                last_url = str(snap.get("url"))
                url_changed_at = time.time()
            if _OAUTH_HOST.search(_host(str(snap.get("url") or ""))):
                steps.append(f"landed on OAuth provider {_host(str(snap.get('url')))}; going back")
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    await page.goto(signup_url or site_url, wait_until="domcontentloaded", timeout=30000)
                await _settle(page, 1200)
                note = "The last click opened an OAuth provider. Use the email field and email/password path only."
                continue
            if not (snap.get("elements") or []) and empty_waits < 4:
                empty_waits += 1
                await page.wait_for_timeout(1200)
                continue
            empty_waits = 0
            sig = _page_sig(snap)
            same = same + 1 if sig == last_sig else 0
            last_sig = sig
            if same >= 3:
                body_tour = str(snap.get("body") or "").lower()
                # Trello's Atlassian pre-board tour freezes on "One last thing!" /
                # "Start using Trello". The data-sis-i click often no-ops; force
                # the role click, then Escape/Close, then follow the continue URL.
                if "one last thing" in body_tour or "start using trello" in body_tour:
                    advanced = False
                    for label in (
                        "Mark this card complete (Start using Trello)",
                        "Start using Trello",
                        "One last thing!",
                        "Close",
                        "Next",
                    ):
                        try:
                            btn = page.get_by_role("button", name=label).first
                            if await btn.count() == 0:
                                continue
                            await btn.click(timeout=4000, force=True)
                            steps.append(f"  force-clicked tour control {label!r}")
                            await _settle(page, 1800)
                            advanced = True
                            break
                        except Exception as exc:  # noqa: BLE001
                            steps.append(f"  tour click {label!r} failed: {type(exc).__name__}")
                    if not advanced:
                        try:
                            await page.keyboard.press("Escape")
                            steps.append("  pressed Escape on stuck Trello tour")
                            await _settle(page, 1200)
                            advanced = True
                        except Exception:
                            pass
                    # Still on id.atlassian.com/signup?…&continue=https://trello.com/…
                    if advanced or same >= 5:
                        cur = str(snap.get("url") or page.url or "")
                        if "id.atlassian.com" in cur and "continue=" in cur:
                            from urllib.parse import parse_qs, unquote, urlparse as _up

                            qs = parse_qs(_up(cur).query)
                            cont = unquote((qs.get("continue") or [""])[0])
                            if cont.startswith("http") and "trello.com" in cont:
                                try:
                                    await page.goto(cont, wait_until="domcontentloaded", timeout=30000)
                                    steps.append(f"  followed Atlassian continue → {cont[:80]}")
                                    await _settle(page, 2000)
                                    same = 0
                                    continue
                                except Exception as exc:  # noqa: BLE001
                                    steps.append(f"  continue goto failed: {type(exc).__name__}")
                    if advanced:
                        same = 0
                        continue
            if same >= 8:
                if api_rejects:
                    return _finish(False, f"email_rejected: {api_rejects[0]}")
                return _finish(False, "stuck: page stopped changing")

            if snap.get("captcha") and same >= 1:
                res = await _clear_captcha(page, snap, spend)
                captcha_log.append(res)
                steps.append(f"captcha {res.get('type','')[:40]} -> {res.get('method')} ok={res.get('ok')}")
                if not res.get("ok"):
                    method = str(res.get("method") or "")
                    # Without CapSolver, a second attempt will not help — release the
                    # Browserbase session instead of burning another 60–120s.
                    fails = sum(1 for c in captcha_log if not c.get("ok"))
                    if method in {"no_capsolver_key", "site_cap_reached"} or fails >= 2:
                        return _finish(False, f"captcha_unsolved ({method})")
                await _settle(page)
                continue

            elements = {int(e["i"]): e for e in (snap.get("elements") or [])}
            # Cookie banners cover submit buttons (Miro, Asana). Dismiss them generically.
            banner = next((e for e in elements.values() if e.get("role") in {"button", "link"}
                           and _COOKIE.match(str(e.get("name") or "").strip())), None)
            if banner is not None and banner_clicks < 2:
                banner_clicks += 1
                try:
                    await page.locator(f"[data-sis-i='{banner['i']}']").first.click(timeout=3000)
                    steps.append(f"  dismissed cookie banner ({banner.get('name')})")
                    await _settle(page, 600)
                    continue
                except Exception:
                    pass
            decision = await _decide(
                snap=snap, ident=ident, site_url=site_url, history=history,
                note=note + (
                    "\nThe page did not change after your last actions. Do not repeat them; "
                    f"these had no effect: {'; '.join(dead[-5:])}. Try a different control "
                    "(a primary button, Continue/Next/Skip/Done, Close, or press Escape). Controls "
                    "that failed twice are removed from the list."
                    if same else ""
                ),
                hint=SITE_HINTS.get(site, ""),
                dead_names={n for n, c in dead_count.items() if c >= 2},
            )
            note = ""
            bad = [a for a in (decision or {}).get("actions") or [] if isinstance(a, dict)
                   and str(a.get("do")) in {"fill", "click", "check", "select"}
                   and (a.get("i") is None or str(a.get("i")).lstrip("-").isdigit() and int(a.get("i")) not in elements)]
            if decision and bad and len(bad) == len(decision.get("actions") or []):
                if ident.get("code") and await _type_code(page, ident["code"]):
                    steps.append("  typed emailed code (model could not find the box)")
                    await _settle(page, 1500)
                    continue
                note = ("Your last reply used element numbers that are not in the list. Only use i "
                        "values from the Elements list; if the control you want is not listed, choose "
                        "another listed control, press a key, scroll, or wait.")
                steps.append("  model used unknown element numbers")
                continue
            if not decision:
                steps.append("model gave no decision")
                continue
            status = str(decision.get("status") or "working").lower()
            body_low = str(snap.get("body") or "").lower()
            if status == "need_email" and re.search(r"verifying (it|that)|checking your browser|just a moment", body_low):
                verifying += 1
                if verifying >= 4:
                    return _finish(False, "bot_check: the site's 'verifying it's you' check never cleared")
                steps.append("site is running a bot check; waiting")
                await page.wait_for_timeout(4000)
                continue
            if status == "need_email" and _ERROR_TEXT.search(body_low) and not ident.get("code"):
                m = _ERROR_TEXT.search(body_low)
                note = (f"The page shows an error ({m.group(0)!r}); no email was sent. Reload the "
                        "page (goto the current URL), wait, then fill and submit the form again.")
                steps.append(f"error on page: {m.group(0)}")
                errors_seen += 1
                if errors_seen >= 3:
                    return _finish(False, f"site_error: {m.group(0)}")
                continue
            thought = str(decision.get("thought") or "")[:140]
            steps.append(f"{urlparse(str(snap.get('url'))).netloc}{urlparse(str(snap.get('url'))).path[:50]} :: {status} :: {thought}")
            if on_step is not None:
                try:
                    maybe = on_step({"phase": "signup", "status": status, "thought": thought, "url": snap.get("url")})
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception:
                    pass

            if status == "signed_in":
                ok, evidence = await _verify_signed_in(snap)
                if ok:
                    # A reload must still show the workspace (cookie/session really set).
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    await _settle(page, 2500)
                    snap2 = await _snapshot(page)
                    ok2, evidence2 = await _verify_signed_in(snap2)
                    onboarding = bool(_ONBOARDING_PATH.search(urlparse(str(snap2.get("url"))).path or ""))
                    if ok2 and not _has_password_or_email_field(snap2) and not onboarding:
                        steps.append(f"verified after reload: {evidence2}")
                        return _finish(True, "signed_up", evidence2 or evidence)
                    note = f"After reload the page does not look signed in: {evidence2}"
                else:
                    note = f"Verifier says not yet in the signed-in app: {evidence}. Continue."
                continue

            if status == "blocked":
                reason = str(decision.get("reason") or "blocked")
                if reason == "captcha":
                    res = await _clear_captcha(page, snap, spend)
                    captcha_log.append(res)
                    steps.append(f"captcha -> {res.get('method')} ok={res.get('ok')}")
                    if res.get("ok"):
                        await _settle(page)
                        continue
                    return _finish(False, f"captcha_unsolved ({res.get('method')})")
                return _finish(False, reason)

            rej = _EMAIL_REJECT.search(body_low)
            email_box = any(
                e.get("tag") == "input" and ("email" in f"{e.get('type')} {e.get('name')} {e.get('placeholder')} {e.get('field')}".lower())
                for e in snap.get("elements") or []
            )
            if email_submitted and rej and email_box:
                rejects += 1
                # Gmail is the only inbox; there is nothing to swap to. Two
                # clear rejections of the same Gmail alias end the attempt.
                if rejects >= 2:
                    dom = ident["email"].split("@")[1]
                    steps.append(f"email rejected: {rej.group(0)} ({dom})")
                    return _finish(False, f"email_rejected: {rej.group(0)} ({dom})")
            acts_now = [a for a in (decision.get("actions") or []) if isinstance(a, dict)
                        and str(a.get("do")) not in {"wait"}]
            if ident.get("email") and ident["email"].lower() in (str(snap.get("body")) + " " + str(snap.get("url"))).lower().replace("%40", "@"):
                email_submitted = True
            if status == "need_email" and (acts_now or not email_submitted):
                # The model wants to submit a form first (or no email was typed yet).
                status = "working"
            if status == "need_email" and not ident.get("code"):
                left = max(5.0, min(75.0, deadline - time.time() - 10))
                steps.append(f"waiting for email to {ident['email'].split('@')[1]} (up to {int(left)}s)")
                mail = await asyncio.to_thread(inbox.wait, site, email_since, left, seen_mail)
                email_waits += 1
                if not mail:
                    if email_waits >= 2:
                        return _finish(False, "email_timeout")
                    note = "No email arrived yet. If there is a resend control use it, else wait."
                    continue
                steps.append(f"mail: {mail['subject'][:60]!r} code={'yes' if mail.get('code') else 'no'} links={len(mail.get('links') or [])}")
                code_box = any(
                    e.get("tag") in {"input", "textarea"} and e.get("type") not in {"checkbox", "radio", "password"}
                    and ("email" not in f"{e.get('name')} {e.get('placeholder')} {e.get('field')} {e.get('type')}".lower())
                    for e in snap.get("elements") or []
                )
                code_first = bool(mail.get("code")) and "code" in str(mail.get("subject") or "").lower()
                if mail.get("code") and (code_box or code_first or not mail.get("links")):
                    ident["code"] = mail["code"]
                    if await _type_code(page, mail["code"]):
                        steps.append("  typed emailed code into the code box")
                        history.append("typed the emailed verification code")
                        await _settle(page, 1500)
                        note = ("The emailed code was typed into the code box. If a Verify/Continue "
                                "button is enabled, click it; otherwise wait.")
                    else:
                        note = ("The emailed verification code is available as {code}. Enter it into the "
                                "code field; if this page has none, open the control that lets you enter a code.")
                        pending_links = list(mail.get("links") or [])
                    continue
                if mail.get("links"):
                    link = await _pick_link(mail)
                    await page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    steps.append(f"opened emailed link {_host(link)}{urlparse(link).path[:40]} (of {len(mail['links'])})")
                    await _settle(page, 1500)
                    continue
                if mail.get("code"):
                    ident["code"] = mail["code"]
                    note = "The emailed verification code is available as {code}."
                    continue
                note = f"An email arrived but had no code or link. Subject: {mail['subject'][:80]}"
                continue

            if pending_links and ident.get("code"):
                pending_wait += 1
                if pending_wait >= 3:
                    link = await _pick_link({"links": pending_links, "subject": "", "text": ""})
                    pending_links = []
                    await page.goto(link, wait_until="domcontentloaded", timeout=30000)
                    steps.append(f"no code box appeared; opened emailed link {_host(link)}{urlparse(link).path[:40]}")
                    await _settle(page, 1500)
                    continue
            acts = decision.get("actions") or []
            if same and history:
                for h in history[-3:]:
                    if h.startswith("click"):
                        dead.append(h)
                        m = re.search(r"'(.*)'$|\"(.*)\"$", h)
                        if m:
                            nm = m.group(1) or m.group(2)
                            dead_count[nm] = dead_count.get(nm, 0) + 1
            elif not same:
                dead_count.clear()
            if not isinstance(acts, list) or not acts:
                await page.wait_for_timeout(1200)
                continue
            for act in acts[:8]:
                if not isinstance(act, dict):
                    continue
                try:
                    done = await asyncio.wait_for(_do(page, act, ident, elements, site), timeout=15)
                except Exception as exc:  # noqa: BLE001
                    done = f"{act.get('do')} [{act.get('i')}] failed: {type(exc).__name__}"
                done = _redact(done, ident)
                if str(act.get("do")) == "fill" and "{email}" in str(act.get("value") or "") or (
                    str(act.get("do")) == "fill" and ident.get("email") and ident["email"] in str(act.get("value") or "")
                ):
                    email_submitted = True
                history.append(done)
                steps.append("  " + done)
                if str(act.get("do")) == "fill":
                    # Let invisible bot checks finish before the submit that follows.
                    gap = 2.5 - (time.time() - url_changed_at)
                    if gap > 0:
                        await page.wait_for_timeout(int(gap * 1000))
                if str(act.get("do")) in {"click", "goto", "press"}:
                    await _settle(page, 700)
                    if str(getattr(page, "url", "")) != str(snap.get("url")):
                        break  # new page: re-read before acting again
            await _settle(page, 900)
        return _finish(False, "timeout")
    except Exception as exc:  # noqa: BLE001
        steps.append(f"error {exc!r}"[:160])
        return _finish(False, f"error: {type(exc).__name__}")
    finally:
        try:
            page.context.remove_listener("page", _on_popup)
        except Exception:
            pass
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass
