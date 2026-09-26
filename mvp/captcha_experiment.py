#!/usr/bin/env python3
"""Captcha-type survey and solve trials.

The 60-site fresh score is not updated here. Browserbase sessions are tagged
owner=signup and capped at two. CapSolver calls go through the spend ledger
and stop when the live balance would drop below $1.

Usage:
  PYTHONPATH=src:. .venv/bin/python -m mvp.captcha_experiment detect
  PYTHONPATH=src:. .venv/bin/python -m mvp.captcha_experiment trials --per-type 10
  PYTHONPATH=src:. .venv/bin/python -m mvp.captcha_experiment report
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POOL_PATH = ROOT / "mvp" / "signup_captcha_pool.json"
OUT_DIR = ROOT / "results" / "captcha_spend"
DETECT_PATH = OUT_DIR / "detections.jsonl"
TRIAL_PATH = OUT_DIR / "trials.jsonl"
COUNTS_PATH = OUT_DIR / "type_counts.json"
POLICY_PATH = OUT_DIR / "method_policy.json"

# Prefer a visible checkbox / puzzle over an invisible script include.
TYPE_PRIORITY = (
    "arkose",
    "hcaptcha",
    "geetest",
    "datadome",
    "turnstile",
    "recaptcha_enterprise",
    "recaptcha_v2",
    "recaptcha_v3_enterprise",
    "recaptcha_v3",
    "recaptcha",
    "aws_waf",
    "image_text",
    "slider",
    "cloudflare_challenge",
)

# reCAPTCHA image-classification question ids from CapSolver's docs.
_RECAPTCHA_QUESTIONS = {
    "taxi": "/m/0pg52",
    "bus": "/m/01bjv",
    "school bus": "/m/02yvhj",
    "motorcycle": "/m/04_sv",
    "tractor": "/m/013xlm",
    "chimney": "/m/01jk_4",
    "crosswalk": "/m/014xcs",
    "traffic light": "/m/015qff",
    "bicycle": "/m/0199g",
    "parking meter": "/m/015qbp",
    "car": "/m/0k4j",
    "bridge": "/m/015kr",
    "boat": "/m/019jd",
    "palm tree": "/m/0cdl1",
    "mountain": "/m/09d_r",
    "fire hydrant": "/m/01pns0",
    "stair": "/m/01lynh",
}

PAID_METHODS = {
    "capsolver",
    "capsolver_v2_enterprise",
    "image_to_text",
    "recaptcha_classification",
    "funcaptcha_probe",
}

METHODS_FOR_TYPE = {
    "recaptcha_v2": ["browserbase", "capsolver"],
    "recaptcha": ["browserbase", "capsolver"],
    "recaptcha_enterprise": ["browserbase", "capsolver"],
    "recaptcha_v3": ["browserbase", "capsolver"],
    "recaptcha_v3_enterprise": ["browserbase", "capsolver", "capsolver_v2_enterprise"],
    "turnstile": ["browserbase", "capsolver"],
    "geetest": ["browserbase", "capsolver"],
    "hcaptcha": ["browserbase", "image_to_text", "recaptcha_classification"],
    "arkose": ["browserbase", "mouse_drag", "funcaptcha_probe"],
    "image_text": ["browserbase", "image_to_text"],
    "slider": ["browserbase", "mouse_drag"],
    "datadome": ["browserbase", "mouse_drag"],
    "cloudflare_challenge": ["browserbase"],
    "aws_waf": ["browserbase", "capsolver"],
}


def _experiment_env() -> None:
    os.environ["BROWSERBASE_THROTTLE"] = "1"
    os.environ["BROWSERBASE_MAX_CONCURRENT"] = "2"
    os.environ["BROWSERBASE_CREATE_INTERVAL_S"] = "0.3"
    os.environ["MVP_CAPTCHA_EXPERIMENT"] = "1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yn(flag: bool) -> str:
    return "y" if flag else "n"


def load_pool() -> list[dict[str, Any]]:
    data = json.loads(POOL_PATH.read_text())
    return list(data.get("sites") or [])


def primary_type(types: list[str]) -> str:
    found = set(types or [])
    for name in TYPE_PRIORITY:
        if name in found:
            return name
    return "none"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


_JSONL_LOCK = threading.Lock()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True) + "\n"
    with _JSONL_LOCK:
        with path.open("a") as fh:
            fh.write(line)


_DETECT_JS = r"""
() => {
  const html = (document.documentElement && document.documentElement.innerHTML) || '';
  const text = ((document.body && document.body.innerText) || '').slice(0, 1500);
  const srcs = [...document.querySelectorAll('iframe,script,img')].map(n => n.src || n.getAttribute('src') || '');
  const srcBlob = srcs.join('\n');
  const blob = (html + '\n' + srcBlob).slice(0, 400000);
  const types = [];
  const add = (t) => { if (t && types.indexOf(t) < 0) types.push(t); };
  if (/arkoselabs|funcaptcha/i.test(srcBlob) || document.querySelector('[data-pkey], iframe[src*="arkoselabs"], iframe[src*="funcaptcha"]')) add('arkose');
  if (/hcaptcha/i.test(srcBlob) || document.querySelector('.h-captcha, iframe[src*="hcaptcha"]')) add('hcaptcha');
  if (/challenges\.cloudflare\.com|turnstile/i.test(srcBlob) || document.querySelector('.cf-turnstile, iframe[src*="challenges.cloudflare.com"]')) add('turnstile');
  if (/just a moment/i.test(document.title || '') || (/checking your browser/i.test(text) && text.length < 900)) add('cloudflare_challenge');
  if (/geetest/i.test(srcBlob) || document.querySelector('[class*="geetest"], iframe[src*="geetest"]')) add('geetest');
  if (/captcha-delivery\.com|datadome/i.test(srcBlob)) add('datadome');
  if (/awswaf|aws-waf/i.test(srcBlob) || /gokuProps|awswaf/i.test(blob.slice(0, 80000))) add('aws_waf');
  const widget = /recaptcha/i.test(srcBlob) || !!document.querySelector('.g-recaptcha, iframe[src*="recaptcha"]');
  const bframe = srcs.some(s => /recaptcha\/(?:enterprise\/)?(?:api2\/)?bframe|recaptcha\/api2\/anchor/.test(s));
  const enterprise = /recaptcha\/enterprise|grecaptcha\.enterprise/i.test(srcBlob + blob.slice(0, 20000));
  const v3 = /recaptcha\/api\.js\?render=|recaptcha\/enterprise\.js\?render=/i.test(srcBlob);
  if (widget || enterprise || v3) {
    if (enterprise && bframe) add('recaptcha_enterprise');
    else if (enterprise && v3) add('recaptcha_v3_enterprise');
    else if (enterprise) add('recaptcha_enterprise');
    else if (bframe) add('recaptcha_v2');
    else if (v3) add('recaptcha_v3');
    else add('recaptcha_v2');
  }
  if (document.querySelector('.geetest_slider_button, [class*="slider-button"], [class*="slide-btn"], [role="slider"]')) add('slider');
  if (document.querySelector('img[src*="captcha" i], img[alt*="captcha" i]')) add('image_text');
  let sitekey = null;
  let action = null;
  const keyed = document.querySelector('[data-sitekey], [data-captcha-sitekey], .g-recaptcha, .h-captcha, .cf-turnstile');
  if (keyed) {
    sitekey = keyed.getAttribute('data-sitekey') || keyed.getAttribute('data-captcha-sitekey');
    action = keyed.getAttribute('data-action') || keyed.getAttribute('data-captcha-action');
  }
  if (!sitekey) {
    const pkey = document.querySelector('[data-pkey]');
    if (pkey) sitekey = pkey.getAttribute('data-pkey');
  }
  if (!sitekey) {
    for (const src of srcs) {
      let m = src.match(/[?&#](?:sitekey|siteKey)=([^&?#]+)/);
      if (!m) m = src.match(/[?&]render=([A-Za-z0-9_-]{20,})/);
      if (m) { sitekey = decodeURIComponent(m[1]); break; }
    }
  }
  if (!sitekey) {
    const m = blob.match(/\b(0x4[A-Za-z0-9_-]{10,})\b/);
    if (m) sitekey = m[1];
  }
  if (!sitekey) {
    const m = blob.match(/\b(6L[A-Za-z0-9_-]{20,})\b/);
    if (m) sitekey = m[1];
  }
  let gt = null, challenge = null, captchaId = null;
  const gtM = blob.match(/["']gt["']\s*[:=]\s*["']([0-9a-f]{8,})["']/i);
  if (gtM) gt = gtM[1];
  const chM = blob.match(/["']challenge["']\s*[:=]\s*["']([0-9a-f-]{8,})["']/i);
  if (chM) challenge = chM[1];
  const idM = blob.match(/captchaId["']?\s*[:=]\s*["']([0-9a-f-]{8,})["']/i) || blob.match(/captcha_id=([0-9a-f-]{8,})/i);
  if (idM) captchaId = idM[1];
  return {types, sitekey, action, gt, challenge, captchaId, title: (document.title || '').slice(0, 120)};
}
"""


def _release_leftover_experiment_sessions() -> int:
    _experiment_env()
    from mvp.kill_switch import list_running_browserbase, release_browserbase_session

    rows = list_running_browserbase(owner="signup", study_id="signup-captcha")
    closed = 0
    for row in rows:
        sid = row.get("id") or ""
        if sid and release_browserbase_session(sid):
            closed += 1
    return closed


async def _with_page(solve_captchas: bool, fn: Any, *, proxies: bool = False) -> Any:
    _experiment_env()
    from capability.browserbase_client import close_session, create_session

    # Detection wants the widget to stay visible, so it skips residential
    # proxies (those creates were timing out and hiding nothing we need).
    # Trials that compare Browserbase's solver ask for proxies and fall back.
    if proxies:
        attempts = [
            {"proxies": True, "solve_captchas": solve_captchas, "advanced_stealth": False},
            {"proxies": False, "solve_captchas": solve_captchas, "advanced_stealth": False},
        ]
    else:
        attempts = [
            {"proxies": False, "solve_captchas": solve_captchas, "advanced_stealth": False},
        ]
    session = None
    last_exc: BaseException | None = None
    for kwargs in attempts:
        try:
            session = await asyncio.to_thread(
                create_session,
                keep_alive=False,
                owner="signup",
                study_id="signup-captcha",
                **kwargs,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            session = None
    if session is None:
        raise RuntimeError(f"browserbase_create_failed: {type(last_exc).__name__}" if last_exc else "no_session")
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(session.connect_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(20000)
            return await fn(page)
    finally:
        try:
            await asyncio.to_thread(close_session, session.id)
        except Exception:
            pass


async def _goto_signup(page: Any, url: str) -> str | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:  # noqa: BLE001
        return f"goto:{type(exc).__name__}"
    await page.wait_for_timeout(2500)
    try:
        await page.evaluate(
            """() => {
              const nodes = [...document.querySelectorAll('button, [role=button], a')];
              for (const n of nodes) {
                const t = ((n.innerText || n.getAttribute('aria-label') || '') + '').toLowerCase();
                if (/accept all|accept cookies|i agree|got it|allow all/.test(t) && t.length < 40) {
                  try { n.click(); } catch (e) {}
                  return;
                }
              }
            }"""
        )
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    return None


async def _signals(page: Any) -> dict[str, Any]:
    try:
        info = await page.evaluate(_DETECT_JS)
    except Exception:
        info = None
    return info if isinstance(info, dict) else {}


def _row_type(info: dict[str, Any]) -> str:
    ctype = primary_type(list(info.get("types") or []))
    if ctype != "none":
        return ctype
    key = str(info.get("sitekey") or "")
    if key.startswith("0x4"):
        return "turnstile"
    if key.startswith("6L"):
        return "recaptcha"
    if len(key) == 36 and key.count("-") == 4:
        return "hcaptcha"
    return "none"


async def detect_one(site: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    host = site["host"]

    async def run(page: Any) -> dict[str, Any]:
        err = await _goto_signup(page, site["url"])
        info = await _signals(page)
        if not info.get("types"):
            try:
                await page.evaluate(
                    """() => {
                      const el = document.querySelector('input[type=email], input[name*=email i]');
                      if (el) { el.focus(); el.click(); return; }
                      const nodes = [...document.querySelectorAll('a, button')];
                      for (const n of nodes) {
                        const t = ((n.innerText || '') + '').trim().toLowerCase();
                        if (t.length > 32) continue;
                        if (/sign up|get started|start free|create account|try free|register/.test(t)) {
                          n.click();
                          return;
                        }
                      }
                    }"""
                )
            except Exception:
                pass
            await page.wait_for_timeout(4000)
            info = await _signals(page)
        ctype = _row_type(info)
        return {
            "site": host,
            "url": site["url"],
            "cohort": site.get("cohort"),
            "group": site.get("group"),
            "type": ctype,
            "types": info.get("types") or [],
            "sitekey": info.get("sitekey"),
            "action": info.get("action"),
            "gt": info.get("gt"),
            "challenge": info.get("challenge"),
            "captchaId": info.get("captchaId"),
            "title": info.get("title"),
            "final_url": (page.url or "")[:300],
            "error": err,
            "ok": err is None,
            "seconds": round(time.time() - started, 2),
            "ts": _now(),
        }

    try:
        return await _with_page(False, run, proxies=False)
    except Exception as exc:  # noqa: BLE001
        return {
            "site": host,
            "url": site["url"],
            "cohort": site.get("cohort"),
            "group": site.get("group"),
            "type": "error",
            "types": [],
            "ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
            "seconds": round(time.time() - started, 2),
            "ts": _now(),
        }


def write_type_counts(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows if rows is not None else _read_jsonl(DETECT_PATH)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        host = row.get("site")
        if host:
            latest[host] = row
    counts: dict[str, int] = {}
    new_counts: dict[str, int] = {}
    for row in latest.values():
        ctype = row.get("type") or "error"
        counts[ctype] = counts.get(ctype, 0) + 1
        if row.get("cohort") == "new":
            new_counts[ctype] = new_counts.get(ctype, 0) + 1
    new_n = sum(1 for row in latest.values() if row.get("cohort") == "new")
    doc = {
        "updated_at": _now(),
        "sites": len(latest),
        "new_sites": new_n,
        "counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "new_counts": dict(sorted(new_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    COUNTS_PATH.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


async def run_detect(*, limit: int | None = None) -> dict[str, Any]:
    _experiment_env()
    closed = _release_leftover_experiment_sessions()
    if closed:
        print(f"released {closed} leftover signup-captcha sessions", flush=True)
    done = {
        row.get("site")
        for row in _read_jsonl(DETECT_PATH)
        if row.get("type") not in {None, "", "none", "error"}
    }
    sites = [s for s in load_pool() if s.get("host") not in done]
    if limit:
        sites = sites[:limit]
    print(f"detect {len(sites)} sites ({len(done)} already classified)", flush=True)
    sem = asyncio.Semaphore(2)

    async def one(site: dict[str, Any]) -> None:
        async with sem:
            row = await detect_one(site)
            _append_jsonl(DETECT_PATH, row)
            print(
                f"detect {row.get('site')} type={row.get('type')} ok={row.get('ok')} {row.get('seconds')}s",
                flush=True,
            )

    await asyncio.gather(*(one(site) for site in sites))
    return write_type_counts()


def _captcha_type_for_method(ctype: str, method: str) -> str:
    if method == "capsolver_v2_enterprise":
        return "recaptcha_v2_enterprise"
    if method in {"image_to_text"}:
        return "image_text"
    if method == "recaptcha_classification":
        return "recaptcha_classification"
    if method == "funcaptcha_probe":
        return "arkose"
    return ctype


def _question_id(text: str) -> str | None:
    low = (text or "").lower()
    for needle, qid in _RECAPTCHA_QUESTIONS.items():
        if needle in low:
            return qid
    return None


async def _challenge_shot(page: Any) -> str | None:
    selectors = [
        "iframe[src*='hcaptcha']",
        "iframe[src*='recaptcha'][src*='bframe']",
        "img[src*='captcha' i]",
        ".geetest_panel",
        "canvas",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            png = await loc.screenshot(type="png", timeout=4000)
            if png:
                return base64.b64encode(png).decode()
        except Exception:
            continue
    try:
        png = await page.screenshot(type="png", full_page=False)
        return base64.b64encode(png).decode()
    except Exception:
        return None


async def _is_blocked(page: Any) -> bool:
    """True only when a challenge or widget is actually on the page.

    A captcha script that never opens a challenge is not a clear.
    """
    from mvp.captcha import _challenge_visible, page_looks_captcha_blocked

    try:
        if await _challenge_visible(page):
            return True
    except Exception:
        pass
    try:
        info = await page_looks_captcha_blocked(page)
    except Exception:
        return False
    return bool(
        info.get("blocked")
        or info.get("challenge_visible")
        or info.get("widget_present")
        or info.get("text_block")
    )


async def _arm_form(page: Any) -> None:
    """Focus the email field and press the signup control so lazy widgets mount."""
    try:
        await page.evaluate(
            """() => {
              const set = (el, value) => {
                el.focus();
                const proto = HTMLInputElement.prototype;
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                if (desc && desc.set) desc.set.call(el, value);
                else el.value = value;
                el.dispatchEvent(new Event('input', {bubbles:true}));
              };
              const email = document.querySelector('input[type=email], input[name*=email i]');
              if (email && !email.value) set(email, 'captcha.trial@example.com');
              const buttons = [...document.querySelectorAll('button, [type=submit], input[type=submit]')];
              for (const b of buttons) {
                const label = ((b.innerText || b.value || '') + '').toLowerCase();
                if (/sign\\s*up|continue|create|register|submit|get started/.test(label)) {
                  try { b.click(); } catch (e) {}
                  return;
                }
              }
            }"""
        )
    except Exception:
        pass
    try:
        await page.wait_for_timeout(2500)
    except Exception:
        pass


async def _try_signup(page: Any, host: str) -> str:
    """Submit a fresh alias only after the captcha is already cleared."""
    try:
        from mvp.identity import _base_identity_fields, _generate_password, email_for_host

        base = _base_identity_fields()
        email = email_for_host(base.get("username") or "", host, tag="capx", force_dotted=True)
        password = _generate_password()
    except Exception:
        return "n"
    try:
        await page.evaluate(
            """([email, password]) => {
              const set = (el, value) => {
                const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                if (desc && desc.set) desc.set.call(el, value);
                else el.value = value;
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
              };
              const fields = [...document.querySelectorAll('input')];
              for (const el of fields) {
                const blob = ((el.name || '') + ' ' + (el.id || '') + ' ' + (el.type || '') + ' ' + (el.placeholder || '')).toLowerCase();
                if (/email/.test(blob) && !el.value) set(el, email);
                else if (/password/.test(blob) && el.type !== 'hidden') set(el, password);
              }
              const btns = [...document.querySelectorAll('button, [type=submit], input[type=submit]')];
              for (const b of btns) {
                const label = ((b.innerText || b.value || '') + '').toLowerCase();
                if (/sign\\s*up|create|register|continue|get started/.test(label)) {
                  b.disabled = false;
                  try { b.click(); } catch (e) {}
                  return;
                }
              }
            }""",
            [email, password],
        )
        await page.wait_for_timeout(5000)
        text = ""
        try:
            text = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 2000)")
        except Exception:
            text = ""
        low = (text or "").lower()
        if any(
            phrase in low
            for phrase in (
                "check your email",
                "verify your email",
                "confirmation",
                "welcome",
                "dashboard",
                "inbox",
                "account created",
            )
        ):
            return "y"
    except Exception:
        return "n"
    return "n"


def _trial_cost(site: str, started_ts: str) -> float:
    from mvp.captcha_spend import _read_rows

    total = 0.0
    for row in _read_rows():
        if row.get("event") != "createTask" or row.get("site") != site:
            continue
        if str(row.get("ts") or "") < started_ts:
            continue
        try:
            total += float(row.get("cost") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 6)


async def _paid_call(page: Any, *, site: str, method: str, info: dict[str, Any]) -> dict[str, Any]:
    from mvp.captcha import _capsolver_solve, _inject_token
    from mvp.captcha_spend import SpendCapError, begin_signup_attempt, get_balance

    balance = get_balance()
    if balance is not None and balance < 1.05:
        return {"token": "n", "cleared": "n", "note": "balance_floor", "cost": 0.0}
    ctype = info.get("type") or "recaptcha"
    task_type = None
    captcha_type = _captcha_type_for_method(ctype, method)
    extra: dict[str, Any] = {}
    for key in ("gt", "challenge", "captchaId"):
        if info.get(key):
            extra[key] = info[key]
    sitekey = str(info.get("sitekey") or info.get("captchaId") or info.get("gt") or "")
    if captcha_type in {"geetest", "geetest_v4"} and not (
        extra.get("gt") or extra.get("captchaId") or sitekey
    ):
        return {"token": "n", "cleared": "n", "note": "missing_geetest_fields", "cost": 0.0}
    if method == "image_to_text":
        shot = await _challenge_shot(page)
        if not shot:
            return {"token": "n", "cleared": "n", "note": "no_image", "cost": 0.0}
        extra = {"body": shot, "module": "common"}
        sitekey = ""
        task_type = "ImageToTextTask"
    elif method == "recaptcha_classification":
        question = ""
        try:
            question = await page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 500)"
            )
        except Exception:
            question = ""
        qid = _question_id(question or "")
        if not qid:
            return {"token": "n", "cleared": "n", "note": "question_unmapped", "cost": 0.0}
        shot = await _challenge_shot(page)
        if not shot:
            return {"token": "n", "cleared": "n", "note": "no_image", "cost": 0.0}
        extra = {"image": shot, "question": qid}
        sitekey = str(info.get("sitekey") or "")
        task_type = "ReCaptchaV2Classification"
    elif method == "funcaptcha_probe":
        task_type = "FunCaptchaTaskProxyLess"
        if not sitekey:
            return {"token": "n", "cleared": "n", "note": "no_sitekey", "cost": 0.0}
    elif method == "capsolver" and captcha_type == "aws_waf":
        task_type = "AntiAwsWafTaskProxyLess"
    if method in {"capsolver", "capsolver_v2_enterprise"} and captcha_type.startswith("recaptcha") and not sitekey:
        return {"token": "n", "cleared": "n", "note": "no_sitekey", "cost": 0.0}
    if method == "capsolver" and captcha_type == "turnstile" and not sitekey:
        return {"token": "n", "cleared": "n", "note": "no_sitekey", "cost": 0.0}
    try:
        begin_signup_attempt(site)
    except SpendCapError as exc:
        return {"token": "n", "cleared": "n", "note": str(exc)[:120], "cost": 0.0}
    started = _now()
    token = await asyncio.to_thread(
        _capsolver_solve,
        "",
        sitekey=sitekey,
        page_url=page.url or info.get("url") or "",
        captcha_type=captcha_type,
        action=info.get("action"),
        timeout_s=90,
        blocking=True,
        extra=extra or None,
        task_type_override=task_type,
    )
    cleared = False
    if token and method != "funcaptcha_probe":
        try:
            await _inject_token(page, token, captcha_type)
            await page.wait_for_timeout(3000)
        except Exception:
            pass
        cleared = not await _is_blocked(page)
    elif token:
        cleared = not await _is_blocked(page)
    return {
        "token": _yn(bool(token)),
        "cleared": _yn(bool(cleared)),
        "note": "" if token else "no_token",
        "cost": _trial_cost(site, started),
    }


async def trial_one(detection: dict[str, Any], method: str, repeat: int) -> dict[str, Any]:
    from mvp.captcha import human_drag

    started = time.time()
    host = detection["site"]
    ctype = detection.get("type") or "none"
    solve_captchas = method == "browserbase"
    base = {
        "site": host,
        "type": ctype,
        "method": method,
        "repeat": repeat,
        "cohort": detection.get("cohort"),
        "ts": _now(),
    }

    async def run(page: Any) -> dict[str, Any]:
        err = await _goto_signup(page, detection["url"])
        info = await _signals(page)
        info["type"] = ctype
        info["url"] = detection["url"]
        for key in ("sitekey", "gt", "challenge", "captchaId", "action"):
            if not info.get(key) and detection.get(key):
                info[key] = detection.get(key)
        if err:
            return {**base, "token": "n", "cleared": "n", "signup": "n", "cost": 0.0, "seconds": round(time.time() - started, 2), "note": err}
        await _arm_form(page)
        blocked_before = await _is_blocked(page)
        if not blocked_before:
            return {
                **base,
                "token": "n",
                "cleared": "n",
                "signup": "n",
                "cost": 0.0,
                "seconds": round(time.time() - started, 2),
                "note": "not_blocked",
            }
        if method == "browserbase":
            await page.wait_for_timeout(20000)
            cleared = not await _is_blocked(page)
            signup = await _try_signup(page, host) if cleared else "n"
            return {
                **base,
                "token": "n",
                "cleared": _yn(cleared),
                "signup": signup,
                "cost": 0.0,
                "seconds": round(time.time() - started, 2),
                "note": "bb_wait",
            }
        if method == "mouse_drag":
            dragged = await human_drag(page)
            cleared = bool(dragged.get("ok")) and not await _is_blocked(page)
            signup = await _try_signup(page, host) if cleared else "n"
            return {
                **base,
                "token": "n",
                "cleared": _yn(cleared),
                "signup": signup,
                "cost": 0.0,
                "seconds": round(time.time() - started, 2),
                "note": dragged.get("detail") or "",
            }
        paid = await _paid_call(page, site=host, method=method, info=info)
        cleared = paid.get("cleared") == "y" and not await _is_blocked(page)
        signup = await _try_signup(page, host) if cleared else "n"
        return {
            **base,
            "token": paid.get("token") or "n",
            "cleared": _yn(cleared),
            "signup": signup,
            "cost": paid.get("cost") or 0.0,
            "seconds": round(time.time() - started, 2),
            "note": paid.get("note") or "",
        }

    try:
        # Residential proxy creates were timing out. Both arms use the same
        # non-proxy Browserbase browser; only solve_captchas differs.
        return await _with_page(solve_captchas, run, proxies=False)
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "token": "n",
            "cleared": "n",
            "signup": "n",
            "cost": 0.0,
            "seconds": round(time.time() - started, 2),
            "note": f"{type(exc).__name__}:{str(exc)[:140]}",
        }


def _schedule(per_type: int) -> list[tuple[dict[str, Any], str, int]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(DETECT_PATH):
        if row.get("site"):
            latest[row["site"]] = row
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in latest.values():
        ctype = row.get("type") or "none"
        if ctype in {"none", "error"}:
            continue
        by_type.setdefault(ctype, []).append(row)
    done = {(r.get("site"), r.get("method"), int(r.get("repeat") or 0)) for r in _read_jsonl(TRIAL_PATH)}
    jobs: list[tuple[dict[str, Any], str, int]] = []
    probe_done = any(r.get("method") == "funcaptcha_probe" for r in _read_jsonl(TRIAL_PATH))
    for ctype, sites in sorted(by_type.items()):
        methods = METHODS_FOR_TYPE.get(ctype, ["browserbase"])
        sites = sorted(sites, key=lambda r: (0 if r.get("cohort") == "new" else 1, r.get("site") or ""))
        if not sites:
            continue
        for method in methods:
            target = 1 if method == "funcaptcha_probe" else per_type
            if method == "funcaptcha_probe" and probe_done:
                continue
            scheduled = 0
            repeat = 0
            while scheduled < target and repeat < 10:
                for site in sites:
                    if scheduled >= target:
                        break
                    key = (site.get("site"), method, repeat)
                    if key not in done:
                        jobs.append((site, method, repeat))
                        scheduled += 1
                repeat += 1
    return jobs


def write_policy(trials: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    trials = trials if trials is not None else _read_jsonl(TRIAL_PATH)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in trials:
        grouped.setdefault((row.get("type") or "", row.get("method") or ""), []).append(row)
    types: dict[str, Any] = {}
    task_for = {
        "capsolver": None,
        "capsolver_v2_enterprise": "ReCaptchaV2EnterpriseTaskProxyLess",
        "image_to_text": "ImageToTextTask",
        "recaptcha_classification": "ReCaptchaV2Classification",
    }
    captcha_type_for = {
        "capsolver_v2_enterprise": "recaptcha_v2_enterprise",
    }
    for (ctype, method), rows in grouped.items():
        if not ctype or method in {"funcaptcha_probe"}:
            continue
        n = len(rows)
        cleared = sum(1 for r in rows if r.get("cleared") == "y")
        if cleared < 1:
            continue
        rate = cleared / n
        current = types.get(ctype)
        if current and current.get("cleared_rate", 0) > rate:
            continue
        if current and current.get("cleared_rate") == rate and method != "browserbase":
            # Prefer a clearing paid method over a tie with browserbase only when
            # it cleared at least as often. Equal rates keep the first, which is
            # fine; a strictly better rate replaces it above.
            pass
        spec: dict[str, Any] = {
            "method": method,
            "cleared": cleared,
            "n": n,
            "cleared_rate": round(rate, 3),
        }
        if method in task_for and task_for[method]:
            spec["task"] = task_for[method]
        if method == "capsolver":
            from mvp.captcha import capsolver_task_type

            spec["task"] = capsolver_task_type(ctype)
            spec["captcha_type"] = ctype
        if method in captcha_type_for:
            spec["captcha_type"] = captcha_type_for[method]
        types[ctype] = spec
    doc = {
        "apply_to_signup": bool(types),
        "updated_at": _now(),
        "types": types,
        "note": "Signup pays only for types whose best trial method cleared at least once.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def report() -> dict[str, Any]:
    counts = write_type_counts()
    trials = _read_jsonl(TRIAL_PATH)
    from mvp.captcha_spend import get_balance, spent_usd

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in trials:
        grouped.setdefault((row.get("type") or "", row.get("method") or ""), []).append(row)
    lines = []
    for key in sorted(grouped):
        rows = grouped[key]
        n = len(rows)
        token = sum(1 for r in rows if r.get("token") == "y")
        cleared = sum(1 for r in rows if r.get("cleared") == "y")
        signup = sum(1 for r in rows if r.get("signup") == "y")
        cost = round(sum(float(r.get("cost") or 0) for r in rows), 6)
        lines.append(
            {
                "type": key[0],
                "method": key[1],
                "n": n,
                "token_rate": round(token / n, 3) if n else 0,
                "cleared_rate": round(cleared / n, 3) if n else 0,
                "signup_rate": round(signup / n, 3) if n else 0,
                "token": token,
                "cleared": cleared,
                "signup": signup,
                "cost": cost,
            }
        )
    doc = {
        "updated_at": _now(),
        "type_counts": counts,
        "rates": lines,
        "ledger_spent_usd": spent_usd(),
        "balance": get_balance(),
        "trials": len(trials),
    }
    (OUT_DIR / "experiment_report.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps(doc, indent=2), flush=True)
    return doc


async def run_trials(*, per_type: int) -> None:
    _experiment_env()
    closed = _release_leftover_experiment_sessions()
    if closed:
        print(f"released {closed} leftover signup-captcha sessions", flush=True)
    from mvp.captcha_spend import capsolver_key

    print(f"capsolver_key_set {bool(capsolver_key())}", flush=True)
    jobs = _schedule(per_type)
    print(f"trials queued {len(jobs)}", flush=True)
    sem = asyncio.Semaphore(2)

    async def one(job: tuple[dict[str, Any], str, int]) -> None:
        detection, method, repeat = job
        async with sem:
            from mvp.captcha_spend import get_balance

            if method in PAID_METHODS:
                balance = get_balance()
                if balance is not None and balance < 1.05:
                    row = {
                        "site": detection.get("site"),
                        "type": detection.get("type"),
                        "method": method,
                        "repeat": repeat,
                        "token": "n",
                        "cleared": "n",
                        "signup": "n",
                        "cost": 0.0,
                        "seconds": 0,
                        "note": "balance_floor",
                        "ts": _now(),
                    }
                    _append_jsonl(TRIAL_PATH, row)
                    print(f"trial skip {row['site']} {method} balance_floor", flush=True)
                    return
            row = await trial_one(detection, method, repeat)
            _append_jsonl(TRIAL_PATH, row)
            print(
                f"trial {row.get('site')} {row.get('type')} {row.get('method')} "
                f"token={row.get('token')} cleared={row.get('cleared')} signup={row.get('signup')} "
                f"cost={row.get('cost')} {row.get('seconds')}s {row.get('note') or ''}",
                flush=True,
            )

    # Chunk so a balance floor mid-run is observed between batches.
    for i in range(0, len(jobs), 4):
        batch = jobs[i : i + 4]
        await asyncio.gather(*(one(job) for job in batch))
        write_policy()
    write_policy()
    report()


def main() -> None:
    parser = argparse.ArgumentParser(description="Captcha type experiment")
    sub = parser.add_subparsers(dest="cmd", required=True)
    det = sub.add_parser("detect")
    det.add_argument("--limit", type=int, default=0)
    tri = sub.add_parser("trials")
    tri.add_argument("--per-type", type=int, default=10)
    sub.add_parser("report")
    sub.add_parser("counts")
    args = parser.parse_args()
    if args.cmd == "detect":
        doc = asyncio.run(run_detect(limit=args.limit or None))
        print(json.dumps(doc, indent=2), flush=True)
    elif args.cmd == "trials":
        asyncio.run(run_trials(per_type=args.per_type))
    elif args.cmd == "report":
        report()
    elif args.cmd == "counts":
        print(json.dumps(write_type_counts(), indent=2), flush=True)


if __name__ == "__main__":
    main()
