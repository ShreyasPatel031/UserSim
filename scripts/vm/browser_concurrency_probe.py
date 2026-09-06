#!/usr/bin/env python3
"""Probe how many concurrent local Chromium sessions survive browser-use CDP load.

Matches bakeoff threading: ThreadPoolExecutor, each thread runs asyncio.run()
with BrowserSession + vision screenshots (ScreenshotWatchdog path).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

DEFAULT_URL = "https://example.com"
SCREENSHOT_ROUNDS = 8


async def _worker_async(worker_id: int, url: str, rounds: int) -> dict:
    profile = BrowserProfile(headless=True, disable_security=True)
    session = BrowserSession(browser_profile=profile)
    errors: list[str] = []
    timeouts = 0
    screenshots_ok = 0
    t0 = time.monotonic()
    try:
        await session.start()
        await session.navigate_to(url)
        await asyncio.sleep(1.0)
        for _ in range(rounds):
            try:
                await session.get_browser_state_summary(include_screenshot=True)
                screenshots_ok += 1
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                errors.append(msg[:240])
                if "timeout" in msg.lower() or "timed out" in msg.lower():
                    timeouts += 1
            await asyncio.sleep(0.4)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"fatal: {exc}"[:240])
    finally:
        try:
            await session.stop()
        except Exception:
            pass
    elapsed = time.monotonic() - t0
    return {
        "worker_id": worker_id,
        "elapsed_s": round(elapsed, 2),
        "screenshots_ok": screenshots_ok,
        "errors": len(errors),
        "timeouts": timeouts,
        "ok": len(errors) == 0 and screenshots_ok == rounds,
        "sample_error": errors[0] if errors else None,
    }


def _worker(worker_id: int, url: str, rounds: int) -> dict:
    return asyncio.run(_worker_async(worker_id, url, rounds))


def run_probe(workers: int, url: str, rounds: int) -> dict:
    t0 = time.monotonic()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_worker, i, url, rounds) for i in range(workers)]
        for fut in as_completed(futs):
            results.append(fut.result())
    elapsed = time.monotonic() - t0
    ok = sum(1 for r in results if r["ok"])
    return {
        "workers": workers,
        "url": url,
        "screenshot_rounds": rounds,
        "wall_elapsed_s": round(elapsed, 2),
        "workers_ok": ok,
        "workers_failed": workers - ok,
        "total_timeouts": sum(r["timeouts"] for r in results),
        "total_screenshots_ok": sum(r["screenshots_ok"] for r in results),
        "passed": ok == workers,
        "results": sorted(results, key=lambda r: r["worker_id"]),
    }


def _host_info() -> dict:
    try:
        import os

        cpu = os.cpu_count()
    except Exception:
        cpu = None
    mem_gb = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:
        pass
    return {
        "platform": platform.platform(),
        "cpu_count": cpu,
        "mem_total_gb": mem_gb,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="browser-use local Chromium concurrency probe")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--sweep", action="store_true", help="Test workers 1..max until failure")
    ap.add_argument("--max", type=int, default=8)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--rounds", type=int, default=SCREENSHOT_ROUNDS)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    report: dict = {"host": _host_info(), "probes": []}
    if args.sweep:
        for w in range(1, args.max + 1):
            r = run_probe(w, args.url, args.rounds)
            report["probes"].append(r)
            print(json.dumps(r, indent=2), flush=True)
            if not r["passed"]:
                print(f"SWEEP_STOP: unstable at workers={w}", flush=True)
                break
    else:
        r = run_probe(args.workers, args.url, args.rounds)
        report["probes"].append(r)
        print(json.dumps(r, indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))
        print(f"Wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
