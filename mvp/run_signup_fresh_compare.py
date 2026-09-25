#!/usr/bin/env python3
"""Fresh-alias signup runner for branch comparison.

Provisions a unique plus-alias (never reuses a registered mailbox), runs
auto_signup with one Browserbase session tagged owner=signup.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

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
from mvp.auto_signup import sign_up  # noqa: E402


SITES = {
    "trello": "https://trello.com/",
    "hashnode": "https://hashnode.com/",
    "stackblitz": "https://stackblitz.com/",
    "wix": "https://www.wix.com/",
    "codepen": "https://codepen.io/",
}


def provision_fresh(url: str, *, nonce: str) -> Identity:
    """Always mint a new identity with unique alias tag — never reuse."""
    from datetime import datetime, timezone

    host = host_for_url(url)
    base = _base_identity_fields()
    if not base["username"] or "@" not in base["username"]:
        raise RuntimeError("No base email in secrets/credentials.json")
    stem = host.split(".")[0]
    tag = f"{stem}{nonce}"[:32]
    email = email_for_host(
        base["username"],
        host,
        tag=tag,
        force_dotted=uses_dotted_alias(host),
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
        import shutil

        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    return identity


def _running_signup_sessions() -> int:
    try:
        from capability.browserbase_client import Browserbase, browserbase_api_key

        bb = Browserbase(api_key=browserbase_api_key())
        listed = bb.sessions.list()
        items = getattr(listed, "data", None) or getattr(listed, "items", None) or listed
        n = 0
        for s in items:
            status = getattr(s, "status", None) or (
                s.get("status") if isinstance(s, dict) else None
            )
            meta = getattr(s, "user_metadata", None) or getattr(s, "metadata", None) or {}
            if isinstance(meta, str):
                meta = {}
            if status == "RUNNING" and (
                (meta or {}).get("owner") == "signup"
                or (meta or {}).get("purpose") == "signup"
            ):
                n += 1
        return n
    except Exception as exc:  # noqa: BLE001
        print(f"session list warn: {exc!r}", flush=True)
        return -1


async def run_one(
    name: str, url: str, *, nonce: str, timeout: float, shot_dir: Path | None = None
) -> dict:
    from capability.browserbase_client import reset_local_slots
    from mvp.kill_switch import kill_all_browserbase
    try:
        from capability.browserbase_client import BB_OWNER_SIGNUP
    except ImportError:
        BB_OWNER_SIGNUP = "signup"

    print(f"\n===== SIGNUP {name} url={url} nonce={nonce} =====", flush=True)
    # #33 kill_all may not take owner= — try both signatures.
    try:
        released = kill_all_browserbase(owner=BB_OWNER_SIGNUP)
    except TypeError:
        released = kill_all_browserbase()
    reset_local_slots()
    print(f"pre-clean signup sessions: {released}", flush=True)
    running = _running_signup_sessions()
    print(f"running_signup_sessions_before={running}", flush=True)
    if running > 0:
        # Soft wait: release again then proceed if still stuck (orphans).
        time.sleep(3)
        try:
            kill_all_browserbase(owner=BB_OWNER_SIGNUP)
        except TypeError:
            kill_all_browserbase()
        reset_local_slots()
        running = _running_signup_sessions()
        print(f"running_signup_sessions_retry={running}", flush=True)

    ident = provision_fresh(url, nonce=nonce)
    print(
        f"fresh identity host={ident.host} tag={ident.alias_tag} "
        f"email={ident.email.split('+')[0]}+…@{ident.email.split('@')[1]}",
        flush=True,
    )

    t0 = time.time()
    result = await sign_up(
        url,
        timeout_s=timeout,
        headed=False,
        identity=ident,
        product_host=ident.host,
    )
    elapsed = round(time.time() - t0, 1)
    try:
        post = kill_all_browserbase(owner=BB_OWNER_SIGNUP)
    except TypeError:
        post = kill_all_browserbase()
    reset_local_slots()
    running_after = _running_signup_sessions()

    safe = {k: v for k, v in (result or {}).items() if k != "password"}
    if "email" in safe and isinstance(safe["email"], str) and "@" in safe["email"]:
        e = safe["email"]
        safe["email"] = e.split("+")[0][:3] + "+…@" + e.split("@")[1]
    shot = ROOT / "secrets" / "signup_steps" / ident.host / "final.png"
    shot_rel = ""
    if shot_dir is not None and shot.is_file():
        dest = shot_dir / f"{name}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(shot.read_bytes())
        try:
            shot_rel = str(dest.relative_to(ROOT))
        except ValueError:
            shot_rel = str(dest)
    out = {
        "site": name,
        "url": url,
        "ok": bool(safe.get("ok")),
        "reason": safe.get("reason") or safe.get("status") or safe.get("blocked"),
        "detail": (safe.get("detail") or "")[:240],
        "elapsed_s": elapsed,
        "alias_tag": ident.alias_tag,
        "email_scheme": "dotted" if "+" not in ident.email else "plus",
        "signed_via": safe.get("signed_via"),
        "ignored_blocker": safe.get("ignored_blocker"),
        "backend": safe.get("backend"),
        "bb_session": safe.get("browserbase_session_url"),
        "screenshot": shot_rel,
        "running_signup_before": running,
        "running_signup_after": running_after,
        "released_after": post,
    }
    print(f"RESULT {json.dumps(out)}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch-label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=480)
    ap.add_argument(
        "--sites",
        default="trello,hashnode,stackblitz,wix,codepen",
    )
    ap.add_argument("--nonce", default=None)
    args = ap.parse_args()

    os.environ.setdefault("BROWSERBASE_MAX_CONCURRENT", "1")
    os.environ.setdefault("BROWSERBASE_SESSION_OWNER", "signup")
    os.environ.setdefault("MVP_SIGNUP_BROWSERBASE", "1")
    os.environ.setdefault("MVP_CAPTCHA_SOLVER", "1")
    os.environ["USE_BROWSERBASE"] = "1"

    nonce_base = args.nonce or secrets.token_hex(3)
    sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    out = Path(args.out)
    shot_dir = ROOT / "results" / "signup_matrix" / f"{args.branch_label}_{nonce_base}"
    results = []
    for i, name in enumerate(sites):
        url = SITES.get(name)
        if not url:
            raise SystemExit(f"unknown site {name!r}; choose from {sorted(SITES)}")
        nonce = f"{nonce_base}{i:x}"
        try:
            results.append(
                asyncio.run(
                    run_one(
                        name,
                        url,
                        nonce=nonce,
                        timeout=args.timeout,
                        shot_dir=shot_dir,
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "site": name,
                    "url": url,
                    "ok": False,
                    "reason": "runner_error",
                    "detail": repr(exc)[:240],
                    "alias_tag": None,
                }
            )
            print(f"RUNNER_ERROR {name}: {exc!r}", flush=True)

    payload = {
        "branch": args.branch_label,
        "nonce_base": nonce_base,
        "results": results,
        "ok_count": sum(1 for r in results if r.get("ok")),
        "n": len(results),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nWROTE {out} ok={payload['ok_count']}/{payload['n']}", flush=True)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
