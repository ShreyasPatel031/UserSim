#!/usr/bin/env python3
"""Signup benchmark — 40 products, skip already-servable hosts.

  python scripts/local/signup_benchmark.py status
  python scripts/local/signup_benchmark.py next
  python scripts/local/signup_benchmark.py run              # next pending only
  python scripts/local/signup_benchmark.py run clickup.com
  python scripts/local/signup_benchmark.py run --all-pending

Done = cookie-verified on this machine (secrets/site_states + seed_status),
or hosts listed in mvp/signup_benchmark20.json skip_hosts /
MVP_SIGNUP_BENCHMARK_SKIP. Mac-only identities.json signed_up does NOT count.
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
_BENCH_40 = ROOT / "mvp" / "signup_benchmark40.json"
_BENCH_20 = ROOT / "mvp" / "signup_benchmark20.json"
BENCH_PATH = _BENCH_40 if _BENCH_40.is_file() else _BENCH_20
OUT_DIR = ROOT / "results" / "signup_benchmark"
SITE_STATES = ROOT / "secrets" / "site_states"
PROGRESS_PATH = OUT_DIR / "progress.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "local"))


def _norm(host: str) -> str:
    h = (host or "").strip().lower()
    return h[4:] if h.startswith("www.") else h


def _registrable(host: str) -> str:
    parts = _norm(host).split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def load_benchmark() -> dict:
    return json.loads(BENCH_PATH.read_text(encoding="utf-8"))


def load_progress() -> dict:
    if PROGRESS_PATH.is_file():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {"runs": [], "done_hosts": [], "failed": {}}


def save_progress(data: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _site_state_authed(path: Path, host: str) -> bool:
    """True only if the jar has an auth-looking cookie for host (not mere existence)."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    want = _registrable(host)
    # Require strong auth signals. Bare "sess"/"sid" matches analytics noise
    # (analytics_session_id, _gd_session, __ssid) and inflated skip_servable.
    auth_hints = (
        "auth_token",
        "access_token",
        "refresh_token",
        "id_token",
        "jwt",
        "credential",
        "logged_in",
        "is_logged",
        "_auth",
        "session_token",
        "sid_token",
    )
    # Also allow short exact-ish names common in real sessions.
    auth_exact = {"session", "sid", "token", "auth", "login"}
    noise = (
        "analytics",
        "ab.storage",
        "_ga",
        "_gid",
        "csrf",
        "xsrf",
        "intercom",
        "logged-out",
        "logged_out",
        "logout",
        "anonymous",
        "guest",
        "session_id",  # amplitude/segment style
        "fpgsid",
        "__ssid",
        "_uetsid",
        "phpsessid",
        "jsessionid",
        "browser_sess",
        "monolith-login",  # Evernote pre-auth
        "login-state",
        "login-code",
        "unauth",
    )
    for cookie in state.get("cookies") or []:
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        parts = domain.split(".")
        etld = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        if etld != want and want not in domain:
            continue
        name = str(cookie.get("name") or "").lower()
        if any(n in name for n in noise):
            continue
        if name in auth_exact or any(h in name for h in auth_hints):
            # Require a non-trivial value so empty marketing flags do not count.
            if len(str(cookie.get("value") or "")) >= 12:
                return True
    # Bitwarden-style SPA auth lives in localStorage, not cookies.
    for origin in state.get("origins") or []:
        origin_host = str(origin.get("origin") or "").lower()
        if want not in origin_host:
            continue
        for item in origin.get("localStorage") or []:
            name = str(item.get("name") or "").lower()
            if name.startswith("user_") and (
                "vault" in name or "account" in name or "token" in name
            ):
                return True
    return False


def servable_hosts() -> set[str]:
    """Hosts this machine can actually serve (auth cookies), not every jar file."""
    found: set[str] = set()
    script = ROOT / "scripts" / "vm" / "seed_status.py"
    if script.is_file():
        try:
            out = subprocess.check_output(
                [sys.executable, str(script)],
                cwd=str(ROOT),
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            data = json.loads(out)
            for h in data.get("servable") or []:
                found.add(_norm(str(h)))
        except Exception:
            pass
    # Fallback / supplement: auth-looking cookies in site_states jars.
    if SITE_STATES.is_dir():
        for p in SITE_STATES.glob("*.json"):
            host = _norm(p.stem)
            if host in found:
                continue
            if _site_state_authed(p, host):
                found.add(host)
    for part in (os.environ.get("MVP_SIGNUP_BENCHMARK_SKIP") or "").split(","):
        if part.strip():
            found.add(_norm(part))
    return found


def skip_set(bench: dict) -> set[str]:
    skips = {_norm(h) for h in (bench.get("skip_hosts") or [])}
    skips |= servable_hosts()
    expanded = set(skips)
    for h in list(skips):
        expanded.add(_registrable(h))
    return expanded


def pending_products(bench: dict) -> list[dict]:
    skips = skip_set(bench)
    progress = load_progress()
    done = {_norm(h) for h in (progress.get("done_hosts") or [])}
    products = sorted(
        bench.get("products") or [], key=lambda p: int(p.get("priority") or 99)
    )
    out: list[dict] = []
    for p in products:
        host = _norm(p.get("host") or "")
        if not host:
            continue
        if host in skips or _registrable(host) in skips:
            continue
        if host in done or _registrable(host) in done:
            continue
        out.append(p)
    return out


def cmd_status(_: argparse.Namespace) -> int:
    bench = load_benchmark()
    pending = pending_products(bench)
    progress = load_progress()
    print(
        json.dumps(
            {
                "total": len(bench.get("products") or []),
                "skip_servable": sorted(skip_set(bench)),
                "pending": [p["host"] for p in pending],
                "pending_count": len(pending),
                "progress_done": progress.get("done_hosts") or [],
                "next": pending[0]["host"] if pending else None,
            },
            indent=2,
        )
    )
    return 0


def cmd_next(_: argparse.Namespace) -> int:
    pending = pending_products(load_benchmark())
    print(pending[0]["host"] if pending else "none")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from signup_targets import _run_one  # noqa: WPS433

    bench = load_benchmark()
    pending = pending_products(bench)
    if args.host:
        want = {_norm(h) for h in args.host}
        hosts = [p["host"] for p in pending if _norm(p["host"]) in want]
        missing = want - {_norm(h) for h in hosts}
        if missing and args.force:
            hosts.extend(sorted(missing))
        elif missing:
            print(
                f"skip (already done / not pending): {', '.join(sorted(missing))}",
                flush=True,
            )
    elif args.all_pending:
        hosts = [p["host"] for p in pending]
    else:
        hosts = [pending[0]["host"]] if pending else []

    if not hosts:
        print("nothing to run")
        return 0

    print(f"benchmark run hosts={hosts}", flush=True)
    results: list[dict] = []
    if args.parallel <= 1:
        for i, h in enumerate(hosts):
            results.append(_run_one(h, i, args.timeout, args.max_steps, True))
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = {
                pool.submit(_run_one, h, i, args.timeout, args.max_steps, True): h
                for i, h in enumerate(hosts)
            }
            for fut in as_completed(futs):
                results.append(fut.result())

    progress = load_progress()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in results:
        host = _norm(str(row.get("host") or ""))
        progress.setdefault("runs", []).append(
            {
                "ts": ts,
                "host": host,
                "ok": bool(row.get("ok")),
                "reason": row.get("reason"),
            }
        )
        if row.get("ok"):
            done = set(progress.get("done_hosts") or [])
            done.add(host)
            done.add(_registrable(host))
            progress["done_hosts"] = sorted(done)
            progress.setdefault("failed", {}).pop(host, None)
        else:
            progress.setdefault("failed", {})[host] = row.get("reason") or "unknown"
    save_progress(progress)

    OUT_DIR.mkdir(parents=True, exist_ok=True)  # noqa: ensure dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_DIR / f"run_{stamp}.json"
    out.write_text(json.dumps({"hosts": hosts, "results": results}, indent=2) + "\n")
    for row in results:
        mark = "OK" if row.get("ok") else "FAIL"
        print(f"  {mark} {row.get('host')} -> {row.get('reason')}", flush=True)
    print(f"wrote {out}")
    return 0 if any(r.get("ok") for r in results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("next")
    p_run = sub.add_parser("run")
    p_run.add_argument("host", nargs="*")
    p_run.add_argument("--all-pending", action="store_true")
    p_run.add_argument("--force", action="store_true")
    p_run.add_argument("--timeout", type=int, default=int(os.environ.get("TIMEOUT_S", "480")))
    p_run.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "35")))
    p_run.add_argument("--parallel", type=int, default=1)
    args = ap.parse_args()
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "next":
        return cmd_next(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
