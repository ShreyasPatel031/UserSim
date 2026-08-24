#!/usr/bin/env python3
"""Run a UserSim study from the terminal: feed a URL + customer segment, watch
activity and screenshots land as the testing agents browse the live site.

    .venv/bin/python mvp/cli.py --url https://example.com --segment "..."
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def _open_image(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fmt_time(iso: str) -> str:
    return iso.split("T", 1)[-1][:8] if "T" in iso else iso


async def _watch(study, *, run_dir: Path, open_screenshots: bool, poll_s: float) -> None:
    seen_log = 0
    seen_shots: set[str] = set()
    while True:
        await asyncio.sleep(poll_s)
        log = study.activity_log
        for entry in log[seen_log:]:
            print(f"[{_fmt_time(entry['at'])}] {entry['message']}")
        seen_log = len(log)

        for sess in study.live_sessions.values():
            for step in sess.get("trace") or []:
                shot = step.get("screenshot_url")
                if not shot or shot in seen_shots:
                    continue
                seen_shots.add(shot)
                filename = shot.rsplit("/", 1)[-1]
                local_path = run_dir / sess["agent_id"] / "screenshots" / filename
                if local_path.is_file():
                    print(f"  screenshot: {local_path}")
                    if open_screenshots:
                        _open_image(local_path)

        if study.status in {"complete", "error"}:
            return


def _print_summary(study) -> None:
    if study.status == "error":
        print(f"\nFAILED: {study.error}")
        return
    summary = study.summary or {}
    print("\n=== Executive summary ===")
    print(summary.get("headline", ""))
    print("\nTop friction:")
    for item in summary.get("top_friction") or []:
        print(f"  - {item}")
    print("\nTop strengths:")
    for item in summary.get("top_strengths") or []:
        print(f"  - {item}")
    print(f"\nSegment fit: {summary.get('segment_fit_score')}/10 — {summary.get('segment_fit_rationale', '')}")
    print("\nRecommendations:")
    for rec in summary.get("recommendations") or []:
        print(f"  [{rec.get('priority')}] {rec.get('action')} — {rec.get('rationale')}")


async def _run(args: argparse.Namespace) -> None:
    from mvp.paths import MVP_RUNS_DIR
    from mvp.study import STUDIES, create_study, run_study

    study = create_study(args.url, args.segment)
    run_dir = MVP_RUNS_DIR / study.id
    print(f"Study {study.id}\n  url: {study.url}\n  segment: {study.segment}\n")

    task = asyncio.create_task(run_study(study.id))
    await _watch(study, run_dir=run_dir, open_screenshots=not args.no_open, poll_s=args.poll)
    await task
    _print_summary(STUDIES[study.id])
    print(f"\nFull trace: {run_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Public URL to test (no login required)")
    ap.add_argument("--segment", required=True, help="Customer segment description")
    ap.add_argument("--agents", type=int, default=4, help="Number of persona/task agents to run (default: 4)")
    ap.add_argument("--max-steps", type=int, default=12, help="Max browser-use steps per agent (default: 12)")
    ap.add_argument("--browser-concurrency", type=int, default=3, help="Concurrent local Chromium sessions (default: 3)")
    ap.add_argument("--show-browser", action="store_true", help="Show the Chromium windows instead of headless")
    ap.add_argument("--no-open", action="store_true", help="Don't auto-open each screenshot as it lands")
    ap.add_argument("--poll", type=float, default=1.5, help="Seconds between progress polls (default: 1.5)")
    args = ap.parse_args()

    os.environ["MVP_AGENT_COUNT"] = str(args.agents)
    os.environ["MVP_MAX_BROWSER_STEPS"] = str(args.max_steps)
    os.environ["MVP_BROWSER_CONCURRENCY"] = str(args.browser_concurrency)
    os.environ["MVP_BROWSER_HEADLESS"] = "false" if args.show_browser else "true"

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
