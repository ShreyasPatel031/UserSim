"""Runs on the VM. Opens each URL (stdin) in a browser through the fetch gateway (Camoufox on the VM's own IP first,
then through the residential proxy; Apify only with ALLOW_APIFY=1) and scrolls to the bottom until nothing new loads
(or MAX_SCROLLS), the way a person scrolling the page would. Records every JSON response the page receives from
producthunt.com and the final page HTML. One JSON line per URL: {url, status, route, scrolls, responses, html}.
Run with:  FETCH_JOB=ph-scroll python3 vm_scroll.py 2 < urls.txt > out.jsonl"""
import json, sys, threading
from concurrent.futures import ThreadPoolExecutor

from _gate import fetchgate

MAX_SCROLLS = 400
lock, stop = threading.Lock(), threading.Event()


def one(url):
    if stop.is_set():
        return
    rec = {"url": url, "status": 0, "route": "", "scrolls": 0, "responses": []}
    try:
        r = fetchgate.fetch(url, scroll=True, capture="producthunt.com", max_scrolls=MAX_SCROLLS)
        rec.update(status=r["status"], route=r["route"], scrolls=r.get("scrolls", 0),
                   responses=[{"url": x["url"], "status": x["status"], "body": x["body"]}
                              for x in r.get("responses", []) if "body" in x],
                   html=(r.get("html") or "")[:8_000_000])
    except fetchgate.BudgetExceeded as e:
        stop.set(); print(f"budget stop: {e}", file=sys.stderr, flush=True); return
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)[:300]
    with lock:
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    urls = [x.strip() for x in sys.stdin if x.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 2) as ex:
        list(ex.map(one, urls))
    print(json.dumps(fetchgate.job_summary()), file=sys.stderr, flush=True)
    sys.exit(3 if stop.is_set() else 0)
