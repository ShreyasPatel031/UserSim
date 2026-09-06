#!/usr/bin/env python3
"""Parallel signup batch against 20 public products.

Each worker gets its own Chrome CDP port so runs do not collide.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "results" / "signup_batch"

PRODUCTS = [
    "https://linear.app",
    "https://www.notion.so",
    "https://todoist.com",
    "https://clickup.com",
    "https://calendly.com",
    "https://airtable.com",
    "https://www.canva.com",
    "https://www.figma.com",
    "https://miro.com",
    "https://www.loom.com",
    "https://coda.io",
    "https://bitwarden.com",
    "https://www.dropbox.com",
    "https://zoom.us",
    "https://buffer.com",
    "https://webflow.com",
    "https://github.com",
    "https://gitlab.com",
    "https://www.reddit.com",
    "https://medium.com",
]


def _host(url: str) -> str:
    h = (urlparse(url).hostname or url).lower()
    return h[4:] if h.startswith("www.") else h


def _run_one(url: str, idx: int, timeout_s: int, max_steps: int, headless: bool) -> dict:
    port = 9400 + idx
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "mvp.auto_signup",
        "--url",
        url,
        "--timeout",
        str(timeout_s),
        "--max-steps",
        str(max_steps),
        "--cdp-port",
        str(port),
    ]
    if headless:
        cmd.append("--headless")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}:{ROOT}"
    env["SIGNUP_HEADLESS"] = "1" if headless else "0"
    env["MVP_CAPTCHA_ALLOW_HUMAN"] = "0"
    env["MVP_SIGNUP_CDP_PORT"] = str(port)
    start = time.time()
    print(f"→ start [{idx}] {url} port={port}", flush=True)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s + 60,
        )
        elapsed = int(time.time() - start)
        out = (proc.stdout or "").strip()
        # Last JSON object on stdout
        row = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    row = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if row is None and out.startswith("{"):
            try:
                row = json.loads(out)
            except json.JSONDecodeError:
                row = None
        if row is None:
            row = {
                "ok": False,
                "reason": "no_json",
                "raw": out[:400],
                "stderr_tail": (proc.stderr or "")[-500:],
            }
        row["url"] = url
        row["elapsed_s"] = elapsed
        row["exit_code"] = proc.returncode
        row["cdp_port"] = port
    except subprocess.TimeoutExpired:
        row = {
            "url": url,
            "ok": False,
            "reason": "process_timeout",
            "elapsed_s": int(time.time() - start),
            "exit_code": -1,
            "cdp_port": port,
        }
    except Exception as exc:
        row = {
            "url": url,
            "ok": False,
            "reason": f"runner_error:{type(exc).__name__}",
            "detail": str(exc)[:200],
            "elapsed_s": int(time.time() - start),
            "exit_code": -1,
            "cdp_port": port,
        }
    status = "OK" if row.get("ok") else f"FAIL:{row.get('reason')}"
    print(f"← done  [{idx}] {url} {status} ({row.get('elapsed_s')}s)", flush=True)
    return row


def main() -> int:
    if (ROOT / "secrets" / "env").is_file():
        for line in (ROOT / "secrets" / "env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    workers = int(os.environ.get("SIGNUP_PARALLEL", "5"))
    timeout_s = int(os.environ.get("SIGNUP_TIMEOUT_S", "150"))
    max_steps = int(os.environ.get("SIGNUP_MAX_STEPS", "20"))
    headless = os.environ.get("SIGNUP_HEADLESS", "1") == "1"
    limit = int(os.environ.get("SIGNUP_LIMIT", "0") or "0")
    # Skip hosts already attempted in a prior summary if SKIP_DONE=1
    skip_done = os.environ.get("SIGNUP_SKIP_DONE", "0") == "1"
    done_hosts: set[str] = set()
    if skip_done:
        for path in sorted(OUT_DIR.glob("batch_*_summary.json")):
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            for r in data.get("results") or []:
                if r.get("url"):
                    done_hosts.add(_host(r["url"]))

    products = [u for u in PRODUCTS if _host(u) not in done_hosts] if skip_done else list(PRODUCTS)
    if limit > 0:
        products = products[:limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = OUT_DIR / f"batch_parallel_{stamp}.jsonl"
    summary_path = OUT_DIR / f"batch_parallel_{stamp}_summary.json"

    print(
        f"Parallel signup workers={workers} timeout={timeout_s}s "
        f"products={len(products)} → {log_path}",
        flush=True,
    )
    if not products:
        print("Nothing to do")
        return 0

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_one, url, i, timeout_s, max_steps, headless): url
            for i, url in enumerate(products)
        }
        for fut in as_completed(futures):
            row = fut.result()
            results.append(row)
            with log_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            ok = sum(1 for r in results if r.get("ok"))
            fail = len(results) - ok
            print(f"  tally: {ok} ok / {fail} fail / {len(results)} done", flush=True)

    by_reason: dict[str, int] = {}
    for r in results:
        key = r.get("reason") or ("ok" if r.get("ok") else "unknown")
        by_reason[key] = by_reason.get(key, 0) + 1
    summary = {
        "stamp": stamp,
        "parallel": workers,
        "total": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "fail": sum(1 for r in results if not r.get("ok")),
        "by_reason": by_reason,
        "results": sorted(results, key=lambda r: r.get("url") or ""),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("total", "ok", "fail", "by_reason")}, indent=2))
    print(f"summary → {summary_path}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
