"""Export a seed's signed-in accounts to the bucket the MCP engine reads (mvp/sim_mcp/site_states.py).

Run ON a seed, as the user that owns ~/usersim (it needs the venv's Playwright):
    ~/usersim/.venv/bin/python ~/usersim/scripts/vm/export_seed_states.py            # dry run: list what it found
    ~/usersim/.venv/bin/python ~/usersim/scripts/vm/export_seed_states.py --upload   # write missing domains
    ... --upload --force                                                            # also overwrite existing ones

Sources on the identity disk /var/lib/usersim-seed/<seed-id>/:
  site_states/<host>.json   Playwright storage_state per host (app.asana.com.json, asana.com.json, ...)
  profiles/<host>/          Chrome user-data dirs; exported with a headless persistent context when the domain has no
                            site_states file (profiles/_mcp_engine, the engine's own Chromium profile, is skipped)
Hosts are merged per registrable domain (app.asana.com + asana.com -> asana.com). Domains without a live cookie for
the site are skipped. producthunt.com is never exported. Uploads use `gcloud storage` with the VM's service account.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DEFAULT_PREFIX = "gs://usersim-bakeoff-347838016394/seed_states"
NEVER = {"producthunt.com"}


def registrable_domain(host: str) -> str:
    try:
        from mvp.sim_mcp.sessions import registrable_domain as rd

        return rd(host)
    except Exception:  # noqa: BLE001 (minimal checkout)
        parts = host.lower().removeprefix("www.").split(".")
        return ".".join(parts[-2:])


def live_cookies(state: dict, domain: str) -> list[dict]:
    now = time.time()
    out = []
    for c in state.get("cookies") or []:
        cdom = str(c.get("domain") or "").lstrip(".").lower()
        exp = c.get("expires")
        if (cdom == domain or cdom.endswith("." + domain)) and not (isinstance(exp, (int, float)) and 0 < exp < now):
            out.append(c)
    return out


def seed_id() -> str:
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/attributes/seed-id",
            headers={"Metadata-Flavor": "Google"})
        return urllib.request.urlopen(req, timeout=3).read().decode().strip()  # noqa: S310
    except Exception:  # noqa: BLE001
        return subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()


def merge(into: dict, state: dict) -> None:
    seen = {(c.get("name"), c.get("domain"), c.get("path")) for c in into["cookies"]}
    for c in state.get("cookies") or []:
        key = (c.get("name"), c.get("domain"), c.get("path"))
        if key not in seen:
            into["cookies"].append(c)
            seen.add(key)
    origins = {o.get("origin") for o in into["origins"]}
    for o in state.get("origins") or []:
        if o.get("origin") not in origins:
            into["origins"].append(o)
            origins.add(o.get("origin"))


def export_profile(profile: Path) -> dict | None:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(profile), headless=True,
                                                       args=["--disable-extensions"])
            state = ctx.storage_state()
            ctx.close()
            return state
    except Exception as exc:  # noqa: BLE001 (profile locked or from another Chrome version)
        print(f"  ! profile {profile.name}: {exc!r}"[:200])
        return None


def gcs_ls(prefix: str) -> set[str]:
    out = subprocess.run(["gcloud", "storage", "ls", prefix + "/"], capture_output=True, text=True)
    return {Path(line.strip()).stem for line in out.stdout.splitlines() if line.strip().endswith(".json")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite domains already in the bucket")
    ap.add_argument("--no-profiles", action="store_true")
    a = ap.parse_args()
    sid = seed_id()
    root = Path(a.root or f"/var/lib/usersim-seed/{sid}")
    states: dict[str, dict] = {}
    sources: dict[str, list[str]] = {}
    for f in sorted((root / "site_states").glob("*.json")):
        try:
            st = json.loads(f.read_text())
        except ValueError:
            continue
        st = st.get("storage_state", st) if isinstance(st, dict) else {}
        dom = registrable_domain(f.stem)
        states.setdefault(dom, {"cookies": [], "origins": []})
        merge(states[dom], st)
        sources.setdefault(dom, []).append(f"site_states/{f.name}")
    if not a.no_profiles:
        for prof in sorted(p for p in (root / "profiles").glob("*") if p.is_dir() and not p.name.startswith("_")):
            dom = registrable_domain(prof.name)
            if dom in states and live_cookies(states[dom], dom):
                continue
            st = export_profile(prof)
            if st:
                states.setdefault(dom, {"cookies": [], "origins": []})
                merge(states[dom], st)
                sources.setdefault(dom, []).append(f"profiles/{prof.name}")
    existing = gcs_ls(a.prefix) if a.upload else set()
    print(f"seed {sid}: {len(states)} domains from {root}")
    for dom in sorted(states):
        live = live_cookies(states[dom], dom)
        if dom in NEVER or not live:
            print(f"  skip   {dom:28} live cookies {len(live)}{' (never exported)' if dom in NEVER else ''}")
            continue
        action = "found"
        if a.upload:
            if dom in existing and not a.force:
                action = "exists"
            else:
                entry = {"domain": dom, "storage_state": states[dom], "seed": sid, "saved_at": time.time(),
                         "study_id": "", "address": "", "source": "seed_disk:" + ",".join(sources[dom])}
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
                    json.dump(entry, tmp)
                ok = subprocess.run(["gcloud", "storage", "cp", tmp.name, f"{a.prefix}/{dom}.json"],
                                    capture_output=True, text=True).returncode == 0
                Path(tmp.name).unlink(missing_ok=True)
                action = "upload" if ok else "FAILED"
        print(f"  {action:6} {dom:28} live cookies {len(live):3}  from {', '.join(sources[dom])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
