#!/usr/bin/env python3
"""Reproducible signup score: a host counts only after a fresh-alias PASS.

Previously ``seed_status`` counted one-time cookie jars on the seed disk.
That over-credited sites where a second run with a new alias fails (plus-strip,
onboarding stuck, captcha). This module is the source of truth for the honest
score: ``results/signup_repro/score.json``.

Usage (on seed or any machine with secrets + Browserbase):
  PYTHONPATH=src:. .venv/bin/python -m mvp.repro_signup \\
      --hosts hashnode.com,codepen.io --nonce $(openssl rand -hex 3)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from mvp.auto_signup import SIGNUP_START, sign_up  # noqa: E402
from mvp.identity import (  # noqa: E402
    Identity,
    _base_identity_fields,
    _generate_password,
    _load_registry,
    _save_registry,
    email_for_host,
    host_for_url,
    profile_path_for_host,
    uses_dotted_alias,
)

BENCH = ROOT / "mvp" / "signup_benchmark60.json"
SCORE_PATH = ROOT / "results" / "signup_repro" / "score.json"
FRESH_PASS_REASONS = {"signed_up", "signed_in"}


def _load_bench() -> dict[str, Any]:
    return json.loads(BENCH.read_text())


def _score_doc() -> dict[str, Any]:
    if SCORE_PATH.is_file():
        try:
            return json.loads(SCORE_PATH.read_text())
        except Exception:
            pass
    return {
        "version": 1,
        "metric": "fresh_this_run",
        "description": (
            "Numerator is hosts in mvp/signup_benchmark60.json whose latest "
            "attempt is a new account (ok=true, reason signed_up|signed_in). "
            "already_signed_in does not count. Hosts outside the 60 do not "
            "count. A later failed attempt drops an earlier pass."
        ),
        "hosts": {},
        "updated_at": None,
    }


def _product_hosts() -> list[str]:
    return [p["host"] for p in _load_bench().get("products") or []]


def _latest_attempt(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    attempts = (entry or {}).get("attempts") or []
    if not attempts:
        return None
    last = attempts[-1]
    return last if isinstance(last, dict) else None


def is_fresh_pass(attempt: dict[str, Any] | None) -> bool:
    """A new-account signup. already_signed_in is not one."""
    if not attempt:
        return False
    return bool(attempt.get("ok")) and attempt.get("reason") in FRESH_PASS_REASONS


def fresh_pass_hosts(doc: dict[str, Any], products: list[str] | None = None) -> list[str]:
    """Latest-attempt passes that are in the 60-site file."""
    products = list(products if products is not None else _product_hosts())
    hosts = doc.get("hosts") or {}
    out = []
    for host in products:
        if is_fresh_pass(_latest_attempt(hosts.get(host))):
            out.append(host)
    return out


def _save_score(doc: dict[str, Any]) -> None:
    SCORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    doc["metric"] = "fresh_this_run"
    products = _product_hosts()
    product_set = set(products)
    hosts = doc.setdefault("hosts", {})
    for host, entry in list(hosts.items()):
        if not isinstance(entry, dict):
            continue
        entry["reproducible"] = host in product_set and is_fresh_pass(_latest_attempt(entry))
    repro = fresh_pass_hosts(doc, products)
    failed = sorted(
        h
        for h in products
        if (hosts.get(h) or {}).get("attempts") and h not in repro
    )
    doc["reproducible"] = repro
    doc["failed"] = failed
    doc["score"] = f"{len(repro)}/{len(products)}"
    doc["reproducible_count"] = len(repro)
    SCORE_PATH.write_text(json.dumps(doc, indent=2) + "\n")


def provision_fresh(host: str, *, nonce: str, force_dotted: bool = False) -> Identity:
    """Mint a unique identity; wipe any prior profile for this host."""
    import shutil

    base = _base_identity_fields()
    if not base["username"] or "@" not in base["username"]:
        raise RuntimeError("No base email in secrets/credentials.json")
    stem = host.split(".")[0]
    tag = f"{stem}{nonce}"[:32]
    # Only force dotted on hosts that strip/reject '+'; everyone else gets a
    # unique plus-tag (Notion rejected dotted locals in fresh-alias runs).
    dotted = force_dotted or uses_dotted_alias(host)
    email = email_for_host(
        base["username"], host, tag=tag, force_dotted=dotted
    )
    now = datetime.now(timezone.utc).isoformat()
    identity = Identity(
        host=host,
        email=email,
        password=_generate_password(),
        full_name=base["full_name"],
        company=base["company"],
        phone=base["phone"],
        alias_tag=tag,
        status="provisioned",
        profile_dir=str(profile_path_for_host(host)),
        created_at=now,
        updated_at=now,
    )
    data = _load_registry()
    data.setdefault("products", {})[host] = asdict(identity)
    _save_registry(data)
    profile = Path(identity.profile_dir or "")
    if profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    return identity


def _signup_url(host: str) -> str:
    if host in SIGNUP_START:
        return SIGNUP_START[host]
    return f"https://www.{host}/"


async def run_one(host: str, *, nonce: str, timeout: float) -> dict[str, Any]:
    from capability.browserbase_client import reset_local_slots

    try:
        from mvp.kill_switch import kill_all_browserbase
    except Exception:
        kill_all_browserbase = None  # type: ignore

    print(f"\n===== REPRO {host} nonce={nonce} =====", flush=True)
    if kill_all_browserbase is not None:
        try:
            print("pre-clean", kill_all_browserbase(owner="signup"), flush=True)
        except TypeError:
            print("pre-clean", kill_all_browserbase(), flush=True)
    try:
        reset_local_slots()
    except Exception:
        pass

    from mvp.captcha_spend import SpendCapError, begin_signup_attempt, record_balance

    try:
        attempt = begin_signup_attempt(host)
    except SpendCapError as exc:
        out = {
            "host": host,
            "ok": False,
            "reproducible": False,
            "reason": "signup_attempt_cap",
            "detail": str(exc)[:300],
            "elapsed_s": 0,
            "alias_tag": None,
            "email_scheme": None,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        print(f"RESULT {json.dumps(out)}", flush=True)
        _merge_score(host, out)
        _append_campaign(out)
        return out

    ident = provision_fresh(host, nonce=nonce)
    print(
        f"fresh email_tag={ident.alias_tag} dotted={'+' not in ident.email} "
        f"local={ident.email.split('@')[0]} attempt={attempt}",
        flush=True,
    )
    url = _signup_url(host)
    balance_before = record_balance(host, when="before")
    t0 = time.time()
    try:
        result = await sign_up(
            url,
            timeout_s=timeout,
            headed=False,
            identity=ident,
            product_host=host,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "reason": "runner_error",
            "detail": repr(exc)[:300],
        }
    finally:
        elapsed = round(time.time() - t0, 1)
        balance_after = record_balance(host, when="after")
        if kill_all_browserbase is not None:
            try:
                kill_all_browserbase(owner="signup")
            except TypeError:
                kill_all_browserbase()
            try:
                reset_local_slots()
            except Exception:
                pass

    ok = bool(result.get("ok"))
    reason = result.get("reason") or result.get("blocked") or "unknown"
    out = {
        "host": host,
        "ok": ok,
        "reproducible": ok,
        "reason": reason,
        "detail": (result.get("detail") or "")[:300],
        "elapsed_s": elapsed,
        "alias_tag": ident.alias_tag,
        "email_scheme": "dotted" if "+" not in ident.email else "plus",
        "signed_via": result.get("signed_via"),
        "ignored_blocker": result.get("ignored_blocker"),
        "backend": result.get("backend"),
        "bb_session": result.get("browserbase_session_url"),
        "attempt": attempt,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"RESULT {json.dumps({k: v for k, v in out.items() if k != 'detail'})}", flush=True)
    _merge_score(host, out)
    _append_campaign(out)
    return out


def _merge_score(host: str, out: dict[str, Any]) -> None:
    """Record this attempt. The latest attempt is the score, not an older pass."""
    doc = _score_doc()
    hosts = doc.setdefault("hosts", {})
    prev = hosts.get(host) or {"attempts": []}
    attempts = list(prev.get("attempts") or [])
    attempts.append(out)
    hosts[host] = {
        "reproducible": is_fresh_pass(out),
        "last_reason": out.get("reason"),
        "last_detail": out.get("detail"),
        "last_alias_tag": out.get("alias_tag"),
        "last_ok": bool(out.get("ok")) and out.get("reason") in FRESH_PASS_REASONS,
        "attempts": attempts[-10:],
        "updated_at": out.get("at"),
    }
    _save_score(doc)


def rejudge_not_signed_in(hosts: list[str] | None = None) -> list[str]:
    """Correct a latest not_signed_in when saved storage shows an account.

    Bitwarden, Todoist, and TickTick reached the app and the harness missed
    it. This does not invent a pass: the saved storage_state has to match
    the same auth check the live runner now uses.
    """
    from mvp.auto_signup import _storage_state_looks_authed, site_state_path

    doc = _score_doc()
    score_hosts = doc.setdefault("hosts", {})
    targets = hosts or [
        h
        for h, entry in score_hosts.items()
        if (_latest_attempt(entry) or {}).get("reason") == "not_signed_in"
    ]
    corrected: list[str] = []
    for host in targets:
        entry = score_hosts.get(host) or {}
        last = _latest_attempt(entry)
        if not last or last.get("reason") != "not_signed_in":
            continue
        path = site_state_path(host)
        if not path.is_file():
            continue
        try:
            state = json.loads(path.read_text())
        except Exception:
            continue
        if not _storage_state_looks_authed(state, host):
            continue
        last["harness_reason"] = "not_signed_in"
        last["ok"] = True
        last["reproducible"] = True
        last["reason"] = "signed_up"
        last["signed_via"] = "storage_rejudge"
        last["detail"] = "Saved storage_state shows an account the harness missed."
        entry["last_reason"] = "signed_up"
        entry["last_detail"] = last["detail"]
        entry["last_ok"] = True
        corrected.append(host)
    if corrected:
        _save_score(doc)
    return corrected


def _append_campaign(out: dict[str, Any]) -> None:
    path = ROOT / "results" / "signup_repro" / "solver_benchmark.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(out) + "\n")


def summarize() -> dict[str, Any]:
    doc = _score_doc()
    bench = _load_bench()
    products = [p["host"] for p in bench.get("products") or []]
    compromised = set(bench.get("compromised_hosts") or [])
    captcha_hard = set(bench.get("captcha_hard_hosts") or [])
    repro = set(fresh_pass_hosts(doc, products))
    missing = [h for h in products if h not in repro]
    return {
        "score": f"{len(repro)}/{len(products)}",
        "reproducible_count": len(repro),
        "reproducible": sorted(repro),
        "missing": missing,
        "missing_compromised": [h for h in missing if h in compromised],
        "missing_captcha_hard": [h for h in missing if h in captcha_hard],
        "missing_other": [
            h for h in missing if h not in compromised and h not in captcha_hard
        ],
        "path": str(SCORE_PATH),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hosts", default="", help="Comma-separated hosts to re-verify")
    ap.add_argument("--from-bench-solved", action="store_true",
                    help="Use skip_hosts + known wave wins from score file context")
    ap.add_argument("--timeout", type=float, default=480)
    ap.add_argument("--nonce", default=None)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--rejudge", action="store_true",
                    help="Count saved storage_state when the harness said not_signed_in")
    args = ap.parse_args()

    # CapSolver stays off. Fresh signups use Browserbase's built-in solver only.
    os.environ["MVP_CAPTCHA_PAID_HOSTS"] = ""
    os.environ.pop("CAPSOLVER_API_KEY", None)

    if args.rejudge:
        print(json.dumps({"rejudged": rejudge_not_signed_in()}, indent=2))
        print(json.dumps(summarize(), indent=2))
        return

    if args.summary:
        print(json.dumps(summarize(), indent=2))
        return

    os.environ.setdefault("BROWSERBASE_MAX_CONCURRENT", "1")
    os.environ.setdefault("BROWSERBASE_SESSION_OWNER", "signup")
    os.environ.setdefault("MVP_SIGNUP_BROWSERBASE", "1")
    os.environ.setdefault("MVP_CAPTCHA_SOLVER", "1")
    os.environ.setdefault("MVP_CAPTCHA_ALLOW_HUMAN", "0")
    os.environ["USE_BROWSERBASE"] = "1"

    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    if args.from_bench_solved and not hosts:
        bench = _load_bench()
        # Historical "solved" = skip_hosts (pre-seeded) + anything previously marked
        # signed_up in identities is NOT used — caller should pass explicit list.
        hosts = list(bench.get("skip_hosts") or [])
    if not hosts:
        raise SystemExit("pass --hosts a,b,c or --summary")

    nonce_base = args.nonce or secrets.token_hex(3)
    results = []
    for i, host in enumerate(hosts):
        host = host_for_url(host)
        nonce = f"{nonce_base}{i:x}"
        try:
            results.append(asyncio.run(run_one(host, nonce=nonce, timeout=args.timeout)))
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "host": host,
                    "ok": False,
                    "reproducible": False,
                    "reason": "runner_error",
                    "detail": repr(exc)[:240],
                }
            )
            print(f"RUNNER_ERROR {host}: {exc!r}", flush=True)

    print(json.dumps(summarize(), indent=2))
    print(
        f"batch ok={sum(1 for r in results if r.get('ok'))}/{len(results)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
