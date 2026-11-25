"""PRODUCT-USE-1 runner (PREREG addendum 11). For day D's frozen line-up: every launch x user x {launch, competitor 1, competitor 2}
is one browser session on the UserSim MCP server (seed VMs, Camoufox; producthunt.com blocked in the browser context), driven by
Gemini 2.5 Flash through scripts/mcp_runner_gemini.py and scripts/mcp_study_runner.run_cell (single sessions, no study).

Each user does the same category core task on all three products. After the three sessions, one debrief call per user (Gemini, text
only, temperature 0) reads that user's three traces and returns per product: completion, would-use 0-1, top 3 problems / likes,
artefact tag (signup_wall | captcha | block | js_only | timeout | engine | none) with evidence, plus the preference ordering with
reasons. Access artefacts are kept out of product findings (product findings = problems not tagged as artefacts).

  python runner.py D [--rehearsal] [--max-launches K] [--par P] [--max-usd X]
Traces (private, core IP):  tmp/e5/private/product_use/D/traces/<launch>/<user>_<slot>.json
Outputs (frozen, public):   results/calibration/D/product_use/outputs.json  (aggregates per launch; no person data)
"""
import asyncio, json, os, re, subprocess, sys, time
from pathlib import Path
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "cohort_calibration"))
# MCP bearer token (Shreyas, Nov 25: read usersim-MVP_MCP_TOKEN via gcloud for the product-use test; never print it). Held in this
# process's environment only (mcp_study_runner._headers reads MCP_CLIENT_TOKEN); never logged, written to disk or put in outputs.
if os.environ.get("PU_TOKEN_FROM_SECRET") == "1" and not os.environ.get("MCP_CLIENT_TOKEN"):
    _r = subprocess.run(["gcloud", "secrets", "versions", "access", "latest", "--secret=usersim-MVP_MCP_TOKEN", "--project=project-amer-scs-sandbox"],
                        capture_output=True, text=True)
    _t = [x for x in re.split(r"[ ,]+", _r.stdout.strip()) if x]
    if _t: os.environ["MCP_CLIENT_TOKEN"] = _t[0].split("=", 1)[-1]
    print("mcp token:", "loaded" if _t else "NOT loaded (anonymous caps apply)", flush=True); del _r, _t
import sim_model  # noqa: E402
MAINWT = os.environ.get("PU_MAINWT") or os.path.join(os.environ.get("PU_WORK", "/tmp/pu"), "mainwt")
sys.path.insert(0, os.path.join(MAINWT, "scripts")); sys.path.insert(0, os.path.join(MAINWT, "src")); sys.path.insert(0, MAINWT)
import mcp_study_runner as R  # noqa: E402
from mcp_study_runner_lib import SpendGate  # noqa: E402
from mcp_runner_gemini import GeminiDriver, vertex_client  # noqa: E402

B = "gs://usersim-bakeoff-347838016394/usersim_sim"; PRIV = f"{B}/tmp/e5/private/product_use"
args = [a for a in sys.argv[1:] if not a.startswith("--")]; D = args[0]; REH = "--rehearsal" in sys.argv
opt = lambda k, d: type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
MAXL, PAR, MAXUSD = opt("--max-launches", 15), opt("--par", int(os.environ.get("PU_PAR", "5"))), opt("--max-usd", 14.0)
MAX_TURNS, MAX_CELL_USD = int(os.environ.get("PU_MAX_TURNS", "40")), float(os.environ.get("PU_MAX_CELL_USD", "0.12"))
DEADLINE = pd.Timestamp(os.environ["PU_DEADLINE_UTC"]) if os.environ.get("PU_DEADLINE_UTC") else None   # no new session after this (freeze)
TAG = D + ("_rehearsal" if REH else ""); PUB = f"{B}/{'_rehearsal/' if REH else ''}results/calibration/{D}/product_use"
WORK = Path(os.environ.get("PU_WORK", "/tmp/pu")) / TAG; WORK.mkdir(parents=True, exist_ok=True)
if "claude" in R.MODEL.lower(): sys.exit("RUNNER_MODEL must be Gemini")

LU = json.loads(subprocess.run(["gsutil", "cat", f"{PRIV}/{TAG}/lineup_full.json"], capture_output=True, check=True).stdout)
LAUNCHES = [l for l in LU["launches"]][:MAXL]
USERS = LU["users"]

def task_text(l):
    return (f"{l['core_task']}\n\nThe moment of value for this kind of product: {l['value_moment']}\n\n"
            "Rules: you are trying this product for the first time on its website. Use only free options; never enter payment details. "
            "Sign up only if the product requires it to reach the moment of value. The first time you reach the moment of value, START your thought "
            "for that step with the word VALUE_REACHED. If this product does the job in a different way than described, do the closest "
            "version of the job that this product offers; give up only if it truly does not do this kind of job. If something stops you (a signup wall you cannot pass, a captcha, an access "
            "block, a page that does not load or needs a desktop app or mobile app), finish with outcome 'blocked' and say exactly what stopped you. "
            "Otherwise finish when you have reached the moment of value or decided you cannot.")
def persona_text(u):
    return ("A Product Hunt member who tries new products. What is known about them (their activity before today):\n" + u["profile"][:1800])

CELLS = []
for l in LAUNCHES:
    slots = [("launch", l["url"])] + [(f"comp{k + 1}", c["url"]) for k, c in enumerate(l.get("competitors") or [])]
    for ui, u in enumerate(USERS.get(l["id"], [])[:4]):
        for slot, url in slots:
            if url: CELLS.append({"cell_id": f"{l['id']}_{u['user_key']}_{slot}", "site": url, "persona": persona_text(u), "task": task_text(l),
                                  "_launch": l["id"], "_user": u["user_key"], "_slot": slot, "_wave": 0 if ui == 0 else 1})
# order: round-robin over launches so a budget stop cuts from the bottom of the structural top 15 (spec), not mid-launch
CELLS.sort(key=lambda c: ([x["id"] for x in LAUNCHES].index(c["_launch"]), c["_user"], c["_slot"]))

FULL = {}   # session_id -> [(tool, full thought or notes)]
def _wrap(llm):
    orig = llm.messages.create
    def create(*a, **k):
        resp = orig(*a, **k)
        for b in resp.content:
            if getattr(b, "type", "") == "tool_use" and isinstance(b.input, dict) and b.input.get("session_id"):
                FULL.setdefault(b.input["session_id"], []).append((b.name, str(b.input.get("thought") or b.input.get("notes") or "")[:1200], b.input.get("outcome")))
        return resp
    llm.messages.create = create; return llm

async def main():
    llm = GeminiDriver(vertex_client(os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"), os.environ.get("RUNNER_LOCATION", "global")))
    llm = _wrap(llm)
    gate = SpendGate(max_usd=MAXUSD, max_retries=200); sem = asyncio.Semaphore(PAR); out = WORK / "cells"; out.mkdir(exist_ok=True)
    async def one(c):
        f = out / f"{c['cell_id']}.json"
        if f.exists(): return json.loads(f.read_text())
        async with sem:
            if gate.over_cap(): return {"cell": c, "error": "budget stop"}
            if DEADLINE and pd.Timestamp.now(tz="UTC") > DEADLINE: return {"cell": c, "error": "deadline stop (freeze)"}
            t0 = time.time()
            try: log = await R.run_cell("", {k: v for k, v in c.items() if not k.startswith("_")}, MAX_TURNS, MAX_CELL_USD, out, llm, gate)
            except Exception as e: log = {"cell": c, "error": "runner: " + repr(e)[:300]}
            log["cell"] = c; log["wall_s"] = round(time.time() - t0); log["full"] = FULL.get(log.get("session_id"), []); f.write_text(json.dumps(log, default=str)); return log
    # wave 1: each launch's first user on every site (creates the account when a site needs one); wave 2: the other users log in to that
    # account (same_account_as) instead of signing up again (4 signups per site from one IP triggered rate limits and captchas, Nov 24 rehearsal)
    w1 = await asyncio.gather(*[one(c) for c in CELLS if c["_wave"] == 0])
    acct = {}
    for lg in w1:
        if lg.get("session_id"): acct.setdefault(lg["cell"]["site"], lg["session_id"])
    w2c = []
    for c in CELLS:
        if c["_wave"] == 1:
            c = dict(c)
            if c["site"] in acct:
                c["task"] += (f"\n\nAccount: another tester already tried this site. If it needs an account, call usersim_signup_identity with "
                              f"same_account_as=\"{acct[c['site']]}\" and log in with the account it returns; sign up yourself only if that fails.")
            w2c.append(c)
    w2 = await asyncio.gather(*[one(c) for c in w2c])
    return list(w1) + list(w2), gate.total_usd

t0 = time.time(); LOGS, USD = asyncio.run(main())
by = {}
for lg in LOGS: c = lg["cell"]; by.setdefault((c["_launch"], c["_user"]), {})[c["_slot"]] = lg

def brief(lg):
    st = lg.get("steps") or []; full = lg.get("full") or []
    th = [f[1] for f in full if f[0] == "usersim_act"] or [(s.get("args") or {}).get("thought") or s.get("thought") or "" for s in st if s.get("tool") == "usersim_act"]
    v = next((k for k, t in enumerate(th) if "VALUE_REACHED" in (t or "")[:40]), None)
    notes = next((f[1] for f in full if f[0] == "usersim_finish"), None) or next(((s.get("args") or {}).get("notes") for s in st if s.get("tool") == "usersim_finish"), "")
    outcome = next((f[2] for f in full if f[0] == "usersim_finish"), None) or next(((s.get("args") or {}).get("outcome") for s in st if s.get("tool") == "usersim_finish"), None)
    errs = sum(1 for s in st if s.get("rejected") or "error" in str(s.get("result", ""))[:200].lower())
    return {"n_steps": len(th), "steps_to_value": (v + 1) if v is not None else None, "seconds": lg.get("seconds") or lg.get("wall_s"),
            "error_steps": errs, "engine_error": lg.get("error"), "outcome": outcome, "finish": f"outcome={outcome}; notes: {notes}"[:1200],
            "thoughts": [f"{k + 1}. {t[:260]}" for k, t in enumerate(th)][:45]}

DEBRIEF = """You are {who}. Today you tried three products for the same job, one after another. Here is your own step log for each.
Job: {task}

{blocks}

Answer as this person, honestly, from what happened in the logs only. For each product, first decide whether you were stopped by an ACCESS
ARTEFACT rather than by the product itself: signup_wall (needed an account you could not create or verify), captcha, block (access denied,
bot check, region block), js_only (page did not render or needed an app/desktop download), timeout (ran out of steps/time while the page
was still loading), engine (the browser session failed to start or crashed), or none. Problems caused by an artefact go in "artefact_evidence",
NOT in "problems". Problems are about the product: its onboarding, clarity, features, speed, output quality, pricing seen, etc.
Reply JSON only:
{{"products": {{"A": {{"completed": true|false, "artefact": "...", "artefact_evidence": "...", "would_use": 0.0-1.0,
  "value_step": <number of the step in that product's log where you first got the job's result, or null>,
  "problems": ["...", "...", "..."], "likes": ["...", "...", "..."]}}, "B": {{...}}, "C": {{...}}}},
 "preference": [all three of "A","B","C", the one you would choose for this job first; a product that could not do the job for you
   ranks below those that could; break ties by which you would rather try again], "reasons": {{"A_vs_B": "...", "A_vs_C": "..."}}}}"""

rows, deb_usd = [], 0.0
for l in LAUNCHES:
    names = {"launch": l["name"], **{f"comp{k + 1}": c["name"] for k, c in enumerate(l.get("competitors") or [])}}
    for u in USERS.get(l["id"], [])[:4]:
        S = by.get((l["id"], u["user_key"]), {}); lab = {"launch": "A", "comp1": "B", "comp2": "C"}
        if not S: continue
        bl = []
        for slot, lg in S.items():
            b = brief(lg); S[slot]["_brief"] = b
            bl.append(f"Product {lab[slot]} ({names[slot]}, {lg['cell']['site']}):\nsteps {b['n_steps']}, engine error: {b['engine_error']}\n"
                      + "\n".join(b["thoughts"]) + f"\nFinish: {b['finish'][:700]}")
        p = DEBRIEF.format(who="the person described here: " + u["profile"][:600], task=l["core_task"], blocks="\n\n".join(bl))
        r = sim_model.call(p, max_tokens=1500, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
        try: dj = json.loads(m.group(0))
        except Exception: dj = {"parse_error": (r or "")[:300]}
        inv = {v: k for k, v in lab.items()}
        for slot, lg in S.items():
            pj = (dj.get("products") or {}).get(lab[slot], {}); b = lg["_brief"]
            art = pj.get("artefact") or ("engine" if b["engine_error"] else "none")
            rows.append({"launch_id": l["id"], "structural_rank": l["structural_rank"], "category": l["category"], "user": u["user_key"], "slot": slot,
                         "product": names[slot], "url": lg["cell"]["site"], "artefact": art, "artefact_evidence": pj.get("artefact_evidence"),
                         "completed": pj.get("completed"), "would_use": pj.get("would_use"), "problems": pj.get("problems") or [], "likes": pj.get("likes") or [],
                         "driver_outcome": b["outcome"], "n_steps": b["n_steps"], "steps_to_value": (pj.get("value_step") if isinstance(pj.get("value_step"), int) else b["steps_to_value"]), "seconds": b["seconds"], "error_steps": b["error_steps"],
                         "pref_rank": ([inv.get(x) for x in dj.get("preference") or []].index(slot) + 1) if slot in [inv.get(x) for x in dj.get("preference") or []] else None,
                         "n_ranked": len(dj.get("preference") or []), "reasons": dj.get("reasons")})
        # private trace store: full logs + debrief, per user and product
        for slot, lg in S.items():
            t = WORK / f"trace_{l['id']}_{u['user_key']}_{slot}.json"; lg2 = {k: v for k, v in lg.items() if k != "_brief"}
            t.write_text(json.dumps({"log": lg2, "debrief": dj, "lineup_day": D}, default=str))
            subprocess.run(["gsutil", "-q", "cp", str(t), f"{PRIV}/{TAG}/traces/{l['id']}/{u['user_key']}_{slot}.json"])

R_ = pd.DataFrame(rows)
def agg(g):
    a = g[g.slot == "launch"]; ok = a[a.artefact == "none"]
    return pd.Series({"n_user_sessions": len(a), "artefact_rate": round(float((a.artefact != "none").mean()), 3) if len(a) else None,
                      "would_use": round(float(ok.would_use.astype(float).mean()), 3) if len(ok) else None,
                      "pref_score": round(float(((ok.n_ranked - ok.pref_rank) / (ok.n_ranked - 1).clip(lower=1)).mean()), 3) if len(ok) and ok.pref_rank.notna().any() else None,
                      "completion": round(float(ok.completed.astype(bool).mean()), 3) if len(ok) else None,
                      "steps_to_value_med": float(ok.steps_to_value.median()) if ok.steps_to_value.notna().any() else None,
                      "competitor_artefact_rate": round(float((g[g.slot != "launch"].artefact != "none").mean()), 3) if (g.slot != "launch").any() else None})
A = R_.groupby("launch_id").apply(agg).reset_index() if len(R_) else pd.DataFrame()
if len(A): A["sim_score"] = A.would_use.fillna(A.would_use.median()) * A.pref_score.fillna(0.5)     # pre-registered re-order key: would-use x preference
commit = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or os.environ.get("PU_COMMIT", "")
OUT = {"day": D, "rehearsal": REH, "frozen_at": pd.Timestamp.now(tz="UTC").isoformat(),
       "freeze_deadline": pd.Timestamp(D + " 03:30", tz="America/Los_Angeles").tz_convert("UTC").isoformat(), "code_commit": commit,
       "lineup_frozen_at": LU["frozen_at"], "n_cells": len(CELLS), "n_sessions_run": sum(1 for x in LOGS if x.get("session_id")),
       "model_usd_sessions": round(USD, 3), "minutes": round((time.time() - t0) / 60, 1), "driver_model": R.MODEL,
       "launches": A.to_dict("records") if len(A) else [],
       "findings": R_[["launch_id", "slot", "product", "category", "artefact", "completed", "would_use", "problems", "likes", "steps_to_value", "n_steps", "error_steps", "pref_rank", "n_ranked"]].to_dict("records") if len(R_) else []}
OUT["on_time"] = OUT["frozen_at"] <= OUT["freeze_deadline"]
p = WORK / "outputs.json"; p.write_text(json.dumps(OUT, indent=1, default=str)); subprocess.run(["gsutil", "-q", "cp", str(p), f"{PUB}/outputs.json"])
print(json.dumps({k: OUT[k] for k in ("day", "n_cells", "n_sessions_run", "model_usd_sessions", "minutes", "on_time")},
                 default=str), "artefacts:", R_.artefact.value_counts().to_dict() if len(R_) else {})
