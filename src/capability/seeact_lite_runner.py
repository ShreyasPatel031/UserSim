"""Lightweight SeeAct-style two-stage harness on Playwright + Vertex.

Stage 1 (generate): choose next action from numbered interactive elements.
Stage 2 (ground): execute via Playwright click/type by index.

No SeeAct PyPI install — keeps browser-use deps intact.
Same task dict + result shape as browser_use_runner for harness bakeoff.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from google import genai
from google.genai import types
from playwright.async_api import async_playwright

from auth import vertex_credentials
from capability import (
    BAKEOFF_MODEL,
    CAPABLE_AGENT_PREAMBLE,
    MAX_ACTIONS,
    OUT_DIR,
    USER_AGENT,
    VIEWPORT,
    cost_usd,
    location_for,
)
from capability.judge import judge_task
from config import GCP_PROJECT

GENERATE_SYSTEM = """You are a web agent. Given a task and numbered interactive elements, output ONE next action as JSON only:
{"action":"CLICK"|"TYPE"|"SELECT"|"PRESS_ENTER"|"SCROLL"|"DONE"|"FAIL",
 "element_index": <int or null>,
 "text": "<typed text or null>",
 "reason":"<short>"}

Rules:
- element_index must refer to an element in the list (or null for SCROLL/DONE/FAIL/PRESS_ENTER).
- Prefer search boxes and filters matching the task.
- DONE only when the page clearly shows the requested result.
- FAIL only if blocked (CAPTCHA/login wall) or impossible.
"""


def _client(model: str, location: str) -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=location,
        credentials=vertex_credentials(),
    )


def _parse_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"action": "FAIL", "reason": f"bad_json:{raw[:120]}"}


def _generate(
    client: genai.Client, model: str, prompt: str
) -> tuple[dict[str, Any], int, int]:
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=400,
            response_mime_type="application/json",
        ),
    )
    usage = resp.usage_metadata
    pt = int(getattr(usage, "prompt_token_count", 0) or 0)
    ot = int(getattr(usage, "candidates_token_count", 0) or 0)
    return _parse_json(resp.text or "{}"), pt, ot


async def _list_elements(page, limit: int = 40) -> list[dict[str, Any]]:
    return await page.evaluate(
        """(limit) => {
          const out = [];
          const sel = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="option"]';
          for (const el of document.querySelectorAll(sel)) {
            if (out.length >= limit) break;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const style = window.getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') continue;
            const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || '').trim().slice(0, 80);
            out.push({
              tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              text,
              href: (el.getAttribute('href') || '').slice(0, 120),
            });
          }
          return out;
        }""",
        limit,
    )


def _format_elements(elements: list[dict[str, Any]]) -> str:
    lines = []
    for i, e in enumerate(elements):
        bits = [f"[{i}]", e.get("tag", ""), e.get("type", ""), e.get("text", "")]
        if e.get("href"):
            bits.append(f"href={e['href'][:60]}")
        lines.append(" ".join(x for x in bits if x))
    return "\n".join(lines) if lines else "(no interactive elements)"


async def _click_index(page, idx: int) -> bool:
    return await page.evaluate(
        """(idx) => {
          const sel = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="option"]';
          const els = [];
          for (const el of document.querySelectorAll(sel)) {
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const style = window.getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') continue;
            els.push(el);
          }
          if (idx < 0 || idx >= els.length) return false;
          els[idx].click();
          return true;
        }""",
        idx,
    )


async def _type_index(page, idx: int, text: str) -> bool:
    return await page.evaluate(
        """([idx, text]) => {
          const sel = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="option"]';
          const els = [];
          for (const el of document.querySelectorAll(sel)) {
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const style = window.getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') continue;
            els.push(el);
          }
          if (idx < 0 || idx >= els.length) return false;
          const el = els[idx];
          el.focus();
          if ('value' in el) {
            el.value = text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          }
          return true;
        }""",
        [idx, text],
    )


async def _run_async(
    task: dict, model: str, max_actions: int, run_dir: Path, location: str | None = None
) -> dict:
    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    loc = location or location_for(model)
    client = _client(model, loc)

    actions: list[dict] = []
    prompt_tokens = output_tokens = 0
    final_url = task["start_url"]
    end_title = ""
    screenshot: bytes | None = None
    is_done = False
    stop_reason = "unknown"
    harness_error: str | None = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=VIEWPORT, user_agent=USER_AGENT
            )
            page = await context.new_page()
            await page.goto(task["start_url"], wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(1500)

            for step in range(max_actions):
                url = page.url
                title = await page.title()
                elements = await _list_elements(page)
                el_text = _format_elements(elements)
                prompt = (
                    f"{GENERATE_SYSTEM}\n\n"
                    f"{CAPABLE_AGENT_PREAMBLE}\n\n"
                    f"TASK: {task['task']}\n"
                    f"URL: {url}\n"
                    f"TITLE: {title}\n"
                    f"ELEMENTS:\n{el_text}\n"
                )
                decision, pt, ot = await asyncio.to_thread(
                    _generate, client, model, prompt
                )
                prompt_tokens += pt
                output_tokens += ot

                action = str(decision.get("action", "FAIL")).upper()
                idx = decision.get("element_index")
                text = decision.get("text") or ""
                actions.append(
                    {
                        "i": step + 1,
                        "action": decision,
                        "result": None,
                        "url": url,
                    }
                )

                if action == "DONE":
                    is_done = True
                    stop_reason = "agent_done"
                    break
                if action == "FAIL":
                    stop_reason = f"model_fail:{decision.get('reason', '')}"[:200]
                    harness_error = stop_reason
                    break
                if action == "SCROLL":
                    await page.mouse.wheel(0, 800)
                    await page.wait_for_timeout(500)
                    continue
                if action == "PRESS_ENTER":
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)
                    continue

                if idx is None:
                    if "apartments.com" in url and text:
                        await page.goto(
                            f"https://www.apartments.com/{quote_plus(str(text))}/",
                            wait_until="domcontentloaded",
                            timeout=60_000,
                        )
                        continue
                    stop_reason = "missing_element_index"
                    harness_error = stop_reason
                    break

                try:
                    idx_i = int(idx)
                except (TypeError, ValueError):
                    stop_reason = f"bad_index:{idx}"
                    harness_error = stop_reason
                    break

                if action == "CLICK":
                    ok = await _click_index(page, idx_i)
                    if not ok:
                        stop_reason = f"click_miss:{idx_i}"
                        harness_error = stop_reason
                        break
                    await page.wait_for_timeout(1500)
                elif action in ("TYPE", "SELECT"):
                    ok = await _type_index(page, idx_i, str(text))
                    if not ok:
                        stop_reason = f"type_miss:{idx_i}"
                        harness_error = stop_reason
                        break
                    await page.wait_for_timeout(400)
                    if action == "TYPE":
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1500)
                else:
                    stop_reason = f"unknown_action:{action}"
                    harness_error = stop_reason
                    break
            else:
                stop_reason = "max_actions"

            final_url = page.url
            end_title = await page.title()
            try:
                screenshot = await page.screenshot(type="png")
                (run_dir / "final.png").write_bytes(screenshot)
            except Exception as exc:  # noqa: BLE001
                (run_dir / "screenshot_error.txt").write_text(str(exc)[:400])
            await browser.close()
    except Exception as e:  # noqa: BLE001
        harness_error = f"{type(e).__name__}: {e}"
        stop_reason = f"exception:{harness_error}"[:200]

    summary_lines = []
    for a in actions:
        summary_lines.append(f"{a['i']}. {a.get('action')} @ {a.get('url')}")
    if is_done:
        summary_lines.append("(agent signaled done)")
    if harness_error:
        summary_lines.append(f"(harness: {harness_error})")

    judgment = judge_task(
        task["task"],
        final_url or task["start_url"],
        "\n".join(summary_lines),
        screenshot,
        end_title,
    )
    prompt_tokens += judgment.get("prompt_tokens", 0)
    output_tokens += judgment.get("output_tokens", 0)
    status = judgment["status"]
    success = status == "SUCCESS"

    failure_category = None
    if not success:
        if status in {"BLOCKED", "SITE_CHANGED"}:
            failure_category = status
        elif harness_error:
            failure_category = "HARNESS"
        elif len(actions) >= max_actions:
            failure_category = "PLANNING"
        elif is_done:
            failure_category = "PREMATURE_STOP"
        else:
            failure_category = "MODEL_REASONING"

    out = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "eval_index": task.get("eval_index"),
        "task": task["task"],
        "website": task["website"],
        "model": model,
        "harness": "seeact_lite",
        "observation_mode": "seeact_lite_axtree",
        "start_url": task["start_url"],
        "actions": actions,
        "num_actions": len(actions),
        "stop_reason": stop_reason,
        "success": success,
        "status": status,
        "judge_reason": judgment.get("reason"),
        "judge_evidence": judgment.get("evidence"),
        "failure_category": failure_category,
        "final_url": final_url,
        "final_title": end_title,
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost_usd(model, prompt_tokens, output_tokens)
        + float(judgment.get("estimated_cost_usd") or 0),
        "trace_dir": str(run_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "run.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def run_seeact_lite(
    task: dict,
    model: str = BAKEOFF_MODEL,
    max_actions: int = MAX_ACTIONS,
    run_dir: Path | None = None,
    location: str | None = None,
) -> dict:
    run_dir = run_dir or (
        OUT_DIR / "traces" / f"sa_{task.get('eval_index', 'x')}_{uuid.uuid4().hex[:8]}"
    )
    return asyncio.run(_run_async(task, model, max_actions, run_dir, location=location))
