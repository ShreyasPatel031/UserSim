"""Full e2e studies through the UserSim MCP (docs/E2E_TEST.md): target + 2 competitors, 6 personas, 6 tasks = 108 cells.

Starts each study with usersim_start_study (empty personas/tasks/competitors are filled by the server's planner), then
runs every cell as its own simulated user: Claude Haiku on Vertex gets the server's usersim_simulate_user prompt and
the observe / act / finish tools (same loop as docs/mcp-test/clients/haiku_vertex_client.py). Cells run in parallel up
to --parallel; a start refused because the server is at its session limit is retried. When every cell is done it
fetches usersim_get_report and writes everything under --out.

    PYTHONPATH=src:. python scripts/mcp_study_runner.py https://www.clockify.me https://kanbanflow.com https://dynalist.io \\
        https://www.notion.com https://basecamp.com --parallel 8

MCP_CLIENT_TOKEN (optional) is sent as a bearer token; without it the anonymous caps in mvp/sim_mcp/limits.json apply
(anon_max_cells_per_study must be >= 108 for a full study). Needs Vertex credentials for the Haiku driver.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("USERSIM_MCP_URL", "https://35-202-98-224.sslip.io/mcp")
MODEL = os.environ.get("RUNNER_MODEL", "claude-haiku-4-5@20251001")
# The simulated user needs the signup tools too: the server prompt (usersim_simulate_user) tells it to call
# usersim_signup_identity and the verification wait/open tools, and a signup task cannot pass without them.
SUB_TOOLS = {"usersim_observe", "usersim_act", "usersim_finish", "usersim_signup_identity",
             "usersim_wait_for_verification_code", "usersim_wait_for_verification_link",
             "usersim_open_verification_link", "usersim_solve_captcha", "usersim_signup_phone", "usersim_wait_for_sms_code"}
BUSY = ("limit", "at capacity", "too many", "busy", "try again")


def _headers() -> dict:
    tok = os.environ.get("MCP_CLIENT_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _text(res) -> str:
    return "".join(c.text for c in res.content if c.type == "text")


def _blocks(res) -> list[dict]:
    out = []
    for c in res.content:
        if c.type == "text":
            out.append({"type": "text", "text": c.text})
        elif c.type == "image":
            out.append({"type": "image", "source": {"type": "base64", "media_type": c.mimeType, "data": c.data}})
    return out or [{"type": "text", "text": "(empty)"}]


async def call(tool: str, args: dict) -> object:
    """One MCP call on a fresh connection (the server is stateless; sessions are keyed by session_id)."""
    async with streamablehttp_client(URL, headers=_headers(), timeout=120, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await s.call_tool(tool, args)


async def run_cell(study_id: str, cell: dict, max_turns: int, out: Path, llm) -> dict:
    log = {"cell": cell, "steps": [], "started": time.time()}
    async with streamablehttp_client(URL, headers=_headers(), timeout=120, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            start = ({"study_id": study_id, "cell_id": cell["cell_id"]} if study_id else
                     {"product_url": cell["site"], "persona": cell["persona"], "task": cell["task"]})
            for attempt in range(60):  # wait for a free browser slot
                st = await s.call_tool("usersim_start_session", start)
                meta = _text(st)
                try:
                    m = json.loads(meta[meta.index("{"):]) if "{" in meta else {}
                except ValueError:
                    m = {}
                if m.get("session_id"):
                    break
                if any(b in meta.lower() for b in BUSY):
                    await asyncio.sleep(30)
                    continue
                log["error"] = meta[:600]
                return log
            else:
                log["error"] = "no free session slot after 30 min"
                return log
            sid = m["session_id"]
            log["session_id"] = sid
            tools = (await s.list_tools()).tools
            prompt = await s.get_prompt("usersim_simulate_user", {"session_id": sid, "persona": cell.get("persona") or "",
                                                                 "task": cell.get("task") or ""})
            system = "\n".join(x.content.text for x in prompt.messages if getattr(x.content, "text", None))
            atools = [{"name": t.name, "description": (t.description or "")[:3000], "input_schema": t.inputSchema}
                      for t in tools if t.name in SUB_TOOLS]
            msgs = [{"role": "user", "content": f"Begin. Your session_id is {sid}. Call usersim_observe first."}]
            finished = False
            for turn in range(max_turns):
                imgs = [(i, j) for i, mm in enumerate(msgs) if isinstance(mm["content"], list)
                        for j, b in enumerate(mm["content"]) if b.get("type") == "tool_result"
                        and any(x.get("type") == "image" for x in b.get("content", []))]
                for i, j in imgs[:-2]:  # keep the 2 newest screenshots
                    b = msgs[i]["content"][j]
                    b["content"] = [x for x in b["content"] if x.get("type") != "image"] + [{"type": "text", "text": "[older screenshot removed]"}]
                resp = await asyncio.to_thread(llm.messages.create, model=MODEL, max_tokens=1024, system=system,
                                               tools=atools, messages=msgs)
                msgs.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
                uses = [b for b in resp.content if b.type == "tool_use"]
                if not uses:
                    msgs.append({"role": "user", "content": "Use a tool: observe, act, or finish."})
                    continue
                results = []
                for u in uses:
                    args = dict(u.input)
                    args.setdefault("session_id", sid)
                    res = await s.call_tool(u.name, args)
                    a = args.get("action")
                    log["steps"].append({"turn": turn, "tool": u.name, "action": a if isinstance(a, (str, type(None))) else a.get("type")})
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": _blocks(res)})
                    if u.name == "usersim_finish":
                        finished = True
                        log["finish"] = _text(res)[:1500]
                msgs.append({"role": "user", "content": results})
                if finished:
                    break
            if not finished:
                res = await s.call_tool("usersim_finish", {"session_id": sid, "outcome": "gave_up",
                                                           "notes": f"Runner hit its {max_turns}-turn cap."})
                log["finish"] = _text(res)[:1500]
    log["seconds"] = round(time.time() - log["started"])
    (out / f"{cell['cell_id']}.json").write_text(json.dumps(log, indent=1))
    return log


async def run_study(product_url: str, parallel: int, max_turns: int, root: Path, llm) -> dict:
    st = await call("usersim_start_study", {"product_url": product_url, "personas": [], "tasks": [], "competitors": []})
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
    print(f"[{product_url}] study {study['study_id']} {len(study['cells'])} cells  watch {study.get('watch_url')}", flush=True)
    sem = asyncio.Semaphore(parallel)

    async def one(cell):
        async with sem:
            try:
                return await run_cell(study["study_id"], cell, max_turns, out, llm)
            except Exception as exc:  # noqa: BLE001 - one cell's failure must not stop the study
                return {"cell": cell, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    logs = await asyncio.gather(*(one(c) for c in study["cells"]))
    report = ""
    for _ in range(20):  # the server writes the report after the last cell
        report = _text(await call("usersim_get_report", {"study_id": study["study_id"]}))
        if "still being written" not in report.lower():
            break
        await asyncio.sleep(30)
    (out / "report.md").write_text(report)
    done = sum(1 for x in logs if x.get("finish"))
    summary = {"product_url": product_url, "study_id": study["study_id"], "report_url": study.get("report_url"),
               "cells": len(logs), "finished": done, "errors": [x.get("error") for x in logs if x.get("error")][:10]}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"[{product_url}] done {done}/{len(logs)}  report {study.get('report_url')}", flush=True)
    return summary


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("products", nargs="+")
    ap.add_argument("--parallel", type=int, default=8, help="cells at once per study")
    ap.add_argument("--max-turns", type=int, default=90)
    ap.add_argument("--out", default="results/mcp_studies")
    ap.add_argument("--smoke", nargs=2, metavar=("PERSONA", "TASK"),
                    help="one session (no study) on the first product: checks the driver without a 108-cell study")
    a = ap.parse_args()
    from anthropic import AnthropicVertex
    from auth import vertex_credentials  # the repo's loader (file, base64 env or metadata server)

    llm = AnthropicVertex(project_id=os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"), region="global",
                          credentials=vertex_credentials())
    root = Path(a.out)
    root.mkdir(parents=True, exist_ok=True)
    if a.smoke:
        cell = {"cell_id": f"smoke_{int(time.time())}", "site": a.products[0], "persona": a.smoke[0], "task": a.smoke[1]}
        log = await run_cell("", cell, a.max_turns, root, llm)
        print(json.dumps({k: log.get(k) for k in ("session_id", "error", "finish", "seconds")}, indent=1)[:2500])
        print("steps", len(log["steps"]))
        return
    res = await asyncio.gather(*(run_study(p, a.parallel, a.max_turns, root, llm) for p in a.products))
    (root / f"run_{int(time.time())}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
