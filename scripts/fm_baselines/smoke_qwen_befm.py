#!/usr/bin/env python3
"""Qwen3-8B-Base BehaviorBench smoke: serve model, run tiny tasks, validate JSON schema.

Env:
  FLOOR_MODEL   default Qwen/Qwen3-8B-Base
  SMOKE_N       num-samples for survey task (default 8)
  SMOKE_GAME_N  num-samples-per-game (default 8)
  ROOT          default /opt/usersim_fm (GCP) or /content/fm_baselines
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
if not ROOT.exists():
    ROOT = Path("/content/fm_baselines")

RESULTS = ROOT / "results" / "qwen3_8b_base_befm"
BB_DATA = ROOT / "data" / "BehaviorBench"
BB_REPO = ROOT / "behaviorbench_eval"
SERVER = ROOT / "scripts" / "qwen_openai_server.py"
PORT = int(os.environ.get("PORT", "8000"))
MODEL_NAME = "qwen3-8b-base"
FLOOR_MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
SMOKE_N = int(os.environ.get("SMOKE_N", "8"))
SMOKE_GAME_N = int(os.environ.get("SMOKE_GAME_N", "8"))

REQUIRED_TOP = {"timestamp", "metrics", "num_tasks", "tasks"}
REQUIRED_TASK = {"task_name", "metrics", "metadata", "predictions"}


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
    """Prefer system python3 with a working torch/transformers stack (DL image)."""
    for cand in ("python3", sys.executable):
        try:
            subprocess.check_call(
                [
                    cand,
                    "-c",
                    "from transformers import AutoModelForCausalLM; import torch",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return cand
        except Exception:
            continue
    return "python3"


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


def install(eval_py: str, server_py: str) -> None:
    # Eval client (BehaviorBench needs >=3.11): no torch needed
    sh(f"{eval_py} -m pip install -q -U pip")
    sh(
        f"{eval_py} -m pip install -q "
        "openai python-dotenv pyyaml numpy scipy scikit-learn "
        "pandas tenacity rouge-score"
    )
    if not BB_REPO.exists():
        sh(f"git clone --depth 1 https://github.com/umich-foreseer/behaviorbench_eval.git {BB_REPO}")
    sh(f"{eval_py} -m pip install -q -e {BB_REPO}")

    # Model server: reuse existing torch stack; only ensure API deps
    sh(f"{server_py} -m pip install -q fastapi uvicorn pydantic")
    _torchaudio_stub(server_py)


def symlink_data() -> None:
    assert BB_DATA.exists(), f"missing BehaviorBench at {BB_DATA}"
    link = BB_REPO / "data"
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.is_dir() and not any(link.iterdir()):
        link.rmdir()
    if not link.exists():
        link.symlink_to(BB_DATA)


def start_server(server_py: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["FLOOR_MODEL"] = FLOOR_MODEL
    env["PORT"] = str(PORT)
    # HF token if present
    tok = Path.home() / ".cache" / "huggingface" / "token"
    if tok.exists():
        env["HF_TOKEN"] = tok.read_text().strip()
        env["HUGGING_FACE_HUB_TOKEN"] = env["HF_TOKEN"]

    log_path = RESULTS / "server.log"
    RESULTS.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "w")
    proc = subprocess.Popen(
        [server_py, "-u", str(SERVER)],
        cwd=str(ROOT),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def pump() -> None:
        # mirror last lines occasionally
        while proc.poll() is None:
            time.sleep(5)

    threading.Thread(target=pump, daemon=True).start()

    deadline = time.time() + 1200
    while time.time() < deadline:
        if proc.poll() is not None:
            print(log_path.read_text()[-2000:], flush=True)
            raise RuntimeError(f"server exited early rc={proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2)
            print("server healthy", flush=True)
            return proc
        except Exception:
            time.sleep(3)
    raise TimeoutError("server did not become healthy")


def run_eval(py: str, tasks: list[str], out_dir: Path, extra: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = (
        f"cd {BB_REPO} && "
        f"MODEL_NAME={MODEL_NAME} API_BASE=http://127.0.0.1:{PORT}/v1 "
        f"{py} -m behaviorbench.eval.main "
        f"--task {' '.join(tasks)} "
        f"--model-type local "
        f"--model-name {MODEL_NAME} "
        f"--api-base http://127.0.0.1:{PORT}/v1 "
        f"--temperature 0.6 --top-p 0.95 --top-k 20 "
        f"--max-tokens 64 --concurrency 1 "
        f"--output-dir {out_dir} "
        + " ".join(extra)
    )
    print(f"=== EVAL {tasks} ===", flush=True)
    sh(cmd, check=True)


def validate_result(path: Path, expect_task: str) -> dict:
    data = json.loads(path.read_text())
    missing = REQUIRED_TOP - set(data)
    if missing:
        raise AssertionError(f"{path.name}: missing top keys {missing}")
    if data["num_tasks"] < 1:
        raise AssertionError(f"{path.name}: num_tasks={data['num_tasks']}")
    tasks = data["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise AssertionError(f"{path.name}: empty tasks")
    task = tasks[0]
    missing_t = REQUIRED_TASK - set(task)
    if missing_t:
        raise AssertionError(f"{path.name}: task missing {missing_t}")
    if task["task_name"] != expect_task:
        raise AssertionError(f"expected task {expect_task}, got {task['task_name']}")
    if not isinstance(task["metrics"], dict) or not task["metrics"]:
        raise AssertionError(f"{path.name}: empty metrics")
    preds = task["predictions"]
    if not isinstance(preds, list) or len(preds) < 1:
        raise AssertionError(f"{path.name}: no predictions")
    # prediction row shape
    sample = preds[0]
    if not isinstance(sample, dict):
        raise AssertionError(f"prediction not dict: {type(sample)}")
    # Canonical BehaviorBench prediction row:
    # prompt / raw_output / parsed_prediction / expected
    need = {"prompt", "raw_output", "parsed_prediction", "expected"}
    missing_p = need - set(sample)
    if missing_p:
        raise AssertionError(f"{path.name}: prediction missing {missing_p}; got {sorted(sample)}")
    parsed_ok = sum(
        1
        for p in preds
        if isinstance(p, dict) and p.get("parsed_prediction") is not None
    )
    meta = task.get("metadata") or {}
    return {
        "file": str(path),
        "task": expect_task,
        "n_preds": len(preds),
        "parsed_non_null": parsed_ok,
        "num_failed_parses": meta.get("num_failed_parses"),
        "failed_parse_rate": meta.get("failed_parse_rate"),
        "metric_keys": sorted(k for k in task["metrics"] if not str(k).startswith("_")),
        "metrics_sample": {
            k: task["metrics"][k]
            for k in list(task["metrics"])[:8]
            if not str(k).startswith("_")
        },
        "raw_sample": str(sample.get("raw_output"))[:120],
    }


def latest_json(out_dir: Path) -> Path:
    files = sorted(out_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [p for p in files if p.name != "SMOKE_SUMMARY.json"]
    if not files:
        raise FileNotFoundError(f"no result json under {out_dir}")
    return files[0]


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    assert SERVER.exists(), f"missing {SERVER}"
    assert BB_DATA.exists(), f"missing {BB_DATA}"

    eval_py = ensure_python311()
    server_py = ensure_server_python()
    print("eval_py", eval_py, "server_py", server_py, flush=True)
    install(eval_py, server_py)
    symlink_data()

    proc = start_server(server_py)
    reports = []
    try:
        survey_out = RESULTS / "smoke_pers_score_pred"
        run_eval(
            eval_py,
            ["pers_score_pred"],
            survey_out,
            [f"--num-samples {SMOKE_N}", "--seed 0"],
        )
        reports.append(validate_result(latest_json(survey_out), "pers_score_pred"))

        game_out = RESULTS / "smoke_game_behavior_dictator"
        run_eval(
            eval_py,
            ["game_behavior_dictator"],
            game_out,
            [f"--num-samples-per-game {SMOKE_GAME_N}", "--seed 0"],
        )
        reports.append(validate_result(latest_json(game_out), "game_behavior_dictator"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()

    summary = {
        "model": FLOOR_MODEL,
        "smoke_n": SMOKE_N,
        "smoke_game_n": SMOKE_GAME_N,
        "reports": reports,
        "schema_ok": True,
    }
    (RESULTS / "SMOKE_SUMMARY.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    # Require at least some parses so we know format is usable
    if all(r["parsed_non_null"] == 0 for r in reports):
        print("SMOKE_FORMAT_WARN: schema ok but zero parsed outputs", flush=True)
        raise SystemExit(2)
    print("SMOKE_PASSED", flush=True)


if __name__ == "__main__":
    main()
