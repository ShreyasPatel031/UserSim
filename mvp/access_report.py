"""Report product access status: identities, profiles, blockers.

Usage:
  PYTHONPATH=src:. .venv/bin/python -m mvp.access_report
  PYTHONPATH=src:. .venv/bin/python -m mvp.access_report --check https://linear.app
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mvp.captcha import status as captcha_status
from mvp.credentials import vault_status
from mvp.email_codes import _imap_creds, imap_ready
from mvp.identity import get_identity, list_identities, provision_identity
from mvp.profile_pool import profile_for_url
from mvp.sms_provider import status as sms_status


def _profile_freshness(path: Path | None) -> str:
    if not path or not path.is_dir():
        return "missing"
    try:
        mtimes = [p.stat().st_mtime for p in path.rglob("*") if p.is_file()]
        if not mtimes:
            return "empty"
        import datetime

        latest = max(mtimes)
        return datetime.datetime.fromtimestamp(latest).isoformat(timespec="seconds")
    except Exception:
        return "unknown"


def build_report() -> dict:
    identities = list_identities()
    products = []
    for ident in identities:
        profile = Path(ident.profile_dir) if ident.profile_dir else None
        products.append(
            {
                **ident.public_dict(),
                "profile_freshness": _profile_freshness(profile),
                "profile_exists": bool(profile and profile.is_dir()),
            }
        )

    imap = {"configured": False}
    creds = _imap_creds()
    if creds:
        ok, reason = imap_ready(creds[0], creds[1])
        imap = {"configured": True, "ok": ok, "reason": reason}

    return {
        "vault": vault_status(),
        "imap": imap,
        "sms": sms_status(),
        "captcha": captcha_status(),
        "products": products,
        "product_count": len(products),
    }


def check_url(url: str) -> dict:
    ident = get_identity(url) or provision_identity(url)
    profile = profile_for_url(url)
    from mvp.session_health import check

    signed = None
    try:
        signed = check(url)
    except Exception as exc:
        signed = f"error:{type(exc).__name__}"
    return {
        "url": url,
        "identity": ident.public_dict(),
        "profile": str(profile) if profile else None,
        "profile_freshness": _profile_freshness(profile),
        "signed_in": signed,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Product access / signup status report")
    ap.add_argument("--check", metavar="URL", help="Probe one URL (identity + health)")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    if args.check:
        report = check_url(args.check)
    else:
        report = build_report()

    if args.json:
        print(json.dumps(report, indent=2))
        return

    if args.check:
        print(f"URL:        {report['url']}")
        ident = report["identity"]
        print(f"Email:      {ident.get('email')}")
        print(f"Status:     {ident.get('status')} blocker={ident.get('blocker')}")
        print(f"Profile:    {report['profile']} ({report['profile_freshness']})")
        print(f"Signed in:  {report['signed_in']}")
        return

    print(f"Vault sites: {report['vault'].get('site_count')}  push={report['vault'].get('push_topic_set')}")
    print(f"IMAP:        {report['imap']}")
    print(f"SMS:         {report['sms']}")
    print(f"CAPTCHA:     {report['captcha']}")
    print(f"Products:    {report['product_count']}")
    if not report["products"]:
        print("  (none yet — run: python -m mvp.auto_signup --url https://...)")
        return
    print()
    print(f"{'HOST':<28} {'STATUS':<12} {'BLOCKER':<18} {'EMAIL':<36} PROFILE")
    for p in report["products"]:
        print(
            f"{p['host']:<28} {p['status']:<12} {str(p.get('blocker') or '-'):<18} "
            f"{p['email']:<36} {p['profile_freshness']}"
        )


if __name__ == "__main__":
    main()
    sys.exit(0)
