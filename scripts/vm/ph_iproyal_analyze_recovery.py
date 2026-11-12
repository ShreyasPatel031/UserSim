#!/usr/bin/env python3
"""From feeder status JSONL: 429/block gaps, recovery times, long-run effective ppm."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


def ts(u: str) -> float | None:
    try:
        return datetime.fromisoformat(u.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def load_rows(path: Path) -> list[dict]:
    rows = []
    for ln in path.read_text().splitlines():
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return rows


def analyze(rows: list[dict], since: float | None = None) -> dict:
    events: list[tuple[float, str, dict]] = []
    for j in rows:
        t = ts(j.get("utc") or "")
        if t is None or (since and t < since):
            continue
        ev = j.get("event") or ""
        if ev == "stopped_on_block" or (
            j.get("rc") == 3 and j.get("handle") and "429" in (j.get("detail") or "")
        ):
            events.append((t, "block", j))
        elif j.get("rc") == 0 and j.get("handle"):
            events.append((t, "complete", j))
        elif ev == "start":
            events.append((t, "start", j))

    # Pair each block with next complete or start (whichever first)
    recoveries: list[float] = []
    block_times: list[float] = []
    i = 0
    while i < len(events):
        t, kind, j = events[i]
        if kind in ("block", "stopped_on_block"):
            block_times.append(t)
            t_end = None
            for k in range(i + 1, len(events)):
                t2, kind2, _ = events[k]
                if kind2 in ("complete", "start"):
                    t_end = t2
                    break
            if t_end is not None:
                recoveries.append(t_end - t)
        i += 1

    t0 = min((e[0] for e in events), default=None)
    t1 = max((e[0] for e in events), default=None)
    completes = sum(1 for _, k, j in events if k == "complete")
    hours = ((t1 - t0) / 3600.0) if t0 and t1 and t1 > t0 else 0.0
    eff_ppm = (completes / hours / 60.0) if hours > 0 else 0.0

    # Idle gaps: >3min without complete between block and next complete
    idle_gaps = [g for g in recoveries if g > 180]

    out = {
        "blocks": len(block_times),
        "completes": completes,
        "hours_span": round(hours, 3),
        "effective_complete_ppm": round(eff_ppm, 3),
        "recovery_sec_median": round(median(recoveries), 1) if recoveries else None,
        "recovery_sec_p90": round(sorted(recoveries)[int(len(recoveries) * 0.9)], 1)
        if len(recoveries) > 1
        else (round(recoveries[0], 1) if recoveries else None),
        "recovery_sec_max": round(max(recoveries), 1) if recoveries else None,
        "idle_gaps_over_3min": len(idle_gaps),
        "n_recovery_samples": len(recoveries),
    }
    return out


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    since_s = sys.argv[2] if len(sys.argv) > 2 else None
    since = ts(since_s + "Z" if since_s and not since_s.endswith("Z") else since_s or "") if since_s else None
    if not path or not path.is_file():
        print(json.dumps({"error": "usage: ph_iproyal_analyze_recovery.py STATUS.jsonl [since_utc]"}))
        sys.exit(1)
    rows = load_rows(path)
    print(json.dumps(analyze(rows, since), indent=2))


if __name__ == "__main__":
    main()
