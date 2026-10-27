"""Runs on the VM. Opens each URL (stdin, one per line) in a browser through the fetch gateway (Camoufox on the VM's
own IP first, then residential), scrolls and clicks "more comments" a few times, and records every JSON response from
Product Hunt's own data endpoint. Writes one JSON line per URL to stdout: {url, status, route, responses: [...]}.
Used as:  ssh vm 'FETCH_JOB=ph-browse python3 ~/php/vmbrowse.py 3' < urls.txt > out.jsonl"""
import json, sys, threading
from concurrent.futures import ThreadPoolExecutor

from _gate import fetchgate

lock, stop = threading.Lock(), threading.Event()


def one(url):
    if stop.is_set():
        return
    rec = {"url": url, "status": 0, "route": "", "responses": []}
    try:
        r = fetchgate.fetch(url, scroll=True, max_scrolls=6, capture="producthunt.com")
        html = r.get("html") or ""
        rec.update(status=r["status"], route=r["route"], responses=r.get("responses", []), html_len=len(html),
                   html=html[:3_000_000])
    except fetchgate.BudgetExceeded as e:
        stop.set(); print(f"budget stop: {e}", file=sys.stderr, flush=True); return
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)[:200]
    with lock:
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    urls = [x.strip() for x in sys.stdin if x.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 3) as ex:
        list(ex.map(one, urls))
    print(json.dumps(fetchgate.job_summary()), file=sys.stderr, flush=True)
    sys.exit(3 if stop.is_set() else 0)
