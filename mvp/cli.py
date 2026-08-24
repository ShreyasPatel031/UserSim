#!/usr/bin/env python3
"""Run a UserSim study from the terminal: feed a URL + customer segment, watch
activity stream live, and open a browser viewer showing the exact same UI as
the web app (personas, live trace, bbox screenshots, QA report).

    .venv/bin/python mvp/cli.py --url https://example.com --segment "..."

If a UserSim server is already running (e.g. `uvicorn mvp.server:app --port
8787`), this talks to it directly — the viewer and the CLI share the same
study. Otherwise it starts one itself, in-process, on --port.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402


def _open_url(url: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 — best-effort only, e.g. no display in a sandbox
        pass


def _fmt_time(iso: str) -> str:
    return iso.split("T", 1)[-1][:8] if "T" in iso else iso


async def _ensure_server(port: int) -> tuple[str, bool]:
    """Return (base_url, started_own_server) for a running UserSim server."""
    base_url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{base_url}/health", timeout=1.5)
            if r.status_code == 200:
                return base_url, False
        except httpx.HTTPError:
            pass

        import uvicorn

        from mvp.server import app as fastapi_app

        config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        for _ in range(50):
            try:
                r = await client.get(f"{base_url}/health", timeout=1.0)
                if r.status_code == 200:
                    return base_url, True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)

    raise RuntimeError(f"Could not start a UserSim server on port {port}")


def _print_summary(data: dict) -> None:
    if data.get("status") == "error":
        print(f"\nFAILED: {data.get('error')}")
        return
    summary = data.get("summary") or {}
    print("\n=== QA report ===")
    print(summary.get("headline", ""))
    print("\nTop issues found:")
    for item in summary.get("top_friction") or []:
        print(f"  - {item}")
    print("\nWhat works well:")
    for item in summary.get("top_strengths") or []:
        print(f"  - {item}")
    print(f"\nPersona fit: {summary.get('segment_fit_score')}/10 — {summary.get('segment_fit_rationale', '')}")
    print("\nRecommendations:")
    for rec in summary.get("recommendations") or []:
        print(f"  [{rec.get('priority')}] {rec.get('action')} — {rec.get('rationale')}")


async def _run(args: argparse.Namespace) -> None:
    # Only takes effect if this process ends up starting its own embedded server —
    # an already-running external server keeps whatever concurrency it was started with.
    os.environ["MVP_BROWSER_CONCURRENCY"] = str(args.browser_concurrency)

    base_url, started_own = await _ensure_server(args.port)
    if not started_own:
        print(f"Reusing UserSim server already running at {base_url}")
        print(f"(--browser-concurrency={args.browser_concurrency} only applies when this CLI starts its own server; ignored here)\n")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/api/studies",
            json={
                "url": args.url,
                "segment": args.segment,
                "agent_count": args.agents,
                "max_steps": args.max_steps,
                "headless": not args.show_browser,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        study_id = payload.get("study_id") or payload.get("id")
        viewer_url = f"{base_url}/?study={study_id}"

        print(f"Study {study_id}\n  url: {args.url}\n  segment: {args.segment}\n  viewer: {viewer_url}\n")
        if not args.no_viewer:
            _open_url(viewer_url)

        seen_log = 0
        data: dict = {}
        while True:
            await asyncio.sleep(args.poll)
            r = await client.get(f"{base_url}/api/studies/{study_id}")
            r.raise_for_status()
            data = r.json()

            log = data.get("activity_log") or []
            for entry in log[seen_log:]:
                print(f"[{_fmt_time(entry['at'])}] {entry['message']}")
            seen_log = len(log)

            if data.get("status") in {"complete", "error"}:
                break

    _print_summary(data)
    print(f"\nViewer: {viewer_url}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Public URL to test (no login required)")
    ap.add_argument("--segment", required=True, help="Customer segment / user profile description")
    ap.add_argument("--agents", type=int, default=4, help="Number of persona/task agents to run (default: 4)")
    ap.add_argument("--max-steps", type=int, default=12, help="Max browser-use steps per agent (default: 12)")
    ap.add_argument("--browser-concurrency", type=int, default=3, help="Concurrent local Chromium sessions (default: 3)")
    ap.add_argument("--show-browser", action="store_true", help="Show the Chromium windows instead of headless")
    ap.add_argument("--port", type=int, default=8787, help="UserSim server port — reused if already running (default: 8787)")
    ap.add_argument("--no-viewer", action="store_true", help="Don't auto-open the viewer URL in a browser")
    ap.add_argument("--poll", type=float, default=1.5, help="Seconds between progress polls (default: 1.5)")
    args = ap.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
