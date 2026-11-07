#!/usr/bin/env python3
"""Emit setup timing markers as JSON (setup_timing.jsonl + log fallbacks)."""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def parse_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def line_utc(line: str, day: str | None, fallback_mtime: float) -> str | None:
    tm = re.match(r"^(\d{2}):(\d{2}):(\d{2})\b", line)
    if not tm:
        return None
    if day:
        return f"{day[0:4]}-{day[4:6]}-{day[6:8]}T{tm.group(1)}:{tm.group(2)}:{tm.group(3)}Z"
    dt = datetime.fromtimestamp(fallback_mtime, tz=timezone.utc)
    return dt.strftime(f"%Y-%m-%dT{tm.group(1)}:{tm.group(2)}:{tm.group(3)}Z")


def first_match_after(patterns: list[str], after: datetime | None) -> str | None:
    """Scan run/session logs newest-first; return first matching event at/after `after`."""
    files = sorted(
        glob.glob("/opt/ph/reuse/run_*.log") + glob.glob("/opt/ph/reuse/out/_session_*.log"),
        key=os.path.getmtime,
        reverse=True,
    )
    candidates: list[tuple[datetime, str]] = []
    for fp in files:
        try:
            st = os.stat(fp)
            if st.st_size == 0:
                continue
            text = open(fp, errors="replace").read().splitlines()
        except OSError:
            continue
        day = None
        bm = re.search(r"run_(\d{8})T", fp)
        if bm:
            day = bm.group(1)
        for line in text:
            if not any(re.search(pat, line) for pat in patterns):
                continue
            utc = line_utc(line, day, st.st_mtime)
            dt = parse_utc(utc)
            if not utc or not dt:
                continue
            if after and dt < after:
                continue
            candidates.append((dt, utc))
            break  # first match in this file chronologically
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def main() -> None:
    marks: dict[str, str] = {}
    p = Path("/opt/ph/reuse/setup_timing.jsonl")
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev, utc = o.get("event"), o.get("utc")
            if ev and utc:
                # Keep earliest for boot phases; latest for pull phases filled below.
                marks.setdefault(ev, utc)

    sup = Path("/opt/ph/reuse/supervisor.log")
    if "supervisor_ready" not in marks and sup.exists():
        for line in sup.read_text().splitlines():
            m = re.search(r"supervisor_strat start (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", line)
            if m:
                marks["supervisor_ready"] = m.group(1)
                break
    if "batch_launch" not in marks and sup.exists():
        for line in reversed(sup.read_text().splitlines()):
            m = re.search(r"^launch .* (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$", line)
            if m:
                marks["batch_launch"] = m.group(1)
                break

    after = parse_utc(marks.get("batch_launch"))
    # Prefer structured marks only if they are after launch; else fall back to logs.
    for key, patterns in (
        ("identity_ready", [r"FINGERPRINT_(NEW|REUSED)"]),
        ("first_pull", [r" paged ", r" paged_v2 "]),
    ):
        existing = parse_utc(marks.get(key))
        if existing and after and existing >= after:
            continue
        v = first_match_after(patterns, after)
        if v:
            marks[key] = v
        elif key in marks and after and existing and existing < after:
            del marks[key]

    for fp in sorted(glob.glob("/opt/ph/reuse/out/*.json"), key=os.path.getmtime):
        base = os.path.basename(fp)
        if base.startswith("_") or base == "hb.json":
            continue
        jdt = datetime.fromtimestamp(os.path.getmtime(fp), tz=timezone.utc)
        if after and jdt < after:
            continue
        marks["first_json"] = jdt.strftime("%Y-%m-%dT%H:%M:%SZ")
        break

    print(json.dumps(marks, sort_keys=True))


if __name__ == "__main__":
    main()
