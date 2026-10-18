"""Live SMS check, no token: lease the number to session A, B is busy, A's wait times out cleanly, A ends -> B gets it.
The phone number is masked in the output (it is the owner's real phone)."""
import asyncio, json, re, time
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
URL = "https://35-202-98-224.sslip.io/mcp"

def mask(d):
    s = json.dumps(d)
    return re.sub(r"\+?\d[\d\s().-]{6,}\d", lambda m: "***" + re.sub(r"\D", "", m.group(0))[-2:], s)

async def call(s, tool, args):
    res = await s.call_tool(tool, args)
    return json.loads(res.content[0].text)

async def main():
    async with streamablehttp_client(URL, timeout=300, sse_read_timeout=600) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            sa = await call(s, "usersim_start_session", {"product_url": "https://example.com", "persona": "Sam.", "task": "SMS lease check A"})
            sb = await call(s, "usersim_start_session", {"product_url": "https://example.com", "persona": "Sam.", "task": "SMS lease check B"})
            a, b = sa["session_id"], sb["session_id"]
            print("sessions A", a[:8], "B", b[:8])
            print("A signup_phone:", mask(await call(s, "usersim_signup_phone", {"session_id": a})))
            print("B signup_phone:", mask(await call(s, "usersim_signup_phone", {"session_id": b})))
            print("B wait_for_sms_code:", mask(await call(s, "usersim_wait_for_sms_code", {"session_id": b, "timeout_s": 10})))
            t = time.time()
            print("A wait_for_sms_code:", mask(await call(s, "usersim_wait_for_sms_code", {"session_id": a, "timeout_s": 20})), f"({time.time()-t:.0f}s)")
            print("A finish:", (await call(s, "usersim_finish", {"session_id": a, "outcome": "gave_up", "notes": "SMS lease check"})).get("study_id"))
            print("B signup_phone after A ended:", mask(await call(s, "usersim_signup_phone", {"session_id": b})))
            print("B finish:", (await call(s, "usersim_finish", {"session_id": b, "outcome": "gave_up", "notes": "SMS lease check"})).get("study_id"))
asyncio.run(main())
