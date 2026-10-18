"""Live cap check, no token: open 3 sessions (the per-IP limit), a 4th must be refused; then finish all."""
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
URL = "https://35-202-98-224.sslip.io/mcp"

async def main():
    async with streamablehttp_client(URL, timeout=300, sse_read_timeout=600) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            ids = []
            for i in range(4):
                res = await s.call_tool("usersim_start_session", {"product_url": "https://example.com",
                    "persona": "Sam, a curious developer.", "task": f"Cap check {i+1}: see what this site is."})
                meta = json.loads(res.content[0].text)
                if "error" in meta:
                    print(f"start #{i+1}: REFUSED ->", meta["error"])
                else:
                    ids.append(meta["session_id"]); print(f"start #{i+1}: ok session {meta['session_id'][:8]}")
            for sid in ids:
                res = await s.call_tool("usersim_finish", {"session_id": sid, "outcome": "gave_up", "notes": "cap check, closing"})
                print("finish", sid[:8], json.loads(res.content[0].text).get("study_id"))
asyncio.run(main())
