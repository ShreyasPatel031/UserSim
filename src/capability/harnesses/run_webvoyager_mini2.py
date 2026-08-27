"""Run upstream WebVoyager on Mini-2 against Vertex gemini-2.5-flash.

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

from capability import BAKEOFF_MODEL  # noqa: E402

VENDOR = ROOT / "vendor" / "WebVoyager"
VENV_PY = ROOT / ".venv-webvoyager" / "bin" / "python"
PROXY_BASE = "http://127.0.0.1:4000/v1"
PROXY_KEY = "sk-usersim-local"


def build_tasks() -> list[dict]:
    from capability.mini2_tasks import MINI2_TASKS

    return [
        {
            "web_name": t["website"],
            "id": f"mini2--{i}",
            "ques": t["task"],
            "web": t["start_url"],
            "task_id": t["task_id"],
        }
        for i, t in enumerate(MINI2_TASKS)
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Upstream WebVoyager on Mini-2")
    ap.add_argument("--model", default=BAKEOFF_MODEL)
    ap.add_argument("--max-iter", type=int, default=33)
    ap.add_argument("--out-dir", default=str(ROOT / "results" / "capability" / "webvoyager"))
    args = ap.parse_args()

    if not VENDOR.exists():
        raise SystemExit(f"Missing {VENDOR}; run setup_webvoyager.sh first")

    out_dir = Path(args.out_dir)
    download_dir = out_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["OPENAI_BASE_URL"] = PROXY_BASE
    env["OPENAI_API_KEY"] = PROXY_KEY

    # One process per task: upstream run.py lets a Selenium exception escape the
    # task loop, so a crash on one site would otherwise abort the rest.
    outcomes = []
    for task in build_tasks():
        task_file = out_dir / f"task_{task['id'].replace('--', '_')}.jsonl"
        task_file.write_text(json.dumps(task) + "\n")
        run_dir = out_dir / "runs" / task["id"].replace("--", "_")
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
            "--output_dir", str(run_dir),
            "--download_dir", str(download_dir),
        ]
        print(f"START webvoyager | {task['web_name']} | {task['id']}", flush=True)
        proc = subprocess.run(cmd, cwd=str(VENDOR), env=env)
        print(
            f"DONE  webvoyager | {task['web_name']} | {task['id']} | exit={proc.returncode}",
            flush=True,
        )
        outcomes.append(
            {
                "task_id": task["task_id"],
                "eval_index": task["id"],
                "website": task["web_name"],
                "task": task["ques"],
                "start_url": task["web"],
                "exit_code": proc.returncode,
                "run_dir": str(run_dir),
            }
        )

    manifest = out_dir / "mini2_outcomes.json"
    manifest.write_text(json.dumps({"model": args.model, "runs": outcomes}, indent=2))
    print(f"Wrote {manifest}", flush=True)


if __name__ == "__main__":
    main()
