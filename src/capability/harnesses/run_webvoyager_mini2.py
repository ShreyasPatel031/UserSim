"""Run upstream WebVoyager on Mini-2 against Vertex gemini-3.6-flash.

WebVoyager talks plain OpenAI, so it needs no patching at all: a litellm proxy
(see litellm_vertex_proxy.yaml) exposes Vertex on an OpenAI-compatible endpoint
and OPENAI_BASE_URL points the harness at it.

Prereqs:
  1. proxy running on 127.0.0.1:4000
  2. vendor/WebVoyager cloned, .venv-webvoyager built (see setup_webvoyager.sh)
  3. a `google-chrome` on PATH for Selenium
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

VENDOR = ROOT / "vendor" / "WebVoyager"
VENV_PY = ROOT / ".venv-webvoyager" / "bin" / "python"
PROXY_BASE = "http://127.0.0.1:4000/v1"
PROXY_KEY = "sk-usersim-local"


def write_task_file(path: Path) -> list[dict]:
    from capability.mini2_tasks import MINI2_TASKS

    tasks = []
    for i, t in enumerate(MINI2_TASKS):
        tasks.append(
            {
                "web_name": t["website"],
                "id": f"mini2--{i}",
                "ques": t["task"],
                "web": t["start_url"],
                "task_id": t["task_id"],
            }
        )
    path.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
    return tasks


def main() -> None:
    ap = argparse.ArgumentParser(description="Upstream WebVoyager on Mini-2")
    ap.add_argument("--model", default="gemini-3.6-flash")
    ap.add_argument("--max-iter", type=int, default=33)
    ap.add_argument("--out-dir", default=str(ROOT / "results" / "capability" / "webvoyager"))
    args = ap.parse_args()

    if not VENDOR.exists():
        raise SystemExit(f"Missing {VENDOR}; run setup_webvoyager.sh first")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    task_file = out_dir / "mini2_tasks.jsonl"
    tasks = write_task_file(task_file)
    print(f"Wrote {len(tasks)} tasks to {task_file}", flush=True)

    env = dict(os.environ)
    env["OPENAI_BASE_URL"] = PROXY_BASE
    env["OPENAI_API_KEY"] = PROXY_KEY

    cmd = [
        str(VENV_PY),
        "run.py",
        "--test_file", str(task_file),
        "--api_key", PROXY_KEY,
        "--api_model", args.model,
        "--max_iter", str(args.max_iter),
        "--max_attached_imgs", "3",
        "--temperature", "0",
        "--seed", "42",
        "--headless",
        "--output_dir", str(out_dir / "runs"),
        "--download_dir", str(out_dir / "downloads"),
    ]
    print("RUN:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(VENDOR), env=env)
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
