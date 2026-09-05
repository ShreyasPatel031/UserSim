"""Run one shard of the 90-run video-platform comparative experiment."""

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
from browser_use.browser.profile import BrowserProfile, ProxySettings
from google.oauth2.credentials import Credentials
from playwright.async_api import async_playwright

from capability.video_platform_personas import all_video_tasks
from config import GCP_PROJECT


def gce_credentials() -> Credentials:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return Credentials(token=json.load(response)["access_token"])


def browser_options(task: dict, state: Path, proxy: str | None) -> tuple[str | None, str | None]:
    if task["website"] != "youtube":
        return None, None
    return (str(state), proxy)


async def verify(task: dict, state: Path, proxy: str | None) -> dict:
    state_path, proxy_url = browser_options(task, state, proxy)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            proxy={"server": proxy_url} if proxy_url else None,
        )
        context = await browser.new_context(storage_state=state_path)
        page = await context.new_page()
        await page.goto(task["start_url"], wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(4_000)
        result = {"url": page.url, "title": await page.title()}
        if task["website"] == "youtube":
            result.update(
                avatar_count=await page.locator("#avatar-btn, button#avatar-btn").count(),
                sign_in_links=await page.locator('a:has-text("Sign in")').count(),
            )
        await context.close()
        await browser.close()
        return result


async def launch_authenticated_youtube_cdp(
    state: Path, proxy: str | None, profile_dir: Path, port: int
) -> tuple[dict, subprocess.Popen, str]:
    """Launch Chrome, inject cookies, verify avatar, and keep that browser alive."""
    data = json.loads(state.read_text())
    cookies = []
    for cookie in data.get("cookies", []):
        row = dict(cookie)
        if row.get("partitionKey") is not None and not isinstance(row.get("partitionKey"), str):
            row.pop("partitionKey", None)
        cookies.append(row)
    chrome = os.environ.get("MVP_CHROME_PATH") or str(
        Path.home() / ".cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
    )
    cmd = [
        chrome,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,800",
    ]
    if proxy:
        cmd.append(f"--proxy-server={proxy}")
    cmd.append("about:blank")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1):
                break
        except Exception:
            await asyncio.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("chrome_cdp_start_timeout")
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0]
    await context.add_cookies(cookies)
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(4_000)
    result = {
        "url": page.url,
        "title": await page.title(),
        "avatar_count": await page.locator("#avatar-btn, button#avatar-btn").count(),
        "sign_in_links": await page.locator('a:has-text("Sign in")').count(),
    }
    # Stop only Playwright's transport; Chrome and its authenticated context stay alive.
    await pw.stop()
    return result, proc, cdp_url


async def run_one(
    task: dict,
    *,
    state: Path,
    proxy: str | None,
    out_dir: Path,
    trace_dir: Path,
    credentials: Credentials,
    max_steps: int,
    semaphore: asyncio.Semaphore,
    gcs: str | None,
) -> dict:
    async with semaphore:
        started = datetime.now(timezone.utc)
        row = {
            "task_id": task["task_id"],
            "eval_index": task["eval_index"],
            "website": task["website"],
            "persona_id": task["persona_id"],
            "persona_name": task["persona_name"],
            "goal_key": task["goal_key"],
            "goal_title": task["goal_title"],
            "comparative_group": task["comparative_group"],
            "model": "gemini-2.5-flash-lite",
            "started_at": started.isoformat(),
        }
        out_path = out_dir / f"{task['eval_index']}.json"
        run_trace = trace_dir / str(task["eval_index"])
        run_trace.mkdir(parents=True, exist_ok=True)
        chrome_proc = None
        try:
            cdp_url = None
            if task["website"] == "youtube":
                check, chrome_proc, cdp_url = await launch_authenticated_youtube_cdp(
                    state, proxy, run_trace / "youtube_profile", 30000 + task["eval_index"] % 10000
                )
            else:
                check = await verify(task, state, proxy)
            row["preflight"] = check
            # The account avatar is the definitive signed-in signal. YouTube can
            # render a secondary "Sign in" link inside unrelated embedded UI even
            # while the global account avatar is present.
            if task["website"] == "youtube" and check.get("avatar_count", 0) < 1:
                raise RuntimeError("youtube_not_signed_in")
            state_path, proxy_url = browser_options(task, state, proxy)
            llm = ChatGoogle(
                model="gemini-2.5-flash-lite",
                vertexai=True,
                credentials=credentials,
                project=GCP_PROJECT,
                location="us-central1",
                temperature=0,
            )
            profile = BrowserProfile(
                headless=True,
                storage_state=None if task["website"] == "youtube" else state_path,
                cdp_url=cdp_url,
                proxy=ProxySettings(server=proxy_url) if proxy_url and not cdp_url else None,
                viewport={"width": 1280, "height": 800},
                disable_security=True,
            )
            agent = Agent(
                task=f"Open {task['start_url']}. {task['task']}",
                llm=llm,
                browser_profile=profile,
                use_vision=True,
                max_actions_per_step=3,
                save_conversation_path=str(run_trace / "conversation"),
            )
            t0 = time.time()
            history = await agent.run(max_steps=max_steps)
            row["elapsed_s"] = round(time.time() - t0, 3)
            row["final_result"] = history.final_result()
            urls = history.urls()
            row["final_url"] = urls[-1] if urls else ""
            row["ok"] = bool(row["final_result"])
        except Exception as exc:
            row.update(ok=False, error=f"{type(exc).__name__}:{exc}"[:500])
        finally:
            if chrome_proc is not None and chrome_proc.poll() is None:
                chrome_proc.terminate()
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        out_path.write_text(json.dumps(row, indent=2, default=str))
        if gcs:
            subprocess.run(
                ["gcloud", "storage", "cp", str(out_path), f"{gcs.rstrip('/')}/results/"],
                check=False,
                capture_output=True,
                timeout=120,
            )
        print(json.dumps({k: row.get(k) for k in ("eval_index", "website", "ok", "error")}), flush=True)
        return row


async def main_async(args: argparse.Namespace) -> int:
    websites = {value.strip() for value in args.websites.split(",") if value.strip()}
    eligible = [task for task in all_video_tasks() if task["website"] in websites]
    tasks = [t for i, t in enumerate(eligible) if i % args.num_shards == args.shard_id]
    if args.eval_indices:
        wanted = {int(value) for value in args.eval_indices.split(",") if value.strip()}
        tasks = [task for task in tasks if task["eval_index"] in wanted]
    out_dir = Path(args.out_dir)
    trace_dir = Path(args.trace_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)
    if args.resume and args.gcs:
        subprocess.run(
            ["gcloud", "storage", "cp", f"{args.gcs.rstrip('/')}/results/*.json", str(out_dir)],
            check=False,
            capture_output=True,
            timeout=180,
        )
    if args.resume:
        tasks = [task for task in tasks if not (out_dir / f"{task['eval_index']}.json").is_file()]
    credentials = gce_credentials()
    semaphore = asyncio.Semaphore(args.workers)
    rows = await asyncio.gather(*[
        run_one(
            task,
            state=Path(args.state),
            proxy=args.proxy,
            out_dir=out_dir,
            trace_dir=trace_dir,
            credentials=credentials,
            max_steps=args.max_steps,
            semaphore=semaphore,
            gcs=args.gcs,
        )
        for task in tasks
    ])
    summary = {
        "shard_id": args.shard_id,
        "num_shards": args.num_shards,
        "n": len(rows),
        "ok": sum(bool(r.get("ok")) for r in rows),
        "youtube_signed_in": sum(
            r.get("website") == "youtube" and (r.get("preflight") or {}).get("avatar_count", 0) > 0
            for r in rows
        ),
        "results": rows,
    }
    summary_path = out_dir / f"shard_{args.shard_id}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    if args.gcs:
        subprocess.run(
            ["gcloud", "storage", "cp", str(summary_path), f"{args.gcs.rstrip('/')}/summaries/"],
            check=False,
            capture_output=True,
            timeout=120,
        )
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2), flush=True)
    return 0 if summary["ok"] == summary["n"] else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard-id", type=int, required=True)
    ap.add_argument("--num-shards", type=int, default=12)
    ap.add_argument("--websites", default="youtube,vimeo,dailymotion")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=18)
    ap.add_argument("--eval-indices", default="")
    ap.add_argument("--state", default="secrets/site_states/www.youtube.com.json")
    ap.add_argument("--proxy", default=os.environ.get("BROWSER_PROXY"))
    ap.add_argument("--out-dir", default="results/video_experiment")
    ap.add_argument("--trace-dir", default="results/video_experiment/traces")
    ap.add_argument("--gcs", default=os.environ.get("VIDEO_EXPERIMENT_GCS"))
    ap.add_argument("--resume", action="store_true")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
