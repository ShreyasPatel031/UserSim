#!/usr/bin/env python3
"""Build committed voice-bakeoff page payload from voice-public-d28b7070.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results" / "capability" / "voice-public-d28b7070.json"
OUT_RAW = ROOT / "mvp" / "experiment_results" / "voice-public-d28b7070_result.json"
OUT_SYNTH = ROOT / "mvp" / "experiment_results" / "voice-public-d28b7070_result.synthesized.json"
PUBLIC_TRACES = ROOT / "public" / "bakeoff-traces"


def link_traces(runs: list[dict]) -> None:
    PUBLIC_TRACES.mkdir(parents=True, exist_ok=True)
    for r in runs:
        td = r.get("trace_dir") or ""
        if not td:
            continue
        src = Path(td)
        if not src.is_dir():
            continue
        dest = PUBLIC_TRACES / src.name
        if dest.exists():
            continue
        try:
            dest.symlink_to(src.resolve())
        except OSError:
            pass


def main() -> int:
    if not SOURCE.is_file():
        print(f"Missing source: {SOURCE}", file=sys.stderr)
        return 1
    raw = json.loads(SOURCE.read_text())
    link_traces(raw.get("runs") or [])

    from mvp.transform_bakeoff_results import transform_proven_harness_results
    from mvp.synthesize_voice_public_insights import attach_public_insights

    page = transform_proven_harness_results(raw)
    page["id"] = "voice-public-d28b7070"
    page = attach_public_insights(page, raw.get("runs") or [])

    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT_RAW.write_text(json.dumps(raw, indent=2, default=str))
    OUT_SYNTH.write_text(json.dumps(page, indent=2, default=str))
    print(f"Wrote {OUT_SYNTH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
