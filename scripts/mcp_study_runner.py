"""Full e2e studies through the UserSim MCP (docs/E2E_TEST.md): target + 2 competitors, 6 personas, 6 tasks = 108 cells.

Starts each study with usersim_start_study (empty personas/tasks/competitors are filled by the server's planner), then
runs every cell as its own simulated user: Gemini 2.5 Flash on Vertex (scripts/mcp_runner_gemini.py; no Claude in
pipelines) gets the server's usersim_simulate_user prompt and the observe / act / finish tools, sees the newest
screenshot each turn and must answer with exactly one tool call. Append-only history, spend caps, a 3-cell pilot per
study, and bounded retries.

    PYTHONPATH=src:. python scripts/mcp_study_runner.py https://tally.so --competitors https://fillout.com,https://typeform.com \\
        --parallel 11 --max-usd 20 --max-cell-usd 0.5 --max-turns 40

EACH positional product URL starts its OWN full 108-cell study (target = that URL; competitors from --competitors, or
picked by the server when omitted). Three URLs = three studies = 324 cells. For one study of a target against two
rivals, pass the target alone and the rivals with --competitors.

Cost (gemini-2.5-flash Vertex list: $0.30/M input, $2.50/M output incl. thinking): roughly $0.002–0.004 per model turn
(one screenshot + history in, one call out, thinking budget RUNNER_THINKING_BUDGET=1024), so a few dollars to ~$10 for a
full 108-cell study. Pilot mode (default) runs one cell per site first and aborts if the projected
total would exceed --max-usd.

MCP_CLIENT_TOKEN (optional) is sent as a bearer token; without it the anonymous caps in mvp/sim_mcp/limits.json apply
(anon_max_cells_per_study must be >= 108 for a full study). Needs Vertex credentials (src/auth.py) for Gemini.
RUNNER_MODEL overrides the model (default gemini-2.5-flash), RUNNER_LOCATION the Vertex location (default global).

Flags:
  --parallel (12)          Max concurrent cells per study
  --max-turns (40)         Model turns per cell
  --max-usd (20)           Stop the whole run when estimated model spend reaches this
  --max-cell-usd (0.5)     Stop a single cell when its spend reaches this
  --max-retries (50)       Total model+tool retries across the run, then stop
  --no-pilot               Skip the 3-cell pilot and fan out immediately
  --competitors A,B        Rival URLs for usersim_start_study (empty: the server picks 2)
  --resume STUDY_ID        Run every cell that never got a server session (crash, cap, overloaded server).
                           Cells that ran (<cell>.json with a session_id) are kept; never-started ones are saved as
                           <cell>.notrun.json and run again.
  --smoke PERSONA TASK     One session on the first product URL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mcp_study_runner_lib import (
    CONDENSE_AFTER_TURNS,
    MAX_MODEL_ATTEMPTS,
    MAX_TOOL_ATTEMPTS,
    SpendGate,
    TranscriptState,
    backoff_seconds,
    build_api_messages,
    condense_messages,
    is_retryable_error,
    mcp_content_to_blocks,
    pilot_cells_for_study,
    signup_first,
    pilot_should_abort,
    prepare_system,
    prepare_tools,
    summarize_steps,
    usage_cache_fields,
)

URL = os.environ.get("USERSIM_MCP_URL", "https://35-202-98-224.sslip.io/mcp")
MODEL = os.environ.get("RUNNER_MODEL", "gemini-2.5-flash")
SUB_TOOLS = {
    "usersim_observe",
    "usersim_act",
    "usersim_finish",
    "usersim_signup_identity",
    "usersim_wait_for_verification_code",
    "usersim_wait_for_verification_link",
    "usersim_open_verification_link",
    "usersim_solve_captcha",
    "usersim_signup_phone",
    "usersim_wait_for_sms_code",
}
BUSY = ("limit", "at capacity", "too many", "busy", "try again")
START_WAIT_S = int(os.environ.get("RUNNER_START_WAIT_S", str(90 * 60)))
STOP_NOTE = "stopped: runner spend cap"


def _headers() -> dict:
    tok = os.environ.get("MCP_CLIENT_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _text(res) -> str:
    return "".join(c.text for c in res.content if c.type == "text")


def _has_image(res) -> bool:
    return any(getattr(c, "type", None) == "image" for c in getattr(res, "content", None) or [])


def _blocks(res, *, include_image: bool = True) -> list[dict]:
    return mcp_content_to_blocks(res.content, include_image=include_image)


def _leaf(exc: BaseException) -> str:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {str(exc)[:300] or repr(exc)[:300]}"


async def tool(name: str, args: dict, gate: SpendGate, retries: int = MAX_TOOL_ATTEMPTS):
    for k in range(retries):
        if gate.over_cap():
            raise RuntimeError(STOP_NOTE)
        try:
            async with streamablehttp_client(URL, headers=_headers(), timeout=120, sse_read_timeout=900) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    return await s.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001
            if not is_retryable_error(exc) or k == retries - 1:
                raise RuntimeError(f"{name}: {_leaf(exc)}") from None
            if not gate.record_retry():
                raise RuntimeError(gate.stop_reason or STOP_NOTE) from None
            await asyncio.sleep(backoff_seconds(k, base=5.0))


def _result_brief(txt: str, rejected: bool) -> dict:
    """What the server said back, for debugging stuck cells: page url, captcha state, action error."""
    out: dict[str, Any] = {"rejected": rejected}
    try:
        d = json.loads(txt[txt.index("{"):]) if "{" in txt else {}
    except ValueError:
        d = {}
    if isinstance(d, dict):
        for k in ("url", "step", "steps_left", "action_error", "note"):
            if d.get(k):
                out[k] = str(d[k])[:200]
        if d.get("captcha"):
            out["captcha"] = json.dumps(d["captcha"], default=str)[:200]
    elif rejected:
        out["error"] = txt[:200]
    return out


def _save_cell(out: Path, cell: dict, log: dict) -> None:
    """A cell counts as run only once a server session existed for it. A cell the runner never started (spend cap,
    retry budget, crash) is saved as <cell>.notrun.json, so --resume runs it (Nov 17: an overloaded server made the
    runner write 43 never-started cells as done, and --resume skipped them)."""
    if log.get("session_id"):
        (out / f"{cell['cell_id']}.json").write_text(json.dumps(log, indent=1))
        (out / f"{cell['cell_id']}.notrun.json").unlink(missing_ok=True)
    else:
        log["not_run"] = True
        (out / f"{cell['cell_id']}.notrun.json").write_text(json.dumps(log, indent=1))


def cell_done(out: Path, cell_id: str) -> bool:
    """Did this cell run (a server session existed)? Logs from older runners without a session_id are not done."""
    p = out / f"{cell_id}.json"
    if not p.exists():
        return False
    try:
        return bool(json.loads(p.read_text()).get("session_id"))
    except (ValueError, OSError):
        return False


def _stop_note(gate: SpendGate) -> str:
    return f"stopped: {gate.stop_reason}" if gate.stop_reason else STOP_NOTE


def stall_summary(steps: list[dict]) -> dict:
    """Longest run of identical actions with no page change (a stuck cell), and how many steps saw a captcha."""
    best = cur = 0
    prev = None
    for st in steps:
        key = (st.get("action"), st.get("url"))
        cur = cur + 1 if st.get("tool") == "usersim_act" and key == prev else 1
        prev = key if st.get("tool") == "usersim_act" else None
        best = max(best, cur)
    return {"max_repeat_same_action_and_url": best, "captcha_steps": sum(1 for st in steps if st.get("captcha"))}


async def listing(what: str, *args):
    async with streamablehttp_client(URL, headers=_headers(), timeout=120, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await (s.list_tools() if what == "tools" else s.get_prompt(*args))


async def ask_model(llm, gate: SpendGate, system: list, atools: list, state: TranscriptState, log: dict):
    api_msgs = build_api_messages(state)
    last_cost = 0.0
    for k in range(MAX_MODEL_ATTEMPTS):
        if gate.over_cap():
            raise RuntimeError(STOP_NOTE)
        try:
            resp = await asyncio.to_thread(
                llm.messages.create,
                model=MODEL,
                max_tokens=1024,
                system=system,
                tools=atools,
                messages=api_msgs,
            )
            last_cost = gate.record_usage(resp.usage)
            cache = usage_cache_fields(resp.usage)
            log.setdefault("cache_usage", []).append(cache)
            log.setdefault("model_usd", 0.0)
            log["model_usd"] = round(log["model_usd"] + last_cost, 6)
            return resp
        except Exception as exc:  # noqa: BLE001
            if not is_retryable_error(exc) or k == MAX_MODEL_ATTEMPTS - 1:
                raise RuntimeError(f"model: {_leaf(exc)}") from None
            if not gate.record_retry():
                raise RuntimeError(gate.stop_reason or STOP_NOTE) from None
            await asyncio.sleep(backoff_seconds(k))
    raise RuntimeError("model: exhausted retries")


async def run_cell(
    study_id: str,
    cell: dict,
    max_turns: int,
    max_cell_usd: float,
    out: Path,
    llm,
    gate: SpendGate,
) -> dict:
    log: dict[str, Any] = {"cell": cell, "steps": [], "started": time.time(), "model_usd": 0.0}
    start = (
        {"study_id": study_id, "cell_id": cell["cell_id"]}
        if study_id
        else {"product_url": cell["site"], "persona": cell["persona"], "task": cell["task"]}
    )
    m: dict = {}
    # A held cell waits for its site's one signup run (server signup_gate), which can take a whole session budget.
    wait_until = time.time() + START_WAIT_S
    while time.time() < wait_until:
        if gate.over_cap():
            log["error"] = log["finish"] = _stop_note(gate)
            _save_cell(out, cell, log)
            return log
        try:
            meta = _text(await tool("usersim_start_session", start, gate))
        except RuntimeError as exc:
            if STOP_NOTE in str(exc) or gate.stop_reason:
                log["error"] = gate.stop_reason or str(exc)
                log["finish"] = _stop_note(gate)
                _save_cell(out, cell, log)
                return log
            raise
        try:
            m = json.loads(meta[meta.index("{"):]) if "{" in meta else {}
        except ValueError:
            m = {}
        if m.get("session_id"):
            break
        if any(b in meta.lower() for b in BUSY):
            log["held_s"] = round(START_WAIT_S - (wait_until - time.time()))
            await asyncio.sleep(30)
            continue
        log["error"] = meta[:600]
        _save_cell(out, cell, log)
        return log
    else:
        log["error"] = f"no free session slot after {START_WAIT_S // 60} min"
        _save_cell(out, cell, log)
        return log
    sid = m["session_id"]
    log["session_id"] = sid
    tools = (await listing("tools")).tools
    prompt = await listing(
        "prompt",
        "usersim_simulate_user",
        {"session_id": sid, "persona": cell.get("persona") or "", "task": cell.get("task") or ""},
    )
    system_text = "\n".join(x.content.text for x in prompt.messages if getattr(x.content, "text", None))
    system = prepare_system(system_text)
    atools = prepare_tools(
        [
            {"name": t.name, "description": (t.description or "")[:3000], "input_schema": t.inputSchema}
            for t in tools
            if t.name in SUB_TOOLS
        ]
    )
    state = TranscriptState()
    state.append_user(f"Begin. Your session_id is {sid}. Call usersim_observe first.")
    finished = False
    stop_cap = False
    for turn in range(max_turns):
        if gate.over_cap() or log["model_usd"] >= max_cell_usd:
            stop_cap = True
            break
        if state.turn_count >= CONDENSE_AFTER_TURNS:
            summary = summarize_steps(log["steps"])
            state.messages = condense_messages(state.messages, summary)
            state.turn_count = 0
            state.latest_screenshot = None
        resp = await ask_model(llm, gate, system, atools, state, log)
        state.append_assistant([b.model_dump(exclude_none=True) for b in resp.content])
        state.turn_count += 1
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            state.append_user("Use a tool: observe, act, or finish.")
            continue
        for u in uses:
            args = dict(u.input)
            args.setdefault("session_id", sid)
            if u.name == "usersim_finish":
                args.setdefault("notes", "Finished by the simulated user.")
                args.setdefault("outcome", "completed")
            a = args.get("action")
            step = {
                "turn": turn,
                "tool": u.name,
                "action": a if isinstance(a, (str, type(None))) else a.get("type"),
                "args": {k: (v if not isinstance(v, str) else v[:120]) for k, v in args.items() if k != "session_id"},
                "thought": " ".join(b.text for b in resp.content if b.type == "text")[:300],
            }
            log["steps"].append(step)
            try:
                res = await tool(u.name, args, gate, retries=MAX_TOOL_ATTEMPTS if u.name == "usersim_observe" else MAX_TOOL_ATTEMPTS)
                txt = _text(res)
                rejected = txt.startswith("Error executing tool")
                step.update(_result_brief(txt, rejected))
                nudged = False
                if u.name == "usersim_finish" and not rejected:
                    try:
                        nudged = json.loads(txt).get("finished") is False
                    except (ValueError, AttributeError):
                        pass
                if u.name == "usersim_observe" or _has_image(res):
                    # every tool that returns a screenshot (act, solve_captcha, open_verification_link ...) refreshes
                    # the one the model sees. Only observe did: after an act the model kept looking at the first
                    # page and clicked "Accept All" 17 times (Oct 23 Smartsheet smoke runs).
                    state.append_observe_tool_result(u.id, res.content, is_error=rejected)
                else:
                    state.append_tool_result(u.id, _blocks(res, include_image=False), is_error=rejected)
                if u.name == "usersim_finish" and not (rejected or nudged):
                    finished = True
                    log["finish"] = txt[:1500]
            except RuntimeError as exc:
                if STOP_NOTE in str(exc) or gate.stop_reason:
                    stop_cap = True
                    log["error"] = gate.stop_reason or str(exc)
                    break
                log.setdefault("tool_errors", []).append(str(exc)[:300])
                state.append_tool_result(
                    u.id,
                    [
                        {
                            "type": "text",
                            "text": f"{exc}. The action may or may not have happened: call usersim_observe.",
                        }
                    ],
                    is_error=True,
                )
            except Exception as exc:  # noqa: BLE001
                log.setdefault("tool_errors", []).append(str(exc)[:300])
                state.append_tool_result(
                    u.id,
                    [
                        {
                            "type": "text",
                            "text": f"{exc}. The action may or may not have happened: call usersim_observe.",
                        }
                    ],
                    is_error=True,
                )
        if finished or stop_cap:
            break
    notes_extra = f" model_usd={log.get('model_usd', 0):.4f}"
    if stop_cap:
        notes = f"{STOP_NOTE}.{notes_extra}"
        try:
            res = await tool(
                "usersim_finish",
                {"session_id": sid, "outcome": "gave_up", "notes": notes},
                gate,
                retries=1,
            )
            log["finish"] = _text(res)[:1500]
        except Exception:
            log["finish"] = notes
    elif not finished:
        res = await tool(
            "usersim_finish",
            {
                "session_id": sid,
                "outcome": "gave_up",
                "notes": f"Runner hit its {max_turns}-turn cap.{notes_extra}",
            },
            gate,
        )
        log["finish"] = _text(res)[:1500]
    if log.get("finish", "").startswith("Error executing tool") or '"finished": false' in log.get("finish", ""):
        log["error"] = "finish rejected: " + log["finish"][:300]
    log["seconds"] = round(time.time() - log["started"])
    log["stall"] = stall_summary(log["steps"])
    log["total_runner_usd"] = round(gate.total_usd, 6)
    _save_cell(out, cell, log)
    return log


async def _spend_printer(gate: SpendGate, interval: float = 30.0) -> None:
    while not gate.over_cap():
        await asyncio.sleep(interval)
        print(f"[spend] ${gate.total_usd:.4f} / ${gate.max_usd:.2f}  retries {gate.retries_used}/{gate.max_retries}", flush=True)


async def run_study(
    product_url: str,
    parallel: int,
    max_turns: int,
    max_cell_usd: float,
    root: Path,
    llm,
    gate: SpendGate,
    resume: str = "",
    no_pilot: bool = False,
    competitors: list[str] | None = None,
) -> dict:
    if resume:
        out = root / resume
        study = json.loads((out / "study.json").read_text())
        todo = [c for c in study["cells"] if not cell_done(out, c["cell_id"])]
        print(f"[{product_url}] resuming study {resume}: {len(todo)} of {len(study['cells'])} cells left", flush=True)
    else:
        st = await tool("usersim_start_study", {"product_url": product_url, "personas": [], "tasks": [],
                                                 "competitors": list(competitors or [])}, gate)
        txt = _text(st)
        try:
            study = json.loads(txt)
        except ValueError:
            return {"product_url": product_url, "error": txt[:800]}
        if "study_id" not in study:
            return {"product_url": product_url, "error": txt[:800]}
        out = root / study["study_id"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "study.json").write_text(json.dumps(study, indent=1))
        todo = study["cells"]
        print(f"[{product_url}] study {study['study_id']} {len(todo)} cells  watch {study.get('watch_url')}", flush=True)

    if gate.over_cap():
        return {"product_url": product_url, "study_id": study["study_id"], "error": gate.stop_reason or STOP_NOTE}

    pilot_done: set[str] = set()
    if not resume and not no_pilot and todo:
        pilots = pilot_cells_for_study(todo)
        pilot_ids = {c["cell_id"] for c in pilots}
        print(f"[{product_url}] pilot: {len(pilots)} cells (one per site)", flush=True)
        pilot_logs = await _run_cells_parallel(
            study, pilots, max_turns, max_cell_usd, out, llm, gate, parallel, product_url
        )
        pilot_done = pilot_ids
        costs = [float(x.get("model_usd") or 0) for x in pilot_logs if not x.get("error")]
        if costs:
            mean = sum(costs) / len(costs)
            abort, projected = pilot_should_abort(mean, len(study["cells"]), gate.max_usd)
            print(
                f"[{product_url}] pilot mean ${mean:.4f}/cell → projected ${projected:.2f} for {len(study['cells'])} cells "
                f"(cap ${gate.max_usd:.2f})",
                flush=True,
            )
            if abort:
                msg = (
                    f"Pilot projection ${projected:.2f} exceeds --max-usd ${gate.max_usd:.2f}. "
                    "Tune caching/caps or pass --no-pilot to override."
                )
                print(f"[{product_url}] ABORT: {msg}", flush=True)
                return {"product_url": product_url, "study_id": study["study_id"], "error": msg, "pilot_projected_usd": projected}
        todo = [c for c in todo if c["cell_id"] not in pilot_done]

    if todo and not gate.over_cap():
        await _run_cells_parallel(study, signup_first(todo), max_turns, max_cell_usd, out, llm, gate, parallel,
                                  product_url)

    report = ""
    for _ in range(20):
        if gate.over_cap():
            break
        report = _text(await tool("usersim_get_report", {"study_id": study["study_id"]}, gate))
        if "still being written" not in report.lower():
            break
        await asyncio.sleep(30)
    (out / "report.md").write_text(report)
    _save_server_study(out, study)
    finished = sum(1 for c in study["cells"] if cell_done(out, c["cell_id"]))
    summary = {
        "product_url": product_url,
        "study_id": study["study_id"],
        "report_url": study.get("report_url"),
        "cells": len(study["cells"]),
        "finished": finished,
        "not_run": len(study["cells"]) - finished,
        "runner_total_usd": round(gate.total_usd, 6),
        "errors": [],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"[{product_url}] done  runner spend ${gate.total_usd:.4f}  report {study.get('report_url')}", flush=True)
    if finished < len(study["cells"]):
        print(f"[{product_url}] {len(study['cells']) - finished} cells never ran: --resume {study['study_id']}", flush=True)
    return summary


def _save_server_study(out: Path, study: dict) -> None:
    """The server keeps every step's thought, click args and screenshot url; keep a copy (gzip) with the runner logs."""
    base = (study.get("report_url") or "").split("/report")[0]
    if not base:
        return
    try:
        import gzip
        import urllib.request

        with urllib.request.urlopen(f"{base}/api/studies/{study['study_id']}", timeout=120) as r:
            (out / "server_study.json.gz").write_bytes(gzip.compress(r.read()))
    except Exception as exc:  # noqa: BLE001
        print(f"could not save the server's copy of the study: {_leaf(exc)}", flush=True)


async def _run_cells_parallel(
    study: dict,
    cells: list[dict],
    max_turns: int,
    max_cell_usd: float,
    out: Path,
    llm,
    gate: SpendGate,
    parallel: int,
    product_url: str,
) -> list[dict]:
    sem = asyncio.Semaphore(parallel)
    done = [0]
    tasks: list[asyncio.Task] = []

    async def one(cell: dict) -> dict:
        if gate.over_cap():
            res = {"cell": cell, "error": gate.stop_reason or STOP_NOTE, "finish": _stop_note(gate)}
            _save_cell(out, cell, res)
            return res
        async with sem:
            if gate.over_cap():
                res = {"cell": cell, "error": gate.stop_reason or STOP_NOTE, "finish": _stop_note(gate)}
                _save_cell(out, cell, res)
                return res
            try:
                return await run_cell(study["study_id"], cell, max_turns, max_cell_usd, out, llm, gate)
            except Exception as exc:  # noqa: BLE001
                res = {"cell": cell, "error": _leaf(exc), "traceback": "".join(traceback.format_exception(exc))[-3000:]}
                (out / f"{cell['cell_id']}.error.json").write_text(json.dumps(res, indent=1))
                return res
            finally:
                done[0] += 1
                print(f"[{product_url}] {done[0]}/{len(cells)} cells ended (batch)", flush=True)

    async def cancel_when_capped() -> None:
        while not gate.over_cap():
            await asyncio.sleep(0.25)
        for t in tasks:
            if not t.done():
                t.cancel()

    watcher = asyncio.create_task(cancel_when_capped())
    for c in cells:
        if gate.over_cap():
            break
        tasks.append(asyncio.create_task(one(c)))
    try:
        if tasks:
            return list(await asyncio.gather(*tasks, return_exceptions=False))
    finally:
        watcher.cancel()
    return []


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("products", nargs="+", help="target product URL(s); EACH one starts its own 108-cell study")
    ap.add_argument("--competitors", default="", help="comma-separated rival URLs for usersim_start_study")
    ap.add_argument("--parallel", type=int, default=12, help="cells at once per study")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--max-usd", type=float, default=20.0, help="stop the whole run at this model spend")
    ap.add_argument("--max-cell-usd", type=float, default=0.5, help="stop a cell at this model spend")
    ap.add_argument("--max-retries", type=int, default=50, help="total retries across model and MCP tools")
    ap.add_argument("--no-pilot", action="store_true", help="skip 3-cell pilot and cost projection")
    ap.add_argument("--out", default="results/mcp_studies")
    ap.add_argument("--resume", metavar="STUDY_ID", help="continue a study whose runner died")
    ap.add_argument(
        "--smoke",
        nargs=2,
        metavar=("PERSONA", "TASK"),
        help="one session (no study) on the first product",
    )
    a = ap.parse_args()
    from mcp_runner_gemini import GeminiDriver, vertex_client

    if "claude" in MODEL.lower():
        raise SystemExit("RUNNER_MODEL must be a Gemini model (no Claude in pipelines)")
    llm = GeminiDriver(vertex_client(os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"),
                                     os.environ.get("RUNNER_LOCATION", "global")))
    competitors = [u.strip() for u in a.competitors.split(",") if u.strip()]
    if len(a.products) > 1 and not a.resume:
        print(f"NOTE: {len(a.products)} product URLs = {len(a.products)} separate studies "
              f"({108 * len(a.products)} cells). For one study with rivals use --competitors.", flush=True)
    root = Path(a.out)
    root.mkdir(parents=True, exist_ok=True)
    gate = SpendGate(max_usd=a.max_usd, max_retries=a.max_retries)
    printer = asyncio.create_task(_spend_printer(gate))
    try:
        if a.smoke:
            cell = {
                "cell_id": f"smoke_{int(time.time())}",
                "site": a.products[0],
                "persona": a.smoke[0],
                "task": a.smoke[1],
            }
            log = await run_cell("", cell, a.max_turns, a.max_cell_usd, root, llm, gate)
            print(json.dumps({k: log.get(k) for k in ("session_id", "error", "finish", "seconds", "model_usd")}, indent=1)[:2500])
            print("steps", len(log["steps"]))
            return
        res = await asyncio.gather(
            *(
                run_study(
                    p,
                    a.parallel,
                    a.max_turns,
                    a.max_cell_usd,
                    root,
                    llm,
                    gate,
                    a.resume or "",
                    a.no_pilot,
                    competitors,
                )
                for p in a.products
            )
        )
        payload = {"studies": res, "runner_total_usd": round(gate.total_usd, 6), "retries_used": gate.retries_used}
        (root / f"run_{int(time.time())}.json").write_text(json.dumps(payload, indent=1))
        print(f"Runner total model spend: ${gate.total_usd:.4f}", flush=True)
        print(json.dumps(res, indent=1))
    finally:
        printer.cancel()


if __name__ == "__main__":
    asyncio.run(main())
