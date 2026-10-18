"""Minimal client for the UserSim MCP server (branch mcp-signup-parity, docs/mcp/README.md).

Reads USERSIM_MCP_URL and MCP_CLIENT_TOKEN from secrets/usersim_mcp_token.env and
never prints the token. Usage:
  python mcp_client.py list
  python mcp_client.py call <tool> '<json args>'
Text results print as-is; screenshots are saved under results/mcp_shots/.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE.parents[1] / "secrets" / "usersim_mcp_token.env"
SHOTS = HERE / "results" / "mcp_shots"


def _env() -> tuple[str, str]:
    vals = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals["USERSIM_MCP_URL"], vals["MCP_CLIENT_TOKEN"]


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
    url, token = _env()
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(url, headers=headers, timeout=60, sse_read_timeout=600) as (r, w, _):
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
    asyncio.run(main())
