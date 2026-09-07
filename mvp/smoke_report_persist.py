#!/usr/bin/env python3
"""Smoke: confirm a study summary is persisted and readable as a report.

Usage:
  PYTHONPATH=. python mvp/smoke_report_persist.py [--base URL] [--study ID]
  PYTHONPATH=. python mvp/smoke_report_persist.py --run --base https://usersim.vercel.app

Without --run, verifies an existing study (default: known e2e example.com).
With --run, starts a test_mode study, polls to completion, then verifies.
Writes /opt/cursor/artifacts/smoke-report.md and smoke-report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_STUDY = "d7884443-203e-4080-9dda-4347346d86ef"  # langchain.com e2e
ARTIFACT_DIR = Path(os.environ.get("CURSOR_ARTIFACTS_DIR", "/opt/cursor/artifacts"))
DEFAULT_SMOKE_URL = os.environ.get("SMOKE_URL", "https://useagency.dev/")


def _get(url: str, timeout: float = 30) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, payload: dict, timeout: float = 60) -> dict:
    """POST JSON. Prod may return one object or NDJSON progress lines."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            # Prefer a single JSON body so we can poll; some hosts still stream.
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8").strip()
    if not raw:
        raise SystemExit("FAIL empty POST response")
    # Single JSON object
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # NDJSON / SSE-ish: take last parseable object that has an id
    last: dict | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last = obj
            if obj.get("study_id") or (obj.get("id") and obj.get("stream_event") in {None, "progress", "complete"}):
                # Prefer first line that carries study_id for async kickoff
                if obj.get("study_id"):
                    return obj
    if last:
        return last
    raise SystemExit(f"FAIL could not parse POST response: {raw[:400]}")


def _report_markdown(data: dict) -> str:
    summary = data.get("summary") or {}
    lines = [
        f"# Smoke report — {data.get('url') or 'study'}",
        "",
        f"- **Study ID:** `{data.get('id')}`",
        f"- **Status:** `{data.get('status')}`",
        f"- **Live:** https://usersim.vercel.app/live?study={data.get('id')}",
        f"- **Report:** https://usersim.vercel.app/report?study={data.get('id')}",
        "",
        "## Executive summary",
        "",
        summary.get("headline") or "_(no headline)_",
        "",
        f"**Segment fit:** {summary.get('segment_fit_score', '—')}",
        "",
        summary.get("segment_fit_rationale") or "",
        "",
        "### Top friction",
        "",
    ]
    for item in summary.get("top_friction") or []:
        lines.append(f"- {item}")
    lines += ["", "### Top strengths", ""]
    for item in summary.get("top_strengths") or []:
        lines.append(f"- {item}")
    lines += ["", "### Conversion outlook", "", summary.get("conversion_outlook") or "—", "", "### Recommendations", ""]
    for rec in summary.get("recommendations") or []:
        if isinstance(rec, dict):
            lines.append(
                f"- **[{rec.get('priority', 'medium')}]** {rec.get('action', '')} — {rec.get('rationale', '')}"
            )
        else:
            lines.append(f"- {rec}")
    agents = data.get("agent_results") or []
    if agents:
        lines += ["", "## Session recaps", ""]
        for r in agents:
            lines.append(
                f"### {r.get('persona_name', 'User')} — {r.get('task_title', 'Task')}"
            )
            lines.append("")
            lines.append(r.get("product_feedback") or "")
            if r.get("quote"):
                lines.append("")
                lines.append(f"> {r['quote']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def verify_study(base: str, study_id: str) -> dict:
    data = _get(f"{base.rstrip('/')}/api/studies/{study_id}")
    summary = data.get("summary") or {}
    if data.get("status") != "complete":
        raise SystemExit(f"FAIL: status={data.get('status')!r} (want complete)")
    if not summary.get("headline") and not summary.get("recommendations"):
        raise SystemExit("FAIL: summary missing headline/recommendations — not persisted")
    print(f"OK persisted summary for {study_id}")
    print(f"  url={data.get('url')}")
    print(f"  headline={(summary.get('headline') or '')[:140]}")
    print(f"  recommendations={len(summary.get('recommendations') or [])}")
    print(f"  agent_results={len(data.get('agent_results') or [])}")
    return data


def run_new_study(base: str, timeout_s: int) -> str:
    payload = {
        "url": DEFAULT_SMOKE_URL,
        "test_mode": True,
        "skip_competitors": True,
        "segment": "Curious first-time visitor evaluating the product",
        "tasks": ["Explore the homepage and decide if this product is worth trying"],
    }
    print(f"→ POST {base}/api/studies (test_mode url={DEFAULT_SMOKE_URL})")
    started = _post(f"{base.rstrip('/')}/api/studies", payload, timeout=90)
    study_id = started.get("study_id") or started.get("id")
    if not study_id:
        # sync complete response
        if started.get("status") == "complete" and started.get("summary"):
            return started.get("id") or ""
        raise SystemExit(f"FAIL unexpected start response: {json.dumps(started)[:400]}")
    print(f"  study_id={study_id}")
    elapsed = 0
    poll = 5
    while elapsed < timeout_s:
        try:
            data = _get(f"{base.rstrip('/')}/api/studies/{study_id}", timeout=30)
        except urllib.error.HTTPError as exc:
            print(f"  [{elapsed}s] HTTP {exc.code}")
            time.sleep(poll)
            elapsed += poll
            continue
        status = data.get("status")
        phase = data.get("phase")
        print(f"  [{elapsed}s] status={status} phase={phase}")
        if status == "complete":
            return study_id
        if status == "error":
            raise SystemExit(f"FAIL study error: {data.get('error')}")
        time.sleep(poll)
        elapsed += poll
    raise SystemExit(f"FAIL timeout after {timeout_s}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("SMOKE_BASE", "https://usersim.vercel.app"))
    ap.add_argument("--study", default=os.environ.get("SMOKE_STUDY", DEFAULT_STUDY))
    ap.add_argument("--run", action="store_true", help="Start a new test_mode study")
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("SMOKE_TIMEOUT_S", "420")))
    args = ap.parse_args()

    study_id = args.study
    if args.run:
        study_id = run_new_study(args.base, args.timeout)
        if not study_id:
            raise SystemExit("FAIL: no study id from run")

    data = verify_study(args.base, study_id)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / "smoke-report.json"
    md_path = ARTIFACT_DIR / "smoke-report.md"
    json_path.write_text(json.dumps(data, indent=2)[:500_000] + "\n")
    md_path.write_text(_report_markdown(data))
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(f"Report URL: {args.base.rstrip('/')}/report?study={study_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
