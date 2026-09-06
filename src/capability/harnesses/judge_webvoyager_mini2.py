"""Judge upstream-WebVoyager Mini-2 runs with the same judge as the other harnesses.

WebVoyager writes per-task dirs containing agent.log, interact_messages.json and
numbered screenshots; this reduces those to the judge's inputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from capability import OUT_DIR, cost_usd  # noqa: E402
from capability.judge import judge_task  # noqa: E402


def _task_dir(run_dir: Path) -> Path | None:
    hits = sorted(run_dir.rglob("interact_messages.json"))
    if hits:
        return hits[-1].parent
    # A crash aborts before interact_messages.json is written; the screenshots
    # and agent.log are still there and are enough to judge the final state.
    logs = sorted(run_dir.rglob("agent.log"))
    return logs[-1].parent if logs else None


def _latest_screenshot(task_dir: Path) -> Path | None:
    shots = list(task_dir.glob("screenshot*.png"))
    if not shots:
        return None

    def idx(p: Path) -> int:
        m = re.search(r"(\d+)", p.stem)
        return int(m.group(1)) if m else -1

    return max(shots, key=idx)


def _actions_and_tokens(task_dir: Path) -> tuple[list[str], int, int, str]:
    actions: list[str] = []
    answer = ""

    messages_path = task_dir / "interact_messages.json"
    log = task_dir / "agent.log"
    log_text = log.read_text(errors="ignore") if log.exists() else ""

    if messages_path.exists():
        for m in json.loads(messages_path.read_text()):
            if m.get("role") != "assistant":
                continue
            content = m.get("content")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            content = str(content or "")
            act = re.search(r"Action:\s*(.+)", content)
            if act:
                actions.append(act.group(1).strip()[:200])
            ans = re.search(r"ANSWER[;:]\s*(.+)", content, re.S)
            if ans:
                answer = ans.group(1).strip()[:600]
    elif log_text:
        for line in log_text.splitlines():
            act = re.search(r"Action:\s*(.+)", line)
            if act:
                actions.append(act.group(1).strip()[:200])
            ans = re.search(r"ANSWER[;:]\s*(.+)", line)
            if ans:
                answer = ans.group(1).strip()[:600]

    if not actions:
        # A crashed run logs iteration markers but never dumps the messages;
        # the iteration count is the only step evidence left.
        iters = re.findall(r"Iter:\s*(\d+)", log_text)
        actions = [f"(iteration {i}, action not recorded)" for i in iters]

    pt = re.findall(r"Accumulate Prompt Tokens:\s*(\d+)", log_text)
    ct = re.findall(r"Accumulate Completion Tokens:\s*(\d+)", log_text)
    return actions, int(pt[-1]) if pt else 0, int(ct[-1]) if ct else 0, answer


def main() -> None:
    ap = argparse.ArgumentParser(description="Judge WebVoyager Mini-2 runs")
    ap.add_argument(
        "--outcomes",
        default=str(OUT_DIR / "webvoyager" / "mini2_outcomes.json"),
    )
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data = json.loads(Path(args.outcomes).read_text())
    model = data["model"]
    runs = []

    for r in data["runs"]:
        task_dir = _task_dir(Path(r["run_dir"]))
        crashed = r.get("exit_code", 0) != 0
        actions: list[str] = []
        pt = ct = 0
        answer = ""
        shot = None
        if task_dir:
            actions, pt, ct, answer = _actions_and_tokens(task_dir)
            shot_path = _latest_screenshot(task_dir)
            if shot_path:
                shot = shot_path.read_bytes()

        lines = [f"{i}. {a}" for i, a in enumerate(actions, start=1)]
        if answer:
            lines.append(f"(agent ANSWER: {answer})")
        if crashed:
            lines.append(f"(harness crashed, exit={r['exit_code']})")

        judgment = judge_task(r["task"], r["start_url"], "\n".join(lines), shot, "")
        status = judgment["status"]
        success = status == "SUCCESS"
        pt += judgment.get("prompt_tokens", 0)
        ct += judgment.get("output_tokens", 0)

        failure_category = None
        if not success:
            if status in {"BLOCKED", "SITE_CHANGED"}:
                failure_category = status
            elif crashed:
                failure_category = "HARNESS"
            elif answer:
                failure_category = "PREMATURE_STOP"
            else:
                failure_category = "PLANNING"

        runs.append(
            {
                **r,
                "model": model,
                "harness": "webvoyager_upstream",
                "observation_mode": "webvoyager_som_screenshot",
                "num_actions": len(actions),
                "actions": actions,
                "answer": answer,
                "crashed": crashed,
                "success": success,
                "status": status,
                "judge_reason": judgment.get("reason"),
                "failure_category": failure_category,
                "input_tokens": pt,
                "output_tokens": ct,
                "estimated_cost_usd": round(
                    cost_usd(model, pt, ct) + float(judgment.get("estimated_cost_usd") or 0), 4
                ),
            }
        )

    slug = model.replace(".", "").replace("/", "-")
    out_path = Path(args.out or (OUT_DIR / f"mini2_webvoyager_{slug}.json"))
    summary = {
        "stage": "mini2_webvoyager_upstream",
        "harness": "webvoyager_upstream",
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
