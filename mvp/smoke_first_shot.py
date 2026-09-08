#!/usr/bin/env python3
"""Measure time-to-first-screenshot for a 1-agent vercel-mode study.

Cheap smoke: test_mode + skip_competitors + one task.
Prints timeline and FAILS if first screenshot takes > threshold.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000"
URL = "https://useagency.dev/"
# Opening frame should land well under this after session is up.
MAX_SHOT_S = float(__import__("os").environ.get("SMOKE_MAX_FIRST_SHOT_S", "45"))


def post_start() -> str:
    payload = {
        "url": URL,
        "test_mode": True,
        "skip_competitors": True,
        "segment": "Founders",
        "tasks": ["Skim the homepage"],
    }
    req = urllib.request.Request(
        f"{BASE}/api/studies",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    # Only need first NDJSON object with an id — don't wait for full stream.
    with urllib.request.urlopen(req, timeout=120) as resp:
        buf = b""
        deadline = time.time() + 90
        while time.time() < deadline:
            chunk = resp.read(2048)
            if not chunk:
                break
            buf += chunk
            for line in buf.splitlines():
                try:
                    obj = json.loads(line.decode())
                except Exception:
                    continue
                sid = obj.get("study_id") or obj.get("id")
                if sid:
                    return str(sid)
    raise SystemExit("FAIL: no study_id from POST")


def get_study(sid: str) -> dict:
    with urllib.request.urlopen(f"{BASE}/api/studies/{sid}", timeout=30) as resp:
        return json.loads(resp.read().decode())


def first_shot(data: dict) -> tuple[str | None, str | None, int]:
    live = data.get("live_sessions") or {}
    items = list(live.values()) if isinstance(live, dict) else list(live or [])
    for sess in items:
        for step in sess.get("trace") or []:
            url = step.get("screenshot_url")
            if url:
                return url, step.get("action"), len(items)
    return None, None, len(items)


def live_active_at(data: dict) -> tuple[bool, str | None]:
    live = data.get("live_sessions") or {}
    items = list(live.values()) if isinstance(live, dict) else list(live or [])
    for sess in items:
        if sess.get("live_active") and sess.get("live_view_url"):
            return True, sess.get("live_view_url")
    return False, None


def first_acting_thought(data: dict) -> str | None:
    live = data.get("live_sessions") or {}
    items = list(live.values()) if isinstance(live, dict) else list(live or [])
    skip = ("waiting", "opened ")
    for sess in items:
        for th in sess.get("live_thoughts") or []:
            text = (th.get("text") or "").strip()
            low = text.lower()
            if text and not any(low.startswith(s) for s in skip):
                return text
    return None


def main() -> int:
    t0 = time.time()
    print(f"→ POST study base={BASE} url={URL}")
    sid = post_start()
    t_id = time.time()
    print(f"  study_id={sid}  (+{t_id - t0:.1f}s to id)")

    t_sessions = None
    t_url = None
    t_shot = None
    t_live = None
    t_thought = None
    shot_url = None
    shot_action = None
    thought_text = None
    last_phase = ""

    while time.time() - t0 < MAX_SHOT_S + 60:
        try:
            data = get_study(sid)
        except urllib.error.HTTPError as exc:
            print(f"  GET HTTP {exc.code}")
            time.sleep(1)
            continue
        phase = (data.get("phase") or "")[:70]
        live = data.get("live_sessions") or {}
        items = list(live.values()) if isinstance(live, dict) else list(live or [])
        n = len(items)
        if n and t_sessions is None:
            t_sessions = time.time()
            print(f"  first live_sessions={n}  (+{t_sessions - t0:.1f}s from start)")
        if t_url is None:
            for sess in items:
                site = sess.get("site_url") or ""
                if site:
                    t_url = time.time()
                    print(f"  url_chosen={site}  (+{t_url - t0:.1f}s from start)")
                    break
            if t_url is None:
                for task in data.get("tasks") or []:
                    site = task.get("site_url") or data.get("url") or ""
                    if site and (data.get("tasks") or []):
                        # Tasks exist with a site — URL decision is done.
                        t_url = time.time()
                        print(f"  url_chosen(task)={site}  (+{t_url - t0:.1f}s from start)")
                        break
        url, action, _ = first_shot(data)
        if t_live is None:
            active, _ = live_active_at(data)
            if active:
                t_live = time.time()
                print(f"  live_active  (+{t_live - t0:.1f}s from start)")
        if t_thought is None:
            th = first_acting_thought(data)
            if th:
                t_thought = time.time()
                thought_text = th
                print(f"  first_thought (+{t_thought - t0:.1f}s): {th[:80]}")
        if phase != last_phase:
            print(
                f"  [{time.time() - t0:5.1f}s] status={data.get('status')} "
                f"phase={phase} sessions={n} shot={bool(url)} "
                f"live={bool(t_live)} thought={bool(t_thought)}"
            )
            last_phase = phase
        if url and t_shot is None:
            t_shot = time.time()
            shot_url = url
            shot_action = action
        # Need shot + live for TTFT UX check; don't wait forever for thought.
        if t_shot and t_live:
            break
        if url and time.time() - t0 > MAX_SHOT_S + 20:
            break
        time.sleep(0.35)

    # Kill to save Browserbase $
    try:
        req = urllib.request.Request(
            f"{BASE}/api/runtime/kill",
            data=json.dumps(
                {"study_id": sid, "agents": True, "vms": False, "seeds": False}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=30).read()
        print("  killed study (save $)")
    except Exception as exc:
        print(f"  kill failed: {exc!r}")

    print("---")
    print(f"study_id:     {sid}")
    if t_url:
        print(f"url_chosen:   +{t_url - t0:.1f}s")
    if t_sessions:
        print(f"sessions_at:  +{t_sessions - t0:.1f}s")
    if t_shot:
        print(f"first_shot:   +{t_shot - t0:.1f}s  ({shot_url})")
        print(f"shot_action:  {shot_action}")
        if t_url:
            print(f"gap_url_to_shot: {t_shot - t_url:.1f}s  ← after task URL chosen")
        if t_sessions:
            print(f"gap_sessions_to_shot: {t_shot - t_sessions:.1f}s")
    if t_live and t_url:
        print(f"gap_url_to_live: {t_live - t_url:.1f}s  ← TTFT UX (live browser on)")
    if t_thought and t_url:
        print(f"gap_url_to_thought: {t_thought - t_url:.1f}s  ({(thought_text or '')[:60]})")
    if t_shot:
        gap = (t_shot - t_url) if t_url else (t_shot - t0)
        live_gap = (t_live - t_url) if (t_live and t_url) else None
        if gap <= MAX_SHOT_S and t_shot - t0 <= MAX_SHOT_S + 60:
            print(f"OK first screenshot {gap:.1f}s after URL known")
            if live_gap is not None:
                print(f"OK live_active {live_gap:.1f}s after URL known")
            return 0
        print(f"FAIL first screenshot gap {gap:.1f}s > {MAX_SHOT_S:.0f}s")
        return 1
    print(f"FAIL no screenshot within timeout (waited {time.time() - t0:.1f}s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())