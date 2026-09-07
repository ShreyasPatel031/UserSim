#!/usr/bin/env python3
"""Qwen3-8B-Base BehaviorBench floor via vLLM.

Protocol (docs/plans/fm_gpu_eval_protocol.md):
  MODE=smoke  small representative slice, write SMOKE_OK.json
  MODE=full   refuse unless smoke passed + watchdog armed + concurrency>=32

Env:
  MODE                 smoke | full  (default full)
  FLOOR_MODEL          default Qwen/Qwen3-8B-Base
  ROOT                 /opt/usersim_fm or /content/fm_baselines
  CONCURRENCY          client threads (default 32, minimum 32)
  MAX_NUM_SEQS         vLLM in-flight seqs (default 64, minimum 64)
  MAX_TOKENS           default 64
  WORKFLOW_MAX_TOKENS  default 512
  GPU_MEM_UTIL         default 0.90
  MAX_MODEL_LEN        default 4096
  SKIP_WORKFLOW        1 to skip BLEURT workflow group
  SMOKE_N              survey samples in smoke (default 8)
  SMOKE_GAME_N         game samples in smoke (default 8)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol import (  # noqa: E402
    require_smoke,
    require_vllm_concurrency,
    require_watchdog,
    validate_harness_json,
    write_smoke_ok,
)

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
if not ROOT.exists():
    ROOT = Path("/content/fm_baselines")

RESULTS = ROOT / "results" / "qwen3_8b_base_befm"
BB_DATA = ROOT / "data" / "BehaviorBench"
BB_REPO = ROOT / "behaviorbench_eval"
PORT = int(os.environ.get("PORT", "8000"))
MODEL_NAME = os.environ.get("SERVED_MODEL_NAME", "qwen3-8b-base")
FLOOR_MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "64"))
WORKFLOW_MAX_TOKENS = int(os.environ.get("WORKFLOW_MAX_TOKENS", "512"))
SKIP_WORKFLOW = os.environ.get("SKIP_WORKFLOW", "0") == "1"
CONCURRENCY = int(os.environ.get("CONCURRENCY", "32"))
MAX_NUM_SEQS = int(os.environ.get("MAX_NUM_SEQS", "64"))
GPU_MEM_UTIL = os.environ.get("GPU_MEM_UTIL", "0.90")
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "4096"))
MODE = os.environ.get("MODE", "full").strip().lower()
SMOKE_N = int(os.environ.get("SMOKE_N", "8"))
SMOKE_GAME_N = int(os.environ.get("SMOKE_GAME_N", "8"))

WORKFLOW_TASKS = [
    "workflow_idea_generation",
    "workflow_method_recommendation",
    "workflow_outcome_prediction",
    "workflow_title_prediction",
    "workflow_impact_prediction",
]

TASK_GROUPS: list[list[str]] = [
    ["pers_score_pred"],
    ["surv_resp_pred"],
    ["seq_surv_resp"],
    ["missing_surv_resp"],
    ["demo_pred_age"],
    ["acrossdim_pers_score"],
    ["strategic_gameplay_guessing"],
    ["ieo_economics"],
    ["game_behavior_dictator"],
    ["game_behavior_ultimatum_proposer"],
    ["game_behavior_ultimatum_responder"],
    ["game_behavior_trust_investor"],
    ["game_behavior_trust_banker"],
    ["game_behavior_public_goods"],
    ["game_behavior_bomb"],
    ["game_behavior_guessing"],
    ["game_behavior_push_pull"],
    ["multiround_behavior_dictator"],
    ["multiround_behavior_trust_investor"],
    ["multiround_behavior_trust_banker_inv50"],
    ["multiround_behavior_trust_banker_inv100"],
    ["multiround_behavior_public_goods"],
    ["multiround_behavior_bomb"],
    ["multiround_behavior_guessing"],
    ["multiround_behavior_push_pull"],
    ["acrossgame_behavior_dictator"],
    ["acrossgame_behavior_ultimatum_proposer"],
    ["acrossgame_behavior_ultimatum_responder"],
    ["acrossgame_behavior_trust_investor"],
    ["acrossgame_behavior_trust_banker"],
    ["acrossgame_behavior_public_goods"],
    ["acrossgame_behavior_bomb"],
    ["acrossgame_behavior_guessing"],
    ["acrossgame_behavior_push_pull"],
]
if not SKIP_WORKFLOW:
    TASK_GROUPS.append(list(WORKFLOW_TASKS))

EXPECTED_TASKS = sorted({t for g in TASK_GROUPS for t in g})


def sh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)


def ensure_python311() -> str:
    for cand in ("python3.11", "python3.12"):
        try:
            out = subprocess.check_output(
                [cand, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                text=True,
            ).strip()
            major, minor = map(int, out.split("."))
            if (major, minor) >= (3, 11):
                return cand
        except Exception:
            continue
    sh("sudo apt-get update -qq")
    sh("sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev")
    return "python3.11"


def ensure_server_python() -> str:
    return os.environ.get("SERVER_PY", "python3")


def _torchaudio_stub(py: str) -> None:
    try:
        site = subprocess.check_output(
            [py, "-c", "import site; print(site.getusersitepackages())"], text=True
        ).strip()
        ta = Path(site) / "torchaudio"
        ta.mkdir(parents=True, exist_ok=True)
        (ta / "__init__.py").write_text('__version__ = "0.0.0"\n')
    except Exception as e:
        print("torchaudio stub skip", e, flush=True)


def _module_ok(py: str, mod: str) -> bool:
    return subprocess.run([py, "-c", f"import {mod}"], capture_output=True).returncode == 0


def install(eval_py: str, server_py: str) -> None:
    if os.environ.get("SKIP_INSTALL", "").strip() in {"1", "true", "TRUE"}:
        print("SKIP_INSTALL=1", flush=True)
        return
    if not _module_ok(eval_py, "behaviorbench.eval.main"):
        sh(f"{eval_py} -m pip install -q -U pip")
        sh(
            f"{eval_py} -m pip install -q "
            "openai python-dotenv pyyaml numpy scipy scikit-learn "
            "pandas tenacity rouge-score"
        )
        if not BB_REPO.exists():
            sh(f"git clone --depth 1 https://github.com/umich-foreseer/behaviorbench_eval.git {BB_REPO}")
        sh(f"{eval_py} -m pip install -q -e {BB_REPO}")
        if not SKIP_WORKFLOW:
            sh(f"{eval_py} -m pip install -q evaluate", check=False)
            sh(
                f"{eval_py} -m pip install -q "
                "'bleurt @ git+https://github.com/google-research/bleurt.git'",
                check=False,
            )
    else:
        print("eval deps already present", flush=True)
    _torchaudio_stub(server_py)
    if _module_ok(server_py, "vllm"):
        print("vllm already present", flush=True)
    else:
        sh(f"{server_py} -m pip install -q -U 'vllm>=0.6.0'", check=False)


def symlink_data() -> None:
    assert BB_DATA.exists(), f"missing BehaviorBench at {BB_DATA}"
    link = BB_REPO / "data"
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir() and not any(link.iterdir()):
        link.rmdir()
    if not link.exists():
        link.symlink_to(BB_DATA)


def write_progress(done: list[str], failed: list[str], current: list[str] | None) -> None:
    payload = {
        "model": FLOOR_MODEL,
        "engine": "vllm",
        "concurrency": CONCURRENCY,
        "max_num_seqs": MAX_NUM_SEQS,
        "done": done,
        "failed": failed,
        "current": current,
        "n_done": len(done),
        "n_expected": len(EXPECTED_TASKS),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "PROGRESS.json").write_text(json.dumps(payload, indent=2))


def task_already_done(task: str) -> bool:
    out = RESULTS / "full" / ("workflow" if task.startswith("workflow_") else task)
    if not out.exists():
        return False
    for p in out.rglob("*.json"):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        tasks = d.get("tasks") or []
        names = {t.get("task_name") for t in tasks if isinstance(t, dict)}
        metrics = d.get("metrics") or {}
        if task in names or task in metrics:
            return True
    return False


def workflow_already_done() -> bool:
    return all(task_already_done(t) for t in WORKFLOW_TASKS)


def start_vllm(server_py: str) -> subprocess.Popen:
    env = os.environ.copy()
    tok = Path.home() / ".cache" / "huggingface" / "token"
    if tok.exists():
        env["HF_TOKEN"] = tok.read_text().strip()
        env["HUGGING_FACE_HUB_TOKEN"] = env["HF_TOKEN"]
    env["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
    env.setdefault("VLLM_ENGINE_READY_TIMEOUT_S", "600")
    env.setdefault("VLLM_ENGINE_ITERATION_TIMEOUT_S", "300")

    RESULTS.mkdir(parents=True, exist_ok=True)
    log_path = RESULTS / "vllm.log"
    logf = open(log_path, "a")
    logf.write(f"\n===== start {datetime.now(timezone.utc).isoformat()} =====\n")
    logf.flush()
    cmd = [
        server_py,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        FLOOR_MODEL,
        "--served-model-name",
        MODEL_NAME,
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "--dtype",
        os.environ.get("DTYPE", "bfloat16"),
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--gpu-memory-utilization",
        GPU_MEM_UTIL,
        "--max-num-seqs",
        str(MAX_NUM_SEQS),
        "--trust-remote-code",
        "--enforce-eager",
    ]
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=logf, stderr=subprocess.STDOUT)
    deadline = time.time() + 1800
    while time.time() < deadline:
        if proc.poll() is not None:
            print(log_path.read_text()[-20000:], flush=True)
            raise RuntimeError(f"vLLM exited early rc={proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2)
            print("vllm healthy", flush=True)
            return proc
        except Exception:
            time.sleep(3)
    raise TimeoutError("vLLM did not become healthy")


def run_eval(py: str, tasks: list[str], out_dir: Path, max_tokens: int, extra: list[str] | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    extra_s = " ".join(extra or [])
    cmd = (
        f"cd {BB_REPO} && "
        f"MODEL_NAME={MODEL_NAME} API_BASE=http://127.0.0.1:{PORT}/v1 "
        f"{py} -m behaviorbench.eval.main "
        f"--task {' '.join(tasks)} "
        f"--model-type local "
        f"--model-name {MODEL_NAME} "
        f"--api-base http://127.0.0.1:{PORT}/v1 "
        f"--temperature 0.6 --top-p 0.95 --top-k 20 "
        f"--max-tokens {max_tokens} --concurrency {CONCURRENCY} "
        f"--output-dir {out_dir} {extra_s}"
    )
    print(f"=== EVAL {tasks} max_tokens={max_tokens} concurrency={CONCURRENCY} ===", flush=True)
    sh(cmd, check=True)


def latest_json(out_dir: Path) -> Path:
    files = sorted(out_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [p for p in files if p.name not in {"SMOKE_OK.json", "SUMMARY.json", "PROGRESS.json"}]
    if not files:
        raise FileNotFoundError(f"no result json under {out_dir}")
    return files[0]


def run_smoke(eval_py: str) -> None:
    reports = []
    survey_out = RESULTS / "smoke_pers_score_pred"
    run_eval(
        eval_py,
        ["pers_score_pred"],
        survey_out,
        MAX_TOKENS,
        [f"--num-samples {SMOKE_N}", "--seed 0"],
    )
    reports.append(validate_harness_json(latest_json(survey_out), "pers_score_pred"))
    game_out = RESULTS / "smoke_game_behavior_dictator"
    run_eval(
        eval_py,
        ["game_behavior_dictator"],
        game_out,
        MAX_TOKENS,
        [f"--num-samples-per-game {SMOKE_GAME_N}", "--seed 0"],
    )
    reports.append(validate_harness_json(latest_json(game_out), "game_behavior_dictator"))
    write_smoke_ok(
        RESULTS,
        reports,
        {
            "model": FLOOR_MODEL,
            "concurrency": CONCURRENCY,
            "max_num_seqs": MAX_NUM_SEQS,
            "smoke_n": SMOKE_N,
            "smoke_game_n": SMOKE_GAME_N,
        },
    )
    print(json.dumps({"smoke": reports}, indent=2), flush=True)
    print("SMOKE_PASSED", flush=True)


def collect_summary(done: list[str], failed: list[str]) -> dict:
    metrics_by_task: dict[str, dict] = {}
    for task in done:
        out = RESULTS / "full" / ("workflow" if task.startswith("workflow_") else task)
        files = sorted(out.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            m = d.get("metrics") or {}
            if task in m:
                metrics_by_task[task] = m[task]
                break
            for t in d.get("tasks") or []:
                if isinstance(t, dict) and t.get("task_name") == task:
                    metrics_by_task[task] = t.get("metrics") or {}
                    break
            if task in metrics_by_task:
                break

    workflow_bleurts = []
    for t in WORKFLOW_TASKS:
        m = metrics_by_task.get(t) or {}
        for k, v in m.items():
            if "bleurt" in k.lower() and isinstance(v, (int, float)):
                workflow_bleurts.append(float(v))
                break

    summary = {
        "model": FLOOR_MODEL,
        "engine": "vllm",
        "concurrency": CONCURRENCY,
        "tasks": sorted(done),
        "failed": failed,
        "coverage": {
            "actual": len(done),
            "expected": len(EXPECTED_TASKS),
            "unit": "tasks",
            "complete": len(done) >= len(EXPECTED_TASKS) and not failed,
            "failed": failed,
            "tasks": sorted(done),
        },
        "metrics_by_task": metrics_by_task,
        "workflow": {
            "average_bleurt": (
                sum(workflow_bleurts) / len(workflow_bleurts) if workflow_bleurts else None
            ),
            "n_bleurt": len(workflow_bleurts),
        },
        "distributional_win_rate": None,
        "individual_win_rate": None,
        "complete": len(done) >= len(EXPECTED_TASKS) and not failed,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2))
    return summary


def completed_so_far() -> list[str]:
    done: list[str] = []
    for g in TASK_GROUPS:
        if g == WORKFLOW_TASKS:
            if workflow_already_done():
                done.extend(WORKFLOW_TASKS)
        elif len(g) == 1 and task_already_done(g[0]):
            done.append(g[0])
    return done


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    assert BB_DATA.exists(), f"missing {BB_DATA}"
    if MODE not in {"smoke", "full"}:
        raise SystemExit(f"MODE must be smoke|full, got {MODE}")
    require_vllm_concurrency(CONCURRENCY, MAX_NUM_SEQS)
    if MODE == "full":
        require_watchdog()
        require_smoke(RESULTS)

    eval_py = ensure_python311()
    server_py = ensure_server_python()
    print(
        "mode",
        MODE,
        "eval_py",
        eval_py,
        "server_py",
        server_py,
        "concurrency",
        CONCURRENCY,
        "max_num_seqs",
        MAX_NUM_SEQS,
        flush=True,
    )
    install(eval_py, server_py)
    symlink_data()

    if MODE == "full":
        done = completed_so_far()
        failed: list[str] = []
        write_progress(done, failed, None)
        print("resume done", done, flush=True)
    else:
        done = []
        failed = []

    proc = start_vllm(server_py)
    try:
        if MODE == "smoke":
            run_smoke(eval_py)
            return
        for g in TASK_GROUPS:
            if g == WORKFLOW_TASKS:
                if all(t in done for t in WORKFLOW_TASKS):
                    print("SKIP workflow", flush=True)
                    continue
                out_dir = RESULTS / "full" / "workflow"
                max_tok = WORKFLOW_MAX_TOKENS
            else:
                task = g[0]
                if task in done:
                    print("SKIP", task, flush=True)
                    continue
                out_dir = RESULTS / "full" / task
                max_tok = MAX_TOKENS

            write_progress(done, failed, g)
            try:
                run_eval(eval_py, g, out_dir, max_tok)
                for t in g:
                    if t not in done:
                        done.append(t)
                write_progress(done, failed, None)
                collect_summary(done, failed)
            except Exception as e:
                print(f"FAILED {g}: {e}", flush=True)
                for t in g:
                    if t not in failed:
                        failed.append(t)
                write_progress(done, failed, None)
                collect_summary(done, failed)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()

    summary = collect_summary(done, failed)
    print(
        json.dumps(
            {k: summary[k] for k in ("coverage", "workflow", "failed", "complete", "engine")},
            indent=2,
        ),
        flush=True,
    )
    if summary["complete"]:
        print("FULL_PASSED", flush=True)
    else:
        print("FULL_PARTIAL", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
