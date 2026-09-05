"""OM2W OSS Browserbase-class unblock bakeoff (preflight only, no LLM).

Baseline: chromium_headless (current fleet default).
Alternatives: camoufox (anti-detect Firefox), steel (self-host Docker CDP),
patchright (patched Chromium), chromium_headful (Xvfb control).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from capability import OUT_DIR, USER_AGENT, VIEWPORT
from capability.site_preflight import PreflightResult, classify_page_block
from capability.tasks import FULL300_INDICES, load_tasks

BackendFn = Callable[[str, int], Awaitable[PreflightResult]]

# Serialize Steel session create/use — local Steel is ~1 concurrent session.
_STEEL_LOCK = threading.Lock()
_STEEL_BASE = os.environ.get("STEEL_API_URL", "http://127.0.0.1:3000")


async def _read_page_state(page, start_url: str) -> PreflightResult:
    title = ""
    try:
        title = await page.title()
    except Exception:  # noqa: BLE001
        pass
    final_url = page.url
    try:
        body = (await page.inner_text("body"))[:4000]
    except Exception:  # noqa: BLE001
        body = ""
    blocked, reason = classify_page_block(final_url=final_url, title=title, body=body)
    return PreflightResult(blocked, reason, final_url, title, None)


async def _probe_playwright_chromium(start_url: str, timeout_ms: int, *, headless: bool) -> PreflightResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport=VIEWPORT, user_agent=USER_AGENT)
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(800)
        except Exception as exc:  # noqa: BLE001
            await browser.close()
            return PreflightResult(True, f"navigation_error:{exc}"[:200], start_url, "", None)
        out = await _read_page_state(page, start_url)
        await browser.close()
    return out


async def probe_chromium_headless(start_url: str, timeout_ms: int = 25000) -> PreflightResult:
    return await _probe_playwright_chromium(start_url, timeout_ms, headless=True)


async def probe_chromium_headful(start_url: str, timeout_ms: int = 25000) -> PreflightResult:
    return await _probe_playwright_chromium(start_url, timeout_ms, headless=False)


async def probe_camoufox(start_url: str, timeout_ms: int = 25000) -> PreflightResult:
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError as exc:
        return PreflightResult(True, f"backend_unavailable:camoufox:{exc}"[:200], start_url, "", None)

    try:
        async with AsyncCamoufox(headless=True, exclude_addons=["UBO"]) as browser:
            page = await browser.new_page()
            try:
                await page.set_viewport_size(VIEWPORT)
            except Exception:  # noqa: BLE001
                pass
            try:
                await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
                await page.wait_for_timeout(800)
            except Exception as exc:  # noqa: BLE001
                return PreflightResult(True, f"navigation_error:{exc}"[:200], start_url, "", None)
            return await _read_page_state(page, start_url)
    except Exception as exc:  # noqa: BLE001
        return PreflightResult(True, f"backend_error:camoufox:{exc}"[:200], start_url, "", None)


async def probe_patchright(start_url: str, timeout_ms: int = 25000) -> PreflightResult:
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:
        return PreflightResult(True, f"backend_unavailable:patchright:{exc}"[:200], start_url, "", None)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport=VIEWPORT, user_agent=USER_AGENT)
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(800)
        except Exception as exc:  # noqa: BLE001
            await browser.close()
            return PreflightResult(True, f"navigation_error:{exc}"[:200], start_url, "", None)
        out = await _read_page_state(page, start_url)
        await browser.close()
    return out


def _steel_http(method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = Request(
        f"{_STEEL_BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw else {}


async def probe_steel(start_url: str, timeout_ms: int = 25000) -> PreflightResult:
    """Self-hosted Steel Browser via local API + CDP (Browserbase-class OSS)."""
    from playwright.async_api import async_playwright

    with _STEEL_LOCK:
        try:
            session = _steel_http("POST", "/v1/sessions", {})
        except Exception as exc:  # noqa: BLE001
            return PreflightResult(True, f"backend_unavailable:steel:{exc}"[:200], start_url, "", None)

        sid = session.get("id") or session.get("sessionId") or session.get("session_id")
        cdp = (
            session.get("websocketUrl")
            or session.get("websocket_url")
            or session.get("cdpUrl")
            or session.get("cdp_url")
            or (f"ws://127.0.0.1:3000" if not sid else None)
        )
        # Steel local often exposes CDP as ws://.../v1/sessions/{id}/connect or similar
        if sid and not (cdp and "session" in str(cdp)):
            for candidate in (
                f"{_STEEL_BASE.replace('http', 'ws')}/v1/sessions/{sid}",
                f"{_STEEL_BASE.replace('http', 'ws')}/v1/sessions/{sid}/connect",
                session.get("debugUrl"),
            ):
                if candidate:
                    cdp = candidate
                    break
        if not cdp:
            return PreflightResult(
                True,
                f"backend_unavailable:steel:no_cdp keys={list(session)[:20]}",
                start_url,
                "",
                None,
            )

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(str(cdp))
                context = browser.contexts[0] if browser.contexts else await browser.new_context(
                    viewport=VIEWPORT, user_agent=USER_AGENT
                )
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await page.wait_for_timeout(800)
                except Exception as exc:  # noqa: BLE001
                    out = PreflightResult(True, f"navigation_error:{exc}"[:200], start_url, "", None)
                else:
                    out = await _read_page_state(page, start_url)
                await browser.close()
        except Exception as exc:  # noqa: BLE001
            out = PreflightResult(True, f"backend_error:steel:{exc}"[:200], start_url, "", None)
        finally:
            if sid:
                try:
                    _steel_http("DELETE", f"/v1/sessions/{sid}")
                except Exception:  # noqa: BLE001
                    pass
        return out


BACKENDS: dict[str, BackendFn] = {
    "chromium_headless": probe_chromium_headless,
    "chromium_headful": probe_chromium_headful,
    "camoufox": probe_camoufox,
    "patchright": probe_patchright,
    "steel": probe_steel,
}


def unique_start_urls(limit: int | None = None) -> list[dict]:
    tasks = load_tasks(FULL300_INDICES)
    by_host: dict[str, dict] = {}
    for t in tasks:
        host = (t.get("website_host") or urlparse(t["start_url"]).netloc).lower().removeprefix("www.")
        if host not in by_host:
            by_host[host] = {
                "host": host,
                "start_url": t["start_url"],
                "example_eval_index": t["eval_index"],
                "example_task_id": t["task_id"],
            }
    rows = sorted(by_host.values(), key=lambda r: r["host"])
    if limit is not None:
        rows = rows[:limit]
    return rows


def hosts_from_file(path: Path) -> list[dict]:
    """JSON list of hosts, or merged unblock JSON with summary.chromium_headless.blocked_hosts."""
    data = json.loads(path.read_text())
    all_hosts = {h["host"]: h for h in unique_start_urls()}
    if isinstance(data, list):
        wanted = [str(x) for x in data]
    elif isinstance(data, dict) and "summary" in data:
        wanted = list(data["summary"]["chromium_headless"]["blocked_hosts"])
    elif isinstance(data, dict) and "hosts" in data:
        wanted = list(data["hosts"])
    else:
        raise SystemExit(f"Unrecognized hosts file format: {path}")
    missing = [h for h in wanted if h not in all_hosts]
    if missing:
        raise SystemExit(f"Hosts not in OM2W set: {missing[:10]}")
    return [all_hosts[h] for h in wanted]


def _run_one(backend: str, row: dict, timeout_ms: int) -> dict:
    fn = BACKENDS[backend]
    t0 = time.time()
    try:
        result = asyncio.run(fn(row["start_url"], timeout_ms))
    except Exception as exc:  # noqa: BLE001
        result = PreflightResult(True, f"worker_crash:{exc}"[:200], row["start_url"], "", None)
    return {
        "backend": backend,
        "host": row["host"],
        "start_url": row["start_url"],
        "example_eval_index": row["example_eval_index"],
        "example_task_id": row["example_task_id"],
        "blocked": result.blocked,
        "reason": result.reason,
        "final_url": result.final_url,
        "title": result.title,
        "elapsed_s": round(time.time() - t0, 2),
    }


def summarize(rows: list[dict]) -> dict:
    by_backend: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_backend[r["backend"]].append(r)
    summary = {}
    for backend, items in sorted(by_backend.items()):
        n = len(items)
        blocked = sum(1 for x in items if x["blocked"])
        unavailable = sum(
            1
            for x in items
            if str(x.get("reason", "")).startswith(("backend_unavailable", "backend_error"))
        )
        ok = n - blocked
        summary[backend] = {
            "n": n,
            "ok": ok,
            "blocked": blocked,
            "backend_unavailable_or_error": unavailable,
            "ok_rate": round(ok / n, 4) if n else 0.0,
            "blocked_hosts": sorted(
                x["host"]
                for x in items
                if x["blocked"]
                and not str(x.get("reason", "")).startswith(("backend_unavailable", "backend_error"))
            ),
            "error_hosts": sorted(
                (x["host"], x["reason"][:120])
                for x in items
                if str(x.get("reason", "")).startswith(("backend_unavailable", "backend_error"))
            ),
        }
    base_blocked = {x["host"] for x in by_backend.get("chromium_headless", []) if x["blocked"]}
    for backend, items in by_backend.items():
        if backend == "chromium_headless":
            continue
        rescued = sorted(x["host"] for x in items if (not x["blocked"]) and x["host"] in base_blocked)
        summary[backend]["rescued_vs_chromium_headless"] = rescued
        summary[backend]["n_rescued_vs_chromium_headless"] = len(rescued)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="OM2W OSS Browserbase-class unblock bakeoff")
    ap.add_argument(
        "--backends",
        default="chromium_headless,camoufox,steel,patchright",
        help="Comma-separated backend names",
    )
    ap.add_argument("--limit-hosts", type=int, default=None)
    ap.add_argument(
        "--hosts-file",
        type=Path,
        default=None,
        help="JSON with blocked host list (e.g. om2w_unblock_merged.json)",
    )
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout-ms", type=int, default=25000)
    ap.add_argument("--tag", default="bb_class_oss")
    args = ap.parse_args()

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    unknown = [b for b in backends if b not in BACKENDS]
    if unknown:
        raise SystemExit(f"Unknown backends: {unknown}; choose from {sorted(BACKENDS)}")

    hosts = hosts_from_file(args.hosts_file) if args.hosts_file else unique_start_urls(args.limit_hosts)
    jobs = [(b, h) for b in backends for h in hosts]
    print(
        f"OM2W BB-class unblock | hosts={len(hosts)} backends={backends} "
        f"jobs={len(jobs)} workers={args.workers}",
        flush=True,
    )

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(_run_one, b, h, args.timeout_ms) for b, h in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            rows.append(row)
            flag = "BLOCKED" if row["blocked"] else "OK"
            print(f"[{i}/{len(jobs)}] {flag} {row['backend']} {row['host']} :: {row['reason'][:100]}", flush=True)

    summary = summarize(rows)
    out = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "Online-Mind2Web",
        "focus": "browserbase_class_oss_vs_chromium_headless",
        "n_hosts": len(hosts),
        "backends": backends,
        "workers": args.workers,
        "summary": summary,
        "rows": sorted(rows, key=lambda r: (r["backend"], r["host"])),
    }
    path = OUT_DIR / f"om2w_unblock_{args.tag}.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Wrote {path}", flush=True)


if __name__ == "__main__":
    main()
