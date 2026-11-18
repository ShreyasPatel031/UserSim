"""Camoufox Playwright server for the MCP engine on a signup seed (browser_engine = "camoufox").

Run by usersim-seed-camoufox.service (scripts/vm/install_seed_cdp.sh). Listens on the seed's loopback only
(ws://127.0.0.1:9333/usersim); the MCP server reaches it through the IAP tunnel (local port 19320+N) and connects with
playwright.firefox.connect. Each simulated user is one browser context, exactly as with Chromium.

One identity per seed: the fingerprint preset is chosen once, saved on the identity disk
(/var/lib/usersim-seed/<seed-id>/camoufox_preset.json) and reused on every restart. Nothing is randomized per run or
per session; the seed keeps its own static egress IP (no proxy).

    python scripts/vm/seed_camoufox_server.py [--port 9333] [--ws-path usersim] [--headless]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path


def seed_id() -> str:
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/attributes/seed-id",
            headers={"Metadata-Flavor": "Google"})
        return urllib.request.urlopen(req, timeout=3).read().decode().strip()  # noqa: S310
    except Exception:  # noqa: BLE001
        return subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip() or "local"


def identity_dir() -> Path:
    d = Path(os.environ.get("USERSIM_SEED_IDENTITY") or f"/var/lib/usersim-seed/{seed_id()}")
    if not d.is_dir():
        d = Path.home() / "usersim" / "camoufox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fixed_preset(path: Path, os_name: str) -> dict:
    """The seed's one fingerprint preset: loaded if saved, else picked once and saved."""
    if path.is_file():
        return json.loads(path.read_text())
    from camoufox.fingerprints import get_random_preset

    preset = get_random_preset(os=os_name)
    if not preset:
        raise SystemExit(f"camoufox has no fingerprint preset for os={os_name!r}")
    path.write_text(json.dumps(preset))
    os.chmod(path, 0o600)
    return preset


def server_kwargs(a: argparse.Namespace) -> dict:
    preset = fixed_preset(identity_dir() / "camoufox_preset.json", a.os)
    kw = dict(
        host="127.0.0.1",  # loopback only: the IAP tunnel is the way in
        port=a.port,
        ws_path=a.ws_path,
        fingerprint_preset=preset,
        locale="en-US",
        geoip=False,  # no IP lookups; the seed's IP is what it is
        headless=a.headless,
        enable_cache=True,
    )
    if a.executable_path:
        kw["executable_path"] = a.executable_path
    return kw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("USERSIM_CAMOUFOX_PORT", "9333")))
    ap.add_argument("--ws-path", default=os.environ.get("USERSIM_CAMOUFOX_WS_PATH", "usersim"))
    ap.add_argument("--os", default="linux", help="fingerprint OS family (the seeds run Linux)")
    ap.add_argument("--headless", action="store_true", help="default: headed on the seed's Xvfb display (virtual)")
    ap.add_argument("--executable-path", default=os.environ.get("USERSIM_CAMOUFOX_BIN", ""))
    a = ap.parse_args()
    if not a.headless:
        a.headless = "virtual" if not os.environ.get("DISPLAY") else False
    from camoufox.server import launch_server

    launch_server(**server_kwargs(a))


if __name__ == "__main__":
    main()
