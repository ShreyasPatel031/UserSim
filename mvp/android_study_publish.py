"""Publish an Android study (results/android_study/final) as a standard compare study for /report?study=<id>.

Usage: PYTHONPATH=src:. python -m mvp.android_study_publish [upload] [study_id]
"""
import asyncio, json, sys, time, uuid
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/home/ubuntu/repos/UserSim")
F = ROOT / "results/android_study/final"
cfg = json.load(open(ROOT / "results/android_study/config.json"))
rows = json.load(open(F / "rows.json"))
SID = sys.argv[2] if len(sys.argv) > 2 else str(uuid.uuid4())
UPLOAD = len(sys.argv) > 1 and sys.argv[1] == "upload"

apps = cfg["apps"]
keys = ["product"] + [f"competitor_{i}" for i in range(1, len(apps))]
site = {a["name"]: (k, a["web"], a["name"] if k != "product" else "Product", a) for k, a in zip(keys, apps)}
tasks_cfg = [t if isinstance(t, str) else (t.get("prompt") or t.get("title")) for t in cfg["tasks"]]
segment = cfg.get("segment") or "Adults who want to cut back on or quit drinking, comparing sobriety apps on Android"
now = datetime.now(timezone.utc).isoformat()

personas = []
for i, p in enumerate(cfg["personas"]):
    fav = p.get("favors") or ""
    fav_url = next((a["web"] for a in apps if a["name"] == fav), "")
    personas.append({"id": f"p{i+1}", "name": p["name"], "bio": p.get("bio", ""), "occupation": p.get("role", ""),
                     "age_range": "", "location": "", "goals": ["Decide which app fits", "Notice what is confusing"],
                     "favors": "product" if fav == apps[0]["name"] else fav_url, "favors_why": ""})
pid = {p["name"]: p["id"] for p in personas}
pobj = {p["id"]: p for p in personas}

def shot(aid, name):
    return f"/api/studies/{SID}/agents/{aid}/screenshots/{name}"

tasks, results, live, uploads = [], [], [], []
for r in rows:
    k, url, label, app = site[r["app"]]
    ti = tasks_cfg.index(r["task"]) + 1
    p = pid[r["persona"]]
    aid = f"t{ti}__{p}__{k}"
    run = Path(r["run_dir"])
    tr = json.load(open(run / "trace.json"))
    trace = []
    for h in tr.get("history") or []:
        n = int(h.get("step") or len(trace) + 1)
        png = run / f"{n:02d}.png"
        act = h.get("action") or ""
        if h.get("text") and act in ("type",):
            act = f"type {h['text']!r}"[:120]
        st = {"step": n, "action": f"{act} — {h.get('reason','')}"[:300] if act else (h.get("reason") or "")[:300],
              "thought": h.get("reason", ""), "observation": h.get("reason", ""), "url": url,
              "outcome": h.get("result", "")}
        if png.exists():
            st["screenshot_url"] = st["step_screenshot_url"] = shot(aid, f"step_{n}.png")
            uploads.append((png, aid, f"step_{n}.png"))
        trace.append(st)
    if (run / "final.png").exists():
        uploads.append((run / "final.png", aid, "final.png"))
        for st in trace:
            st["final_screenshot_url"] = shot(aid, "final.png")
    sc = dict(r.get("score") or {})
    sc.setdefault("model", "gemini-2.5-flash")
    sc["scored_at_ts"] = time.time()
    common = {"agent_id": aid, "persona_id": p, "persona_name": r["persona"], "persona_bio": pobj[p]["bio"],
              "task_id": aid, "task_title": r["task"], "task_prompt": r["task"],
              "site_key": k, "site_url": url, "site_label": label}
    task = {"id": aid, "title": r["task"], "prompt": r["task"], "persona_id": p, "difficulty_hint": "medium",
            "favors": "product", "favors_why": "", "site_key": k, "site_url": url, "site_label": label}
    tasks.append(task)
    ok = bool(r.get("ok"))
    res = {**common, "completed": ok, "agent_claimed_done": ok, "final_url": url, "visited_urls": [url],
           "opened_url": url, "current_url": url, "page_url": url,
           "needs_account": False, "actions": [{"action": s["action"]} for s in trace], "trace": trace,
           "backend": "android_emulator", "model": "gemini-2.5-flash", "model_provider": "vertex",
           "num_steps": int(r.get("steps") or len(trace)), "stop_reason": r.get("reason") or "",
           "friction_points": [sc["friction_note"]] if sc.get("friction_note") else [],
           "what_was_easy": [], "quote": sc.get("quote", ""), "product_feedback": r.get("summary", ""),
           "final_screenshot_url": shot(aid, "final.png"), "final_screenshot": shot(aid, "final.png"),
           "page_verdict": {"goal_reached": ok, "still_on_opening_screen": False, "reason": r.get("summary", "")},
           "comparison_score": sc, "mode": "native_app", "difficulty": "medium", "error": "", "browser_error": "",
           "phase": "done", "duration_s": r.get("seconds"), "app_package": app["package"], "platform": "android"}
    results.append(res)
    live.append({**common, "status": "done", "trace": trace, "num_steps": res["num_steps"],
                 "final_screenshot": res["final_screenshot"], "final_url": url})

seen = set(); tasks = [t for t in tasks if not (t["id"] in seen or seen.add(t["id"]))]
study = {"id": SID, "url": apps[0]["web"], "segment": segment, "status": "complete", "phase": "Complete",
         "created_at": now, "updated_at": now, "personas": personas, "tasks": tasks, "agent_results": results,
         "live_sessions": live, "activity_log": [], "error": None, "access_backend": "android_emulator",
         "competitors": [a["web"] for a in apps[1:]], "study_mode": "compare", "product_name": apps[0]["name"],
         "competitor_names": {a["web"]: a["name"] for a in apps[1:]},
         "task_specs": [{"prompt": t, "favors": "product", "favors_why": ""} for t in tasks_cfg],
         "competitor_cells": [], "skip_competitors": False, "test_mode": False, "backend": "android_emulator",
         "kill_requested": False, "created_at_ts": time.time(), "completed_at_ts": time.time(),
         "platform": "android", "title": cfg.get("title", "")}

async def finalize():
    from mvp.study import synthesize_summary, _summary_from_agent_results
    from mvp.report_insights import build_report_insights, write_verdict_summary
    from mvp.comparison import apply_comparison_llm
    from mvp.a11y_agent import failure_breakdown
    try:
        s = await synthesize_summary(url=study["url"], segment=segment,
                                     site_summary=f"{cfg.get('title','')} — native Android apps from Google Play",
                                     agent_results=results)
    except Exception as e:
        print("synthesize_summary failed", repr(e)); s = {}
    if not s.get("headline"):
        s = _summary_from_agent_results(results)
    s["failure_breakdown"] = failure_breakdown(results)
    s["site_summary"] = study["url"]; s["access_backend"] = "android_emulator"
    study["summary"] = s
    ins = build_report_insights(study)
    try:
        txt = await asyncio.wait_for(write_verdict_summary({"segment": segment}, ins), timeout=60)
        if txt: s["verdict_summary"] = txt
    except Exception as e:
        print("verdict failed", repr(e))
    s["insights"] = build_report_insights(study)
    if s["insights"].get("headline"): s["headline"] = s["insights"]["headline"]
    await asyncio.wait_for(apply_comparison_llm(study), timeout=300)

asyncio.run(finalize())
from mvp.server import _with_report_insights
view = _with_report_insights(study)
comp = view["summary"].get("comparison") or {}
print("SID", SID, "results", len(results), "tasks", len(tasks), "uploads", len(uploads))
print("headline", view["summary"].get("headline"))
print("comparison sites", [s.get("label") for s in comp.get("sites", [])], "by_task", len(comp.get("by_task") or []))
print("llm", {k: len(v) if isinstance(v, list) else v for k, v in (study["summary"].get("comparison_llm") or {}).items()})
json.dump(study, open(F / "web_study.json", "w"))

if UPLOAD:
    from concurrent.futures import ThreadPoolExecutor
    from mvp.gcs_store import gcs_upload_file, screenshot_gcs_uri, write_study_state, gcs_upload_json, study_gcs_root
    with ThreadPoolExecutor(32) as ex:
        list(ex.map(lambda u: gcs_upload_file(u[0], screenshot_gcs_uri(SID, u[1], u[2]), content_type="image/png"), uploads))
    write_study_state(SID, study)
    gcs_upload_json(f"{study_gcs_root(SID)}/done.json", {"done": True, "at": now})
    print("UPLOADED", SID)
