#!/usr/bin/env python3
"""Serve Be.FM-1.5-4B and run full BehaviorBench (Gate 0).

Subsetting requires ALLOW_PARTIAL=1 and writes PARTIAL.*.json, never SUMMARY.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path("/content/fm_baselines")
DATA = ROOT / "data"
RESULTS = ROOT / "results" / "befm4b"
ADAPTER = ROOT / "models" / "BeFM1.5-4B"
BB_DATA = DATA / "BehaviorBench"
BB_REPO = ROOT / "behaviorbench_eval"
PORT = 8000
os.environ.setdefault("BEHAVIORBENCH_BLEURT_PATH", "/opt/usersim_fm/models/BLEURT-20")
os.environ.setdefault("BEFM_BLEURT_PATH", "/opt/usersim_fm/models/BLEURT-20")

# Make local repo helpers importable when running from UserSim checkout.
_REPO = Path(__file__).resolve().parents[2]
if (_REPO / "scripts" / "fm_baselines").is_dir():
    sys.path.insert(0, str(_REPO / "scripts" / "fm_baselines"))
if (ROOT / "scripts").is_dir():
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from gate_contract import (  # type: ignore
        allow_partial,
        behaviorbench_expected_tasks,
        coverage_block,
        require_full_or_allow,
        write_summary_or_partial,
    )
except ImportError:
    # Minimal inline fallback for Colab if gate_contract.py was not uploaded.
    def allow_partial() -> bool:
        return os.environ.get("ALLOW_PARTIAL", "").strip() in {"1", "true", "TRUE", "yes"}

    def require_full_or_allow(kind: str, detail: str) -> None:
        if allow_partial():
            print(f"ALLOW_PARTIAL=1 — PARTIAL {kind}: {detail}", flush=True)
            return
        raise SystemExit(
            f"Refusing subset ({kind}: {detail}). Set ALLOW_PARTIAL=1 or run the full task set."
        )

    def behaviorbench_expected_tasks() -> list[str]:
        # Keep in sync with docs/plans/gates.yaml / DEFAULT_DATA_PATHS (39 tasks).
        return [
            "pers_score_pred", "surv_resp_pred", "missing_surv_resp", "seq_surv_resp",
            "demo_pred_age", "acrossdim_pers_score",
            "workflow_idea_generation", "workflow_method_recommendation",
            "workflow_outcome_prediction", "workflow_title_prediction",
            "workflow_impact_prediction", "ieo_economics",
            "game_behavior_dictator", "game_behavior_ultimatum_proposer",
            "game_behavior_ultimatum_responder", "game_behavior_trust_investor",
            "game_behavior_trust_banker", "game_behavior_public_goods",
            "game_behavior_bomb", "game_behavior_guessing", "game_behavior_push_pull",
            "multiround_behavior_dictator", "multiround_behavior_trust_investor",
            "multiround_behavior_trust_banker_inv50", "multiround_behavior_trust_banker_inv100",
            "multiround_behavior_public_goods", "multiround_behavior_bomb",
            "multiround_behavior_guessing", "multiround_behavior_push_pull",
            "acrossgame_behavior_dictator", "acrossgame_behavior_ultimatum_proposer",
            "acrossgame_behavior_ultimatum_responder", "acrossgame_behavior_trust_investor",
            "acrossgame_behavior_trust_banker", "acrossgame_behavior_public_goods",
            "acrossgame_behavior_bomb", "acrossgame_behavior_guessing",
            "acrossgame_behavior_push_pull", "strategic_gameplay_guessing",
        ]

    def coverage_block(**kwargs):
        failed = list(kwargs.get("failed") or [])
        complete = bool(kwargs.get("complete")) and not failed
        return {
            "actual": kwargs["actual"],
            "expected": kwargs["expected"],
            "unit": kwargs.get("unit", "tasks"),
            "complete": complete,
            "failed": failed,
            "tasks": kwargs.get("extra", {}).get("tasks") if kwargs.get("extra") else None,
        }

    def write_summary_or_partial(results_dir, summary, *, complete, reason=None):
        results_dir.mkdir(parents=True, exist_ok=True)
        if not complete:
            safe = (reason or "incomplete").replace(" ", "_")[:64]
            path = results_dir / f"PARTIAL.{safe}.json"
            summary = dict(summary)
            summary["complete"] = False
            path.write_text(json.dumps(summary, indent=2))
            return path
        path = results_dir / "SUMMARY.json"
        summary = dict(summary)
        summary["complete"] = True
        path.write_text(json.dumps(summary, indent=2))
        done = results_dir / "DONE.json"
        if done.exists():
            done.unlink()
        return path


def sh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)


def install() -> None:
    sh(f"{sys.executable} -m pip install -q -U pip")
    sh(f"{sys.executable} -m pip uninstall -y tensorflow 2>/dev/null || true")
    sh(f"{sys.executable} -m pip install -q -U 'tensorflow-cpu>=2.15' 'evaluate>=0.4.0' 'rouge-score>=0.1.2' 'git+https://github.com/google-research/bleurt.git'")

    sh(
        f"{sys.executable} -m pip install -q "
        "torch transformers 'peft>=0.17' 'torchao>=0.16' accelerate fastapi uvicorn "
        "openai datasets pyyaml python-dotenv numpy scipy scikit-learn "
        "huggingface_hub"
    )
    sh(f"{sys.executable} -m pip install -q -U 'torchao>=0.16'")
    if not BB_REPO.exists():
        sh(f"git clone --depth 1 https://github.com/umich-foreseer/behaviorbench_eval.git {BB_REPO}")
    sh(f"{sys.executable} -m pip install -q -e {BB_REPO}")


def start_server() -> subprocess.Popen:
    """Serve Be.FM via vLLM continuous batching + LoRA (not per-request generate())."""
    base = os.environ.get("BEFM_BASE", "Qwen/Qwen3-4B-Instruct-2507")
    max_seqs = os.environ.get("BEFM_MAX_NUM_SEQS", "64")
    gpu_util = os.environ.get("BEFM_GPU_MEM_UTIL", "0.90")
    max_len = os.environ.get("BEFM_MAX_MODEL_LEN", "4096")
    log = ROOT / "logs" / "befm_vllm.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    # Prefer the vllm CLI; fall back to python -m.
    vllm_bin = None
    for cand in (
        Path(sys.executable).parent / "vllm",
        Path.home() / ".local" / "bin" / "vllm",
    ):
        if cand.is_file():
            vllm_bin = str(cand)
            break
    if vllm_bin:
        cmd = [
            vllm_bin, "serve", base,
            "--host", "127.0.0.1", "--port", str(PORT),
            "--dtype", "half",
            "--gpu-memory-utilization", gpu_util,
            "--max-model-len", max_len,
            "--max-num-seqs", max_seqs,
            "--enable-lora",
            "--max-lora-rank", "16",
            "--lora-modules", f"befm-1.5-4b={ADAPTER}",
            "--trust-remote-code",
        ]
    else:
        cmd = [
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
            "--model", base,
            "--host", "127.0.0.1", "--port", str(PORT),
            "--dtype", "half",
            "--gpu-memory-utilization", gpu_util,
            "--max-model-len", max_len,
            "--max-num-seqs", max_seqs,
            "--enable-lora",
            "--max-lora-rank", "16",
            "--lora-modules", f"befm-1.5-4b={ADAPTER}",
            "--trust-remote-code",
        ]

    print("+", " ".join(cmd), flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        text=True,
    )

    import urllib.request

    deadline = time.time() + 1200
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"vLLM exited early rc={proc.returncode}; see {log}"
            )
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2)
            print("vLLM server healthy", flush=True)
            return proc
        except Exception:
            time.sleep(3)
    raise TimeoutError(f"vLLM did not become healthy; see {log}")


def symlink_data() -> None:
    link = BB_REPO / "data"
    if link.exists() or link.is_symlink():
        if link.is_symlink() or link.is_file():
            link.unlink()
        else:
            return
    link.symlink_to(BB_DATA)


def resolve_tasks() -> list[str]:
    expected = behaviorbench_expected_tasks()
    override = os.environ.get("BEFM_TASKS", "").strip()
    if override:
        tasks = [t.strip() for t in override.split(",") if t.strip()]
        if set(tasks) != set(expected):
            require_full_or_allow("befm_tasks", f"{len(tasks)}/{len(expected)} tasks")
        return tasks
    return list(expected)


def task_already_done(task: str) -> bool:
    out = RESULTS / task
    if not out.is_dir():
        return False
    # BehaviorBench writes under <task>/<model_name>/*.json
    return any(p.is_file() and p.stat().st_size > 0 for p in out.rglob("*.json"))


WORKFLOW_TASKS = [
    "workflow_idea_generation",
    "workflow_impact_prediction",
    "workflow_method_recommendation",
    "workflow_outcome_prediction",
    "workflow_title_prediction",
]


def run_workflow_bundle() -> bool:
    """BehaviorBench requires all five workflow_* tasks in one --task invocation."""
    import shutil

    if all(task_already_done(t) for t in WORKFLOW_TASKS):
        print("=== SKIP workflow_bundle (all five already done) ===", flush=True)
        return True

    concurrency = int(os.environ.get("BEFM_WORKFLOW_CONCURRENCY", "4"))
    max_tokens = int(os.environ.get("BEFM_WORKFLOW_MAX_TOKENS", "2048"))
    out = RESULTS / "workflow_bundle"
    out.mkdir(parents=True, exist_ok=True)
    task_args = " ".join(WORKFLOW_TASKS)
    cmd = (
        f"cd {BB_REPO} && "
        f"CUDA_VISIBLE_DEVICES= TF_CPP_MIN_LOG_LEVEL=3 "
        f"MODEL_NAME=befm-1.5-4b API_BASE=http://127.0.0.1:{PORT}/v1 "
        f"{sys.executable} -m behaviorbench.eval.main "
        f"--task {task_args} "
        f"--model-type local "
        f"--model-name befm-1.5-4b "
        f"--api-base http://127.0.0.1:{PORT}/v1 "
        f"--temperature 0.6 --top-p 0.95 --top-k 20 "
        f"--max-tokens {max_tokens} --concurrency {concurrency} "
        f"--output-dir {out}"
    )
    print(
        f"=== TASK workflow_bundle (5 together) concurrency={concurrency} max_tokens={max_tokens} ===",
        flush=True,
    )
    r = sh(cmd, check=False)
    if r.returncode != 0:
        print(f"TASK_FAILED workflow_bundle rc={r.returncode}", flush=True)
        return False

    combined = sorted((out / "befm-1.5-4b").glob("combined_5subtasks_*.json"))
    if not combined:
        combined = sorted(out.rglob("combined_5subtasks_*.json"))
    if not combined:
        combined = sorted(p for p in out.rglob("*.json") if p.stat().st_size > 0)
    if not combined:
        print("TASK_FAILED workflow_bundle: no result json written", flush=True)
        return False
    src = combined[-1]
    for task in WORKFLOW_TASKS:
        dest = RESULTS / task / "befm-1.5-4b"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / src.name)
        (dest / "WORKFLOW_BUNDLE.json").write_text(
            json.dumps({"bundle_result": str(src), "task": task}, indent=2)
        )
    print(f"workflow_bundle ok → copied {src.name} into 5 task dirs", flush=True)
    return True


def run_tasks(tasks: list[str]) -> list[str]:
    """Run tasks; return list of failed task names. Failures are recorded, not swallowed."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    concurrency = int(os.environ.get("BEFM_CONCURRENCY", "16"))
    failed: list[str] = []

    workflow = [t for t in tasks if t in WORKFLOW_TASKS]
    other = [t for t in tasks if t not in WORKFLOW_TASKS]

    for task in other:
        if task_already_done(task):
            print(f"=== SKIP {task} (existing result) ===", flush=True)
            continue
        out = RESULTS / task
        out.mkdir(parents=True, exist_ok=True)
        cmd = (
            f"cd {BB_REPO} && "
            f"MODEL_NAME=befm-1.5-4b API_BASE=http://127.0.0.1:{PORT}/v1 "
            f"{sys.executable} -m behaviorbench.eval.main "
            f"--task {task} "
            f"--model-type local "
            f"--model-name befm-1.5-4b "
            f"--api-base http://127.0.0.1:{PORT}/v1 "
            f"--temperature 0.6 --top-p 0.95 --top-k 20 "
            f"--max-tokens 64 --concurrency {concurrency} "
            f"--output-dir {out}"
        )
        print(f"=== TASK {task} concurrency={concurrency} ===", flush=True)
        r = sh(cmd, check=False)
        if r.returncode != 0:
            print(f"TASK_FAILED {task} rc={r.returncode}", flush=True)
            failed.append(task)

    if workflow:
        if not run_workflow_bundle():
            failed.extend([t for t in workflow if not task_already_done(t)])
    return failed


def main() -> None:
    assert ADAPTER.exists(), f"missing adapter at {ADAPTER}"
    assert BB_DATA.exists(), f"missing BehaviorBench at {BB_DATA}"
    if os.environ.get("SKIP_INSTALL", "").strip() not in {"1", "true", "TRUE", "yes"}:
        install()
        sh(f"{sys.executable} -m pip install -q -U 'vllm>=0.6.0'")
    symlink_data()
    proc = start_server()

    tasks = resolve_tasks()
    expected = behaviorbench_expected_tasks()
    print(f"running {len(tasks)}/{len(expected)} BehaviorBench tasks", flush=True)

    try:
        failed = run_tasks(tasks)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()

    cov = coverage_block(
        actual=len(tasks) - len(failed),
        expected=len(expected),
        unit="tasks",
        complete=set(tasks) == set(expected) and not failed,
        failed=failed,
        extra={"tasks": tasks},
    )
    # Board-level win rates must be filled by a separate aggregation step when available.
    summary = {
        "model": "befm/BeFM1.5-4B",
        "tasks": tasks,
        "failed": failed,
        "coverage": cov,
        "distributional_win_rate": None,
        "individual_win_rate": None,
        "note": "Board win rates must be computed from full task metrics before Gate 0 can pass.",
    }
    complete = bool(cov["complete"])
    reason = None
    if not complete:
        if failed:
            reason = f"failed_{len(failed)}_tasks"
        elif set(tasks) != set(expected):
            reason = f"subset_{len(tasks)}_of_{len(expected)}"
        else:
            reason = "incomplete"
    write_summary_or_partial(RESULTS, summary, complete=complete, reason=reason)
    print("complete", complete, "failed", failed, flush=True)


if __name__ == "__main__":
    main()
