"""Run one half of the 30-cell YouTube study on an authenticated seed VM."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from browser_use import Agent, ChatGoogle
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from google.oauth2.credentials import Credentials
from playwright.async_api import async_playwright

from capability.video_platform_personas import all_video_tasks


async def wait_cdp(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{url}/json/version", timeout=1):
                return
        except Exception:
            await asyncio.sleep(0.25)
    raise RuntimeError("chrome_cdp_start_timeout")


def _read_cpu_ticks() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    ticks = [int(value) for value in fields]
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return idle, sum(ticks)


async def cpu_percent() -> float:
    idle_a, total_a = _read_cpu_ticks()
    await asyncio.sleep(0.5)
    idle_b, total_b = _read_cpu_ticks()
    total_delta = max(1, total_b - total_a)
    return 100.0 * (1.0 - (idle_b - idle_a) / total_delta)


async def wait_for_capacity(threshold: float) -> None:
    while await cpu_percent() >= threshold:
        await asyncio.sleep(2.0)


async def run_task(
    task: dict,
    args: argparse.Namespace,
    credentials: Credentials,
    cdp: str,
    semaphore: asyncio.Semaphore,
    launch_lock: asyncio.Lock,
) -> dict:
    async with semaphore:
        # Serialize only admission sampling so queued tasks do not stampede.
        # Running tasks continue; high CPU pauses new admissions temporarily.
        async with launch_lock:
            await wait_for_capacity(args.cpu_threshold)
        return await _run_task(task, args, credentials, cdp)


async def _run_task(task: dict, args: argparse.Namespace, credentials: Credentials, cdp: str) -> dict:
    started = datetime.now(timezone.utc)
    row = {key: task[key] for key in (
        "task_id", "eval_index", "website", "persona_id", "persona_name",
        "goal_key", "goal_title", "comparative_group",
    )}
    row.update(model="gemini-2.5-flash-lite", seed=args.seed_id, started_at=started.isoformat())
    out = Path(args.out_dir) / f"{task['eval_index']}.json"
    trace = Path(args.trace_dir) / str(task["eval_index"])
    trace.mkdir(parents=True, exist_ok=True)
    session: BrowserSession | None = None
    try:
        llm = ChatGoogle(
            model="gemini-2.5-flash-lite", vertexai=True, credentials=credentials,
            project=args.project, location="us-central1", temperature=0,
        )
        session = BrowserSession(
            cdp_url=cdp,
            keep_alive=True,
            viewport={"width": 1440, "height": 900},
            disable_security=True,
        )
        await session.start()
        await session.new_page(task["start_url"])
        agent = Agent(
            task=f"Open {task['start_url']}. {task['task']}",
            llm=llm,
            browser_session=session,
            use_vision=True,
            max_actions_per_step=3,
            save_conversation_path=str(trace / "conversation"),
        )
        t0 = time.time()
        history = await agent.run(max_steps=args.max_steps)
        row["elapsed_s"] = round(time.time() - t0, 3)
        row["final_result"] = history.final_result()
        urls = history.urls()
        row["final_url"] = urls[-1] if urls else ""
        row["ok"] = bool(row["final_result"])
    except Exception as exc:
        row.update(ok=False, error=f"{type(exc).__name__}:{exc}"[:500])
    finally:
        if session is not None:
            try:
                await session.stop()
            except Exception:
                pass
    row["finished_at"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(row, indent=2, default=str))
    print(json.dumps({"eval_index": row["eval_index"], "ok": row["ok"], "error": row.get("error")}), flush=True)
    return row


async def main_async(args: argparse.Namespace) -> int:
    tasks = [task for task in all_video_tasks() if task["website"] == "youtube"]
    tasks = [task for i, task in enumerate(tasks) if i % args.num_seeds == args.seed_id]
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    Path(args.trace_dir).mkdir(parents=True, exist_ok=True)
    if args.resume:
        tasks = [
            task for task in tasks
            if not Path(args.out_dir, f"{task['eval_index']}.json").is_file()
        ]
    token = os.environ.pop("GCP_ACCESS_TOKEN")
    credentials = Credentials(token=token)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (Path(args.profile) / name).unlink(missing_ok=True)
    chrome = subprocess.Popen([
        args.chrome,
        f"--user-data-dir={args.profile}",
        f"--remote-debugging-port={args.port}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1440,900", "https://www.youtube.com/",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    cdp = f"http://127.0.0.1:{args.port}"
    try:
        await wait_cdp(cdp)
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp)
            page = browser.contexts[0].pages[0]
            await page.wait_for_timeout(3_000)
            avatar = await page.locator("button#avatar-btn, ytd-topbar-menu-button-renderer button").count()
        if avatar < 1:
            raise RuntimeError("youtube_seed_not_authenticated")
        semaphore = asyncio.Semaphore(args.workers)
        launch_lock = asyncio.Lock()
        rows = await asyncio.gather(*[
            run_task(task, args, credentials, cdp, semaphore, launch_lock) for task in tasks
        ])
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
    summary = {"seed_id": args.seed_id, "n": len(rows), "ok": sum(bool(r["ok"]) for r in rows), "results": rows}
    Path(args.out_dir, f"youtube_seed_{args.seed_id}_summary.json").write_text(json.dumps(summary, indent=2))
    return 0 if summary["ok"] == summary["n"] else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-id", type=int, required=True)
    ap.add_argument("--num-seeds", type=int, default=2)
    ap.add_argument("--project", default="project-amer-scs-sandbox")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--chrome", default="/usr/bin/chromium")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--max-steps", type=int, default=18)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cpu-threshold", type=float, default=85.0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--trace-dir", required=True)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
