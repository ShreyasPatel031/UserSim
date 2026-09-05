#!/usr/bin/env python3
"""Serve Be.FM-1.5-4B and run BehaviorBench tasks on Colab L4."""
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


def sh(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)


def install() -> None:
    sh(f"{sys.executable} -m pip install -q -U pip")
    sh(
        f"{sys.executable} -m pip install -q "
        "torch transformers 'peft>=0.17' 'torchao>=0.16' accelerate fastapi uvicorn "
        "openai datasets pyyaml python-dotenv numpy scipy scikit-learn "
        "huggingface_hub"
    )
    # Colab sometimes ships an old torchao that peft rejects
    sh(f"{sys.executable} -m pip install -q -U 'torchao>=0.16'")
    if not BB_REPO.exists():
        sh(f"git clone --depth 1 https://github.com/umich-foreseer/behaviorbench_eval.git {BB_REPO}")
    sh(f"{sys.executable} -m pip install -q -e {BB_REPO}")


def write_server() -> Path:
    server = ROOT / "befm_server.py"
    server.write_text(
        r'''
import os
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Any
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

ADAPTER = Path(os.environ.get("BEFM_ADAPTER", "/content/fm_baselines/models/BeFM1.5-4B"))
BASE = "Qwen/Qwen3-4B-Instruct-2507"

print("Loading base", BASE, flush=True)
tok = AutoTokenizer.from_pretrained(str(ADAPTER), trust_remote_code=True)
base = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
)
print("Loading adapter", ADAPTER, flush=True)
model = PeftModel.from_pretrained(base, str(ADAPTER))
model.eval()
print("READY", flush=True)

app = FastAPI()

class Msg(BaseModel):
    role: str
    content: str

class ChatReq(BaseModel):
    model: str = "befm-1.5-4b"
    messages: List[Msg]
    max_tokens: Optional[int] = 64
    temperature: Optional[float] = 0.6
    top_p: Optional[float] = 0.95
    top_k: Optional[int] = 20

@app.get("/v1/models")
def models():
    return {"data": [{"id": "befm-1.5-4b", "object": "model"}]}

@app.post("/v1/chat/completions")
def chat(req: ChatReq):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(prompt, return_tensors="pt").to(model.device)
    gen_kwargs = dict(
        max_new_tokens=req.max_tokens or 64,
        do_sample=True,
        temperature=req.temperature if req.temperature is not None else 0.6,
        top_p=req.top_p if req.top_p is not None else 0.95,
    )
    if req.top_k:
        gen_kwargs["top_k"] = req.top_k
    with torch.no_grad():
        out = model.generate(**inputs, **gen_kwargs)
    text = tok.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
    return {
        "id": "chatcmpl-befm",
        "object": "chat.completion",
        "model": "befm-1.5-4b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": int(inputs.input_ids.shape[1]), "completion_tokens": 0, "total_tokens": 0},
    }
'''
    )
    return server


def start_server(server: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["BEFM_ADAPTER"] = str(ADAPTER)
    # run uvicorn
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "befm_server:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            print("[server]", line.rstrip(), flush=True)

    threading.Thread(target=pump, daemon=True).start()

    # wait until healthy
    import urllib.request

    deadline = time.time() + 900
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early with {proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2)
            print("server healthy", flush=True)
            return proc
        except Exception:
            time.sleep(3)
    raise TimeoutError("server did not become healthy")


def symlink_data() -> None:
    # behaviorbench expects data/ under repo
    link = BB_REPO / "data"
    if link.exists() or link.is_symlink():
        if link.is_symlink() or link.is_file():
            link.unlink()
        else:
            # leave existing dir
            return
    link.symlink_to(BB_DATA)


def run_tasks(tasks: list[str]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    for task in tasks:
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
            f"--max-tokens 64 --concurrency 1 "
            f"--output-dir {out}"
        )
        # survey/game tasks may need more tokens; leave default override via env later
        print(f"=== TASK {task} ===", flush=True)
        sh(cmd, check=False)


def main() -> None:
    assert ADAPTER.exists(), f"missing adapter at {ADAPTER}"
    assert BB_DATA.exists(), f"missing BehaviorBench at {BB_DATA}"
    install()
    symlink_data()
    server = write_server()
    print("wrote", server, flush=True)
    proc = start_server(server)

    # Start with core distributional/individual tasks that define the boards.
    # Full 12-capability suite can be expanded after smoke.
    tasks = [
        "pers_score_pred",
        "surv_resp_pred",
        "seq_surv_resp",
        "missing_surv_resp",
        "demo_pred_age",
        "acrossdim_pers_score",
        "game_behavior_dictator",
        "strategic_gameplay_guessing",
    ]
    try:
        run_tasks(tasks)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()

    # summarize outputs
    summary = {}
    for p in RESULTS.rglob("*.json"):
        try:
            summary[str(p.relative_to(RESULTS))] = json.loads(p.read_text())[:1] if False else "ok"
        except Exception:
            pass
    (RESULTS / "DONE.json").write_text(json.dumps({"tasks": tasks, "files": [str(p) for p in RESULTS.rglob('*')]}, indent=2))
    print("DONE", RESULTS, flush=True)
    for p in sorted(RESULTS.rglob("*")):
        if p.is_file():
            print(" ", p, p.stat().st_size, flush=True)


if __name__ == "__main__":
    main()
