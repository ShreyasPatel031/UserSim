"""Runs on the VM. Reads URLs (one per line) on stdin, fetches them through the Apify proxy (datacenter first,
residential on a block), writes one JSON line per URL to stdout: {url, status, route, html}.
Used as:  ssh vm 'python ~/php/vmfetch.py 8' < urls.txt | gzip > pages.jsonl.gz   (the container can't reach the proxy)"""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as R

P = open(os.path.expanduser("~/php/proxy.txt")).read().strip()
ROUTES = [("dc", P), ("resi", P.replace("//auto:", "//groups-RESIDENTIAL,country-US:"))]
lock = threading.Lock()


def one(url):
    rec = {"url": url, "status": 0, "route": "", "final_url": "", "html": ""}
    for name, px in ROUTES:
        for _ in range(2):
            try:
                r = R.get(url, impersonate="chrome", proxies={"https": px, "http": px}, timeout=60)
                rec.update(status=r.status_code, route=name, final_url=str(r.url))
                if r.status_code == 200:
                    rec["html"] = r.text
                    break
            except Exception as e:  # noqa: BLE001
                rec.update(status=-1, route=name, html=str(e)[:200])
        if rec["status"] == 200:
            break
    with lock:
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    urls = [u.strip() for u in sys.stdin if u.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 8) as ex:
        list(ex.map(one, urls))
