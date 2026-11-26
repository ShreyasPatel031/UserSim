"""Parallel 5-VM Signed-In Google-SSO Camoufox Deep Product-Use Sweep (`pool_b_batch_sweep.py`).

Runs on each of the 5 pinned signed-in Pool B fleet VMs (`slots 32, 40, 42, 44, 45`), reading a
target manifest from GCS (`usersim_sim/raw/fleet_external/_jobs/hillclimb3_targets.jsonl`), sharding
`i % 5 == (account_idx - 1)`, and inspecting each external product URL inside the signed-in Google
Camoufox session (`producthunt.com` strictly blocked per `AGENTS.md` L141):
  1. Full JS/SPA DOM hydration (`title`, `headings`, `ctas`, interactive elements, `/pricing`, `/docs`).
  2. Real `"Continue with Google"` / `"Sign in with Google"` OAuth entry handling BOTH popup windows
     (`window.open` used by Clerk/Firebase/Supabase/Auth0) AND same-tab OAuth redirects!
  3. Post-SSO workspace vs hard-paywall / waitlist / broken-auth classification.
  4. Never solves or clicks CAPTCHAs / anti-bot challenges; uploads incremental JSONL shards to GCS.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
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
_PAYWALL_RE = re.compile(
    r"(\benter\s+(your\s+)?(card|payment|billing)\b|\bcredit\s+card\s+required\b|checkout\.stripe\.com|\bsubscribe\s+to\s+continue\b|\bupgrade\s+to\s+access\b|\bstart\s+\d+-day\s+paid\s+trial\b)",
    re.IGNORECASE,
)
_WAITLIST_AFTER_LOGIN_RE = re.compile(
    r"(\byou['’]?re\s+on\s+the\s+waitlist\b|\brequest\s+early\s+access\b|\baccount\s+pending\s+approval\b|\binvite\s+code\s+required\b)",
    re.IGNORECASE,
)
_WORKSPACE_URL_RE = re.compile(
    r"/(app|dashboard|workspace|projects|onboarding|welcome|studio|editor|chat|home|console|playground)\b",
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
    urllib.request.urlopen(req, timeout=30).read()


def _complete_google_oauth_on_page(oauth_page: Any, email: str) -> bool:
    """Select our signed-in Google account on an OAuth chooser / consent page (popup or main tab)."""
    try:
        oauth_page.wait_for_timeout(1800)
        if oauth_page.is_closed():
            return True
        u = oauth_page.url.lower()
        if "accounts.google.com" not in u:
            return True
        body_low = oauth_page.inner_text("body")[:1500].lower()
        if _CAPTCHA_RE.search(body_low) or "verify it" in body_low:
            return False

        # 1. Click our signed-in account row on oauthchooseaccount
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
                    loc.click(timeout=3500)
                    oauth_page.wait_for_timeout(2500)
                    break
            except Exception:
                continue

        if oauth_page.is_closed():
            return True

        # 2. Click OAuth consent "Continue" / "Allow" if Google asks to share name/email
        for label in ("Continue", "Allow", "Confirm"):
            for sel in (f'button:has-text("{label}")', f'div[role="button"]:has-text("{label}")', f'span:has-text("{label}")'):
                try:
                    if oauth_page.is_closed():
                        return True
                    btn = oauth_page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=3500)
                        oauth_page.wait_for_timeout(2800)
                        break
                except Exception:
                    continue

        return oauth_page.is_closed() or ("accounts.google.com" not in oauth_page.url.lower())
    except Exception:
        return oauth_page.is_closed()


def inspect_one_target(browser: Any, item: dict[str, Any], email: str, signed_in: bool) -> dict[str, Any]:
    lid = str(item["item_id"])
    day = str(item["day"])
    url = str(item["url"])
    t0 = time.time()

    if not url or "producthunt.com" in url.lower():
        return {"item_id": lid, "day": day, "input_url": url, "access_status": "no_url"}

    page = browser.new_page()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=22000)
        page.wait_for_timeout(2000)
        http_code = resp.status if resp else 0
        landing_u = page.url
        if "producthunt.com" in landing_u.lower():
            return {"item_id": lid, "day": day, "input_url": url, "access_status": "blocked_ph_redirect"}

        title = page.title()[:200]
        dom_info = page.evaluate(
            """() => {
                const bodyTxt = document.body ? document.body.innerText : '';
                const hs = Array.from(document.querySelectorAll('h1,h2,h3')).slice(0, 12).map(e => e.innerText.trim()).filter(Boolean);
                const ctas = Array.from(document.querySelectorAll('a,button')).map(e => e.innerText.trim()).filter(t => t.length >= 2 && t.length <= 45).slice(0, 18);
                const hrefs = Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') || '').slice(0, 80);
                const nInputs = document.querySelectorAll('input,textarea,[contenteditable="true"],canvas').length;
                return {bodyTxt: bodyTxt.slice(0, 5000), hs, ctas, hrefs, nInputs};
            }"""
        )
        body_txt = " ".join((dom_info.get("bodyTxt") or "").split())
        low = body_txt.lower()

        if len(body_txt) < 600 and _CAPTCHA_RE.search(low):
            return {
                "item_id": lid,
                "day": day,
                "input_url": url,
                "final_url": landing_u,
                "http_status": http_code,
                "access_status": "captcha",
                "elapsed_s": round(time.time() - t0, 2),
            }

        hrefs_joined = " ".join(dom_info.get("hrefs") or []).lower()
        has_pricing_link = "/pricing" in hrefs_joined or "#pricing" in hrefs_joined
        has_docs_link = "/docs" in hrefs_joined or "docs." in hrefs_joined or "/api" in hrefs_joined
        has_github_link = "github.com/" in hrefs_joined or "github.com/" in landing_u.lower()
        n_inputs = int(dom_info.get("nInputs") or 0)

        sso_attempted = False
        sso_entered = False
        post_sso_url = landing_u
        post_sso_txt = ""
        post_sso_paywall = False
        post_sso_waitlist = False
        post_sso_workspace = False

        sso_selector = (
            'button:has-text("Continue with Google"), a:has-text("Continue with Google"), '
            'button:has-text("Sign in with Google"), a:has-text("Sign in with Google"), '
            'button:has-text("Sign up with Google"), a:has-text("Sign up with Google"), '
            'div[role="button"]:has-text("Continue with Google")'
        )

        if signed_in:
            sso_loc = page.locator(sso_selector)
            if sso_loc.count() == 0:
                # Try clicking Sign in / Log in / Get started / Start for free to expose Google SSO!
                gate_loc = page.locator(
                    'a:has-text("Sign in"), button:has-text("Sign in"), '
                    'a:has-text("Log in"), button:has-text("Log in"), '
                    'a:has-text("Get started"), button:has-text("Get started"), '
                    'a:has-text("Start for free"), button:has-text("Start for free")'
                )
                if gate_loc.count() > 0 and gate_loc.first.is_visible():
                    try:
                        gate_loc.first.click(timeout=3000)
                        page.wait_for_timeout(1800)
                        sso_loc = page.locator(sso_selector)
                    except Exception:
                        pass

            if sso_loc.count() > 0 and sso_loc.first.is_visible():
                sso_attempted = True
                pages_before = len(browser.pages)
                try:
                    sso_loc.first.click(timeout=4000)
                    page.wait_for_timeout(2200)
                    # Case A: OAuth opened a popup window!
                    if len(browser.pages) > pages_before:
                        popup = browser.pages[-1]
                        _complete_google_oauth_on_page(popup, email)
                        page.wait_for_timeout(2800)
                        if not popup.is_closed() and "accounts.google.com" not in popup.url.lower():
                            # Sometimes the popup itself becomes the app window
                            page = popup
                    # Case B: Same-tab redirect to accounts.google.com!
                    elif "accounts.google.com" in page.url.lower():
                        _complete_google_oauth_on_page(page, email)
                        page.wait_for_timeout(2500)

                    post_sso_url = page.url
                    if (
                        "accounts.google.com" not in post_sso_url.lower()
                        and "producthunt.com" not in post_sso_url.lower()
                    ):
                        post_body = " ".join(page.inner_text("body").split())[:3000]
                        if post_sso_url != landing_u or abs(len(post_body) - len(body_txt)) > 120:
                            sso_entered = True
                            post_sso_txt = post_body
                            p_low = post_body.lower()
                            post_sso_paywall = bool(_PAYWALL_RE.search(p_low) or "stripe.com" in post_sso_url.lower())
                            post_sso_waitlist = bool(_WAITLIST_AFTER_LOGIN_RE.search(p_low))
                            post_sso_workspace = bool(
                                not post_sso_paywall
                                and not post_sso_waitlist
                                and (_WORKSPACE_URL_RE.search(post_sso_url) or len(post_body) >= 200)
                            )
                except Exception:
                    pass

        return {
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "item_id": lid,
            "day": day,
            "input_url": url,
            "final_url": landing_u,
            "post_sso_url": post_sso_url,
            "http_status": http_code,
            "access_status": "clean" if (len(body_txt) >= 80 or sso_entered) else "js_empty",
            "elapsed_s": round(time.time() - t0, 2),
            "title": title,
            "headings": dom_info.get("hs") or [],
            "ctas": dom_info.get("ctas") or [],
            "n_interactive_inputs": n_inputs,
            "has_pricing_link": has_pricing_link,
            "has_docs_link": has_docs_link,
            "has_github_link": has_github_link,
            "text_len": len(body_txt),
            "text_excerpt": body_txt[:3000],
            "google_sso_attempted": sso_attempted,
            "google_sso_entered": sso_entered,
            "post_sso_paywall": post_sso_paywall,
            "post_sso_waitlist": post_sso_waitlist,
            "post_sso_workspace": post_sso_workspace,
            "post_sso_excerpt": post_sso_txt[:2000],
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
    ap.add_argument("--job-name", default="hillclimb3")
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
    print(f"[slot {args.slot}] Total shard targets={len(my_targets)}, already_done={len(done_ids)}, todo={len(todo)}", flush=True)

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
            rec = inspect_one_target(browser, item, email=email, signed_in=signed_in)
            rec["slot"] = args.slot
            rec["account_idx"] = args.account_idx
            rec["google_signed_in"] = signed_in
            with open(local_out, "a") as f:
                f.write(json.dumps(rec) + "\n")
            if k % 10 == 0 or k == len(todo):
                gcs_upload_bytes(gcs_out, open(local_out, "rb").read())
                print(f"[slot {args.slot}] {k}/{len(todo)} done (last={rec.get('item_id')} sso_entered={rec.get('google_sso_entered')})", flush=True)

    if os.path.exists(local_out):
        gcs_upload_bytes(gcs_out, open(local_out, "rb").read())
    print(f"[slot {args.slot}] SWEEP COMPLETE ({len(my_targets)} items)", flush=True)


if __name__ == "__main__":
    main()
