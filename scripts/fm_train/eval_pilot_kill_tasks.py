#!/usr/bin/env python3
"""Run the SFT-pilot kill-test eval slice, then apply GO/STOP.

Tasks (first pass):
  - strategic_gameplay_guessing  (Beauty Contest win rate)
  - all 9 game_behavior_*        (single-round W)
  - surv_resp_pred               (survey Acc collapse check)

Reuses scripts/fm_baselines/colab_qwen3_8b_floor_befm.py harness patterns:
serve model (base+adapter) via vLLM / OpenAI-compatible server, call
behaviorbench_eval, write SUMMARY, then apply_pilot_kill_gate.py.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_REPO / "scripts" / "fm_train"))

from apply_pilot_kill_gate import decide  # noqa: E402

GAME_BEHAVIOR = [
    "game_behavior_dictator",
    "game_behavior_ultimatum_proposer",
    "game_behavior_ultimatum_responder",
    "game_behavior_trust_investor",
    "game_behavior_trust_banker",
    "game_behavior_public_goods",
    "game_behavior_bomb",
    "game_behavior_guessing",
    "game_behavior_push_pull",
]
KILL_TASKS = ["strategic_gameplay_guessing", "surv_resp_pred"] + GAME_BEHAVIOR


def sh(cmd: list[str] | str, check: bool = True) -> subprocess.CompletedProcess:
    print("+", cmd if isinstance(cmd, str) else " ".join(cmd), flush=True)
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=check)


def parse_harness_metrics(results_dir: Path) -> dict:
    """Best-effort scrape of BehaviorBench JSON reports under results_dir."""
    beauty = None
    game_ws: list[float] = []
    survey_acc = None

    for path in results_dir.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        text = path.name.lower() + str(path.parent).lower()
        blob = json.dumps(data).lower()

        def find_num(obj, keys):
            if isinstance(obj, dict):
                lower = {k.lower(): v for k, v in obj.items()}
                for k in keys:
                    if k in lower:
                        try:
                            return float(lower[k])
                        except (TypeError, ValueError):
                            pass
                for v in obj.values():
                    n = find_num(v, keys)
                    if n is not None:
                        return n
            elif isinstance(obj, list):
                for v in obj:
                    n = find_num(v, keys)
                    if n is not None:
                        return n
            return None

        if "guessing" in text or "strategic" in text:
            w = find_num(data, ["win_rate", "winrate", "beauty_win"])
            if w is not None:
                beauty = w / 100.0 if w > 1.0 else w
        if "game_behavior" in text or "wasserstein" in blob:
            w = find_num(data, ["wasserstein", "w_avg", "avg_w", "w"])
            if w is not None and 0 < w < 100:
                game_ws.append(w)
        if "surv_resp" in text or "survey" in text:
            a = find_num(data, ["accuracy", "acc", "survey_acc"])
            if a is not None:
                survey_acc = a / 100.0 if a > 1.0 else a

    return {
        "beauty_win": beauty,
        "game_w": (sum(game_ws) / len(game_ws)) if game_ws else None,
        "survey_acc": survey_acc,
        "n_game_w": len(game_ws),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--adapter",
        default=os.environ.get(
            "PILOT_OUT", "/opt/usersim_fm/adapters/qwen3_8b_base_pilot"
        ),
    )
    ap.add_argument(
        "--base-model",
        default=os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base"),
    )
    ap.add_argument(
        "--results",
        type=Path,
        default=None,
        help="directory of already-finished harness JSON (skip serving)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT_REPO / "results" / "fm_train" / "pilot_kill_gate.json",
    )
    ap.add_argument(
        "--metrics-json",
        type=Path,
        default=None,
        help="optional explicit {beauty_win, game_w, survey_acc}",
    )
    ap.add_argument("--dry-run", action="store_true", help="print tasks + gate only")
    args = ap.parse_args()

    print("kill tasks:", KILL_TASKS, flush=True)
    if args.dry_run:
        demo = decide(0.048, 15.4, 0.27)
        print("floor self-check (expect STOP/BORDERLINE):", json.dumps(demo, indent=2))
        return

    metrics = None
    if args.metrics_json and args.metrics_json.exists():
        metrics = json.loads(args.metrics_json.read_text())
    elif args.results and args.results.exists():
        metrics = parse_harness_metrics(args.results)
    else:
        # Prefer calling the existing floor runner with FLOOR_MODEL pointing at
        # a merged adapter path if the operator set PILOT_MERGED_MODEL.
        merged = os.environ.get("PILOT_MERGED_MODEL")
        if not merged:
            print(
                "No --results / --metrics-json and PILOT_MERGED_MODEL unset.\n"
                "Train first, merge adapter into a local dir, then either:\n"
                "  1) run colab_qwen3_8b_floor_befm.py with FLOOR_MODEL=<merged>\n"
                "     restricted to kill tasks, OR\n"
                "  2) pass --metrics-json with beauty_win/game_w/survey_acc.\n"
                f"Adapter expected at: {args.adapter}",
                flush=True,
            )
            # Still write a pending gate stub so the pipeline is wired.
            pending = {
                "verdict": "PENDING",
                "reason": ["eval not run yet — adapter/metrics missing"],
                "adapter": args.adapter,
                "base_model": args.base_model,
                "tasks": KILL_TASKS,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(pending, indent=2) + "\n")
            print(json.dumps(pending, indent=2))
            return

        env = os.environ.copy()
        env["FLOOR_MODEL"] = merged
        env["MODE"] = "full"
        runner = ROOT_REPO / "scripts" / "fm_baselines" / "colab_qwen3_8b_floor_befm.py"
        sh([sys.executable, str(runner)], check=True)
        # Default results path used by floor runner
        default_res = Path(
            os.environ.get("ROOT", "/opt/usersim_fm")
        ) / "results" / "qwen3_8b_base_befm"
        metrics = parse_harness_metrics(default_res)

    beauty = metrics.get("beauty_win")
    game_w = metrics.get("game_w")
    survey = metrics.get("survey_acc")
    if beauty is None or game_w is None:
        raise SystemExit(f"incomplete metrics: {metrics}")

    result = decide(float(beauty), float(game_w), float(survey) if survey is not None else None)
    result["raw_metrics"] = metrics
    result["adapter"] = args.adapter
    result["tasks"] = KILL_TASKS
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["verdict"] == "STOP":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
