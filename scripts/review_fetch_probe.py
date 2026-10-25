"""Which way of fetching G2 / Capterra / Product Hunt review pages gets past their bot protection, from this machine.

Runs every method in mvp/review_fetch.py (Patchright, headed Chromium, headless Chromium, Camoufox, curl_cffi with a
Chrome fingerprint, a plain client) on each URL, through PROXY_URL when it is set and directly, and prints status /
title / size / whether a bot challenge was served. Never prints page content or the proxy.

One-time setup (see docs/discovery/HANDOVER.md):
    pip install curl_cffi httpx playwright patchright "camoufox[geoip]==0.4.11"
    python -m playwright install chromium && python -m patchright install chromium && python -m camoufox fetch

    python scripts/review_fetch_probe.py                      # default URLs, direct from this machine
    PROXY_URL='http://user:pass@gw.dataimpulse.com:823' python scripts/review_fetch_probe.py
    python scripts/review_fetch_probe.py https://www.g2.com/products/notion/reviews
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mvp import review_fetch as F  # noqa: E402

DEFAULT_URLS = [
    "https://www.g2.com/products/linear/reviews",
    "https://www.capterra.com/p/160498/Shortcut/reviews/",
    "https://www.producthunt.com/products/linear/reviews",
]


def main() -> None:
    urls = sys.argv[1:] or DEFAULT_URLS
    proxy = (os.environ.get("PROXY_URL") or "").strip() or None
    print(f"proxy: {'yes' if proxy else 'no (direct from this machine)'}\n")
    for url in urls:
        out = F.probe(url, proxy)
        print("==", url)
        for k, v in out.items():
            if k in ("url", "proxy"):
                continue
            if isinstance(v, dict) and "status" in v:
                ok = "PASS" if v["status"] == 200 and not v["challenge"] else "blocked"
                print(f"  {ok:7} {k:32} status={v['status']} title={v['title'][:50]!r} {v['kb']} KB {v['ms']} ms")
            else:
                print(f"  {'':7} {k:32} {json.dumps(v)[:200]}")
        print()


if __name__ == "__main__":
    main()
