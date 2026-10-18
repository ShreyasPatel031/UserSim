"""Minimal anonymous client for the public UserSim MCP server (docs/mcp/README.md on main): no token, no env.

Copied from experiments/human_experience/mcp_client.py (branch claude/ecstatic-einstein-3e3aq5), minus the token.
USERSIM_MCP_URL overrides the URL. Usage:
  python mcp_client.py list
  python mcp_client.py call <tool> '<json args>'
Text results print as-is; screenshots are saved under results/mcp_shots/.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "shots"
URL = os.environ.get("USERSIM_MCP_URL", "https://35-202-98-224.sslip.io/mcp")


def _brief(text: str) -> str:
    """Observation summary: step, url, visible fields, errors, captcha."""
    try:
        d = json.loads(text)
    except ValueError:
        return text
    if not isinstance(d, dict) or "fields" not in d:
        return text
    out = [f"[{d.get('session_id')}] step {d.get('step')} left {d.get('steps_left')} | {d.get('url')} | {d.get('title')}"]
    for f in d.get("fields") or []:
        extra = " filled" if f.get("filled") else ""
        opts = f" options={f['options'][:6]}" if f.get("options") else ""
        out.append(f"  {f.get('kind')} '{str(f.get('label'))[:60]}' @({f.get('x')},{f.get('y')}){extra}{opts}")
    for k in ("unfilled_fields", "note", "email_hint", "captcha", "action_error", "captcha_presolve"):
        if d.get(k):
            out.append(f"  {k}: {json.dumps(d[k])[:400]}")
    inline = (d.get("page_errors") or {}).get("inline")
    if inline:
        out.append(f"  inline_errors: {inline}")
    return "\n".join(out)


async def main() -> None:
    async with streamable_http_client(URL) as streams:
        r, w = streams[0], streams[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            if sys.argv[1] == "list":
                for t in (await s.list_tools()).tools:
                    print(t.name)
                return
            tool, args = sys.argv[2], json.loads(sys.argv[3] if len(sys.argv) > 3 else "{}")
            brief = "--brief" in sys.argv
            res = await s.call_tool(tool, args)
            for c in res.content:
                if c.type == "text":
                    print(_brief(c.text) if brief else c.text)
                elif c.type == "image":
                    SHOTS.mkdir(parents=True, exist_ok=True)
                    p = SHOTS / f"{tool}_{int(time.time() * 1000)}.jpg"
                    p.write_bytes(base64.b64decode(c.data))
                    print(f"[screenshot] {p}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseExceptionGroup as eg:  # output piped to `head`: the call itself already ran
        if not eg.subgroup(BrokenPipeError):
            raise
