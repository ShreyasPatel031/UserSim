"""Runs on the VM. stdin: JSON lines {competitor, slug}. Fetches the competitor's Product Hunt reviews pages (1-2)
through the fetch gateway (cheapest route that gets the page) and parses them with the app's own parser (mvp.review_parsers.parse_producthunt).
Writes one JSON line per competitor: {competitor, slug, status, reviews: [...]}; raw pages are not kept."""
import json, sys, threading
from concurrent.futures import ThreadPoolExecutor

from _gate import fetchgate

sys.path.insert(0, "/opt/usersim/app")
from mvp import review_parsers as RP  # noqa: E402

lock, stop = threading.Lock(), threading.Event()


def get(url):
    try:
        r = fetchgate.fetch(url)
    except fetchgate.BudgetExceeded as e:
        stop.set(); print(f"budget stop: {e}", file=sys.stderr, flush=True); return -1, ""
    except Exception:  # noqa: BLE001
        return -1, ""
    return (r["status"], r["html"]) if r["route"] and r["status"] in (200, 404) else (-1, "")


def one(job):
    if stop.is_set():
        return
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
    print(json.dumps(fetchgate.job_summary()), file=sys.stderr, flush=True)
    sys.exit(3 if stop.is_set() else 0)
