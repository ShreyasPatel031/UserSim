"""Create or sign into the test accounts the execution cells need.

Opens a counted sign-up attempt first (captcha_spend.begin_signup_attempt), so
paid CAPTCHA solving is allowed under the ledger's per-site caps, then runs the
repo's auto_signup. Usage:
  python provision_accounts.py https://trello.com [--signin]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from mvp import auto_signup  # noqa: E402
from mvp import captcha_spend as cs  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--signin", action="store_true")
    a = ap.parse_args()
    host = (urlparse(a.url).hostname or "").removeprefix("www.")
    attempt = cs.begin_signup_attempt(host)
    cs.bind_signup(host, attempt)
    r = await auto_signup.sign_up(a.url, timeout_s=900, headed=False, signin=a.signin)
    print(json.dumps({k: v for k, v in r.items() if k not in ("password", "actions")}, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
