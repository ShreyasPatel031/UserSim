#!/usr/bin/env python3
"""Replay recorded browser-use actions to generate per-step bbox screenshots (no LLM)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability.trace_screenshots import replay_trace_screenshots
from capability.voice_ai_dashboards import dashboard_for_url, load_storage_state


async def replay_one(run_path: Path, force: bool) -> tuple[bool, str]:
    run = json.loads(run_path.read_text())
    trace_dir = run_path.parent
    shots = trace_dir / "screenshots"
    if shots.is_dir() and any(shots.glob("bbox_*.png")) and not force:
        return True, "skip"
    start_url = run.get("start_url") or ""
    dash = dashboard_for_url(start_url)
    storage_state = load_storage_state(dash.key) if dash else None
    try:
        n = await replay_trace_screenshots(
            trace_dir,
            storage_state=storage_state,
            start_url=start_url,
        )
        return n > 0, f"{n} steps"
    except Exception as exc:  # noqa: BLE001
        (trace_dir / "screenshot_error.txt").write_text(str(exc)[:500])
        return False, str(exc)[:200]


async def main_async(manifest: Path | None, limit: int, force: bool) -> int:
    paths: list[Path] = []
    if manifest:
        data = json.loads(manifest.read_text())
        for r in data.get("runs") or []:
            td = r.get("trace_dir")
            if td:
                paths.append(Path(td) / "run.json")
    else:
        traces = ROOT / "results" / "capability" / "traces"
        paths = sorted(traces.glob("bu_*/run.json"))

    ok = fail = skip = 0
    todo = paths[:limit] if limit else paths
    for rp in todo:
        if not rp.is_file():
            continue
        success, msg = await replay_one(rp, force)
        if msg == "skip":
            skip += 1
            print(f"SKIP {rp.parent.name}")
        elif success:
            ok += 1
            print(f"OK   {rp.parent.name} ({msg})")
        else:
            fail += 1
            print(f"FAIL {rp.parent.name}: {msg}")
    print(f"done: ok={ok} skip={skip} fail={fail}")
    return 0 if fail == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, help="Manifest JSON with trace_dir entries")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true", help="Overwrite existing bbox screenshots")
    args = p.parse_args()
    return asyncio.run(main_async(args.manifest, args.limit, args.force))


if __name__ == "__main__":
    raise SystemExit(main())
