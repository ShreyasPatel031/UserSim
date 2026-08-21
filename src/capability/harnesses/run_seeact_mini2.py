"""Run the real upstream SeeAct agent on Mini-2, backed by Vertex gemini-3.6-flash.

Runs inside .venv-seeact (see setup_seeact.sh) — NOT the main venv.

Only three upstream behaviours are adapted, all at the boundary:
  1. engine_factory allow-lists a fixed set of model names -> supply a Vertex engine.
  2. GeminiEngine passes a local file path as an image_url -> send base64 instead.
  3. normal_launch_async hardcodes headless=False -> no display in this container.

The agent loop, prompts, SoM grounding and action execution are upstream SeeAct.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import litellm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS", str(ROOT / "secrets" / "vertex_adc.json")
)

GCP_PROJECT = "project-amer-scs-sandbox"
VERTEX_LOCATION = "global"  # 3.6 Flash is not served from us-central1

litellm.suppress_debug_info = True

from seeact import agent as seeact_agent  # noqa: E402
from seeact.agent import SeeActAgent  # noqa: E402
from seeact.demo_utils.inference_engine import Engine  # noqa: E402


class VertexGeminiEngine(Engine):
    """SeeAct engine backed by Vertex AI through litellm.

    Mirrors upstream OpenAIEngine.generate: same two-turn prompt shape, same
    return type. Only the transport and the image encoding differ.
    """

    def __init__(self, model: str, temperature: float = 0.0, **kwargs) -> None:
        super().__init__(model=model, temperature=temperature, **kwargs)
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    def generate(
        self,
        prompt: list | None = None,
        max_new_tokens: int = 4096,
        temperature: float | None = None,
        model: str | None = None,
        image_path: str | None = None,
        ouput_0=None,
        turn_number: int = 0,
        **kwargs,
    ) -> str:
        prompt0, prompt1, prompt2 = prompt
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        image_part = {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
        }

        if turn_number == 0:
            messages = [
                {"role": "system", "content": prompt0},
                {"role": "user", "content": [{"type": "text", "text": prompt1}, image_part]},
            ]
        else:
            messages = [
                {"role": "system", "content": prompt0},
                {"role": "user", "content": [{"type": "text", "text": prompt1}, image_part]},
                {"role": "assistant", "content": f"\n\n{ouput_0}"},
                {"role": "user", "content": prompt2},
            ]

        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = litellm.completion(
                    model=f"vertex_ai/{self.model}",
                    messages=messages,
                    max_tokens=max_new_tokens or 4096,
                    temperature=self.temperature if temperature is None else temperature,
                    vertex_project=GCP_PROJECT,
                    vertex_location=VERTEX_LOCATION,
                    **kwargs,
                )
                self.calls += 1
                usage = getattr(resp, "usage", None)
                if usage:
                    self.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                    self.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
                if not resp.choices:
                    # All budget went to thinking tokens; retry with more room.
                    max_new_tokens = min(int(max_new_tokens * 2), 16384)
                    continue
                return resp.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Vertex call failed after retries: {last_err}")


async def _headless_launch(playwright, headless=True, args=None):
    return await playwright.chromium.launch(
        traces_dir=None, headless=True, args=args or []
    )


def _patch_upstream(engine: VertexGeminiEngine) -> None:
    seeact_agent.engine_factory = lambda *a, **kw: engine
    seeact_agent.normal_launch_async = _headless_launch


async def run_one(task: dict, model: str, max_ops: int, out_dir: Path) -> dict:
    engine = VertexGeminiEngine(model=model)
    _patch_upstream(engine)

    run_dir = out_dir / f"seeact_{task['eval_index']}"
    run_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    agent = SeeActAgent(
        model=model,
        save_file_dir=str(run_dir),
        default_task=task["task"],
        default_website=task["start_url"],
        headless=True,
        grounding_strategy="text_choice_som",
        max_auto_op=max_ops,
        max_continuous_no_op=5,
        temperature=0.0,
    )
    agent.engine = engine

    error = None
    final_url = task["start_url"]
    try:
        await agent.start()
        while not agent.complete_flag and agent.time_step < max_ops:
            prediction = await agent.predict()
            if prediction is None:
                break
            await agent.execute(prediction)
        try:
            final_url = agent.page.url
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        try:
            await agent.stop()
        except Exception:  # noqa: BLE001
            pass

    screenshots = sorted((run_dir).rglob("screen_*.png"))
    return {
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "start_url": task["start_url"],
        "model": model,
        "harness": "seeact_upstream",
        "observation_mode": "seeact_som_screenshot",
        "num_actions": agent.time_step,
        "taken_actions": list(agent.taken_actions),
        "complete_flag": bool(agent.complete_flag),
        "stop_reason": "terminate" if agent.complete_flag else "max_ops",
        "final_url": final_url,
        "error": error,
        "input_tokens": engine.prompt_tokens,
        "output_tokens": engine.completion_tokens,
        "llm_calls": engine.calls,
        "elapsed_s": round(time.time() - started, 2),
        "last_screenshot": str(screenshots[-1]) if screenshots else None,
        "run_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Upstream SeeAct on Mini-2 via Vertex")
    ap.add_argument("--model", default="gemini-3.6-flash")
    ap.add_argument("--max-ops", type=int, default=33)
    ap.add_argument("--out", default=str(ROOT / "results" / "capability" / "seeact_mini2_raw.json"))
    ap.add_argument("--task-ids", nargs="*", default=None)
    args = ap.parse_args()

    from capability.mini2_tasks import MINI2_TASKS

    tasks = []
    for i, t in enumerate(MINI2_TASKS):
        tasks.append(
            {
                "task_id": t["task_id"],
                "eval_index": f"mini2_{i}",
                "website": t["website"],
                "task": t["task"],
                "start_url": t["start_url"],
            }
        )
    if args.task_ids:
        want = set(args.task_ids)
        tasks = [t for t in tasks if t["task_id"] in want]

    out_path = Path(args.out)
    trace_dir = out_path.parent / "traces"
    runs = []
    for t in tasks:
        print(f"START seeact | {t['website']} | {t['eval_index']}", flush=True)
        r = asyncio.run(run_one(t, args.model, args.max_ops, trace_dir))
        print(
            f"DONE  seeact | {t['website']} | {t['eval_index']} | steps={r['num_actions']} "
            f"stop={r['stop_reason']} err={r['error']}",
            flush=True,
        )
        runs.append(r)

    out_path.write_text(json.dumps({"model": args.model, "runs": runs}, indent=2, default=str))
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
