"""Persistent Sticky-IP Google SSO Sign-In Driver (`usersim_core/fleet/google_sso_signin.py`).

Signs one fleet VM into its assigned Gmail account (`1..5`) from GCP Secret Manager
(`usersim-fleet-gmail-accounts`) over that VM's PINNED sticky IPRoyal `.purl` proxy
into a persistent Camoufox profile directory (`/var/lib/usersim/profiles/gmail_<idx>`).

Security & Compliance:
  - Never logs or prints passwords or cookies.
  - Strictly 1 account : 1 pinned sticky IP (`NEVER` rotate IP on a Pool B account slot).
  - Never bypasses CAPTCHAs or 2FA/phone verification — if Google presents a challenge,
    records `needs_verification` and exits cleanly without hammering.

Usage on a pinned Pool B fleet VM:
  python3 -m usersim_core.fleet.google_sso_signin \
      --account-idx 1 \
      --purl-file /agent/repos/usersim/secrets/iproyal_fi_16.purl \
      --profile-dir /var/lib/usersim/profiles/gmail_1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from urllib.parse import urlparse


def load_account_from_gsm(account_idx: int, project: str = "project-amer-scs-sandbox") -> tuple[str, str]:
    raw = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=usersim-fleet-gmail-accounts", f"--project={project}"],
        text=True,
    )
    data = json.loads(raw)
    accounts = data.get("accounts") or []
    for acc in accounts:
        if int(acc.get("slot_idx", 0)) == account_idx:
            return str(acc["email"]), str(acc["password"])
    raise ValueError(f"Account slot_idx={account_idx} not found in usersim-fleet-gmail-accounts")


def parse_purl(purl_path: str) -> dict[str, str]:
    txt = open(purl_path).read().strip()
    u = urlparse(txt)
    proxy: dict[str, str] = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        proxy["username"] = u.username
    if u.password:
        proxy["password"] = u.password
    return proxy


def sign_in_google_camoufox(account_idx: int, purl_file: str, profile_dir: str, project: str) -> dict[str, str]:
    from camoufox.sync_api import Camoufox  # type: ignore[import-untyped]

    email, password = load_account_from_gsm(account_idx, project=project)
    proxy = parse_purl(purl_file)
    os.makedirs(profile_dir, exist_ok=True)
    masked = email[:3] + "***@" + email.split("@")[-1]

    with Camoufox(
        headless=True,
        persistent_context=True,
        user_data_dir=profile_dir,
        proxy=proxy,
        geoip=True,
    ) as browser:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)

        # Already signed in on persistent profile?
        if "myaccount.google.com" in page.url:
            return {"status": "already_signed_in", "account": masked, "profile_dir": profile_dir}

        email_box = page.locator('input[type="email"]').first
        email_box.wait_for(state="visible", timeout=20000)
        email_box.fill(email)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3500)

        # Check for captcha / challenge before password
        if page.locator('input[type="password"]').count() == 0:
            return {"status": "needs_verification_or_challenge", "account": masked, "url": page.url.split("?")[0]}

        pw_box = page.locator('input[type="password"]').first
        pw_box.wait_for(state="visible", timeout=20000)
        pw_box.fill(password)
        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)

        cur = page.url
        if "myaccount.google.com" in cur or "mail.google.com" in cur:
            return {"status": "signed_in_ok", "account": masked, "profile_dir": profile_dir}
        return {"status": "needs_verification_or_challenge", "account": masked, "url": cur.split("?")[0]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-idx", type=int, required=True, help="1..5 index inside usersim-fleet-gmail-accounts")
    ap.add_argument("--purl-file", required=True, help="Pinned sticky IPRoyal .purl file (NEVER rotate)")
    ap.add_argument("--profile-dir", required=True, help="Persistent Camoufox user_data_dir on the VM")
    ap.add_argument("--project", default="project-amer-scs-sandbox")
    args = ap.parse_args()

    res = sign_in_google_camoufox(args.account_idx, args.purl_file, args.profile_dir, args.project)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
