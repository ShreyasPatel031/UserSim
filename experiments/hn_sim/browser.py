"""One browser run in Atelier human mode: the public UserSim MCP server (recorded Browserbase browser, the product's
own runner and judge), driven by Gemini 2.5 Flash. The server's usersim_simulate_user prompt is the system prompt, so
the run follows the same rules as product runs. Same code path for past (snapshot URL) and live (product URL) inputs.

run(url, persona, task, max_actions) -> {session_id, steps, outcome, notes, observations, seconds, model_usd, ...}
A captcha stops the run (no paid solving). Sign-up only through usersim_signup_identity (usersim.signups aliases)."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import llm

URL = os.environ.get("USERSIM_MCP_URL", "https://35-202-98-224.sslip.io/mcp")
TOOLS = {"act": "usersim_act", "signup_identity": "usersim_signup_identity",
         "wait_for_verification_code": "usersim_wait_for_verification_code",
         "wait_for_verification_link": "usersim_wait_for_verification_link",
         "open_verification_link": "usersim_open_verification_link"}

PROTOCOL = """You drive the browser by returning ONE JSON object per turn:
{{"thought": "<first person, what you see / expect / find confusing>",
  "tool": "act" | "signup_identity" | "wait_for_verification_code" | "wait_for_verification_link" | "open_verification_link" | "finish",
  "args": {{...}}}}
- act: args = {{"action": {{"type": "click", "x": 640, "y": 400}}}} (types: click, double_click, type {{text,x,y,submit}},
  key {{keys}}, scroll {{dy}}, back, wait {{ms}}, select {{x,y,option}}, navigate {{url}} on the same site only).
- signup_identity: args = {{}} (fresh email + password to type). Only if the product needs an account and has a free plan.
- open_verification_link: args = {{"url": "<link from the mail>"}}.
- finish: args = {{"outcome": "completed" | "gave_up" | "blocked", "notes": "what was easy, hard, confusing, missing"}}.
You have at most {max_actions} actions in total; finish before running out. Never pay, never enter a card, never invite
anyone, never use Google/GitHub sign-in. If a captcha appears, finish with outcome "blocked"."""

OBSERVE = """You just used {url} as this person:
{persona}
Your step log:
{log}
Your notes: {notes}
Report 3-8 observations about the product itself, from what you actually saw, as
{{"observations": [{{"kind": "product_friction" | "product_benefit" | "signup_friction" | "agent_failure",
"feature": "...", "what": "one specific sentence"}}], "worked": true/false (did the product load and do its job at all)}}.
Your own misclicks are agent_failure. No ratings."""


def _meta(res) -> tuple[dict, bytes | None, str]:
    txt, img = "", None
    for c in res.content:
        if c.type == "text":
            txt += c.text
        elif c.type == "image":
            img = base64.b64decode(c.data)
    try:
        d = json.loads(txt)
    except ValueError:
        d = {}
    return (d if isinstance(d, dict) else {}), img, txt


def _brief(d: dict, raw: str) -> str:
    if not d:
        return raw[:600]
    keep = {k: d[k] for k in ("url", "title", "steps_left", "seconds_left", "page_errors", "note", "email_hint",
                              "captcha", "action_error", "unfilled_fields", "email", "code", "links", "error") if d.get(k)}
    keep["fields"] = [{k: f.get(k) for k in ("kind", "label", "x", "y", "filled", "options") if f.get(k) is not None}
                      for f in (d.get("fields") or [])[:25]]
    return json.dumps(keep)[:2500]


async def _run(url: str, persona: str, task: str, max_actions: int, tag: str) -> dict:
    t0 = time.time()
    usd = 0.0
    out = {"url": url, "persona": persona, "task": task, "tag": tag, "steps": [], "outcome": None, "notes": "",
           "error": None, "session_id": None}
    async with streamable_http_client(URL) as streams:
        r, w = streams[0], streams[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("usersim_start_session", {"product_url": url, "persona": persona, "task": task})
            d, img, raw = _meta(res)
            if not d.get("session_id"):
                out["error"] = f"start failed: {raw[:300]}"
                return out
            sid = out["session_id"] = d["session_id"]
            out["watch_url"] = d.get("watch_url")
            p = await s.get_prompt("usersim_simulate_user", {"session_id": sid, "persona": persona, "task": task})
            system = "".join(m.content.text for m in p.messages if getattr(m.content, "type", "") == "text")
            system += "\n\n" + PROTOCOL.format(max_actions=max_actions)
            last, acts = _brief(d, raw), 0
            for turn in range(max_actions + 6):
                hist = "\n".join(f"{i + 1}. {st['tool']} {json.dumps(st['args'])[:160]} | thought: {st['thought'][:160]}"
                                 f" | result: {st['result'][:160]}" for i, st in enumerate(out["steps"][-10:]))
                prompt = (f"Steps so far (latest last):\n{hist or '(none)'}\n\nCurrent page:\n{last}\n\n"
                          f"Actions used: {acts} of {max_actions}. Return the next JSON object.")
                j = await asyncio.to_thread(llm.call, "browser_driver", prompt, system=system, model=llm.FLASH,
                                            temperature=0.3, images=[img] if img else None, cache=False, max_tokens=1024)
                usd += j.get("_usd", 0)
                tool, args, thought = j.get("tool"), j.get("args") or {}, str(j.get("thought") or "")
                if d.get("captcha") and tool != "finish":
                    tool, args = "finish", {"outcome": "blocked", "notes": "captcha: stopped by policy"}
                if acts >= max_actions and tool != "finish":
                    tool, args = "finish", {"outcome": "gave_up", "notes": "action budget used up. " + thought}
                if tool == "finish" or tool not in TOOLS:
                    out["outcome"] = args.get("outcome") if tool == "finish" else "gave_up"
                    out["notes"] = str(args.get("notes") or thought)
                    fin = await s.call_tool("usersim_finish", {"session_id": sid, "outcome": out["outcome"] or "gave_up",
                                                               "notes": out["notes"][:2000]})
                    out["finish"] = _meta(fin)[2][:500]
                    break
                a = {"session_id": sid, **args}
                if tool == "act":
                    a.setdefault("thought", thought or "I continue.")
                    acts += 1
                elif tool == "open_verification_link":
                    a["thought"] = thought or "I open the link in the email."
                    acts += 1
                try:
                    res = await s.call_tool(TOOLS[tool], a)
                    d2, img2, raw2 = _meta(res)
                except Exception as exc:  # noqa: BLE001
                    d2, img2, raw2 = {}, None, f"error: {exc}"
                if img2:
                    img, d = img2, d2
                last = _brief(d2, raw2) if d2 or raw2 else last
                out["steps"].append({"tool": tool, "args": args, "thought": thought, "result": last[:300],
                                     "url": d2.get("url")})
    out["seconds"] = round(time.time() - t0, 1)
    out["actions"] = sum(1 for st in out["steps"] if st["tool"] in ("act", "open_verification_link"))
    log = "\n".join(f"- {st['thought'][:200]}" for st in out["steps"])
    o = await asyncio.to_thread(llm.call, "browser_observe", OBSERVE.format(url=url, persona=persona, log=log or "(none)",
                                                                          notes=out["notes"]), model=llm.FLASH, cache=False)
    usd += o.get("_usd", 0)
    out["observations"] = [x for x in o.get("observations") or [] if isinstance(x, dict)]
    out["worked"] = bool(o.get("worked"))
    out["model_usd"] = round(usd, 5)
    return out


def run(url: str, persona: str, task: str, max_actions: int = 20, tag: str = "") -> dict:
    try:
        return asyncio.run(_run(url, persona, task, max_actions, tag))
    except BaseException as exc:  # noqa: BLE001
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        return {"url": url, "persona": persona, "task": task, "tag": tag, "error": f"{type(exc).__name__}: {exc}"[:400],
                "steps": [], "observations": [], "worked": False}


if __name__ == "__main__":
    import sys
    r = run(sys.argv[1], "A software engineer who reads Hacker News and tries new tools.",
            "Try this product the way you would after seeing it on Show HN.", max_actions=int(sys.argv[2]))
    print(json.dumps({k: v for k, v in r.items() if k != "steps"}, indent=1)[:3000])
    for st in r["steps"]:
        print(st["tool"], json.dumps(st["args"])[:100], "|", st["thought"][:120])
