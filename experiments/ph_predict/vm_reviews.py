"""Runs on the VM. stdin: JSON lines {competitor, slug}. Fetches the competitor's Product Hunt reviews pages (1-2)
through the Apify proxy and parses them with the app's own parser (mvp.review_parsers.parse_producthunt).
Writes one JSON line per competitor: {competitor, slug, status, reviews: [...]}; raw pages are not kept."""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as R

sys.path.insert(0, "/opt/usersim/app")
from mvp import review_parsers as RP  # noqa: E402

P = open(os.path.expanduser("~/php/proxy.txt")).read().strip()
ROUTES = [P, P.replace("//auto:", "//groups-RESIDENTIAL,country-US:")]
lock = threading.Lock()


def get(url):
    for px in ROUTES:
        for _ in range(2):
            try:
                r = R.get(url, impersonate="chrome", proxies={"https": px, "http": px}, timeout=60)
                if r.status_code in (200, 404):
                    return r.status_code, r.text
            except Exception:  # noqa: BLE001
                pass
    return -1, ""


def one(job):
    out = {"competitor": job["competitor"], "slug": job["slug"], "status": None, "reviews": []}
    base = f"https://www.producthunt.com/products/{job['slug']}/reviews"
    for page in (1, 2):
        st, html = get(base if page == 1 else RP.producthunt_next(base, page))
        out["status"] = out["status"] or st
        if st != 200:
            break
        rows = RP.parse_producthunt(html, job["competitor"])
        out["reviews"] += rows
        if len(rows) < 15:
            break
    with lock:
        sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    jobs = [json.loads(l) for l in sys.stdin if l.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 24) as ex:
        list(ex.map(one, jobs))
