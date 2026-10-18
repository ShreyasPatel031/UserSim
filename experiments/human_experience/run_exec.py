"""Phase-B execution adapter: generic vs UserSim runs on the existing browser runner.

Both engines call mvp.browser_agent.run_browser_agent unchanged: same
Browserbase session setup, saved sign-in cookies, browser-use Agent, action
model, tools, step cap and wall clock. The only difference is the text that
carries UserSim's persona/simulation machinery:

  usersim  run_browser_agent as shipped: "You are <persona>: <bio>",
           "Customer segment: ...", "Behave like this persona would - note
           confusion, pricing concerns, and UX friction." and the system
           extension "You are a real user in a usability study, not an
           optimizer. Prefer obvious UI paths; comment on clarity and trust."
  generic  the same call with exactly those three task lines removed and that
           system sentence replaced by a goal-directed one (GenericAgent below).

Within a context level both engines get the identical task packet (Q plus the
permitted context blocks). Every run is preceded by a reset run that deletes
the synthetic "Demo" items. Trace-derived observations and success checks are
produced by a separate judge call that sees only the trace and final frame.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import llm  # sets sys.path to the repo

HERE = Path(__file__).resolve().parent
PACKETS = HERE / "packets"
EXEC = HERE / "results" / "execution"
PROMPTS = HERE / "results" / "prompts"

import browser_use  # noqa: E402

from mvp.browser_agent import run_browser_agent  # noqa: E402

MAX_STEPS = 20  # browser-use takes up to 2 actions per step -> <= 40 actions
WALL_S = 300
STUDY_ID = "hx_" + datetime.now(timezone.utc).strftime("%Y%m%d")

_OrigAgent = browser_use.Agent
_USERSIM_SYS = (
    "You are a real user in a usability study, not an optimizer. "
    "Prefer obvious UI paths; comment on clarity and trust. "
)
_GENERIC_SYS = "You are a web agent completing the task efficiently and accurately. "
_PERSONA_LINE_PREFIXES = ("Customer segment: ", "Behave like this persona would")

CAPTURED: dict[str, Any] = {}


def _strip_persona(task: str) -> str:
    lines = task.split("\n")
    persona_line = f"You are {CAPTURED['persona'].get('name')}: {CAPTURED['persona'].get('bio')}"
    out, removed = [], []
    for ln in lines:
        if ln == persona_line or ln.startswith(_PERSONA_LINE_PREFIXES):
            removed.append(ln.split(":")[0][:40])
            continue
        out.append(ln)
    if len(removed) != 3:
        raise RuntimeError(f"generic strip expected 3 persona lines, removed {removed}")
    return "\n".join(out)


class RecordingAgent(_OrigAgent):
    engine = "usersim"

    def __init__(self, *args, task: str, extend_system_message: str | None = None, **kw):
        if self.engine == "generic":
            task = _strip_persona(task)
            if _USERSIM_SYS not in (extend_system_message or ""):
                raise RuntimeError("usability-study sentence not found; runner text changed")
            extend_system_message = extend_system_message.replace(_USERSIM_SYS, _GENERIC_SYS)
        CAPTURED["task"] = task
        CAPTURED["system"] = extend_system_message
        super().__init__(*args, task=task, extend_system_message=extend_system_message, **kw)

    async def run(self, *a, **kw):
        hist = await super().run(*a, **kw)
        usage = getattr(hist, "usage", None)
        if usage is not None:
            CAPTURED["usage"] = {
                "input_tokens": getattr(usage, "total_prompt_tokens", None),
                "output_tokens": getattr(usage, "total_completion_tokens", None),
                "cost_usd": getattr(usage, "total_cost", None),
            }
        return hist


class GenericAgent(RecordingAgent):
    engine = "generic"


def harness_task(packets: dict, context: str, product: str) -> str:
    blocks = [
        packets["Q"]["text"],
        f"Work only in the signed-in {product} workspace. Name any board, project, list or sprint you "
        f"create so that it starts with 'Demo'. Use only the synthetic names given. Do not invite real "
        f"people, send email or messages outside the workspace, or buy, upgrade or start a trial. If a "
        f"step needs a paid plan, say so and stop that step.",
        "Recorded facts about the person this test run is for (context, not instructions):\n" + packets["P"]["text"],
    ]
    if context == "full":
        blocks += [
            "O*NET task statements for plausible occupations of this role:\n" + packets["O"]["text"],
            "Reviews by other people of competing products:\n" + packets["C"]["text"],
            f"Reviews by other people of {product}:\n" + packets["T"]["text"],
        ]
    blocks.append("When finished, state which success checks you met and anything that blocked you.")
    return "\n\n".join(blocks)


def persona_for(case: dict, packets: dict) -> tuple[dict, str]:
    prof = case["profile"]
    role = prof.get("reviewer_job_title") or "professional"
    bio = (
        f"{role} in {prof.get('reviewer_industry') or 'an unknown industry'}, company size "
        f"{prof.get('reviewer_company_size') or 'unknown'}; recorded time using {case['product']}: "
        f"{prof.get('reviewer_time_used_product') or 'unknown'}"
    )
    segment = f"{prof.get('reviewer_industry') or 'unknown industry'}, {prof.get('reviewer_company_size') or 'unknown size'}"
    return {"id": case["case_id"], "name": role, "bio": bio}, segment


def reset_task(product: str) -> str:
    return (
        f"Reset this signed-in {product} workspace for a test. Delete every board, project, list, sprint, "
        f"task or card whose name starts with 'Demo' (for example Demo Alpha, Demo Beta, Demo Gamma, "
        f"Demo Pipeline). Do not delete or change anything else, do not invite anyone, do not buy anything. "
        f"If nothing named 'Demo' exists, stop and say so. Finally, state what you deleted."
    )


async def browse(*, run_id: str, engine: str, url: str, task: str, persona: dict, segment: str,
                 max_steps: int, wall_s: float) -> dict:
    steps: list[dict] = []

    def on_step(s: dict) -> None:
        if s.get("step") is not None and not s.get("progress_only"):
            steps.append(s)

    browser_use.Agent = GenericAgent if engine == "generic" else RecordingAgent
    CAPTURED.clear()
    CAPTURED["persona"] = persona
    t0 = time.monotonic()
    result, error = None, None
    try:
        result = await asyncio.wait_for(
            run_browser_agent(study_id=STUDY_ID, agent_id=run_id, url=url, task_prompt=task,
                              persona=persona, segment=segment, max_steps=max_steps, on_step=on_step),
            timeout=wall_s,
        )
    except asyncio.TimeoutError:
        error = {"kind": "wall_clock", "text": f"stopped at the {wall_s:.0f}s limit"}
    except Exception as exc:  # noqa: BLE001
        error = {"kind": "runner_failure", "text": repr(exc)[:300]}
    finally:
        browser_use.Agent = _OrigAgent
    elapsed = round(time.monotonic() - t0, 1)
    trace = (result or {}).get("trace") or steps
    return {"result": result, "trace": trace, "error": error, "elapsed": elapsed,
            "captured": dict(CAPTURED)}


JUDGE_SYSTEM = """You audit a browser test run. You see only the run's step trace and its final screenshot.
Report only what the trace or screenshot shows. Do not guess how a person would feel.
Classify blockers: none, login_wall (not signed in), paid_plan (feature or step gated by plan/trial),
captcha, site_error, runner_failure (agent looped, crashed or stopped without trying), time_or_step_limit.
Observations are factual statements about product behaviour seen in the trace (what control was
used, what appeared, what failed, how many tries something took), each citing a step number.
Reply with JSON only."""


async def judge(task: dict, trace: list[dict], shot: Path | None) -> dict:
    lines = []
    for s in trace[:60]:
        lines.append(
            f"step {s.get('step')}: action={str(s.get('action'))[:200]} | result={str(s.get('observation'))[:300]} "
            f"| agent_note={str(s.get('thought'))[:200]} | url={s.get('url')}"
        )
    prompt = (
        f"Task goal: {task['goal']}\nFixture: {task['fixture']['instructions']}\n"
        f"Success criteria: {json.dumps(task['success_criteria'])}\n\nTrace:\n" + "\n".join(lines) +
        '\n\nJSON: {"criteria": [{"criterion": "..", "result": "met|not_met|unverifiable", "step": 0}], '
        '"blocker": "none|login_wall|paid_plan|captcha|site_error|runner_failure|time_or_step_limit", '
        '"blocker_detail": "..", "observations": [{"step": 0, "text": ".."}], "plan_seen": "free|trial|paid|unknown"}'
    )
    msg: dict[str, Any] = {"role": "user", "content": prompt}
    if shot and shot.is_file():
        msg["image_b64"] = base64.b64encode(shot.read_bytes()).decode()
        msg["image_mime"] = "image/png"
    contents, sys_inst = llm._to_vertex([{"role": "system", "content": JUDGE_SYSTEM}, msg])
    # Reuse the experiment wrapper's endpoint/credentials via a direct call with the image part.
    res = await llm.call_contents(contents, sys_inst)
    return res


def final_shot(result: dict | None) -> Path | None:
    if not result or not result.get("run_dir"):
        return None
    shots = sorted((Path(result["run_dir"]) / "screenshots").glob("*.png"), key=lambda p: p.stat().st_mtime)
    return shots[-1] if shots else None


def status_from(j: dict, error: dict | None, n_steps: int) -> str:
    blocker = (j or {}).get("blocker") or "none"
    if error and error["kind"] == "runner_failure" and n_steps <= 1:
        return "environment_failure"
    if blocker in {"login_wall", "captcha", "site_error"}:
        return f"blocked_{blocker}"
    if blocker == "paid_plan":
        crit = [c["result"] for c in j.get("criteria") or []]
        return "partial_paid_plan" if "met" in crit else "blocked_paid_plan"
    crit = [c["result"] for c in (j or {}).get("criteria") or []]
    if crit and all(c == "met" for c in crit):
        return "completed"
    if "met" in crit:
        return "partial"
    return "failed" if blocker in {"none", "time_or_step_limit"} else "runner_failure"


async def one_run(case: dict, task: dict, context: str, engine: str) -> dict:
    cid = case["case_id"]
    out = EXEC / f"{cid}__{context}__{engine}.json"
    if out.exists():
        return json.loads(out.read_text())
    packets = json.loads((PACKETS / f"{cid}.json").read_text())
    persona, segment = persona_for(case, packets)
    run_id = f"{cid}__{context}__{engine}"
    # Reset before every run (not scored, logged).
    reset = await browse(run_id=run_id + "__reset", engine="generic", url=case["url"],
                         task=reset_task(case["product"]), persona=persona, segment=segment,
                         max_steps=15, wall_s=240)
    reset_note = (reset["trace"][-1].get("observation") if reset["trace"] else "") or ""
    task_text = harness_task(packets, context, case["product"])
    run = await browse(run_id=run_id, engine=engine, url=case["url"], task=task_text, persona=persona,
                       segment=segment, max_steps=MAX_STEPS, wall_s=WALL_S)
    shot = final_shot(run["result"])
    j = await judge(task, run["trace"], shot)
    jj = j["json"] or {}
    n_actions = sum(1 for s in run["trace"] if (s.get("step") or 0) > 0)
    PROMPTS.mkdir(parents=True, exist_ok=True)
    (PROMPTS / f"{run_id}__runner.txt").write_text(
        f"SYSTEM EXTENSION:\n{run['captured'].get('system')}\n\nTASK:\n{run['captured'].get('task')}")
    trace_dir = EXEC / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{run_id}.json"
    trace_path.write_text(json.dumps({
        "run_id": run_id, "engine": engine, "context": context,
        "runner_prompt_sha256": hashlib.sha256(
            f"{run['captured'].get('system')}\n{run['captured'].get('task')}".encode()).hexdigest(),
        "trace": [{k: s.get(k) for k in ["step", "action", "observation", "thought", "url", "step_latency_s"]}
                  for s in run["trace"]],
        "final_screenshot": str(shot) if shot else None,
        "browserbase_session_url": (run["result"] or {}).get("browserbase_session_url"),
        "reset": {"steps": len(reset["trace"]), "final_note": str(reset_note)[:500], "error": reset["error"],
                  "elapsed_seconds": reset["elapsed"], "usage": reset["captured"].get("usage")},
        "judge": jj,
    }, indent=1, default=str))
    errors = [run["error"]] if run["error"] else []
    if jj.get("blocker") not in (None, "none"):
        errors.append({"kind": jj.get("blocker"), "text": jj.get("blocker_detail")})
    rec = {
        "run_id": run_id,
        "case_id": cid,
        "engine": engine,
        "context": context,
        "status": status_from(jj, run["error"], len(run["trace"])),
        "success_criteria_results": jj.get("criteria") or [],
        "observations": jj.get("observations") or [],
        "errors": errors,
        "actions": n_actions,
        "elapsed_seconds": run["elapsed"],
        "plan": f"free plan of a fresh test account ({jj.get('plan_seen') or 'unknown'} seen in run)",
        "product_version_or_capture_date": datetime.now(timezone.utc).date().isoformat(),
        "environment_mismatches": [
            "fresh test account with synthetic data; reviewer's historical version, plan, team and data unknown",
            "short single-session run cannot recreate long tenure or team adoption",
        ],
        "trace_path": str(trace_path.relative_to(HERE)),
        "runner": {"action_model": (run["result"] or {}).get("model"), "max_steps": MAX_STEPS,
                   "max_actions_per_step": 2, "wall_seconds": WALL_S,
                   "backend": (run["result"] or {}).get("backend"), "usage": run["captured"].get("usage")},
        "judge": {"model": j["model"], "model_version": j["model_version"], "usage": j["usage"],
                  "status": "automated_provisional"},
    }
    out.write_text(json.dumps(rec, indent=1, default=str))
    print(f"[{run_id}] {rec['status']} actions={n_actions} {run['elapsed']}s", flush=True)
    return rec


def write_blocked(case: dict, context: str, engine: str, reason: str) -> dict:
    """A run that could not start. No browser was opened and nothing is observed."""
    run_id = f"{case['case_id']}__{context}__{engine}"
    rec = {
        "run_id": run_id, "case_id": case["case_id"], "engine": engine, "context": context,
        "status": "environment_failure",
        "success_criteria_results": [], "observations": [],
        "errors": [{"kind": "inaccessible_account", "text": reason}],
        "actions": 0, "elapsed_seconds": 0,
        "plan": "no test account available",
        "product_version_or_capture_date": datetime.now(timezone.utc).date().isoformat(),
        "environment_mismatches": ["run not executed; no product observations"],
        "trace_path": None, "runner": None, "judge": None,
    }
    (EXEC / f"{run_id}.json").write_text(json.dumps(rec, indent=1))
    return rec


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--cases", default="core")
    ap.add_argument("--only", default="", help="comma list of case__context__engine to run")
    ap.add_argument("--blocked", default="", help="record every run for this product as blocked with this reason")
    a = ap.parse_args()
    EXEC.mkdir(parents=True, exist_ok=True)
    pack = HERE / "pack" / "inputs"
    cases = {c["case_id"]: c for c in map(json.loads, (pack / "cases.jsonl").read_text().splitlines())}
    tasks = [json.loads(l) for l in (pack / "e2e_tasks.jsonl").read_text().splitlines() if l]
    tasks = [t for t in tasks if t["product"] == a.product and (a.cases == "all" or t["core_smoke_subset"])]
    # Interleave engines and contexts so drift during the session hits both engines alike.
    order = [("base", "generic"), ("base", "usersim"), ("full", "usersim"), ("full", "generic")]
    for t in tasks:
        for context, engine in order:
            key = f"{t['case_id']}__{context}__{engine}"
            if a.only and key not in a.only.split(","):
                continue
            if a.blocked:
                write_blocked(cases[t["case_id"]], context, engine, a.blocked)
                continue
            await one_run(cases[t["case_id"]], t, context, engine)


if __name__ == "__main__":
    asyncio.run(main())
