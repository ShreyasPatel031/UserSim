"""Stack A: Gemini + native Google Computer Use + Playwright."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import (
    ComputerUse,
    Content,
    Environment,
    FinishReason,
    FunctionResponse,
    FunctionResponseBlob,
    GenerateContentConfig,
    Part,
    Tool,
)
from playwright.sync_api import sync_playwright

from auth import vertex_credentials
from capability import (
    BAKEOFF_LOCATION,
    BAKEOFF_MODEL,
    CAPABLE_AGENT_PREAMBLE,
    MAX_ACTIONS,
    OUT_DIR,
    USER_AGENT,
    VIEWPORT,
    cost_usd,
)
from capability.judge import judge_task
from config import GCP_PROJECT


def _nx(x: int, w: int) -> int:
    return int(x / 1000 * w)


def _ny(y: int, h: int) -> int:
    return int(y / 1000 * h)


def _safety_policy(name: str, args: dict) -> str:
    """Unattended bakeoff policy for require_confirmation.

    CAPTCHA/login/payment → deny (BLOCKED). Cookie/consent banners → auto-approve.
    """
    decision = (args.get("safety_decision") or {}) if isinstance(args, dict) else {}
    if not isinstance(decision, dict):
        return "continue"
    if decision.get("decision") != "require_confirmation":
        return "continue"
    expl = (decision.get("explanation") or "").lower()
    deny_keys = ("captcha", "robot", "verify you", "unusual traffic", "sign in", "log in", "password", "payment", "checkout", "purchase")
    if any(k in expl for k in deny_keys):
        return "deny"
    return "auto_approve"


def _execute(page, fc, sw: int, sh: int) -> dict[str, Any]:
    name = fc.name
    args = dict(fc.args or {})
    safety = _safety_policy(name, args)
    if safety == "deny":
        return {"name": name, "result": "user_denied", "safety_acknowledged": False, "args": args}

    try:
        if name == "open_web_browser":
            result = "success"
        elif name == "navigate":
            page.goto(args["url"], wait_until="domcontentloaded", timeout=25000)
            result = "success"
        elif name == "click_at":
            page.mouse.click(_nx(int(args["x"]), sw), _ny(int(args["y"]), sh))
            result = "success"
        elif name == "hover_at":
            page.mouse.move(_nx(int(args["x"]), sw), _ny(int(args["y"]), sh))
            result = "success"
        elif name == "type_text_at":
            x, y = _nx(int(args["x"]), sw), _ny(int(args["y"]), sh)
            page.mouse.click(x, y)
            time.sleep(0.1)
            if args.get("clear_before_typing", True):
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
            page.keyboard.type(str(args.get("text") or ""), delay=15)
            if args.get("press_enter", False):
                page.keyboard.press("Enter")
            result = "success"
        elif name == "key_combination":
            keys = args.get("keys") or args.get("key") or ""
            if isinstance(keys, list):
                page.keyboard.press("+".join(keys))
            else:
                page.keyboard.press(str(keys))
            result = "success"
        elif name == "scroll_document":
            direction = str(args.get("direction") or "down").lower()
            delta = 600 if direction in {"down", "right"} else -600
            if direction in {"down", "up"}:
                page.mouse.wheel(0, delta)
            else:
                page.mouse.wheel(delta, 0)
            result = "success"
        elif name == "scroll_at":
            page.mouse.move(_nx(int(args["x"]), sw), _ny(int(args["y"]), sh))
            magnitude = int(args.get("magnitude") or 800)
            direction = str(args.get("direction") or "down").lower()
            dy = magnitude if direction == "down" else (-magnitude if direction == "up" else 0)
            dx = magnitude if direction == "right" else (-magnitude if direction == "left" else 0)
            page.mouse.wheel(dx, dy)
            result = "success"
        elif name == "wait_5_seconds":
            time.sleep(5)
            result = "success"
        elif name == "go_back":
            page.go_back(wait_until="domcontentloaded", timeout=15000)
            result = "success"
        elif name == "go_forward":
            page.go_forward(wait_until="domcontentloaded", timeout=15000)
            result = "success"
        elif name == "search":
            # Computer Use search action: typically type into address/search
            page.goto(f"https://www.google.com/search?q={args.get('query','')}", wait_until="domcontentloaded")
            result = "success"
        else:
            result = f"unknown_function:{name}"
        page.wait_for_timeout(700)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        return {
            "name": name,
            "result": result,
            "safety_acknowledged": safety == "auto_approve",
            "args": {k: args[k] for k in args if k != "safety_decision"},
            "safety": safety,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "result": f"error:{exc}"[:300],
            "safety_acknowledged": safety == "auto_approve",
            "args": args,
            "safety": safety,
        }


def run_native_cu(
    task: dict,
    model: str = BAKEOFF_MODEL,
    max_actions: int = MAX_ACTIONS,
    run_dir: Path | None = None,
) -> dict:
    run_id = f"cu_{task['eval_index']}_{uuid.uuid4().hex[:8]}"
    run_dir = run_dir or (OUT_DIR / "traces" / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=BAKEOFF_LOCATION,
        credentials=vertex_credentials(),
    )
    sw, sh = VIEWPORT["width"], VIEWPORT["height"]
    config = GenerateContentConfig(
        tools=[
            Tool(
                computer_use=ComputerUse(
                    environment=Environment.ENVIRONMENT_BROWSER,
                    excluded_predefined_functions=["drag_and_drop"],
                )
            )
        ],
        temperature=0,
    )

    prompt = (
        f"{CAPABLE_AGENT_PREAMBLE}\n\n"
        f"Task: {task['task']}\n"
        f"Start URL (already open): {task['start_url']}\n"
        f"You may take at most {max_actions} UI actions."
    )

    actions: list[dict] = []
    prompt_tokens = output_tokens = 0
    stop_reason = None
    failure_category = None
    blocked = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, user_agent=USER_AGENT)
        page = context.new_page()
        try:
            page.goto(task["start_url"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
        except Exception as exc:  # noqa: BLE001
            browser.close()
            return {
                "run_id": run_id,
                "task_id": task["task_id"],
                "task": task["task"],
                "website": task["website"],
                "model": model,
                "harness": "native_computer_use",
                "observation_mode": "screenshot_computer_use",
                "start_url": task["start_url"],
                "actions": [],
                "num_actions": 0,
                "stop_reason": f"navigation_error:{exc}"[:200],
                "success": False,
                "status": "BLOCKED",
                "failure_category": "BLOCKED",
                "final_url": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        shot = page.screenshot(type="png")
        (run_dir / "step0.png").write_bytes(shot)
        contents: list[Content] = [
            Content(
                role="user",
                parts=[
                    Part(text=prompt),
                    Part.from_bytes(data=shot, mime_type="image/png"),
                ],
            )
        ]

        action_count = 0
        for turn in range(max_actions + 3):
            if action_count >= max_actions:
                stop_reason = "max_actions"
                break
            resp = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            usage = resp.usage_metadata
            prompt_tokens += int(getattr(usage, "prompt_token_count", 0) or 0)
            output_tokens += int(getattr(usage, "candidates_token_count", 0) or 0)

            if not resp.candidates:
                stop_reason = "no_candidates"
                failure_category = "HARNESS"
                break
            cand = resp.candidates[0]
            if cand.finish_reason == FinishReason.SAFETY:
                stop_reason = "model_safety"
                failure_category = "BLOCKED"
                blocked = True
                break

            contents.append(cand.content)
            fcs = [
                part.function_call
                for part in (cand.content.parts or [])
                if getattr(part, "function_call", None)
            ]
            thoughts = [
                part.text
                for part in (cand.content.parts or [])
                if getattr(part, "text", None)
            ]

            if not fcs:
                stop_reason = "model_finished"
                (run_dir / "final_thought.txt").write_text("\n".join(thoughts))
                break

            fr_parts = []
            for fc in fcs:
                if action_count >= max_actions:
                    break
                exec_res = _execute(page, fc, sw, sh)
                action_count += 1
                step_shot = page.screenshot(type="png")
                (run_dir / f"step{action_count}.png").write_bytes(step_shot)
                actions.append(
                    {
                        "i": action_count,
                        "name": exec_res["name"],
                        "args": exec_res.get("args"),
                        "result": exec_res["result"],
                        "safety": exec_res.get("safety"),
                        "url": page.url,
                        "thought": " ".join(thoughts)[:500] if thoughts else None,
                    }
                )
                if exec_res["result"] == "user_denied":
                    blocked = True
                    failure_category = "BLOCKED"
                    stop_reason = "safety_denied"
                payload: dict[str, Any] = {"url": page.url}
                if exec_res["result"] == "user_denied":
                    payload["error"] = "user_denied"
                elif exec_res.get("safety_acknowledged"):
                    payload["safety_acknowledgement"] = True
                if str(exec_res["result"]).startswith("error:"):
                    payload["error"] = exec_res["result"]
                fr_parts.append(
                    Part(
                        function_response=FunctionResponse(
                            name=fc.name,
                            response=payload,
                            parts=[
                                Part(
                                    inline_data=FunctionResponseBlob(
                                        mime_type="image/png", data=step_shot
                                    )
                                )
                            ],
                        )
                    )
                )
            contents.append(Content(role="user", parts=fr_parts))
            if blocked:
                break

        final_url = page.url
        try:
            end_title = page.title()
        except Exception:
            end_title = ""
        final_shot = page.screenshot(type="png")
        (run_dir / "final.png").write_bytes(final_shot)
        browser.close()

    summary = "\n".join(
        f"{a['i']}. {a['name']} {a.get('args')} -> {a['result']} @ {a['url']}"
        for a in actions
    )
    judgment = judge_task(task["task"], final_url, summary, final_shot, end_title)
    prompt_tokens += judgment.get("prompt_tokens", 0)
    output_tokens += judgment.get("output_tokens", 0)
    status = judgment["status"]
    success = status == "SUCCESS"

    if not success and not failure_category:
        # coarse auto-tag; refined later in diagnosis
        if status == "BLOCKED":
            failure_category = "BLOCKED"
        elif status == "SITE_CHANGED":
            failure_category = "SITE_CHANGED"
        elif stop_reason == "max_actions":
            failure_category = "PLANNING"
        elif stop_reason == "model_finished":
            failure_category = "PREMATURE_STOP"
        else:
            failure_category = "MODEL_REASONING"

    out = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task["eval_index"],
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "native_computer_use",
        "observation_mode": "screenshot_computer_use",
        "start_url": task["start_url"],
        "actions": actions,
        "num_actions": len(actions),
        "stop_reason": stop_reason,
        "success": success,
        "status": status,
        "judge_reason": judgment.get("reason"),
        "judge_evidence": judgment.get("evidence"),
        "failure_category": None if success else failure_category,
        "final_url": final_url,
        "final_title": end_title,
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost_usd(model, prompt_tokens, output_tokens)
        + float(judgment.get("estimated_cost_usd") or 0),
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "run.json").write_text(
        __import__("json").dumps(out, indent=2, default=str)
    )
    return out
