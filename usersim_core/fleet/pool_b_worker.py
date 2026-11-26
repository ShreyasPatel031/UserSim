"""Pinned Sticky-IP Pool B Worker: Google SSO Sign-In + Live Product & Competitor Feedback Puller.

Runs on the 5 pinned Pool B fleet VMs (`slots 32, 40, 42, 44, 45`, 1 Gmail account per sticky IP):
  1. Reads assigned Gmail credentials (`slot_idx = 1..5`) directly from GCP Secret Manager
     (`usersim-fleet-gmail-accounts`) and reads the VM's sticky IPRoyal proxy from GCE metadata
     (`instance/attributes/proxy-url`). Never logs passwords, cookies, or tokens.
  2. Signs into `accounts.google.com` inside a persistent Camoufox virtual-display profile
     (`/var/tmp/usersim_google_sso/gmail_<idx>`). Never attempts to solve or bypass CAPTCHAs,
     anti-bot challenges, or phone/2FA gates; records exact `google_auth_status` honestly.
  3. Continuously pulls (sharded `i % 5 == idx - 1`, human-paced):
     - Live PH launch external product URLs (`sites_0005.json`, `producthunt.com` strictly blocked
       per `AGENTS.md` L141) in real Camoufox with JS execution + `"Continue with Google"` OAuth
       click-through when signed in, writing surface records to
       `gs://usersim-bakeoff-347838016394/usersim_sim/raw/fleet_external/<day>/product_surfaces_slot<slot>.jsonl`.
     - Public competitor user-feedback threads (HN Algolia public search API) for SaaS categories,
       writing verbatim user praise/complaint threads to
       `gs://usersim-bakeoff-347838016394/usersim_sim/raw/fleet_external/reviews/competitor_feedback_slot<slot>.jsonl`.
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

SAAS_COMPETITOR_SEEDS = [
    "Linear", "Notion", "Supabase", "Vercel", "Cursor", "PostHog", "Retool", "Airtable",
    "Figma", "Loom", "Calendly", "Stripe", "Clerk", "Resend", "Raycast", "Obsidian",
    "Clay", "Attio", "Deel", "Rippling", "Intercom", "Sentry", "Datadog", "Zapier",
    "n8n", "ElevenLabs", "Perplexity", "v0", "Lovable", "Bolt.new",
]


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


def get_gmail_account(account_idx: int) -> tuple[str, str]:
    tok = get_access_token()
    url = f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/usersim-fleet-gmail-accounts/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    payload = json.loads(base64.b64decode(resp["payload"]["data"]).decode("utf-8"))
    for acc in payload.get("accounts") or []:
        if int(acc.get("slot_idx", 0)) == account_idx:
            return str(acc["email"]), str(acc["password"])
    raise RuntimeError(f"slot_idx={account_idx} not found")


def gcs_download_json(obj_path: str) -> Any:
    tok = get_access_token()
    enc = urllib.parse.quote(obj_path, safe="")
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{enc}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def gcs_upload_bytes(obj_path: str, data: bytes, content_type: str = "application/json") -> None:
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


def _has_google_session_cookie(browser_ctx: Any) -> bool:
    try:
        cookies = browser_ctx.cookies("https://accounts.google.com")
        names = {c.get("name", "") for c in cookies}
        return bool(names & {"SID", "SSID", "HSID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"})
    except Exception:
        return False


def _click_first_visible(page: Any, labels: tuple[str, ...]) -> bool:
    for text in labels:
        for sel in (
            f'button:has-text("{text}")',
            f'div[role="button"]:has-text("{text}")',
            f'a:has-text("{text}")',
            f'li:has-text("{text}")',
            f'span:has-text("{text}")',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=4000)
                    return True
            except Exception:
                continue
    return False


def attempt_google_signin(browser_ctx: Any, page: Any, email: str, password: str) -> dict[str, Any]:
    masked = email[:4] + "***@" + email.split("@")[-1]
    try:
        if _has_google_session_cookie(browser_ctx):
            page.goto("https://myaccount.google.com/?hl=en", wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(2500)
            if _has_google_session_cookie(browser_ctx) and "signin" not in page.url.lower():
                return {"status": "already_signed_in", "account": masked, "final_url": page.url.split("?")[0]}

        page.goto("https://accounts.google.com/signin/v2/identifier?hl=en", wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(3000)

        # Fresh profiles render input[name="identifier"][type="text"] (#identifierId); returning get type="email"
        email_loc = page.locator('input[name="identifier"], input#identifierId, input[type="email"]').first
        try:
            email_loc.wait_for(state="visible", timeout=15000)
        except Exception:
            # Might be on account chooser
            if "choose an account" in page.inner_text("body").lower():
                _click_first_visible(page, (email, "Use another account"))
                page.wait_for_timeout(2500)
                email_loc = page.locator('input[name="identifier"], input#identifierId, input[type="email"]').first

        if email_loc.count() == 0 or not email_loc.is_visible():
            body_snip = " ".join(page.inner_text("body").split())[:180]
            return {"status": "no_email_input", "account": masked, "final_url": page.url.split("?")[0], "detail": body_snip}

        email_loc.fill(email)
        page.wait_for_timeout(500)
        if not _click_first_visible(page, ("Next",)):
            page.keyboard.press("Enter")
        page.wait_for_timeout(4500)

        # Check immediately if Google presented a CAPTCHA — never touch or solve CAPTCHAs!
        cur_u = page.url
        body_mid = " ".join(page.inner_text("body").split())
        low_mid = body_mid.lower()
        if "captcha" in low_mid or "not a robot" in low_mid or page.locator('iframe[src*="recaptcha"], img[src*="captcha"]').count() > 0:
            return {
                "status": "blocked_captcha_before_password",
                "account": masked,
                "final_url": cur_u.split("?")[0],
                "detail": body_mid[:160],
            }

        # Escape passkey prompt to standard password if offered
        if any(k in low_mid for k in ("passkey", "security key", "choose how you want to sign in")):
            if _click_first_visible(page, ("Enter your password", "Use your password", "Try another way")):
                page.wait_for_timeout(3000)
                _click_first_visible(page, ("Enter your password", "Use your password"))
                page.wait_for_timeout(2500)

        pw_loc = page.locator('input[name="Passwd"], input[type="password"]').first
        try:
            pw_loc.wait_for(state="visible", timeout=12000)
        except Exception:
            body_mid2 = " ".join(page.inner_text("body").split())[:180]
            return {
                "status": "challenge_or_rejected_before_password",
                "account": masked,
                "final_url": page.url.split("?")[0],
                "detail": body_mid2,
            }

        pw_loc.fill(password)
        page.wait_for_timeout(600)
        if not _click_first_visible(page, ("Next",)):
            page.keyboard.press("Enter")
        page.wait_for_timeout(6000)

        # Dismiss harmless post-auth passkey / recovery-upsell interstitials ("Not now" / "Skip" / "I understand")
        for _ in range(3):
            if _has_google_session_cookie(browser_ctx):
                break
            cur_low = page.inner_text("body").lower()
            # Never touch 2FA / phone / CAPTCHA challenges — stop immediately if present!
            if any(ch in cur_low for ch in ("verify it's you", "verify it’s you", "enter a phone number", "get a verification code", "confirm your recovery", "captcha")):
                break
            if _click_first_visible(page, ("Not now", "Skip", "I understand", "Continue", "Done")):
                page.wait_for_timeout(3000)
            else:
                break

        has_sess = _has_google_session_cookie(browser_ctx)
        cur_u = page.url
        body_after = " ".join(page.inner_text("body").split())[:220]
        low_after = body_after.lower()

        if has_sess and "challenge" not in cur_u.lower() and "rejected" not in cur_u.lower():
            return {
                "status": "signed_in_ok",
                "account": masked,
                "has_google_sid_cookie": True,
                "final_url": cur_u.split("?")[0],
            }
        if "wrong password" in low_after:
            return {"status": "wrong_password", "account": masked, "final_url": cur_u.split("?")[0]}
        if any(ch in low_after for ch in ("verify it's you", "verify it’s you", "phone number", "verification code", "recovery email")) or "challenge" in cur_u.lower():
            return {
                "status": "google_verification_challenge",
                "account": masked,
                "has_google_sid_cookie": has_sess,
                "final_url": cur_u.split("?")[0],
                "detail": body_after[:180],
            }
        return {
            "status": "signed_in_ok" if has_sess else "post_login_unverified",
            "account": masked,
            "has_google_sid_cookie": has_sess,
            "final_url": cur_u.split("?")[0],
            "detail": body_after[:180],
        }
    except Exception as e:
        return {"status": f"error:{type(e).__name__}", "account": masked, "detail": str(e)[:180]}


def handle_google_oauth_popup_or_redirect(page: Any, email: str) -> bool:
    """Select our signed-in account on an OAuth chooser / consent page (popup or main tab)."""
    try:
        page.wait_for_timeout(1800)
        if page.is_closed():
            return True
        if "accounts.google.com" not in page.url.lower():
            return True
        body_low = page.inner_text("body")[:1500].lower()
        if "captcha" in body_low or "verify it" in body_low:
            return False
        for sel in (
            f'div[data-identifier="{email.lower()}"]',
            f'div[data-email="{email.lower()}"]',
            f'li:has-text("{email}")',
            f'div[role="link"]:has-text("{email}")',
            'div[data-identifier]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=3500)
                    page.wait_for_timeout(2500)
                    break
            except Exception:
                continue
        if page.is_closed():
            return True
        _click_first_visible(page, ("Continue", "Allow", "Confirm"))
        page.wait_for_timeout(2800)
        return page.is_closed() or ("accounts.google.com" not in page.url.lower())
    except Exception:
        return page.is_closed()


def inspect_product_page(browser: Any, page: Any, item_id: str, url: str, signed_in: bool, email: str) -> dict[str, Any]:
    """Visit external launch URL in Camoufox (`producthunt.com` strictly blocked per AGENTS.md)."""
    if not url or "producthunt.com" in url.lower():
        return {"item_id": item_id, "url": url, "status": "skipped_ph_or_empty"}
    t0 = time.time()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        http_code = resp.status if resp else 0
        landing_u = page.url
        if "producthunt.com" in landing_u.lower():
            return {"item_id": item_id, "url": url, "status": "blocked_redirect_to_ph"}

        title = page.title()
        body_txt = " ".join(page.inner_text("body").split())
        low = body_txt.lower()

        sso_attempted = False
        sso_entered = False
        post_sso_url = landing_u
        post_sso_excerpt = ""

        # If signed into Google, test whether launch gates behind Sign In / Continue with Google and enter cleanly!
        if signed_in:
            sso_loc = page.locator(
                'button:has-text("Continue with Google"), a:has-text("Continue with Google"), '
                'button:has-text("Sign in with Google"), a:has-text("Sign in with Google")'
            )
            if sso_loc.count() == 0:
                # Check if clicking "Sign in" / "Get Started" / "Start for free" reveals Google SSO
                gate_loc = page.locator('a:has-text("Sign in"), button:has-text("Sign in"), a:has-text("Log in")')
                if gate_loc.count() > 0 and gate_loc.first.is_visible():
                    try:
                        gate_loc.first.click(timeout=3500)
                        page.wait_for_timeout(2000)
                        sso_loc = page.locator(
                            'button:has-text("Continue with Google"), a:has-text("Continue with Google"), '
                            'button:has-text("Sign in with Google"), a:has-text("Sign in with Google")'
                        )
                    except Exception:
                        pass
            if sso_loc.count() > 0 and sso_loc.first.is_visible():
                sso_attempted = True
                pages_before = len(browser.pages)
                try:
                    sso_loc.first.click(timeout=4500)
                    page.wait_for_timeout(2500)
                    target_p = page
                    if len(browser.pages) > pages_before:
                        popup = browser.pages[-1]
                        handle_google_oauth_popup_or_redirect(popup, email)
                        page.wait_for_timeout(2800)
                        if not popup.is_closed() and "accounts.google.com" not in popup.url.lower():
                            target_p = popup
                    elif "accounts.google.com" in page.url.lower():
                        handle_google_oauth_popup_or_redirect(page, email)
                        page.wait_for_timeout(2500)

                    post_sso_url = target_p.url
                    if "accounts.google.com" not in post_sso_url.lower() and "producthunt.com" not in post_sso_url.lower():
                        p_body = " ".join(target_p.inner_text("body").split())[:2000]
                        if post_sso_url != landing_u or abs(len(p_body) - len(body_txt)) > 120:
                            sso_entered = True
                            post_sso_excerpt = p_body
                except Exception:
                    pass
                finally:
                    for extra_p in list(browser.pages)[1:]:
                        if not extra_p.is_closed():
                            try:
                                extra_p.close()
                            except Exception:
                                pass

        return {
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "item_id": item_id,
            "input_url": url,
            "final_url": landing_u,
            "post_sso_url": post_sso_url,
            "http_status": http_code,
            "elapsed_s": round(time.time() - t0, 2),
            "title": title[:200],
            "text_len": len(body_txt),
            "text_excerpt": body_txt[:2500],
            "post_sso_excerpt": post_sso_excerpt,
            "has_interactive_demo": bool(re.search(r"\b(playground|live demo|try it now|try without signing|sandbox)\b", low)),
            "has_open_source": bool("github.com/" in low or "open source" in low or "npm install" in low or "pip install" in low),
            "has_free_tier": bool(re.search(r"\b(free forever|free plan|start for free|free tier|\$0)\b", low)),
            "has_pricing": bool(re.search(r"\b(pricing|/month|per month|\$\d+)\b", low)),
            "is_waitlist": bool("join waitlist" in low or "join the waitlist" in low or "request early access" in low),
            "google_sso_attempted": sso_attempted,
            "google_sso_entered": sso_entered,
        }
    except Exception as e:
        return {
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "item_id": item_id,
            "input_url": url,
            "status": f"err:{type(e).__name__}",
            "detail": str(e)[:180],
        }


def pull_competitor_feedback_batch(shard_idx: int, n_shards: int, out_jsonl: str, proxy_dict: dict[str, str]) -> int:
    """Pull real user praise/complaint discussions from HN Algolia public API via sticky proxy for Atelier Sim."""
    done_seeds: set[str] = set()
    if os.path.exists(out_jsonl):
        for l in open(out_jsonl):
            try:
                done_seeds.add(str(json.loads(l).get("competitor")))
            except Exception:
                pass
    my_seeds = [s for i, s in enumerate(SAAS_COMPETITOR_SEEDS) if i % n_shards == (shard_idx - 1) and s not in done_seeds]
    if not my_seeds:
        return 0

    # Route urllib through VM's sticky proxy if credentials present
    p_srv = proxy_dict["server"]
    if "username" in proxy_dict and "password" in proxy_dict:
        u_enc = urllib.parse.quote(proxy_dict["username"], safe="")
        p_enc = urllib.parse.quote(proxy_dict["password"], safe="")
        host_port = p_srv.split("://", 1)[-1]
        p_full = f"http://{u_enc}:{p_enc}@{host_port}"
    else:
        p_full = p_srv
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": p_full, "https": p_full}))

    saved = 0
    for comp in my_seeds[:2]:  # Pace gently: 2 competitors per 5-minute cycle
        q = urllib.parse.quote(comp)
        url = f"https://hn.algolia.com/api/v1/search?query={q}&tags=comment&hitsPerPage=15"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(opener.open(req, timeout=15).read().decode("utf-8"))
            hits = raw.get("hits") or []
            rec = {
                "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "competitor": comp,
                "source": "hn_algolia_comments",
                "count": len(hits),
                "comments": [
                    {
                        "objectID": h.get("objectID"),
                        "author": h.get("author"),
                        "created_at": h.get("created_at"),
                        "story_title": h.get("story_title"),
                        "comment_text": (h.get("comment_text") or "")[:1200],
                    }
                    for h in hits[:15]
                ],
            }
            with open(out_jsonl, "a") as f:
                f.write(json.dumps(rec) + "\n")
            saved += 1
            time.sleep(1.5)
        except Exception:
            break
    return saved


def load_today_targets(shard_idx: int, n_shards: int = 5) -> tuple[str, list[tuple[str, str]]]:
    """Fetch latest daily sites_0005.json from GCS and return this worker's shard."""
    today_pt = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8)).date()
    for delta in (0, 1):
        d_str = (today_pt - dt.timedelta(days=delta)).isoformat()
        try:
            j = gcs_download_json(f"usersim_sim/raw/daily/{d_str}/sites_0005.json")
            launches = j.get("launches") or {}
            pairs = []
            for lid, rec in sorted(launches.items()):
                fu = str(rec.get("final_url") or "")
                if fu and "producthunt.com" not in fu.lower():
                    pairs.append((str(lid), fu))
            if pairs:
                my_pairs = [p for i, p in enumerate(pairs) if i % n_shards == (shard_idx - 1)]
                return d_str, my_pairs
        except Exception:
            continue
    return today_pt.isoformat(), []


def run_worker(slot: int, account_idx: int, once: bool = False, retry_auth: bool = False) -> None:
    from camoufox.sync_api import Camoufox  # type: ignore[import-untyped]

    proxy = get_metadata_proxy()
    email, password = get_gmail_account(account_idx)
    prof_dir = f"/var/tmp/usersim_google_sso/gmail_{account_idx}"
    os.makedirs(prof_dir, exist_ok=True)
    out_dir = f"/var/tmp/usersim_poolb_out/slot_{slot}"
    os.makedirs(out_dir, exist_ok=True)

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
        page = browser.pages[0] if browser.pages else browser.new_page()
        # Enforce AGENTS.md L141: block producthunt.com in every Camoufox context!
        try:
            browser.route("**/*producthunt.com/*", lambda route: route.abort())
        except Exception:
            page.route("**/*producthunt.com/*", lambda route: route.abort())

        # If the user signed in natively on Mac over this VM's exact sticky IP and synced
        # imported_storage_state.json, inject those cookies into the persistent Camoufox profile!
        imported_state_path = f"{prof_dir}/imported_storage_state.json"
        if os.path.exists(imported_state_path):
            try:
                st_data = json.load(open(imported_state_path))
                cookies = st_data.get("cookies") or []
                if cookies:
                    browser.add_cookies(cookies)
            except Exception:
                pass

        cached_auth_path = f"{prof_dir}/last_auth_result.json"
        if not retry_auth and os.path.exists(cached_auth_path):
            prev_auth = json.load(open(cached_auth_path))
            if prev_auth.get("status") in ("google_verification_challenge", "blocked_captcha_before_password", "wrong_password"):
                # Do not hammer accounts.google.com on service restarts while awaiting human 1-time verification
                auth_info = prev_auth
            else:
                auth_info = attempt_google_signin(browser, page, email, password)
                json.dump(auth_info, open(cached_auth_path, "w"), indent=2)
        else:
            auth_info = attempt_google_signin(browser, page, email, password)
            json.dump(auth_info, open(cached_auth_path, "w"), indent=2)
        signed_in = auth_info.get("status") in ("signed_in_ok", "already_signed_in")
        auth_report = {
            "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "slot": slot,
            "account_idx": account_idx,
            "proxy_server": proxy["server"],
            **auth_info,
        }
        print(json.dumps(auth_report), flush=True)
        gcs_upload_bytes(
            f"usersim_sim/raw/fleet_external/_status/slot_{slot}_auth.json",
            json.dumps(auth_report, indent=2).encode("utf-8"),
        )

        while True:
            day_str, targets = load_today_targets(account_idx, n_shards=5)
            local_jsonl = f"{out_dir}/surfaces_{day_str}.jsonl"
            if retry_auth and signed_in and os.path.exists(local_jsonl):
                # Re-pull if prior pass ran before Google sign-in succeeded
                has_signed_rows = any('"google_signed_in": true' in l for l in open(local_jsonl))
                if not has_signed_rows:
                    os.remove(local_jsonl)

            done_ids: set[str] = set()
            if os.path.exists(local_jsonl):
                for l in open(local_jsonl):
                    try:
                        done_ids.add(str(json.loads(l).get("item_id")))
                    except Exception:
                        pass

            pulled_now = 0
            sso_entered_count = 0
            for lid, u in targets:
                if lid in done_ids:
                    continue
                rec = inspect_product_page(browser, page, lid, u, signed_in=signed_in, email=email)
                rec["slot"] = slot
                rec["account_idx"] = account_idx
                rec["google_signed_in"] = signed_in
                if rec.get("google_sso_entered"):
                    sso_entered_count += 1
                with open(local_jsonl, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                pulled_now += 1
                time.sleep(3.0)

            if os.path.exists(local_jsonl):
                gcs_upload_bytes(
                    f"usersim_sim/raw/fleet_external/{day_str}/product_surfaces_slot{slot}.jsonl",
                    open(local_jsonl, "rb").read(),
                    content_type="application/x-ndjson",
                )

            comp_jsonl = f"{out_dir}/competitor_feedback.jsonl"
            comp_pulled = pull_competitor_feedback_batch(account_idx, 5, comp_jsonl, proxy)
            if os.path.exists(comp_jsonl):
                gcs_upload_bytes(
                    f"usersim_sim/raw/fleet_external/reviews/competitor_feedback_slot{slot}.jsonl",
                    open(comp_jsonl, "rb").read(),
                    content_type="application/x-ndjson",
                )

            total_comp = sum(1 for _ in open(comp_jsonl)) if os.path.exists(comp_jsonl) else 0
            hb = {
                "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "slot": slot,
                "account_idx": account_idx,
                "google_auth_status": auth_info.get("status"),
                "google_signed_in": signed_in,
                "day": day_str,
                "targets_assigned": len(targets),
                "pulled_this_pass": pulled_now,
                "sso_entered_this_pass": sso_entered_count,
                "total_surfaces_saved_today": len(done_ids) + pulled_now,
                "competitor_feedback_batches_saved": total_comp,
            }
            gcs_upload_bytes(
                f"usersim_sim/raw/fleet_external/_status/slot_{slot}_heartbeat.json",
                json.dumps(hb, indent=2).encode("utf-8"),
            )
            print(json.dumps(hb), flush=True)
            if once:
                break
            retry_auth = False
            time.sleep(300.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--account-idx", type=int, required=True)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--retry-auth", action="store_true")
    args = ap.parse_args()
    run_worker(args.slot, args.account_idx, once=args.once, retry_auth=args.retry_auth)


if __name__ == "__main__":
    main()
