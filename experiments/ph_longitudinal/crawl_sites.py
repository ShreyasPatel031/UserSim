"""Resolve each launch's PH redirect to its real website and save the homepage text (Apify Website Content Crawler).

PH's API only gives producthunt.com/r/<code> links, which Cloudflare blocks for data-centre IPs, so the crawl runs
on Apify with US residential IPs (cheerio, no browser, depth 0). Batches run in parallel; posts already on disk are
skipped, so it can be re-run as more days are collected.

    APIFY_TOKEN=... python experiments/ph_longitudinal/crawl_sites.py [first_day] [Website|Github]
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DAYS = HERE / "cache" / "ph_days"
WEB = HERE / "cache" / "web"
API = "https://api.apify.com/v2"
BATCH, PARALLEL = 300, 4


def _code(url: str) -> str:
    return url.split("/r/")[1].split("?")[0] if "/r/" in (url or "") else ""


def todo(first_day: str, link: str = "Website") -> list[tuple[str, str]]:
    """(post id, redirect code) for each launch's main website, or for its first product link of type `link`."""
    done = {p.stem for p in WEB.glob("*.json")}
    out = []
    for f in sorted(DAYS.glob("*.json")):
        if f.stem < first_day:
            continue
        for e in json.loads(f.read_text())["edges"]:
            n = e["node"]
            if link == "Website":
                code = _code(n.get("website"))
            else:
                code = next((_code(l["url"]) for l in n.get("productLinks") or [] if l["type"] == link), "")
            if code and n["id"] not in done:
                out.append((n["id"], code))
    return out


def run_batch(batch: list[tuple[str, str]]) -> int:
    tok = os.environ["APIFY_TOKEN"]
    by_code = {c: pid for pid, c in batch}
    inp = {"startUrls": [{"url": f"https://www.producthunt.com/r/{c}"} for _, c in batch], "maxCrawlDepth": 0,
           "maxCrawlPages": len(batch), "crawlerType": "cheerio", "saveHtml": False, "saveMarkdown": False,
           "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
           "maxConcurrency": 30, "maxRequestRetries": 1, "requestTimeoutSecs": 30}
    run = requests.post(f"{API}/acts/apify~website-content-crawler/runs", params={"token": tok}, json=inp,
                        timeout=60).json()["data"]
    while run["status"] in ("READY", "RUNNING"):
        time.sleep(20)
        run = requests.get(f"{API}/actor-runs/{run['id']}", params={"token": tok}, timeout=60).json()["data"]
    items = requests.get(f"{API}/datasets/{run['defaultDatasetId']}/items", params={"token": tok, "clean": 1},
                         timeout=300).json()
    seen = set()
    for it in items:
        pid = by_code.get(_code(it.get("url", "")))
        if not pid:
            continue
        seen.add(pid)
        (WEB / f"{pid}.json").write_text(json.dumps({
            "id": pid, "loaded_url": it["crawl"].get("loadedUrl"), "status": it["crawl"].get("httpStatusCode"),
            "title": (it.get("metadata") or {}).get("title"), "description": (it.get("metadata") or {}).get("description"),
            "language": (it.get("metadata") or {}).get("languageCode"), "text": (it.get("text") or "")[:20000]}))
    for pid, _ in batch:  # failed loads: record so they are not retried forever
        if pid not in seen:
            (WEB / f"{pid}.json").write_text(json.dumps({"id": pid, "status": None}))
    usd = run.get("usageTotalUsd")
    print(f"batch of {len(batch)}: {len(seen)} loaded, run {run['status']}, ${usd}", flush=True)
    return len(seen)


def main(first_day: str = "2026-01-01", link: str = "Website") -> None:
    """link="Github" crawls each launch's GitHub link into cache/web_github instead."""
    global WEB
    if link != "Website":
        WEB = HERE / "cache" / f"web_{link.lower()}"
    WEB.mkdir(parents=True, exist_ok=True)
    work = todo(first_day, link)
    print(f"{len(work)} sites to crawl", flush=True)
    batches = [work[i:i + BATCH] for i in range(0, len(work), BATCH)]
    with ThreadPoolExecutor(PARALLEL) as ex:
        list(ex.map(run_batch, batches))


if __name__ == "__main__":
    main(*sys.argv[1:3])
