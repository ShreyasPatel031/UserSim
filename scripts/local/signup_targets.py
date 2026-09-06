"""Run signup for an explicit list of hosts, N at a time.

The packaged batch runner walks a hardcoded PRODUCTS list. This one takes
the hosts on argv so a run can target just the ones worth retrying.

    python scripts/local/signup_targets.py --parallel 4 figma.com loom.com
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "signup_batch"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mvp.auto_signup import signup_start_url as _url  # noqa: E402


def _free_port(preferred: int) -> int:
    """Bind-check so parallel/zombie Chrome does not collide on 9500."""
    import socket

    for port in range(preferred, preferred + 80):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def _run_one(host: str, idx: int, timeout_s: int, max_steps: int, headed: bool) -> dict:
    url = _url(host)
    port = _free_port(9500 + idx * 10)
    log = OUT_DIR / f"targets_{host}.log"
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
    if not headed:
        cmd.append("--headless")

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT / 'src'}:{ROOT}"
    row: dict = {"host": host, "url": url}
    try:
        with log.open("wb") as fh:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=fh,
                timeout=timeout_s + 180,
            )
        out = proc.stdout.decode(errors="ignore")
        log.write_bytes(log.read_bytes() + b"\n--- stdout ---\n" + out.encode())
        parsed = _parse_result_json(out)
        if parsed:
            row.update(parsed)
        else:
            row.update({"ok": False, "reason": "no_result"})
        row["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        row.update({"ok": False, "reason": "process_timeout"})
    except Exception as exc:  # noqa: BLE001
        row.update({"ok": False, "reason": "driver_error", "detail": str(exc)[:200]})
    return row


def _parse_result_json(out: str) -> dict | None:
    """Pick the last JSON object that looks like an auto_signup result.

    Pretty-printed multi-line JSON plus earlier brace-y log noise used to make
    ``rfind('{')`` + ``json.loads`` throw ``Extra data`` and report every win as
    ``driver_error``.
    """
    decoder = json.JSONDecoder()
    last: dict | None = None
    idx = 0
    while True:
        start = out.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(out, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict) and "ok" in obj and "host" in obj:
            last = obj
        idx = end
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="+")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = OUT_DIR / f"targets_{stamp}_summary.json"

    print(f"signup targets={len(args.hosts)} parallel={args.parallel}", flush=True)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(
                _run_one, h, i, args.timeout, args.max_steps, not args.headless
            ): h
            for i, h in enumerate(args.hosts)
        }
        for fut in as_completed(futures):
            row = fut.result()
            results.append(row)
            mark = "OK " if row.get("ok") else "FAIL"
            print(
                f"  [{len(results)}/{len(args.hosts)}] {mark} {row['host']}"
                f" -> {row.get('reason')}",
                flush=True,
            )

    by_reason: dict[str, int] = {}
    for r in results:
        key = r.get("reason") or ("ok" if r.get("ok") else "unknown")
        by_reason[key] = by_reason.get(key, 0) + 1
    summary = {
        "stamp": stamp,
        "total": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "fail": sum(1 for r in results if not r.get("ok")),
        "by_reason": by_reason,
        "results": sorted(results, key=lambda r: r.get("host") or ""),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("total", "ok", "by_reason")}, indent=2))
    print(f"summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
