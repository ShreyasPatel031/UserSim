"""Claude Haiku 4.5 (Vertex) as an MCP client of UserSim: orchestrator starts a session, the subagent loop
gets the server's usersim_simulate_user prompt and the observe/act/finish tools. Token from env, never printed."""
import asyncio, json, os, sys, time
from anthropic import AnthropicVertex
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = sys.argv[1]; SITE = sys.argv[2]; TASK = sys.argv[3]; PERSONA = sys.argv[4]; MAX_TURNS = int(sys.argv[5]) if len(sys.argv) > 5 else 30
MODEL = "claude-haiku-4-5@20251001"; PIN, POUT = 1.0 / 1e6, 5.0 / 1e6
SUB_TOOLS = {"usersim_observe", "usersim_act", "usersim_finish"}

def to_blocks(res):
    out = []
    for c in res.content:
        if c.type == "text":
            out.append({"type": "text", "text": c.text})
        elif c.type == "image":
            out.append({"type": "image", "source": {"type": "base64", "media_type": c.mimeType, "data": c.data}})
    return out or [{"type": "text", "text": "(empty)"}]

async def main():
    llm = AnthropicVertex(project_id=os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"), region="global")
    h = {"Authorization": "Bearer " + os.environ["MCP_CLIENT_TOKEN"]}
    cost = 0.0; log = {"site": SITE, "task": TASK, "model": MODEL, "steps": []}
    async with streamablehttp_client(URL, headers=h, timeout=120, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            st = await s.call_tool("usersim_start_session", {"product_url": SITE, "task": TASK, "persona": PERSONA})
            meta = json.loads(st.content[0].text)
            sid = meta["session_id"]; log["start"] = {k: meta.get(k) for k in ("session_id", "study_id", "watch_url", "report_url", "engine_version")}
            print("started", json.dumps(log["start"]), flush=True)
            prompt = await s.get_prompt("usersim_simulate_user", {"session_id": sid, "persona": PERSONA, "task": TASK})
            system = "\n".join(m.content.text for m in prompt.messages if getattr(m.content, "text", None))
            atools = [{"name": t.name, "description": (t.description or "")[:3000], "input_schema": t.inputSchema}
                      for t in tools if t.name in SUB_TOOLS]
            msgs = [{"role": "user", "content": f"Begin. Your session_id is {sid}. Call usersim_observe first."}]
            finished = False
            for turn in range(MAX_TURNS):
                # keep only the 2 newest screenshots in the context
                imgs = [(i, j) for i, m in enumerate(msgs) if isinstance(m["content"], list)
                        for j, b in enumerate(m["content"]) if b.get("type") == "tool_result"
                        and any(x.get("type") == "image" for x in b.get("content", []))]
                for i, j in imgs[:-2]:
                    b = msgs[i]["content"][j]; b["content"] = [x for x in b["content"] if x.get("type") != "image"] + [{"type": "text", "text": "[older screenshot removed]"}]
                resp = llm.messages.create(model=MODEL, max_tokens=1024, system=system, tools=atools, messages=msgs)
                cost += resp.usage.input_tokens * PIN + resp.usage.output_tokens * POUT
                msgs.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
                uses = [b for b in resp.content if b.type == "tool_use"]
                if not uses:
                    msgs.append({"role": "user", "content": "Use a tool: observe, act, or finish."}); continue
                results = []
                for u in uses:
                    args = dict(u.input); args.setdefault("session_id", sid)
                    res = await s.call_tool(u.name, args)
                    a = args.get("action"); log["steps"].append({"turn": turn, "tool": u.name, "action": a if isinstance(a, (str, type(None))) else a.get("type")})
                    print(f"turn {turn}: {u.name} {log['steps'][-1]['action'] or ''}", flush=True)
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": to_blocks(res)})
                    if u.name == "usersim_finish":
                        finished = True; log["finish"] = res.content[0].text[:1500]
                msgs.append({"role": "user", "content": results})
                if finished:
                    break
            if not finished:
                res = await s.call_tool("usersim_finish", {"session_id": sid, "outcome": "gave_up", "notes": f"Haiku driver hit its {MAX_TURNS}-turn cap."})
                log["finish"] = res.content[0].text[:1500]
            log["model_cost_usd"] = round(cost, 4)
            print("FINISH", log["finish"][:800], flush=True)
            print("COST", log["model_cost_usd"], flush=True)
            json.dump(log, open(f"run_{int(time.time())}.json", "w"), indent=1)

asyncio.run(main())
