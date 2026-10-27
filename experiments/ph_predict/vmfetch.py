"""Runs on the VM. Reads URLs (one per line) on stdin, fetches each through the fetch gateway (cheapest route that gets
the real page: VM IP, VM + Camoufox, residential, residential + Camoufox; Apify only with ALLOW_APIFY=1), writes one
JSON line per URL to stdout: {url, status, route, final_url, html}. The job's route mix and $ go to stderr at the end;
a budget stop (FETCH_BUDGET_USD, default $5 per FETCH_JOB) ends the run with exit code 3.
Used as:  ssh vm 'FETCH_JOB=ph-pages python3 ~/php/vmfetch.py 8' < urls.txt | gzip > pages.jsonl.gz
RESI_ONLY=1: residential routes only (skips the VM's own IP)."""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor

from _gate import fetchgate

ROUTES = ("residential", "residential_camoufox") if os.environ.get("RESI_ONLY") == "1" else None
lock, stop = threading.Lock(), threading.Event()


def one(url):
    if stop.is_set():
        return
    try:
        r = fetchgate.fetch(url, routes=ROUTES)
    except fetchgate.BudgetExceeded as e:
        stop.set(); print(f"budget stop: {e}", file=sys.stderr, flush=True); return
    except Exception as e:  # noqa: BLE001
        r = {"status": -1, "route": "", "final_url": "", "html": str(e)[:200]}
    rec = {"url": url, "status": r["status"], "route": r["route"], "final_url": r["final_url"],
           "html": r["html"] if r["route"] and r["status"] == 200 else r["html"][:200]}
    with lock:
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    urls = [u.strip() for u in sys.stdin if u.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 8) as ex:
        list(ex.map(one, urls))
    print(json.dumps(fetchgate.job_summary()), file=sys.stderr, flush=True)
    sys.exit(3 if stop.is_set() else 0)
