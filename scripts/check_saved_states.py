"""Which saved signed-in states (gs://.../seed_states/<domain>.json) still sign in?

For each domain: load its storage_state into a fresh browser context, open the in-app URL the state implies
(site_states.app_url_for: app.<domain> or a workspace subdomain), wait for redirects, and call it
  LIVE        a signed-in app page: not a login/signup URL, no password box, AND an account / avatar / workspace
              control or a log-out item in the DOM
  UNSURE      not a login page, but no signed-in sign either (a marketing or landing page): not counted as live
  DEAD        sent to a login / signup page
  NO_APP_URL  the state never touched an in-app host (only the marketing site)
  ERROR       the page did not load
Run it ON a seed so the check uses the seed's egress IP (some sites drop sessions seen from a new IP):
    ~/usersim/.venv/bin/python ~/usersim/scripts/check_saved_states.py [--only asana.com,clickup.com] [--mark-dead]
--cdp http://127.0.0.1:9222 uses the seed's running engine Chromium instead of launching one.
--mark-dead flags DEAD states in the bucket (the engine then stops loading them until a cell saves a fresh one).
Never opens producthunt.com.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from mvp.sim_mcp import site_states as SS  # noqa: E402

NEVER = {"producthunt.com"}
FLAGS = ["--disable-extensions", "--disable-component-extensions-with-background-pages"]


def _gcloud(*args: str) -> str:
    return subprocess.run(["gcloud", "storage", *args], capture_output=True, text=True, check=True).stdout


def list_domains(prefix: str) -> list[str]:
    try:
        from mvp.gcs_store import gcs_list_prefix

        uris = gcs_list_prefix(prefix + "/")
    except Exception:  # noqa: BLE001 (no google-cloud-storage on this host)
        uris = _gcloud("ls", prefix + "/").split()
    return sorted(Path(u).stem for u in uris if u.endswith(".json"))


def read_entry(prefix: str, domain: str) -> dict | None:
    try:
        from mvp.gcs_store import gcs_download_json

        return gcs_download_json(f"{prefix}/{domain}.json")
    except Exception:  # noqa: BLE001
        try:
            return json.loads(_gcloud("cat", f"{prefix}/{domain}.json"))
        except Exception:  # noqa: BLE001
            return None


def mark_dead(prefix: str, domain: str, reason: str) -> None:
    """Flag the bucket entry dead (GCS client, or gcloud on a seed without it)."""
    entry = read_entry(prefix, domain)
    if not isinstance(entry, dict) or entry.get("dead"):
        return
    entry.update(dead=True, dead_at=time.time(), dead_reason=reason[:200])
    try:
        from mvp.gcs_store import gcs_upload_json

        gcs_upload_json(f"{prefix}/{domain}.json", entry)
    except Exception:  # noqa: BLE001
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(entry, tmp)
        _gcloud("cp", tmp.name, f"{prefix}/{domain}.json")
        Path(tmp.name).unlink(missing_ok=True)


async def check_one(browser, domain: str, entry: dict) -> dict:
    out = {"domain": domain, "seed": entry.get("seed"), "saved_at": entry.get("saved_at"), "was_dead": bool(entry.get("dead"))}
    state = entry.get("storage_state") or {}
    out["live_cookies"] = len(SS.live_cookies(state, domain))
    url = SS.app_url_for(entry, domain)
    out["app_url"] = url
    if not url:
        out["verdict"] = "NO_APP_URL"
        return out
    ctx = await browser.new_context(storage_state=state, viewport={"width": 1280, "height": 800})
    try:
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:  # noqa: BLE001
            if not (page.url or "").startswith("http"):
                out.update(verdict="ERROR", detail=str(exc).splitlines()[0][:120])
                return out
        await asyncio.sleep(4)  # SPA shells redirect to /login after load
        pw_box = await page.locator("input[type=password]:visible").count() > 0
        try:
            signals = await page.evaluate(SS.SIGNED_IN_JS)
        except Exception:  # noqa: BLE001
            signals = {}
        out["landed"] = (page.url or "")[:160]
        out["title"] = (await page.title())[:60]
        out["signals"] = signals
        if SS.looks_signed_out(page.url, pw_box):
            out["verdict"] = "DEAD"
        else:
            out["verdict"] = "LIVE" if SS.signed_in_signals(signals) else "UNSURE"
        return out
    finally:
        await ctx.close()


async def launch(pw, cdp: str = "", extra_args: list[str] | None = None):
    if cdp:
        return await pw.chromium.connect_over_cdp(cdp)
    return await pw.chromium.launch(headless=True, args=FLAGS + list(extra_args or []))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="")
    ap.add_argument("--only", default="", help="comma-separated domains")
    ap.add_argument("--cdp", default="", help="connect to this CDP endpoint instead of launching Chromium")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--mark-dead", action="store_true")
    ap.add_argument("--json", default="", help="also write the results here")
    a = ap.parse_args()
    prefix = (a.prefix or SS.prefix()).rstrip("/")
    domains = [d.strip() for d in a.only.split(",") if d.strip()] or list_domains(prefix)
    domains = [d for d in domains if d not in NEVER]
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await launch(pw, a.cdp)
        sem = asyncio.Semaphore(max(1, a.parallel))

        async def run(d: str) -> dict:
            async with sem:
                entry = read_entry(prefix, d)
                if not isinstance(entry, dict):
                    return {"domain": d, "verdict": "ERROR", "detail": "unreadable"}
                try:
                    return await check_one(browser, d, entry)
                except Exception as exc:  # noqa: BLE001
                    return {"domain": d, "verdict": "ERROR", "detail": repr(exc)[:120]}

        results = await asyncio.gather(*(run(d) for d in domains))
        if not a.cdp:
            await browser.close()
    for r in results:
        print(f"{r['verdict']:10} {r['domain']:28} {str(r.get('app_url') or ''):42} -> {r.get('landed') or r.get('detail') or ''}")
        if a.mark_dead and r["verdict"] == "DEAD" and not r.get("was_dead"):
            mark_dead(prefix, r["domain"], f"check_saved_states: {r.get('landed', '')}")
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("LIVE", "UNSURE", "DEAD", "NO_APP_URL", "ERROR")}
    print(f"\n{len(results)} domains: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"  ({time.strftime('%Y-%m-%d %H:%M')})")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
