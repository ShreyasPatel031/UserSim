"""Live review scrapes for a list of product names, through the fetch gateway (fetchgate.run_actor), 4 at a time.

    ALLOW_APIFY=1 FETCH_JOB=hm-scrape PYTHONPATH=src python experiments/staged_context/hm/apify_scrape.py names.txt outdir

Writes <outdir>/<slug>.json = {query, run_id, usd, ts, items} (skips names already there). This script never sees
the Apify token; the gateway logs each run's cost and stops the job at its budget (FETCH_BUDGET_USD, default $5).
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import fetchgate  # noqa: E402

ACTOR = "zen-studio~software-review-scraper"


def one(name: str, out: Path) -> None:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    dest = out / f"{s}.json"
    if dest.is_file() and dest.stat().st_size:
        return
    payload = {"query": name, "platforms": ["g2", "capterra", "trustradius", "gartner"], "maxResults": 100,
               "sort": "most_recent", "starRatings": []}
    run: dict = {}
    try:
        items = fetchgate.run_actor(ACTOR, payload, wait_s=1200, estimate_usd=0.6, info=run)
    except fetchgate.BudgetExceeded:
        raise
    except RuntimeError as exc:
        print(f"{name}: {exc}", flush=True)
        return
    dest.write_text(json.dumps({"query": name, "run_id": run.get("run_id"), "usd": run.get("usd"),
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": items}))
    print(f"{name}: {len(items)} reviews ${run.get('usd')}", flush=True)


if __name__ == "__main__":
    names = [x.strip() for x in open(sys.argv[1]) if x.strip()]
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda n: one(n, out), names))
    print(json.dumps(fetchgate.job_summary()), flush=True)
    print("DONE")
