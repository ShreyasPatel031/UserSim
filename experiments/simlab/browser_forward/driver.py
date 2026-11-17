"""Forward browser test driver. A simulated user (Gemini 2.5 Flash, looking at the real screenshots) operates a launched product in UserSim's
recorded cloud browser through the public MCP server. One study per launch (the engine plans 6 users and 6 tasks and shares one signup per
site); only the cells on the launch's own product are run. The browser is never allowed onto producthunt.com.
argv: SP launch_id product_url name out_dir [max_cells]"""
import asyncio, base64, json, os, re, sys, time, urllib.request
SP, LID, URL0, NAME, OUT = sys.argv[1:6]; MAXC = int(sys.argv[6]) if len(sys.argv) > 6 else 36
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
MCP = "https://35-202-98-224.sslip.io/mcp"; STEPS = int(os.environ.get("BF_STEPS", 25)); PAR = int(os.environ.get("BF_PAR", 18)); USD_STOP = float(os.environ.get("USD_STOP", 3))
U = {"in": 0, "out": 0, "calls": 0}; usd = lambda: U["in"] / 1e6 * .3 + U["out"] / 1e6 * 2.5; now = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def gem(text, img=None, max_tokens=1200):
    parts = [{"text": text}] + ([{"inlineData": {"mimeType": "image/jpeg", "data": img}}] if img else [])
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    for i in range(4):
        try:
            req = urllib.request.Request(llm.GEMINI, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r); u = j.get("usageMetadata", {}); U["in"] += u.get("promptTokenCount", 0); U["out"] += u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0); U["calls"] += 1
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e: time.sleep(3 * (i + 1)); err = e
    raise RuntimeError(f"gemini failed: {str(err)[:100]}")
def rpc(name, args):
    err = None
    for i in range(3):
        try:
            req = urllib.request.Request(MCP, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode(), {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
            with urllib.request.urlopen(req, timeout=300) as r: j = json.load(r)
            if "error" in j: return {"error": str(j["error"])[:300]}, None
            c = j["result"].get("content", []); txt = "".join(x.get("text", "") for x in c if x.get("type") == "text"); img = next((x.get("data") for x in c if x.get("type") == "image"), None)
            try: return json.loads(txt), img
            except Exception: return {"error": txt[:300]}, img
        except Exception as e: err = e; time.sleep(4 * (i + 1))
    return {"error": f"transport: {str(err)[:150]}"}, None
async def tool(s, name, args): return await asyncio.to_thread(rpc, name, args)
RULES = """You are playing one real person trying a product for the first time. Stay in persona. You see a screenshot of a 1280x800 browser and a JSON observation.
Choose exactly ONE next step and return JSON only:
{"thought": "<first person, 1-2 sentences: what you see, expect, or find confusing>",
 "tool": "act" | "signup_identity" | "wait_code" | "wait_link" | "open_link" | "solve_captcha" | "finish",
 "action": {...},            // only for tool "act"
 "url": "...",               // only for open_link: a link returned by wait_link
 "outcome": "completed" | "gave_up" | "blocked", "notes": "...",   // only for finish
 "finding": {"kind": "stuck" | "bug" | "missing" | "confusing" | "question" | "liked", "what": "<specific, under 25 words>"} or null}
Actions for "act": {"type":"click","x":..,"y":..} | {"type":"type","text":"..","x":..,"y":..,"submit":false} | {"type":"key","keys":"Enter"} | {"type":"scroll","dy":600} | {"type":"back"} | {"type":"wait","ms":1500} | {"type":"select","x":..,"y":..,"option":".."} | {"type":"navigate","url":"<a URL on the product's own site that you have SEEN on the page>"}
Rules: use the exact x,y of fields listed in the observation. Never guess URLs. Email sign-up only, never Google or GitHub sign-in: call signup_identity to get the email, password and name to type, then wait_code or wait_link for the verification mail. After submitting a form, wait instead of clicking again. If a captcha blocks you, try solve_captcha once or twice, then finish as blocked. Never open producthunt.com.
Report a "finding" whenever something real happens: an error, a dead end, something you looked for and could not find, something unclear, a question you would ask the makers, or something you liked. Finish as soon as the task is done, impossible, or a real person would give up. You have {left} steps left."""
async def cell(study_id, c, sem, rec):
    async with sem:
        R = {"cell_id": c["cell_id"], "persona": c.get("persona"), "task": c.get("task"), "started": now(), "steps": 0, "findings": [], "thoughts": [], "outcome": None, "notes": "", "error": None}
        if usd() > USD_STOP: R["error"] = "gemini budget stop"; rec.append(R); return
        try:
            if True:
                if True:
                    s = None
                    for _try in range(14):
                        obs, img = await tool(s, "usersim_start_session", {"study_id": study_id, "cell_id": c["cell_id"]})
                        if not obs.get("error") or not any(k in str(obs["error"]).lower() for k in ("queued", "limit", "token", "busy", "transport")): break
                        await asyncio.sleep(45)
                    if obs.get("error"): R["error"] = "start: " + str(obs["error"])[:200]; rec.append(R); return
                    sid = obs["session_id"]; R["persona"] = obs.get("persona") or R["persona"]; R["task"] = obs.get("task") or R["task"]; hist = []; extra = ""; fin = None
                    for step in range(STEPS):
                        o = {k: obs.get(k) for k in ("url", "title", "fields", "unfilled_fields", "page_errors", "note", "email_hint", "captcha", "action_error", "steps_left") if obs.get(k)}
                        prompt = RULES.replace("{left}", str(STEPS - step)) + f"\n\nPERSONA: {R['persona']}\nTASK: {R['task']}\n\nWHAT YOU DID SO FAR:\n" + ("\n".join(hist[-10:]) or "(nothing yet)") + (f"\n\nRESULT OF YOUR LAST TOOL CALL: {extra}" if extra else "") + f"\n\nOBSERVATION: {json.dumps(o)[:5000]}"
                        try: d = json.loads(re.search(r"\{.*\}", await asyncio.to_thread(gem, prompt, img), re.S).group(0))
                        except Exception as e: hist.append(f"{step + 1}. (my reply was not valid JSON)"); continue
                        th = str(d.get("thought", ""))[:300]; R["thoughts"].append(th); t = d.get("tool"); extra = ""
                        if isinstance(d.get("finding"), dict) and d["finding"].get("what"): R["findings"].append({"kind": d["finding"].get("kind"), "what": str(d["finding"]["what"])[:200], "step": step + 1, "at": now(), "url": obs.get("url")})
                        if t == "finish": fin = d; break
                        if "producthunt.com" in json.dumps(d).lower(): hist.append(f"{step + 1}. refused: producthunt.com is not allowed"); continue
                        if t == "act": obs2, img2 = await tool(s, "usersim_act", {"session_id": sid, "action": d.get("action") or {}, "thought": th or "I continue."}); R["steps"] += 1
                        elif t == "signup_identity": obs2, img2 = await tool(s, "usersim_signup_identity", {"session_id": sid, "no_plus": bool(obs.get("email_hint"))}); extra = json.dumps({k: obs2.get(k) for k in ("email", "password", "name", "first_name", "last_name", "username", "next", "error") if obs2.get(k)}); obs2, img2 = obs, img
                        elif t in ("wait_code", "wait_link"): r2, _i = await tool(s, "usersim_wait_for_verification_" + t[5:], {"session_id": sid, "timeout_s": 45}); extra = json.dumps({k: r2.get(k) for k in ("found", "code", "links", "subject", "note", "error") if r2.get(k) is not None})[:900]; obs2, img2 = obs, img
                        elif t == "open_link": obs2, img2 = await tool(s, "usersim_open_verification_link", {"session_id": sid, "url": d.get("url", ""), "thought": th or "I click the link in the email."}); R["steps"] += 1
                        elif t == "solve_captcha": obs2, img2 = await tool(s, "usersim_solve_captcha", {"session_id": sid}); R["steps"] += 1
                        else: hist.append(f"{step + 1}. (unknown tool {t})"); continue
                        if obs2.get("error"): extra = (extra + " ERROR: " + str(obs2["error"])[:300]).strip(); obs2, img2 = obs, img
                        hist.append(f"{step + 1}. {t} {json.dumps(d.get('action') or d.get('url') or '')[:160]} — {th[:140]}" + (f" -> {str(obs2.get('action_error'))[:120]}" if obs2.get("action_error") else "")); obs, img = obs2, img2 or img
                    out = (fin or {}).get("outcome") if (fin or {}).get("outcome") in ("completed", "gave_up", "blocked") else "gave_up"
                    R["outcome"] = out if fin else "step_cap"; R["notes"] = str((fin or {}).get("notes") or "Ran out of steps before finishing.")[:600]
                    f, _i = await tool(s, "usersim_finish", {"session_id": sid, "outcome": out, "notes": R["notes"]}); R["judge"] = {k: f.get(k) for k in ("goal_reached", "proof_pass", "error") if f.get(k) is not None}
        except Exception as e: R["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        R["ended"] = now(); rec.append(R); print(c["cell_id"], R["outcome"], R["steps"], len(R["findings"]), R["error"] or "", round(usd(), 2), flush=True)
async def main():
    os.makedirs(OUT, exist_ok=True); t0 = time.time(); meta = {"launch_id": LID, "name": NAME, "product_url": URL0, "started": now(), "step_cap": STEPS}
    st, _i = await tool(None, "usersim_start_study", {"product_url": URL0, "personas": [], "tasks": [], "competitors": []})
    if st.get("error") or not st.get("cells"): meta["error"] = str(st.get("error") or st)[:400]; json.dump(meta, open(f"{OUT}/{LID}.json", "w"), indent=1); print("study error", meta["error"]); return
    cells = st["cells"]; host = lambda u: re.sub(r"^www\.", "", re.sub(r"^https?://", "", str(u or "")).split("/")[0].lower()); h0 = host(URL0)
    print("cell keys", list(cells[0].keys()), {host(c.get("site") or c.get("product_url") or c.get("url")) for c in cells}, flush=True)
    mine = [c for c in cells if host(c.get("site") or c.get("product_url") or c.get("url")) == h0][:MAXC]
    meta.update({"study_id": st["study_id"], "cells_total": len(cells), "cells_on_product": len(mine), "rules": st.get("rules")}); sem = asyncio.Semaphore(PAR); rec = []
    await asyncio.gather(*[cell(st["study_id"], c, sem, rec) for c in mine])
    fs, _i = await tool(None, "usersim_finish_study", {"study_id": st["study_id"]})
    meta.update({"ended": now(), "minutes": round((time.time() - t0) / 60, 1), "gemini_usd": round(usd(), 3), "gemini_calls": U["calls"], "engine_est_usd": round(sum(0.05 + 0.005 * x["steps"] for x in rec), 2), "cells": rec})
    json.dump(meta, open(f"{OUT}/{LID}.json", "w"), indent=1); oc = {}
    for x in rec: oc[x["outcome"] or "error"] = oc.get(x["outcome"] or "error", 0) + 1
    print("DONE", meta["minutes"], "min", oc, "steps", sum(x["steps"] for x in rec), "findings", sum(len(x["findings"]) for x in rec), "gemini $", meta["gemini_usd"], "engine est $", meta["engine_est_usd"])
asyncio.run(main())
