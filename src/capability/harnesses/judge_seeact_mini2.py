"""Judge upstream-SeeAct Mini-2 runs with the same judge used for Browser Use.

SeeAct runs in .venv-seeact and only dumps raw trajectories; scoring happens
here in the main venv so both harnesses are graded identically.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from capability import OUT_DIR, cost_usd  # noqa: E402
from capability.judge import judge_task  # noqa: E402


def _summary_lines(run: dict) -> str:
    lines = [f"{i}. {a}" for i, a in enumerate(run.get("taken_actions") or [], start=1)]
    if run.get("complete_flag"):
        lines.append("(agent issued TERMINATE)")
    if run.get("error"):
        lines.append(f"(harness error: {run['error']})")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Judge SeeAct Mini-2 raw runs")
    ap.add_argument("--raw", default=str(OUT_DIR / "seeact_mini2_raw.json"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    raw = json.loads(Path(args.raw).read_text())
    model = raw["model"]
    runs = []

    for r in raw["runs"]:
        shot = None
        if r.get("last_screenshot") and Path(r["last_screenshot"]).exists():
            shot = Path(r["last_screenshot"]).read_bytes()
        judgment = judge_task(
            r["task"], r.get("final_url") or r["start_url"], _summary_lines(r), shot, ""
        )
        status = judgment["status"]
        success = status == "SUCCESS"
        pt = int(r.get("input_tokens") or 0) + judgment.get("prompt_tokens", 0)
        ot = int(r.get("output_tokens") or 0) + judgment.get("output_tokens", 0)

        failure_category = None
        if not success:
            if status in {"BLOCKED", "SITE_CHANGED"}:
                failure_category = status
            elif r.get("error"):
                failure_category = "HARNESS"
            elif r.get("stop_reason") == "max_ops":
                failure_category = "PLANNING"
            elif r.get("complete_flag"):
                failure_category = "PREMATURE_STOP"
            else:
                failure_category = "MODEL_REASONING"

        runs.append(
            {
                **r,
                "success": success,
                "status": status,
                "judge_reason": judgment.get("reason"),
                "judge_evidence": judgment.get("evidence"),
                "failure_category": failure_category,
                "input_tokens": pt,
                "output_tokens": ot,
                "estimated_cost_usd": round(
                    cost_usd(model, pt, ot) + float(judgment.get("estimated_cost_usd") or 0), 4
                ),
            }
        )

    slug = model.replace(".", "").replace("/", "-")
    out_path = Path(args.out or (OUT_DIR / f"mini2_seeact_{slug}.json"))
    summary = {
        "stage": "mini2_seeact_upstream",
        "harness": "seeact_upstream",
        "model": model,
        "n": len(runs),
        "successes": sum(1 for r in runs if r["success"]),
        "by_status": dict(Counter(r["status"] for r in runs)),
        "total_cost_usd": round(sum(r["estimated_cost_usd"] for r in runs), 4),
        "runs": runs,
    }
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(
        json.dumps(
            {k: summary[k] for k in ("model", "n", "successes", "by_status", "total_cost_usd")},
            indent=2,
        )
    )
    for r in runs:
        print(
            f"{r['website']:12} {r['status']:12} steps={r['num_actions']:3} "
            f"${r['estimated_cost_usd']:.4f}  {r.get('judge_reason', '')[:110]}"
        )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
