"""Run one full UserSim study through the public MCP, with Claude Code (Haiku) agents as the simulated users.

  python scripts/mcp_loop/run_study.py spec.json --out runs/<name> [--parallel 8] [--model haiku]

spec.json: {"product_url": ..., "competitors": [...], "personas": [...], "tasks": [...]}
Env: USERSIM_MCP (default https://atelier-sim.com/mcp), MCP_CLIENT_TOKEN.

Each cell gets its own `claude -p` process with only the usersim MCP tools. The agent's
prompt is the server's own usersim_simulate_user prompt, so this is exactly what any MCP
client would see. Every agent's stream-json trace is kept under <out>/cells/<cell_id>.jsonl.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

URL = os.environ.get("USERSIM_MCP", "https://atelier-sim.com/mcp")


async def call(tool: str, args: dict, *, prompt: bool = False) -> object:
    """One MCP call. Retried on connection errors, except start_study (a retry could create a second study)."""
    tries = 1 if tool == "usersim_start_study" else 5
    for i in range(tries):
        try:
            return await _call_once(tool, args, prompt=prompt)
        except Exception as exc:  # noqa: BLE001  (httpx errors arrive wrapped in ExceptionGroups)
            if i == tries - 1:
                raise
            print(f"retry {tool} after {exc!r}"[:200], flush=True)
            await asyncio.sleep(2 ** (i + 1))


async def _call_once(tool: str, args: dict, *, prompt: bool = False) -> object:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {os.environ['MCP_CLIENT_TOKEN']}"}
    async with streamablehttp_client(URL, headers=headers, timeout=300, sse_read_timeout=600) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if prompt:
                res = await s.get_prompt(tool, args)
                return "\n".join(m.content.text for m in res.messages if getattr(m.content, "text", None))
            res = await s.call_tool(tool, args)
            text = next((c.text for c in res.content if getattr(c, "type", "") == "text"), "")
            try:
                return json.loads(text)
            except ValueError:
                return text


def agent_prompt(sim_prompt: str, study_id: str, cell_id: str) -> str:
    return (
        f"First call usersim_start_session with study_id={study_id!r} and cell_id={cell_id!r} (pass nothing else). "
        "It returns your session_id, the persona you play, the task, and the first screenshot.\n"
        "Then play that simulated user until you call usersim_finish. Do not stop before calling usersim_finish.\n\n"
        + sim_prompt
    )


async def run_cell(cell: dict, study_id: str, sim_prompt: str, out: Path, model: str, sem: asyncio.Semaphore,
                   mcp_config: str, timeout_s: int) -> dict:
    cid = cell["cell_id"]
    log = out / "cells" / f"{cid}.jsonl"
    cmd = ["claude", "-p", agent_prompt(sim_prompt, study_id, cid), "--model", model,
           "--mcp-config", mcp_config, "--strict-mcp-config", "--allowedTools", "mcp__usersim__*",
           "--output-format", "stream-json", "--verbose", "--max-turns", "200"]
    async with sem:
        for attempt in range(1, 4):
            t0 = time.time()
            with open(log, "w") as fh:
                proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=fh,
                                                            stderr=asyncio.subprocess.STDOUT)
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout_s)
                except asyncio.TimeoutError:
                    proc.kill()
                    rc = "timeout"
            dt = round(time.time() - t0)
            print(f"[{time.strftime('%H:%M:%S')}] {cid} rc={rc} {dt}s", flush=True)
            if '"name":"mcp__usersim__usersim_start_session"' in log.read_text(errors="replace").replace(" ", ""):
                return {"cell_id": cid, "rc": rc, "seconds": dt, "attempts": attempt}
            # The agent never reached usersim_start_session: its MCP connection failed at startup (2 of 108 in
            # study f80f043a). The cell is still queued on the server, so run it again.
            log.rename(out / "cells" / f"{cid}.noconnect{attempt}.log")
            print(f"[{time.strftime('%H:%M:%S')}] {cid} never started a session; retrying", flush=True)
            await asyncio.sleep(10)
    return {"cell_id": cid, "rc": "no_mcp", "seconds": 0, "attempts": 3}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--cell-timeout", type=int, default=1800)
    ap.add_argument("--resume", help="existing study_id: run only cells still queued")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "cells").mkdir(parents=True, exist_ok=True)
    spec = json.loads(Path(a.spec).read_text())

    cfg = out / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"usersim": {"type": "http", "url": URL, "headers": {
        "Authorization": f"Bearer {os.environ['MCP_CLIENT_TOKEN']}"}}}}))
    cfg.chmod(0o600)

    if a.resume:
        study_id = a.resume
        started = json.loads((out / "study.json").read_text())
    else:
        started = await call("usersim_start_study", spec)
        if not isinstance(started, dict) or "study_id" not in started:
            sys.exit(f"start_study failed: {started}")
        (out / "study.json").write_text(json.dumps(started, indent=1))
        study_id = started["study_id"]
    print("study", study_id, "watch", started.get("watch_url"), "report", started.get("report_url"), flush=True)

    sim_prompt = await call("usersim_simulate_user", {
        "session_id": "(the session_id returned by usersim_start_session)",
        "persona": "(the persona returned by usersim_start_session)",
        "task": "(the task returned by usersim_start_session)"}, prompt=True)
    cells = started["cells"]
    if a.resume:
        done = {p.stem for p in (out / "cells").glob("*.jsonl") if p.stat().st_size > 0}
        cells = [c for c in cells if c["cell_id"] not in done]
    sem = asyncio.Semaphore(a.parallel)
    results = await asyncio.gather(*(run_cell(c, study_id, sim_prompt, out, a.model, sem, str(cfg), a.cell_timeout)
                                     for c in cells))
    (out / "agents.json").write_text(json.dumps(results, indent=1))

    fin = await call("usersim_finish_study", {"study_id": study_id})
    print("finish_study", fin, flush=True)
    for _ in range(40):
        rep = await call("usersim_get_report", {"study_id": study_id, "format": "json"})
        if isinstance(rep, dict) and not rep.get("note") and not rep.get("error"):
            break
        await asyncio.sleep(30)
    (out / "report.json").write_text(json.dumps(rep, indent=1) if isinstance(rep, dict) else str(rep))
    print("report saved", started.get("report_url"), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
