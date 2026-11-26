"""4-Step Interactive Post-Login SaaS & Demo Tester (`pool_b_interactive_cua.py`).

Runs on the 5 pinned signed-in Pool B fleet VMs (`slots 32, 40, 42, 44, 45`), executing a real
4-step simulated-user session per target launch (`producthunt.com` strictly blocked per `AGENTS.md`):
  Step 1 (Landing): Hydrate SPA, inspect visible CTAs, inputs, code/CLI blocks, and take screenshot #1.
  Step 2 (Enter App / Google SSO): Click primary product entry CTA (`Try`, `Launch App`, `Playground`,
          `Get Started`, `Sign in`, or direct `Continue with Google`, including icon/aria/href OAuth
          buttons in Clerk/Supabase/Firebase/NextAuth/Auth0). Complete Google OAuth (`popup` or
          `redirect`) using the VM's signed-in Gmail session, and click past harmless 1-click onboarding
          interstitials (`Skip`, `Continue`).
  Step 3 (Hands-On Workflow Execution): Inside the post-login app (or live playground / OSS repo),
          interact with the primary workspace input/button (type a realistic test prompt/input or
          trigger a sample/template action), wait for DOM response, measure actual DOM state delta,
          detect error toasts / hard paywalls / waitlists, and take screenshot #2 (`inside_app`).
  Step 4 (Pricing & Docs Verification): Quick check of `/pricing` or `/docs` link if present.

Never solves or clicks CAPTCHAs or anti-bot gates. Uploads JSONL + base64 JPEG thumbnails (only when
zero PH badge strings are present on the page) to GCS for multimodal `gemini-2.5-pro` evaluation.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
import re
import signal
import time
import urllib.parse
import urllib.request
from typing import Any


BUCKET = "usersim-bakeoff-347838016394"
PROJECT = "project-amer-scs-sandbox"

_CAPTCHA_RE = re.compile(
    r"\b(captcha|recaptcha|hcaptcha|turnstile|verify\s+you\s+are\s+human|are\s+you\s+a\s+robot)\b",
    re.IGNORECASE,
)
_PH_BADGE_RE = re.compile(
    r"(product\s*hunt|producthunt\.com|#\s*[1-5]\s*product\s+of\s+the\s+(day|week)|\b\d+\+?\s*upvotes?\b)",
    re.IGNORECASE,
)
_PAYWALL_RE = re.compile(
    r"(\benter\s+(your\s+)?(card|payment|billing)\b|\bcredit\s+card\s+required\b|checkout\.stripe\.com|\bsubscribe\s+to\s+continue\b|\bupgrade\s+to\s+(pro|access|unlock)\b|\bstart\s+\d+-day\s+paid\s+trial\b)",
    re.IGNORECASE,
)
_WAITLIST_RE = re.compile(
    r"(\byou['’]?re\s+on\s+the\s+waitlist\b|\bjoin\s+(the\s+)?waitlist\b|\brequest\s+early\s+access\b|\baccount\s+pending\s+approval\b|\binvite\s+code\s+required\b)",
    re.IGNORECASE,
)
_ERROR_TOAST_RE = re.compile(
    r"(\bsomething\s+went\s+wrong\b|\binternal\s+server\s+error\b|\b500\s+error\b|\bfailed\s+to\s+(load|fetch|generate)\b|\bapplication\s+error:\s+a\s+client-side\s+exception\b)",
    re.IGNORECASE,
)
_WORKSPACE_URL_RE = re.compile(
    r"/(app|dashboard|workspace|projects|onboarding|welcome|studio|editor|chat|home|console|playground|new|build|create)\b",
    re.IGNORECASE,
)


def get_metadata_proxy() -> dict[str, str]:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/attributes/proxy-url",
        headers={"Metadata-Flavor": "Google"},
    )
    raw = urllib.request.urlopen(req, timeout=5).read().decode().strip()
    u = urllib.parse.urlparse(raw)
    out: dict[str, str] = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        out["username"] = urllib.parse.unquote(u.username)
    if u.password:
        out["password"] = urllib.parse.unquote(u.password)
    return out


def get_access_token() -> str:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())["access_token"]


def get_gmail_email(account_idx: int) -> str:
    tok = get_access_token()
    url = f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/usersim-fleet-gmail-accounts/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    payload = json.loads(base64.b64decode(resp["payload"]["data"]).decode("utf-8"))
    for acc in payload.get("accounts") or []:
        if int(acc.get("slot_idx", 0)) == account_idx:
            return str(acc["email"])
    raise RuntimeError(f"slot_idx={account_idx} not found")


def gcs_download_text(obj_path: str) -> str:
    tok = get_access_token()
    enc = urllib.parse.quote(obj_path, safe="")
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{enc}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def gcs_upload_bytes(obj_path: str, data: bytes, content_type: str = "application/x-ndjson") -> None:
    tok = get_access_token()
    enc = urllib.parse.quote(obj_path, safe="")
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o?uploadType=media&name={enc}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": content_type},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=45).read()


def _safe_jpg_b64(page: Any, body_text: str) -> str:
    """Capture a compact 1024px JPEG screenshot ONLY if the visible DOM has zero PH outcome badges."""
    if _PH_BADGE_RE.search(body_text[:4000]):
        return ""
    try:
        raw_bytes = page.screenshot(type="jpeg", quality=48, full_page=False, timeout=5000)
        if len(raw_bytes) <= 140_000:
            return base64.b64encode(raw_bytes).decode("ascii")
    except Exception:
        pass
    return ""


def _complete_google_oauth(oauth_page: Any, email: str) -> bool:
    try:
        oauth_page.wait_for_timeout(1600)
        if oauth_page.is_closed():
            return True
        if "accounts.google.com" not in oauth_page.url.lower():
            return True
        body_low = oauth_page.inner_text("body")[:1500].lower()
        if _CAPTCHA_RE.search(body_low) or "verify it" in body_low:
            return False

        for sel in (
            f'div[data-identifier="{email.lower()}"]',
            f'div[data-email="{email.lower()}"]',
            f'li:has-text("{email}")',
            f'div[role="link"]:has-text("{email}")',
            'div[data-identifier]',
        ):
            try:
                loc = oauth_page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=3000)
                    oauth_page.wait_for_timeout(2400)
                    break
            except Exception:
                continue

        if oauth_page.is_closed():
            return True

        for label in ("Continue", "Allow", "Confirm"):
            for sel in (f'button:has-text("{label}")', f'div[role="button"]:has-text("{label}")', f'span:has-text("{label}")'):
                try:
                    if oauth_page.is_closed():
                        return True
                    btn = oauth_page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=3000)
                        oauth_page.wait_for_timeout(2400)
                        break
                except Exception:
                    continue

        return oauth_page.is_closed() or ("accounts.google.com" not in oauth_page.url.lower())
    except Exception:
        return oauth_page.is_closed()


GOOGLE_SSO_SELECTOR = (
    'button:has-text("Google"), a:has-text("Google"), '
    'div[role="button"]:has-text("Google"), '
    'button[aria-label*="Google" i], a[aria-label*="Google" i], '
    'button[data-provider="google"], a[href*="accounts.google.com"], '
    'button[class*="google" i], a[class*="google" i]'
)

ENTRY_CTA_SELECTOR = (
    'a:has-text("Try"), button:has-text("Try"), '
    'a:has-text("Playground"), button:has-text("Playground"), '
    'a:has-text("Live Demo"), button:has-text("Live Demo"), '
    'a:has-text("Launch App"), button:has-text("Launch App"), '
    'a:has-text("Open App"), button:has-text("Open App"), '
    'a:has-text("Start for free"), button:has-text("Start for free"), '
    'a:has-text("Get Started"), button:has-text("Get Started"), '
    'a:has-text("Get started"), button:has-text("Get started"), '
    'a:has-text("Sign in"), button:has-text("Sign in"), '
    'a:has-text("Log in"), button:has-text("Log in")'
)


def _dom_snapshot(page: Any) -> dict[str, Any]:
    try:
        return page.evaluate(
            """() => {
                const bodyTxt = document.body ? document.body.innerText : '';
                const hs = Array.from(document.querySelectorAll('h1,h2,h3')).slice(0, 12).map(e => e.innerText.trim()).filter(Boolean);
                const ctas = Array.from(document.querySelectorAll('a,button,[role="button"]')).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(t => t.length >= 2 && t.length <= 48).slice(0, 20);
                const inputs = Array.from(document.querySelectorAll('textarea, input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), [contenteditable="true"]')).slice(0, 12).map(e => ({
                    tag: e.tagName.toLowerCase(),
                    type: e.getAttribute('type') || '',
                    placeholder: (e.getAttribute('placeholder') || e.getAttribute('aria-label') || '').slice(0, 80)
                }));
                const codeBlocks = document.querySelectorAll('pre, code').length;
                const canvases = document.querySelectorAll('canvas, video, iframe').length;
                const hrefs = Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') || '').slice(0, 80);
                return {bodyTxt: bodyTxt.slice(0, 4500), hs, ctas, inputs, codeBlocks, canvases, hrefs};
            }"""
        )
    except Exception:
        return {"bodyTxt": "", "hs": [], "ctas": [], "inputs": [], "codeBlocks": 0, "canvases": 0, "hrefs": []}


def run_4step_interactive_session(browser: Any, item: dict[str, Any], email: str, signed_in: bool) -> dict[str, Any]:
    lid = str(item["item_id"])
    day = str(item["day"])
    url = str(item["url"])
    title_claim = str(item.get("title") or "")
    t0 = time.time()

    if not url or "producthunt.com" in url.lower():
        return {"item_id": lid, "day": day, "input_url": url, "access_status": "no_url"}

    page = browser.new_page()
    page.set_default_timeout(7000)
    try:
        page.set_viewport_size({"width": 1280, "height": 800})
    except Exception:
        pass
    steps_trace: list[dict[str, Any]] = []

    def _on_alarm(signum: int, frame: Any) -> None:
        raise TimeoutError("hard_32s_session_watchdog")

    old_h = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(32)
    try:
        # ---------------- STEP 1: LANDING HYDRATION ----------------
        resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1800)
        http_code = resp.status if resp else 0
        landing_u = page.url
        if "producthunt.com" in landing_u.lower():
            return {"item_id": lid, "day": day, "input_url": url, "access_status": "blocked_ph_redirect"}

        s1 = _dom_snapshot(page)
        s1_txt = " ".join((s1.get("bodyTxt") or "").split())
        if len(s1_txt) < 600 and _CAPTCHA_RE.search(s1_txt.lower()):
            return {"item_id": lid, "day": day, "input_url": url, "access_status": "captcha", "elapsed_s": round(time.time() - t0, 2)}

        img1_b64 = _safe_jpg_b64(page, s1_txt)
        steps_trace.append({
            "step": 1,
            "stage": "landing",
            "url": landing_u,
            "headings": (s1.get("hs") or [])[:6],
            "ctas": (s1.get("ctas") or [])[:10],
            "n_inputs": len(s1.get("inputs") or []),
            "code_blocks": int(s1.get("codeBlocks") or 0),
            "text_len": len(s1_txt),
        })

        hrefs_all = [str(h) for h in (s1.get("hrefs") or [])]
        hrefs_low = " ".join(hrefs_all).lower()
        has_pricing_link = "/pricing" in hrefs_low or "#pricing" in hrefs_low
        has_docs_link = "/docs" in hrefs_low or "docs." in hrefs_low or "/api" in hrefs_low or "readme" in hrefs_low
        has_github_link = "github.com/" in hrefs_low or "github.com/" in landing_u.lower()

        # ---------------- STEP 2: ENTER PRODUCT OR GOOGLE OAUTH ----------------
        sso_attempted = False
        sso_entered = False
        cta_clicked = ""

        # First check if a direct interactive playground input is ALREADY on the landing page!
        non_auth_inputs_s1 = [
            inp for inp in (s1.get("inputs") or [])
            if inp.get("type") not in ("email", "password")
            and not any(w in (inp.get("placeholder") or "").lower() for w in ("email", "newsletter", "waitlist"))
        ]
        instant_landing_playground = len(non_auth_inputs_s1) > 0 and not _WAITLIST_RE.search(s1_txt.lower())

        if not instant_landing_playground:
            # Click entry CTA to reach workspace / playground / login screen
            entry_loc = page.locator(ENTRY_CTA_SELECTOR)
            if entry_loc.count() > 0:
                for k_i in range(min(4, entry_loc.count())):
                    cand = entry_loc.nth(k_i)
                    try:
                        if cand.is_visible():
                            lbl = " ".join((cand.inner_text() or "").split())[:40]
                            href_c = (cand.get_attribute("href") or "").lower()
                            if "producthunt.com" in href_c or "twitter.com" in href_c or "linkedin.com" in href_c:
                                continue
                            cta_clicked = lbl
                            pages_b = len(browser.pages)
                            cand.click(timeout=3000)
                            page.wait_for_timeout(1800)
                            if len(browser.pages) > pages_b:
                                new_p = browser.pages[-1]
                                if not new_p.is_closed() and "producthunt.com" not in new_p.url.lower() and "accounts.google.com" not in new_p.url.lower():
                                    page = new_p
                            break
                    except Exception:
                        continue

        # Check if Google SSO button is visible now (broad selector catching Clerk/Supabase/NextAuth/icon buttons!)
        if signed_in and "github.com/" not in page.url.lower():
            sso_loc = page.locator(GOOGLE_SSO_SELECTOR)
            for k_i in range(min(4, sso_loc.count())):
                cand = sso_loc.nth(k_i)
                try:
                    if not cand.is_visible():
                        continue
                    lbl_low = ((cand.inner_text() or "") + " " + (cand.get_attribute("aria-label") or "") + " " + (cand.get_attribute("href") or "")).lower()
                    # Avoid clicking "Google Play" / "Google Chrome" / "Google Cloud" marketing links!
                    if any(bad in lbl_low for bad in ("google play", "chrome web store", "google calendar", "google drive", "google sheets", "google docs", "maps.google")):
                        continue
                    sso_attempted = True
                    pre_sso_u = page.url
                    pages_before = len(browser.pages)
                    cand.click(timeout=3500)
                    page.wait_for_timeout(2200)
                    if len(browser.pages) > pages_before:
                        popup = browser.pages[-1]
                        _complete_google_oauth(popup, email)
                        page.wait_for_timeout(2600)
                        if not popup.is_closed() and "accounts.google.com" not in popup.url.lower() and "producthunt.com" not in popup.url.lower():
                            page = popup
                    elif "accounts.google.com" in page.url.lower():
                        _complete_google_oauth(page, email)
                        page.wait_for_timeout(2500)

                    if "accounts.google.com" not in page.url.lower() and "producthunt.com" not in page.url.lower():
                        s_after_sso = " ".join(page.inner_text("body").split())[:2500]
                        if page.url != pre_sso_u or abs(len(s_after_sso) - len(s1_txt)) > 100:
                            sso_entered = True
                    break
                except Exception:
                    continue

        # Dismiss 1-step post-login onboarding ("Skip", "Continue", "Get Started") if inside app!
        if sso_entered:
            for ob_lbl in ("Skip", "Skip for now", "Continue", "Let's go", "Start"):
                try:
                    ob_btn = page.locator(f'button:has-text("{ob_lbl}")').first
                    if ob_btn.count() > 0 and ob_btn.is_visible():
                        ob_btn.click(timeout=2000)
                        page.wait_for_timeout(1400)
                        break
                except Exception:
                    continue

        s2 = _dom_snapshot(page)
        s2_txt = " ".join((s2.get("bodyTxt") or "").split())
        steps_trace.append({
            "step": 2,
            "stage": "post_entry_or_sso",
            "cta_clicked": cta_clicked,
            "sso_attempted": sso_attempted,
            "sso_entered": sso_entered,
            "url": page.url,
            "headings": (s2.get("hs") or [])[:6],
            "n_inputs": len(s2.get("inputs") or []),
            "text_len": len(s2_txt),
        })

        # ---------------- STEP 3: HANDS-ON INTERACTIVE WORKFLOW EXECUTION ----------------
        workflow_action = "none"
        workflow_responded = False
        dom_delta_chars = 0

        if "accounts.google.com" not in page.url.lower() and "producthunt.com" not in page.url.lower():
            # A. Try typing a realistic test task into the main workspace/playground input!
            work_inp = page.locator(
                'textarea:visible, '
                '[contenteditable="true"]:visible, '
                'input[type="text"]:visible:not([name*="email" i]):not([placeholder*="email" i]):not([placeholder*="search" i]), '
                'input[type="url"]:visible'
            )
            if work_inp.count() > 0:
                try:
                    box = work_inp.first
                    ph_attr = (box.get_attribute("placeholder") or "").lower()
                    test_val = "https://example.com" if ("http" in ph_attr or "url" in ph_attr or "website" in ph_attr) else f"Test {title_claim[:24]} sample workflow"
                    box.click(timeout=2000)
                    box.fill(test_val, timeout=2000)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                    workflow_action = f"typed_input:{ph_attr[:30] or 'workspace_input'}"
                except Exception:
                    pass

            # B. Or click a sample / template / create / demo / README action inside the app!
            if workflow_action == "none":
                act_loc = page.locator(
                    'button:has-text("Generate"), button:has-text("Run"), button:has-text("Create"), '
                    'button:has-text("New"), button:has-text("Example"), button:has-text("Sample"), '
                    'button:has-text("Demo"), a:has-text("Docs"), a:has-text("Documentation")'
                )
                for k_i in range(min(3, act_loc.count())):
                    btn = act_loc.nth(k_i)
                    try:
                        if btn.is_visible():
                            btxt = " ".join((btn.inner_text() or "").split())[:30]
                            btn.click(timeout=2500)
                            page.wait_for_timeout(1800)
                            workflow_action = f"clicked:{btxt}"
                            break
                    except Exception:
                        continue

        s3 = _dom_snapshot(page)
        s3_txt = " ".join((s3.get("bodyTxt") or "").split())
        dom_delta_chars = abs(len(s3_txt) - len(s2_txt))
        if workflow_action != "none" and (dom_delta_chars >= 45 or page.url != steps_trace[-1]["url"]):
            workflow_responded = True

        s3_low = s3_txt.lower()
        hit_paywall = bool(_PAYWALL_RE.search(s3_low) or "checkout.stripe.com" in page.url.lower())
        hit_waitlist = bool(_WAITLIST_RE.search(s3_low))
        hit_error_toast = bool(_ERROR_TOAST_RE.search(s3_low))
        in_workspace_route = bool(_WORKSPACE_URL_RE.search(page.url))

        img3_b64 = _safe_jpg_b64(page, s3_txt) if (page.url != landing_u or dom_delta_chars >= 60) else ""
        steps_trace.append({
            "step": 3,
            "stage": "interactive_execution",
            "workflow_action": workflow_action,
            "workflow_responded": workflow_responded,
            "dom_delta_chars": dom_delta_chars,
            "url": page.url,
            "in_workspace_route": in_workspace_route,
            "hit_paywall": hit_paywall,
            "hit_waitlist": hit_waitlist,
            "hit_error_toast": hit_error_toast,
            "headings": (s3.get("hs") or [])[:6],
            "text_len": len(s3_txt),
        })

        # ---------------- STEP 4: PRICING / DOCS TRANSPARENCY CHECK ----------------
        pricing_excerpt = ""
        if has_pricing_link and "github.com/" not in landing_u.lower():
            for h in hrefs_all:
                if "/pricing" in h.lower():
                    try:
                        pu = urllib.parse.urljoin(landing_u, h)
                        if urllib.parse.urlparse(pu).netloc == urllib.parse.urlparse(landing_u).netloc:
                            page.goto(pu, wait_until="domcontentloaded", timeout=8000)
                            page.wait_for_timeout(900)
                            pricing_excerpt = " ".join(page.inner_text("body").split())[:900]
                    except Exception:
                        pass
                    break

        reached_working_product = bool(
            not hit_paywall
            and not hit_waitlist
            and not hit_error_toast
            and (
                (sso_entered and (in_workspace_route or workflow_responded or len(s3_txt) >= 250))
                or instant_landing_playground
                or workflow_responded
                or has_github_link
            )
        )

        return {
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "item_id": lid,
            "day": day,
            "input_url": url,
            "landing_url": landing_u,
            "final_url": s3.get("url") or steps_trace[-1]["url"],
            "http_status": http_code,
            "access_status": "clean" if (len(s1_txt) >= 80 or sso_entered) else "js_empty",
            "elapsed_s": round(time.time() - t0, 2),
            "cta_clicked": cta_clicked,
            "instant_landing_playground": instant_landing_playground,
            "google_sso_attempted": sso_attempted,
            "google_sso_entered": sso_entered,
            "workflow_action": workflow_action,
            "workflow_responded": workflow_responded,
            "in_workspace_route": in_workspace_route,
            "reached_working_product": reached_working_product,
            "hit_paywall": hit_paywall,
            "hit_waitlist": hit_waitlist,
            "hit_error_toast": hit_error_toast,
            "has_pricing_link": has_pricing_link,
            "has_docs_link": has_docs_link,
            "has_github_link": has_github_link,
            "code_blocks_n": int(s1.get("codeBlocks") or 0) + int(s3.get("codeBlocks") or 0),
            "landing_text": s1_txt[:2200],
            "inside_app_text": s3_txt[:2400],
            "pricing_text": pricing_excerpt,
            "steps_trace": steps_trace,
            "landing_jpg_b64": img1_b64,
            "inside_jpg_b64": img3_b64,
        }
    except Exception as e:
        return {
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "item_id": lid,
            "day": day,
            "input_url": url,
            "access_status": f"err:{type(e).__name__}",
            "detail": str(e)[:160],
            "elapsed_s": round(time.time() - t0, 2),
        }
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_h)
        try:
            for extra_p in list(browser.pages)[1:]:
                if not extra_p.is_closed():
                    extra_p.close()
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--account-idx", type=int, required=True)
    ap.add_argument("--job-name", default="hillclimb4_cua")
    args = ap.parse_args()

    from camoufox.sync_api import Camoufox  # type: ignore[import-untyped]

    proxy = get_metadata_proxy()
    email = get_gmail_email(args.account_idx)
    prof_dir = f"/var/tmp/usersim_google_sso/gmail_{args.account_idx}"
    out_dir = f"/var/tmp/usersim_poolb_out/slot_{args.slot}"
    os.makedirs(out_dir, exist_ok=True)
    local_out = f"{out_dir}/{args.job_name}_results.jsonl"
    gcs_out = f"usersim_sim/raw/fleet_external/_jobs/{args.job_name}_slot{args.slot}.jsonl"

    raw_manifest = gcs_download_text(f"usersim_sim/raw/fleet_external/_jobs/{args.job_name}_targets.jsonl")
    all_targets = [json.loads(l) for l in raw_manifest.splitlines() if l.strip()]
    my_targets = [t for i, t in enumerate(all_targets) if i % 5 == (args.account_idx - 1)]

    done_ids: set[str] = set()
    if os.path.exists(local_out):
        for l in open(local_out):
            try:
                done_ids.add(str(json.loads(l).get("item_id")))
            except Exception:
                pass

    todo = [t for t in my_targets if str(t["item_id"]) not in done_ids]
    print(f"[slot {args.slot}] Interactive 4-step CUA targets={len(my_targets)}, todo={len(todo)}", flush=True)

    with Camoufox(
        headless="virtual",
        canvas_noise=False,
        humanize=True,
        persistent_context=True,
        user_data_dir=prof_dir,
        proxy=proxy,
        geoip=True,
        i_know_what_im_doing=True,
    ) as browser:
        anchor_page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            browser.route("**/*producthunt.com/*", lambda route: route.abort())
        except Exception:
            anchor_page.route("**/*producthunt.com/*", lambda route: route.abort())

        imported_state = f"{prof_dir}/imported_storage_state.json"
        if os.path.exists(imported_state):
            try:
                st_data = json.load(open(imported_state))
                if st_data.get("cookies"):
                    browser.add_cookies(st_data["cookies"])
            except Exception:
                pass

        cookies = browser.cookies("https://accounts.google.com")
        signed_in = any(c.get("name") in ("SID", "SSID", "HSID", "SAPISID", "__Secure-1PSID") for c in cookies)
        print(f"[slot {args.slot}] google_signed_in={signed_in} ({email[:4]}***)", flush=True)

        for k, item in enumerate(todo, start=1):
            rec = run_4step_interactive_session(browser, item, email=email, signed_in=signed_in)
            rec["slot"] = args.slot
            rec["account_idx"] = args.account_idx
            rec["google_signed_in"] = signed_in
            with open(local_out, "a") as f:
                f.write(json.dumps(rec) + "\n")
            if k % 8 == 0 or k == len(todo):
                gcs_upload_bytes(gcs_out, open(local_out, "rb").read())
                print(
                    f"[slot {args.slot}] {k}/{len(todo)} done "
                    f"(id={rec.get('item_id')} sso={rec.get('google_sso_entered')} "
                    f"act={rec.get('workflow_action')} working={rec.get('reached_working_product')})",
                    flush=True,
                )

    if os.path.exists(local_out):
        gcs_upload_bytes(gcs_out, open(local_out, "rb").read())
    print(f"[slot {args.slot}] INTERACTIVE 4-STEP CUA SWEEP COMPLETE ({len(my_targets)} items)", flush=True)


if __name__ == "__main__":
    main()
