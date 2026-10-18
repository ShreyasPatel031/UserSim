"""No-token check of the public UserSim MCP: initialize, tools/list, one cheap session on example.com, finish."""
import asyncio, json, sys, time
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = sys.argv[1] if len(sys.argv) > 1 else "https://35-202-98-224.sslip.io/mcp"

async def main():
    t0 = time.time()
    async with streamablehttp_client(URL, timeout=300, sse_read_timeout=600) as (r, w, _):  # no headers = no token
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("initialize: server", init.serverInfo.name, init.serverInfo.version, "protocol", init.protocolVersion)
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            print(f"tools/list: {len(tools)} tools:", ", ".join(tools))
            res = await s.call_tool("usersim_start_session", {
                "product_url": "https://example.com",
                "persona": "Sam, a curious developer checking what this page is.",
                "task": "Find out what this website is for."})
            meta = json.loads(res.content[0].text)
            if "error" in meta:
                print("start_session ERROR:", meta); return
            imgs = [c for c in res.content if c.type == "image"]
            print("start_session: session", meta["session_id"][:8], "study", meta["study_id"], "url", meta["url"],
                  "title", repr(meta["title"]), "screenshot bytes(b64)", len(imgs[0].data) if imgs else 0)
            res = await s.call_tool("usersim_finish", {"session_id": meta["session_id"], "outcome": "completed",
                                                       "notes": "No-token connectivity check: the page says it is for documentation examples."})
            print("finish:", res.content[0].text[:300])
            res = await s.call_tool("usersim_observe", {"session_id": meta["session_id"]})
            print("observe after finish:", res.content[0].text[:200])
    print(f"elapsed {time.time()-t0:.1f}s")

asyncio.run(main())
