"""Which way of fetching G2 / Capterra / Product Hunt review pages gets past their bot protection, from this machine.

Runs every method in src/fetchgate/ladder.py (Patchright, headed Chromium, headless Chromium, Camoufox, curl_cffi with
a Chrome fingerprint, a plain client) on each URL, through the gateway's residential proxy when this machine has one
(src/fetchgate/creds.py) and directly, and prints status / title / size / whether a bot challenge was served. Never
prints page content or the proxy. Costs are logged by the gateway under job probe-<date>.

One-time setup (see docs/discovery/HANDOVER.md):
    pip install curl_cffi httpx playwright patchright "camoufox[geoip]==0.4.11"
    python -m playwright install chromium && python -m patchright install chromium && python -m camoufox fetch

    PYTHONPATH=src python scripts/review_fetch_probe.py                      # default URLs
    PYTHONPATH=src python scripts/review_fetch_probe.py https://www.g2.com/products/notion/reviews
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fetchgate  # noqa: E402
from fetchgate import creds  # noqa: E402

DEFAULT_URLS = [
    "https://www.g2.com/products/linear/reviews",
    "https://www.capterra.com/p/160498/Shortcut/reviews/",
    "https://www.producthunt.com/products/linear/reviews",
]


def main() -> None:
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return
    urls = sys.argv[1:] or DEFAULT_URLS
    print(f"residential proxy: {'yes' if creds.residential() else 'no (direct from this machine)'}\n")
    for url in urls:
        try:
            out = fetchgate.probe(url, kind="saved")
        except ValueError as exc:
            print(f"== {url}\n  skipped: {exc}\n")
            continue
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
