"""Backward browser test (interim, NOT the forward test). This container's own Chromium visits each launched product's live site after launch
and a simulated visitor (Gemini 2.5 Flash, looking at the real screenshot) does six no-account tasks. No signups, no typing, no forms sent,
producthunt.com never loaded. Launches: the complaint_recall test launches that have a resolved site address (sites_ph.jsonl, before Nov 11).
argv: SP [n_launches]"""
import asyncio, json, os, re, sys, time, urllib.request, itertools
SP = sys.argv[1]; NL = int(sys.argv[2]) if len(sys.argv) > 2 else 999; OUT = f"{SP}/bw"; os.makedirs(f"{OUT}/launches", exist_ok=True)
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
sys.path[:0] = [f"{SP}/phweb", f"{SP}/phweb/src"]
from mvp.ph_site import safe_fetch
STEPS = int(os.environ.get("BW_STEPS", 7)); PAR = int(os.environ.get("BW_PAR", 3)); USD_STOP = float(os.environ.get("USD_STOP", 11))
U = {"in": 0, "out": 0, "calls": 0}; usd = lambda: U["in"] / 1e6 * .3 + U["out"] / 1e6 * 2.5; now = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def gem(text, img=None, max_tokens=700):
    parts = [{"text": text}] + ([{"inlineData": {"mimeType": "image/jpeg", "data": img}}] if img else [])
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    err = None
    for i in range(4):
        try:
            req = urllib.request.Request(llm.GEMINI, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r); u = j.get("usageMetadata", {}); U["in"] += u.get("promptTokenCount", 0); U["out"] += u.get("candidatesTokenCount", 0); U["calls"] += 1
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e: err = e; time.sleep(3 * (i + 1))
    raise RuntimeError(f"gemini failed: {str(err)[:100]}")
TASKS = [("a solo founder evaluating tools for a small product", "Work out what this product does and who it is for, from the home page alone."),
         ("a budget-conscious indie maker", "Find what it costs and exactly what is free. Look for limits, trials and whether a card is needed."),
         ("a developer who reads the docs before trying anything", "Find the documentation or help pages and check they explain how to get started."),
         ("someone on a different device than the makers probably use", "Find which platforms, operating systems, browsers or app stores it supports, and whether there is a download."),
         ("a team lead who needs to know who is behind a product and how to reach them", "Find how to contact support, who makes this, and the privacy or security information."),
         ("a curious first-time visitor with five minutes", "Try the product as far as you can without creating an account: any live demo, example, playground or the main call to action. Stop at any sign-up wall and note what it asks for.")]
RULES = """You are one real person visiting a product's website for the first time. Stay in persona. You see a screenshot of a 1280x800 browser and a JSON observation that lists the visible clickable elements with exact x,y.
Choose exactly ONE next step and return JSON only:
{"thought": "<first person, 1-2 sentences>", "tool": "act" | "finish",
 "action": {"type":"click","x":..,"y":..} | {"type":"scroll","dy":700} | {"type":"back"} | {"type":"wait","ms":1500} | {"type":"navigate","url":"<an href you have SEEN in the elements list>"},
 "outcome": "completed" | "gave_up" | "blocked", "notes": "<what was easy or hard, 1-2 sentences>",   // only for finish
 "finding": {"kind": "bug" | "missing" | "confusing" | "question" | "stuck" | "liked", "what": "<specific, under 25 words>"} or null}
Rules: you cannot type, sign up, log in or submit any form in this visit. Never guess URLs. Use the x,y from the elements list.
Report a "finding" whenever something real happens: an error message, a broken or dead link, a failed request, something you looked for and could not find, something unclear, a question you would ask the makers, or something you liked.
If the observation's notes say a link leaves the product site, a new tab was not followed, or a form was not sent, that is this test's own rule and NOT a fault of the product: do not report it as a bug; treat an error page right after such a note the same way and go back.
Finish as soon as the task is done, impossible without an account, or a real person would give up. You have {left} steps left; finish before they run out."""
class Bridge:
    lock = asyncio.Lock()
    async def start(self):
        env = {k: v for k, v in os.environ.items() if k not in ("VERCEL", "VERCEL_ENV")}
        self.p = await asyncio.create_subprocess_exec("node", f"{OUT}/bridge.js", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=open(f"{OUT}/bridge.err", "a"), env=env, cwd=OUT, limit=2**26)
        self.w = {}; self.n = itertools.count(1); await self.p.stdout.readline(); asyncio.create_task(self.loop())
    async def loop(self):
        while True:
            l = await self.p.stdout.readline()
            if not l: break
            try: o = json.loads(l)
            except Exception: continue
            f = self.w.pop(o.get("id"), None)
            if f and not f.done(): f.set_result(o)
    async def call(self, **m):
        async with self.lock:
            if self.p.returncode is not None: print("bridge restart", flush=True); await self.start()
        i = next(self.n); f = asyncio.get_event_loop().create_future(); self.w[i] = f
        try: self.p.stdin.write((json.dumps(dict(m, id=i)) + "\n").encode()); await self.p.stdin.drain()
        except Exception as e: return {"error": "bridge down"}
        try: return await asyncio.wait_for(f, 75)
        except asyncio.TimeoutError: return {"error": "browser timeout"}
async def cell(B, lid, k, url):
    persona, task = TASKS[k]; cid = f"{lid}-{k}"; R = {"task": task, "started": now(), "steps": 0, "findings": [], "outcome": None, "notes": "", "error": None, "ph_requests_blocked": 0}; t0 = time.time()
    try:
        obs = await B.call(op="open", cell=cid, url=url)
        if obs.get("error"): R["error"] = obs["error"]; R["outcome"] = "error"
        else:
            R["http_status"] = obs.get("status"); hist = []; fin = None
            for step in range(STEPS):
                img = obs.pop("shot", None); o = {k2: v for k2, v in obs.items() if v not in (None, [], "") and k2 not in ("id", "status")}
                prompt = RULES.replace("{left}", str(STEPS - step)) + f"\n\nPERSONA: {persona}\nTASK: {task}\n\nWHAT YOU DID SO FAR:\n" + ("\n".join(hist) or "(nothing yet)") + f"\n\nOBSERVATION: {json.dumps(o)[:6000]}"
                try: d = json.loads(re.search(r"\{.*\}", await asyncio.to_thread(gem, prompt, img), re.S).group(0))
                except Exception as e:
                    hist.append(f"{step + 1}. (no valid reply)")
                    if "gemini failed" in str(e): R["error"] = str(e); break
                    continue
                th = str(d.get("thought", ""))[:260]
                if isinstance(d.get("finding"), dict) and d["finding"].get("what"): R["findings"].append({"kind": d["finding"].get("kind"), "what": re.sub(r"@\w+", "", str(d["finding"]["what"]))[:200], "step": step + 1, "url": obs.get("url")})
                if d.get("tool") == "finish": fin = d; break
                a = d.get("action") or {}
                if "producthunt" in json.dumps(a).lower() or a.get("type") not in ("click", "scroll", "back", "wait", "navigate"): hist.append(f"{step + 1}. refused action {str(a)[:80]}"); continue
                obs = await B.call(op="act", cell=cid, action=a); R["steps"] += 1
                if obs.get("error"): R["error"] = obs["error"]; break
                hist.append(f"{step + 1}. {json.dumps(a)[:110]} — {th[:130]}" + (f" [{'; '.join(obs.get('notes') or [])[:140]}]" if obs.get("notes") else ""))
            R["outcome"] = (fin.get("outcome") if fin and fin.get("outcome") in ("completed", "gave_up", "blocked") else "gave_up") if fin else ("error" if R["error"] else "step_cap"); R["notes"] = re.sub(r"@\w+", "", str((fin or {}).get("notes") or ""))[:400]
        c = await B.call(op="close", cell=cid); R["ph_requests_blocked"] = c.get("ph_requests_blocked", 0)
    except Exception as e: R["error"] = f"{type(e).__name__}: {str(e)[:160]}"; R["outcome"] = "error"
    R["seconds"] = round(time.time() - t0, 1); return R
async def launch(B, sem, lid, url, name):
    path = f"{OUT}/launches/{lid}.json"
    if os.path.exists(path): return
    async with sem:
        if usd() > USD_STOP: return
        t0 = time.time(); M = {"launch_id": lid, "name": name, "url": url, "started": now()}
        try: await safe_fetch.check_url(url)
        except Exception as e: M["skipped"] = f"address check: {str(e)[:120]}"; json.dump(M, open(path, "w"), indent=1); return
        M["cells"] = await asyncio.gather(*[cell(B, lid, k, url) for k in range(len(TASKS))]); M["minutes"] = round((time.time() - t0) / 60, 2); M["ended"] = now()
        if sum(c["outcome"] == "error" for c in M["cells"]) >= 3 and not os.environ.get("BW_FINAL"): print(lid, "bridge failure, not saved", flush=True); return
        json.dump(M, open(path, "w"), indent=1); print(lid, name[:24], M["minutes"], [c["outcome"] for c in M["cells"]], sum(c["steps"] for c in M["cells"]), sum(len(c["findings"]) for c in M["cells"]), "usd", round(usd(), 2), flush=True)
async def main():
    import pandas as pd
    T = {json.loads(l)["id"] for l in open(f"{SP}/cr/truth.jsonl")}; S = {}
    for l in open(f"{SP}/rb/h25data/sites_ph.jsonl"):
        r = json.loads(l)
        if str(r.get("status")) == "200" and str(r.get("parked")) != "True" and len(r.get("text") or "") > 500 and str(r.get("url", "")).startswith("http"): S[str(r["id"])] = r["url"]
    X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "name"]); X["id"] = X.id.astype(str); nm = dict(zip(X.id, X.name))
    ids = sorted(i for i in T if i in S)[:NL]; print("launches", len(ids), flush=True)
    B = Bridge(); await B.start(); sem = asyncio.Semaphore(PAR); await asyncio.gather(*[launch(B, sem, i, S[i], nm.get(i, "")) for i in ids])
    try: B.p.stdin.write(b'{"op":"quit"}\n'); await B.p.stdin.drain()
    except Exception: pass
    print("done usd", round(usd(), 2), "calls", U["calls"])
asyncio.run(main())
