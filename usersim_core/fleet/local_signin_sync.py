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
import socket
import subprocess
import tempfile
import time
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
        f"if sudo systemctl list-unit-files usersim-poolb.service 2>/dev/null | grep -q usersim-poolb; then sudo systemctl stop usersim-poolb.service || true; fi; "
        f"sudo mkdir -p /var/tmp/usersim_google_sso/gmail_{idx}; "
        f"sudo mv {remote_tmp} /var/tmp/usersim_google_sso/gmail_{idx}/imported_storage_state.json; "
        f"sudo chmod 600 /var/tmp/usersim_google_sso/gmail_{idx}/imported_storage_state.json; "
        f"sudo rm -f /var/tmp/usersim_google_sso/gmail_{idx}/last_auth_result.json; "
        f"if sudo systemctl list-unit-files usersim-poolb.service 2>/dev/null | grep -q usersim-poolb; then sudo systemctl start usersim-poolb.service; sleep 2; sudo systemctl is-active usersim-poolb.service; else echo 'cookies synced (no systemd service)'; fi"
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


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_vm_proxy_tunnel(slot: int, proxy: dict[str, str]) -> tuple[subprocess.Popen[Any], dict[str, str]]:
    """Forward a local port through the fleet VM so IPRoyal sees the VM's GCE IP (prevents 403 Forbidden)."""
    vm = f"feeder-fleet-20261108t082000z-{slot}"
    u = urllib.parse.urlparse(proxy["server"])
    local_port = _pick_free_port()
    cmd = [
        "gcloud", "compute", "ssh", vm,
        f"--zone={ZONE}", f"--project={PROJECT}",
        "--tunnel-through-iap", "--quiet",
        "--", "-N", "-L", f"127.0.0.1:{local_port}:{u.hostname}:{u.port}",
    ]
    proc = subprocess.Popen(cmd, env=_gcloud_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait up to 15s for the local tunnel port to start listening
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"SSH tunnel to {vm} exited early (code {proc.returncode})")
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.3)
    tunneled = dict(proxy)
    tunneled["server"] = f"{u.scheme}://127.0.0.1:{local_port}"
    return proc, tunneled


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
    print(f"Sticky Proxy (via VM {args.slot} tunnel): {proxy['server']}", flush=True)
    print(pw_note, flush=True)
    print("Opening SSH tunnel through VM and launching native Camoufox on your Mac...", flush=True)
    print("1. Complete Google sign-in until you see myaccount.google.com.", flush=True)
    print("2. Press Enter in this terminal (before closing Camoufox) to auto-sync to the fleet VM.", flush=True)

    local_prof = os.path.expanduser(f"~/.cache/usersim_local_sso/gmail_{idx}")
    os.makedirs(local_prof, exist_ok=True)
    state_file = tempfile.NamedTemporaryFile(prefix=f"slot_{args.slot}_state_", suffix=".json", delete=False).name

    tunnel_proc, tunneled_proxy = start_vm_proxy_tunnel(args.slot, proxy)
    try:
        with Camoufox(
            headless=False,
            canvas_noise=False,
            persistent_context=True,
            user_data_dir=local_prof,
            proxy=tunneled_proxy,
            geoip=False,
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

            input("\n>>> Sign into Google (and optionally LinkedIn / X / GitHub in extra tabs), then press ENTER here (before closing Camoufox) to save & upload ALL cookies: ")
            state: dict[str, Any] = browser.storage_state()
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
            all_c = state.get("cookies") or []
            google_cookies = [c for c in all_c if "google.com" in (c.get("domain") or "")]
            has_sid = any(c.get("name") in ("SID", "SSID", "HSID", "SAPISID", "__Secure-1PSID") for c in google_cookies)
            has_li = any("linkedin.com" in (c.get("domain") or "") and c.get("name") == "li_at" for c in all_c)
            has_x = any(("x.com" in (c.get("domain") or "") or "twitter.com" in (c.get("domain") or "")) and c.get("name") == "auth_token" for c in all_c)
            has_gh = any("github.com" in (c.get("domain") or "") and c.get("name") == "user_session" for c in all_c)
            print(
                f"[saved] total={len(all_c)} cookies | Google(SID)={has_sid} | LinkedIn(li_at)={has_li} | X(auth_token)={has_x} | GitHub={has_gh}",
                flush=True,
            )
    finally:
        tunnel_proc.terminate()
        try:
            tunnel_proc.wait(timeout=3)
        except Exception:
            tunnel_proc.kill()

    try:
        sync_state_to_vm(args.slot, idx, state_file)
    finally:
        if os.path.exists(state_file):
            os.remove(state_file)


if __name__ == "__main__":
    main()
