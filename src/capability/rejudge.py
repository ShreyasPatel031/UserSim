"""Re-score saved trajectories without touching a browser.

Every run already persists what the judge needs: the action trace in run.json
and the final screenshot in final.png. So when the judge breaks (expired token)
or changes (new prompt, new model), we can recover verdicts for cents instead of
re-running the agent for dollars.

Usage:
    # recover only the runs that could not be scored
    PYTHONPATH=src python -m capability.rejudge \
        --manifest results/capability/full10_mistral_mistral-small-2603_m33.json

    # re-score everything (e.g. after editing the judge prompt)
    PYTHONPATH=src python -m capability.rejudge --manifest <path> --all

Writes the manifest back in place unless --out is given, and refreshes each
trace's run.json so the per-run artifacts stay consistent with the manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability.judge import JUDGE_ERROR, judge_task
from capability.metrics import sort_runs, summarize

# Statuses worth revisiting by default: the judge never rendered a real verdict.
UNRESOLVED = frozenset({JUDGE_ERROR, "AMBIGUOUS"})


def _action_summary(run: dict) -> str:
    lines = [
        f"{a.get('i')}. {a.get('action')} -> {a.get('result')} @ {a.get('url')}"
        for a in run.get("actions") or []
    ]
    if run.get("stop_reason") == "agent_done":
        lines.append("(agent signaled done)")
    return "\n".join(lines)


def _screenshot(run: dict) -> bytes | None:
    trace_dir = run.get("trace_dir")
    if not trace_dir:
        return None
    for name in ("final.png", "preflight.png"):
        path = Path(trace_dir) / name
        if path.is_file():
            return path.read_bytes()
    return None


def rejudge_run(run: dict) -> tuple[dict, bool]:
    """Re-score one run. Returns (updated run, whether the verdict changed)."""
    judgment = judge_task(
        run.get("task", ""),
        run.get("final_url") or run.get("start_url") or "",
        _action_summary(run),
        _screenshot(run),
        run.get("final_title") or "",
    )
    before = run.get("status")
    status = judgment["status"]
    if status == JUDGE_ERROR:
        # Leave the previous verdict alone rather than overwriting it with a
        # second failure to score.
        run["rejudge_error"] = judgment.get("reason")
        return run, False

    run["status"] = status
    run["success"] = status == "SUCCESS"
    run["judge_reason"] = judgment.get("reason")
    run["judge_evidence"] = judgment.get("evidence")
    run.pop("rejudge_error", None)

    if run["success"]:
        run["failure_category"] = None
    elif status in {"BLOCKED", "SITE_CHANGED"}:
        run["failure_category"] = status
    elif run.get("num_actions", 0) >= (run.get("max_actions_budget") or 0):
        run["failure_category"] = "PLANNING"
    elif run.get("stop_reason") == "agent_done":
        run["failure_category"] = "PREMATURE_STOP"
    else:
        run["failure_category"] = "MODEL_REASONING"

    return run, status != before


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-score saved trajectories offline")
    ap.add_argument("--manifest", required=True, help="bakeoff manifest JSON to re-score")
    ap.add_argument("--out", default=None, help="write here instead of in place")
    ap.add_argument(
        "--all",
        action="store_true",
        help="re-score every run, not just unresolved ones",
    )
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    payload = json.loads(manifest_path.read_text())
    runs = list(payload.get("runs") or [])

    targets = [
        r for r in runs if args.all or r.get("status") in UNRESOLVED
    ]
    print(f"{manifest_path.name}: {len(targets)}/{len(runs)} runs to re-score", flush=True)
    if not targets:
        print("Nothing to do.", flush=True)
        return 0

    changed = 0
    for run in targets:
        before = run.get("status")
        _, flipped = rejudge_run(run)
        changed += bool(flipped)
        marker = "->" if flipped else "=="
        note = run.get("rejudge_error")
        print(
            f"  idx={str(run.get('eval_index')):8} {str(run.get('website')):16} "
            f"{before:12} {marker} {run.get('status')}"
            + (f"  [{note[:60]}]" if note else ""),
            flush=True,
        )

    summary = summarize(runs)
    print(
        f"\nchanged={changed}  scored={summary['n_scored']}/{summary['n']}  "
        f"success_rate_scored={summary['success_rate_scored']}  "
        f"success_rate_eligible={summary['success_rate_eligible']}  "
        f"judge_error_rate={summary['judge_error_rate']}",
        flush=True,
    )
    print(f"by_status={summary['by_status']}", flush=True)
    print(f"by_failure_category={summary['by_failure_category']}", flush=True)

    if args.dry_run:
        print("\n--dry-run: nothing written", flush=True)
        return 0

    payload.update(summary)
    payload["runs"] = sort_runs(runs)
    out_path = Path(args.out) if args.out else manifest_path
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nWrote {out_path}", flush=True)

    # Keep per-run artifacts consistent with the manifest we just rewrote.
    for run in targets:
        trace_dir = run.get("trace_dir")
        if not trace_dir:
            continue
        run_json = Path(trace_dir) / "run.json"
        if run_json.is_file():
            run_json.write_text(json.dumps(run, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
