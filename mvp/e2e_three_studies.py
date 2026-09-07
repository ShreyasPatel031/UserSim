#!/usr/bin/env python3
"""Iterative e2e: 3 product URLs → multi-user/task switch + full report each."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000"
OUT = Path("/tmp/usersim_e2e_three.json")

URLS = [
    "https://useagency.dev/",
    "https://recurse.run/",
    "https://www.langchain.com/",
]

TIMEOUT_S = int(__import__("os").environ.get("E2E_TIMEOUT_S", "900"))
POLL_S = 5


def http_json(method: str, path: str, body: dict | None = None, timeout: float = 60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read().decode()
        return json.loads(raw) if raw else {}


def base_task_id(tid: str) -> str:
    return str(tid or "").split("__")[0]


def merge_sessions(data: dict) -> list[dict]:
    tasks = data.get("tasks") or []
    live_raw = data.get("live_sessions") or []
    live = live_raw if isinstance(live_raw, list) else list((live_raw or {}).values())
    completed = data.get("agent_results") or []
    by_id: dict = {}
    for s in live:
        if isinstance(s, dict) and s.get("agent_id"):
            by_id[s["agent_id"]] = {**s}
    for r in completed:
        if not isinstance(r, dict):
            continue
        rid = r.get("agent_id") or r.get("task_id")
        if rid:
            by_id[rid] = {**by_id.get(rid, {}), **r, "status": "complete"}
    out = []
    for t in tasks:
        tid = t.get("id")
        base = by_id.get(tid) or {"agent_id": tid, "status": "pending", "trace": []}
        out.append(
            {
                **base,
                "agent_id": base.get("agent_id") or tid,
                "task_id": base.get("task_id") or tid,
                "task_title": base.get("task_title") or t.get("title"),
                "persona_id": base.get("persona_id") or t.get("persona_id"),
                "persona_name": base.get("persona_name"),
                "site_key": base.get("site_key") or t.get("site_key") or "product",
                "site_url": base.get("site_url") or t.get("site_url") or data.get("url"),
                "trace": base.get("trace") or [],
            }
        )
    return out


def find_session_idx(
    sessions: list[dict],
    *,
    task_base: str = "",
    site_key: str = "",
    persona_id: str = "",
    prefer: str = "",
) -> int:
    ranked = []
    for i, s in enumerate(sessions):
        base = base_task_id(s.get("task_id") or s.get("agent_id"))
        task_ok = not task_base or base == task_base
        persona_ok = (
            not persona_id or not s.get("persona_id") or s.get("persona_id") == persona_id
        )
        key_ok = not site_key or s.get("site_key") == site_key or (
            site_key == "product"
            and (s.get("site_key") == "product" or s.get("site_label") == "Product")
        )
        score = -1
        if task_ok and persona_ok and key_ok:
            score = 100
        elif prefer == "persona" and persona_ok and key_ok:
            score = 90
        elif prefer == "task" and task_ok and key_ok:
            score = 90
        elif prefer == "persona" and persona_ok:
            score = 80
        elif prefer == "task" and task_ok:
            score = 80
        elif task_ok and key_ok:
            score = 60
        elif persona_ok and key_ok:
            score = 55
        if score >= 0:
            ranked.append((score, i))
    ranked.sort(reverse=True)
    return ranked[0][1] if ranked else -1


def shot_ok(session: dict) -> bool:
    return any(step.get("screenshot_url") for step in (session.get("trace") or []))


def verify_ui_switching(data: dict) -> dict:
    sessions = merge_sessions(data)
    personas = sorted(
        {
            s.get("persona_id")
            for s in sessions
            if s.get("persona_id")
            and (
                s.get("trace")
                or s.get("status") in {"complete", "running", "summarizing"}
            )
        }
    )
    task_bases = sorted(
        {
            base_task_id(s.get("task_id") or s.get("agent_id"))
            for s in sessions
            if s.get("task_id") or s.get("agent_id")
        }
    )
    sites = sorted({s.get("site_key") or "product" for s in sessions})

    switch_users = []
    for pid in personas:
        idx = find_session_idx(sessions, persona_id=pid, prefer="persona")
        switch_users.append(
            {
                "persona_id": pid,
                "idx": idx,
                "agent": sessions[idx].get("agent_id") if idx >= 0 else None,
                "ok": idx >= 0,
                "has_shot": shot_ok(sessions[idx]) if idx >= 0 else False,
            }
        )

    switch_tasks = []
    for tb in task_bases:
        idx = find_session_idx(sessions, task_base=tb, prefer="task")
        switch_tasks.append(
            {
                "task_base": tb,
                "idx": idx,
                "agent": sessions[idx].get("agent_id") if idx >= 0 else None,
                "ok": idx >= 0,
                "has_shot": shot_ok(sessions[idx]) if idx >= 0 else False,
            }
        )

    users_ok = len(personas) >= 2 and all(u["ok"] for u in switch_users)
    tasks_ok = len(task_bases) >= 2 and all(t["ok"] for t in switch_tasks)
    distinct_users = len({u["agent"] for u in switch_users if u["agent"]}) >= 2
    distinct_tasks = len({t["agent"] for t in switch_tasks if t["agent"]}) >= 2
    shots_ok = sum(1 for s in sessions if shot_ok(s)) >= 2
    summary = data.get("summary") or {}
    report_ok = bool(
        summary.get("headline")
        or summary.get("recommendations")
        or summary.get("top_friction")
    )

    return {
        "n_sessions": len(sessions),
        "n_personas_with_work": len(personas),
        "n_task_bases": len(task_bases),
        "n_sites": len(sites),
        "personas": personas,
        "task_bases": task_bases,
        "sites": sites,
        "switch_users": switch_users,
        "switch_tasks": switch_tasks,
        "users_switch_ok": users_ok and distinct_users,
        "tasks_switch_ok": tasks_ok and distinct_tasks,
        "shots_ok": shots_ok,
        "report_ok": report_ok,
        "summary_headline": (summary.get("headline") or "")[:120],
        "pass": (
            users_ok
            and distinct_users
            and tasks_ok
            and distinct_tasks
            and shots_ok
            and report_ok
            and data.get("status") == "complete"
        ),
    }


def run_study_stream(url: str, timeout_s: int) -> dict:
    """POST study and consume Vercel-mode NDJSON until complete/error."""
    body = {
        "url": url,
        "test_mode": False,
        "skip_competitors": True,
        "segment": "People evaluating this product for work",
    }
    req = urllib.request.Request(
        f"{BASE}/api/studies",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "X-UserSim-Stream": "1",
        },
    )
    t0 = time.time()
    last: dict = {}
    study_id = ""
    with urllib.request.urlopen(req, timeout=timeout_s + 120) as res:
        ctype = (res.headers.get("Content-Type") or "").lower()
        if "ndjson" in ctype or "stream" in ctype:
            while True:
                line = res.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    chunk = json.loads(text)
                except json.JSONDecodeError:
                    continue
                last = chunk
                study_id = chunk.get("id") or chunk.get("study_id") or study_id
                status = chunk.get("status")
                phase = (chunk.get("phase") or "")[:80]
                print(
                    f"  [{int(time.time() - t0):4d}s] status={status} "
                    f"tasks={len(chunk.get('tasks') or [])} "
                    f"done={len(chunk.get('agent_results') or [])} "
                    f"personas={len(chunk.get('personas') or [])} phase={phase}",
                    flush=True,
                )
                if chunk.get("stream_event") in {"complete", "error"} or status in {
                    "complete",
                    "error",
                }:
                    break
                if time.time() - t0 > timeout_s:
                    raise TimeoutError(f"stream timeout after {timeout_s}s study={study_id}")
        else:
            raw = res.read().decode()
            last = json.loads(raw) if raw else {}
            study_id = last.get("study_id") or last.get("id") or ""

    # Stream can end while the study is still running (proxy/client disconnect).
    # Keep polling until complete/error/timeout.
    if study_id and last.get("status") not in {"complete", "error"}:
        print(f"  stream ended early — polling study {study_id}", flush=True)
        while time.time() - t0 < timeout_s:
            try:
                last = http_json("GET", f"/api/studies/{study_id}", timeout=90)
            except Exception as exc:  # noqa: BLE001
                print(f"  poll warn: {exc!r}", flush=True)
                time.sleep(POLL_S)
                continue
            status = last.get("status")
            print(
                f"  [{int(time.time() - t0):4d}s] poll status={status} "
                f"done={len(last.get('agent_results') or [])} "
                f"phase={(last.get('phase') or '')[:70]}",
                flush=True,
            )
            if status in {"complete", "error", "abandoned"}:
                break
            time.sleep(POLL_S)

    if study_id and last.get("status") == "complete":
        try:
            hydrated = http_json("GET", f"/api/studies/{study_id}", timeout=90)
            if hydrated:
                last = hydrated
        except Exception as exc:  # noqa: BLE001
            print(f"  hydrate warn: {exc!r}", flush=True)
    if not last.get("id") and study_id:
        last["id"] = study_id
    return last


def run_one(url: str) -> dict:
    print(f"\n=== START {url} ===", flush=True)
    t0 = time.time()
    data = run_study_stream(url, TIMEOUT_S)
    study_id = data.get("id") or data.get("study_id")
    if data.get("status") == "error":
        raise RuntimeError(data.get("error") or "study error")
    if data.get("status") != "complete":
        raise RuntimeError(
            f"Study not complete status={data.get('status')} id={study_id} "
            f"phase={data.get('phase')}"
        )

    verify = verify_ui_switching(data)
    elapsed = time.time() - t0
    result = {
        "url": url,
        "study_id": study_id,
        "elapsed_s": round(elapsed, 1),
        "status": data.get("status"),
        "verify": verify,
    }
    print(
        f"=== RESULT {url} pass={verify['pass']} "
        f"users={verify['n_personas_with_work']} tasks={verify['n_task_bases']} "
        f"shots={verify['shots_ok']} report={verify['report_ok']} ({elapsed:.0f}s) ===",
        flush=True,
    )
    if not verify["pass"]:
        print(json.dumps(verify, indent=2)[:2500], flush=True)
    return result


def main() -> int:
    health = http_json("GET", "/health", timeout=10)
    print("health", health, flush=True)
    results = []
    failed = False
    for url in URLS:
        try:
            results.append(run_one(url))
        except Exception as exc:  # noqa: BLE001
            failed = True
            results.append({"url": url, "error": str(exc), "verify": {"pass": False}})
            print(f"FAIL {url}: {exc!r}", flush=True)
            # Release browsers between failures so the next URL isn't starved.
            try:
                http_json(
                    "POST",
                    "/api/runtime/kill",
                    {"agents": True, "vms": False, "seeds": False},
                    timeout=60,
                )
            except Exception:
                pass
    OUT.write_text(json.dumps({"base": BASE, "results": results}, indent=2))
    print(f"\nWrote {OUT}", flush=True)
    all_pass = all((r.get("verify") or {}).get("pass") for r in results) and len(results) == 3
    print("ALL_PASS" if all_pass else "SOME_FAILED", flush=True)
    return 0 if all_pass and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
