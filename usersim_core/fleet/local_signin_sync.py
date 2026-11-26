"""Native macOS Camoufox Sign-In & Auto-Sync to Pinned Pool B Fleet VM.

Opens a 100% native macOS Camoufox browser routed through the EXACT sticky IPRoyal proxy
assigned to a Pool B fleet VM (`slots 32, 40, 42, 44, 45`), lets you complete Google's
1-time sign-in / SMS check with native clicking and copy-paste, and automatically syncs
the signed-in cookies (`imported_storage_state.json`) to that VM and restarts `usersim-poolb.service`.

Usage:
  local_signin_sync.py --slot 32
  local_signin_sync.py --slot 40
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import urllib.parse
from typing import Any


PROJECT = "project-amer-scs-sandbox"
ZONE = "us-central1-a"
SLOT_TO_IDX = {32: 1, 40: 2, 42: 3, 44: 4, 45: 5}


def _gcloud_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/share/google-cloud-sdk/bin:/opt/homebrew/bin:" + env.get("PATH", "")
    env["CLOUDSDK_CORE_ACCOUNT"] = "usersim-cloud-agent@project-amer-scs-sandbox.iam.gserviceaccount.com"
    return env


def get_vm_proxy(slot: int) -> dict[str, str]:
    vm = f"feeder-fleet-20261108t082000z-{slot}"
    cmd = [
        "gcloud", "compute", "instances", "describe", vm,
        f"--zone={ZONE}", f"--project={PROJECT}",
        "--format=value(metadata.items.filter(key:proxy-url).extract(value).flatten())",
    ]
    raw = subprocess.check_output(cmd, env=_gcloud_env(), text=True).strip()
    if not raw:
        raise RuntimeError(f"No proxy-url metadata found on {vm}")
    u = urllib.parse.urlparse(raw)
    out: dict[str, str] = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        out["username"] = urllib.parse.unquote(u.username)
    if u.password:
        out["password"] = urllib.parse.unquote(u.password)
    return out


def get_gmail_account(idx: int) -> tuple[str, str]:
    cmd = [
        "gcloud", "secrets", "versions", "access", "latest",
        "--secret=usersim-fleet-gmail-accounts",
        f"--project={PROJECT}",
    ]
    raw = subprocess.check_output(cmd, env=_gcloud_env(), text=True)
    data = json.loads(raw)
    for acc in data.get("accounts") or []:
        if int(acc.get("slot_idx", 0)) == idx:
            return str(acc["email"]), str(acc["password"])
    raise RuntimeError(f"slot_idx={idx} not found in usersim-fleet-gmail-accounts")


def sync_state_to_vm(slot: int, idx: int, state_path: str) -> None:
    vm = f"feeder-fleet-20261108t082000z-{slot}"
    env = _gcloud_env()
    remote_tmp = f"/tmp/imported_storage_state_{slot}.json"
    print(f"\n[sync] Uploading signed-in cookies to {vm} via IAP...", flush=True)
    subprocess.check_call(
        [
            "gcloud", "compute", "scp", state_path, f"{vm}:{remote_tmp}",
            f"--zone={ZONE}", f"--project={PROJECT}", "--tunnel-through-iap", "--quiet",
        ],
        env=env,
    )
    remote_cmd = (
        f"sudo systemctl stop usersim-poolb.service; "
        f"sudo mkdir -p /var/tmp/usersim_google_sso/gmail_{idx}; "
        f"sudo mv {remote_tmp} /var/tmp/usersim_google_sso/gmail_{idx}/imported_storage_state.json; "
        f"sudo chmod 600 /var/tmp/usersim_google_sso/gmail_{idx}/imported_storage_state.json; "
        f"sudo rm -f /var/tmp/usersim_google_sso/gmail_{idx}/last_auth_result.json; "
        f"sudo systemctl start usersim-poolb.service; "
        f"sleep 2; sudo systemctl is-active usersim-poolb.service"
    )
    subprocess.check_call(
        [
            "gcloud", "compute", "ssh", vm,
            f"--zone={ZONE}", f"--project={PROJECT}", "--tunnel-through-iap", "--quiet",
            f"--command={remote_cmd}",
        ],
        env=env,
    )
    print(f"[sync] Done! {vm} usersim-poolb.service restarted with your signed-in Google session.", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, required=True, choices=sorted(SLOT_TO_IDX.keys()))
    args = ap.parse_args()

    from camoufox.sync_api import Camoufox  # type: ignore[import-untyped]

    idx = SLOT_TO_IDX[args.slot]
    proxy = get_vm_proxy(args.slot)
    email, password = get_gmail_account(idx)

    # Copy password to macOS clipboard via pbcopy so user can Cmd+V without printing it!
    try:
        subprocess.run(["pbcopy"], input=password.encode("utf-8"), check=False)
        pw_note = "(Password copied to your Mac clipboard — just press Cmd+V!)"
    except Exception:
        pw_note = ""

    print(f"=== SLOT {args.slot} (Account #{idx}: {email}) ===", flush=True)
    print(f"Sticky Proxy: {proxy['server']}", flush=True)
    print(pw_note, flush=True)
    print("Opening native Camoufox window on your Mac...", flush=True)
    print("1. Complete Google sign-in until you see myaccount.google.com.", flush=True)
    print("2. Close the Camoufox window (or press Enter here) to auto-sync to the fleet VM.", flush=True)

    local_prof = os.path.expanduser(f"~/.cache/usersim_local_sso/gmail_{idx}")
    os.makedirs(local_prof, exist_ok=True)
    state_file = tempfile.NamedTemporaryFile(prefix=f"slot_{args.slot}_state_", suffix=".json", delete=False).name

    with Camoufox(
        headless=False,
        canvas_noise=False,
        persistent_context=True,
        user_data_dir=local_prof,
        proxy=proxy,
        geoip=True,
        i_know_what_im_doing=True,
    ) as browser:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto("https://accounts.google.com/signin/v2/identifier?hl=en", wait_until="domcontentloaded", timeout=45000)
        try:
            inp = page.locator('input[name="identifier"], input#identifierId, input[type="email"]').first
            inp.wait_for(state="visible", timeout=10000)
            inp.fill(email)
        except Exception:
            pass

        input("\n>>> Press ENTER in this terminal once you are signed in (before closing the browser) to save & upload cookies: ")
        state: dict[str, Any] = browser.storage_state()
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
        google_cookies = [c for c in (state.get("cookies") or []) if "google.com" in (c.get("domain") or "")]
        has_sid = any(c.get("name") in ("SID", "SSID", "HSID", "SAPISID", "__Secure-1PSID") for c in google_cookies)
        print(f"[saved] {len(google_cookies)} Google cookies captured (SID present: {has_sid})", flush=True)

    try:
        sync_state_to_vm(args.slot, idx, state_file)
    finally:
        if os.path.exists(state_file):
            os.remove(state_file)


if __name__ == "__main__":
    main()
