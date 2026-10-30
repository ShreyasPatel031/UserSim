"""Website text for every launch with a resolved site URL (data/sites.jsonl), for page scoring. Reuses pages already
fetched (sites_r*.jsonl.gz, by URL); the rest from the VM's own IP (route 1 of the fetch ladder, free). Keeps the
visible text only (first 4,000 characters), never the full page.
usage: python fetch_sites.py [threads] -> data/sites_text.jsonl"""
import gzip, json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
import requests

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/sites_text.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def text(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", t).strip()[:4000]


def main(threads):
    have = {}
    for fn in ("sites_r.jsonl.gz", "sites_r2.jsonl.gz"):
        for l in gzip.open(f"{D}/{fn}", "rt"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("status") == 200 and r.get("html"):
                have[r["url"]] = text(r["html"])
    S = [json.loads(l) for l in open(f"{D}/sites.jsonl")]
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [r for r in S if r.get("url") and r["id"] not in done]
    lock = threading.Lock(); stats = {"reused": 0, "fetched": 0, "failed": 0}
    print("sites", len(todo), "already fetched", sum(r["url"] in have for r in todo), flush=True)

    def one(r):
        t, how = have.get(r["url"]), "reused"
        if t is None:
            try:
                g = requests.get(r["url"], headers=UA, timeout=20)
                t, how = (text(g.text), "fetched") if g.status_code == 200 else (None, "failed")
            except Exception:  # noqa: BLE001
                t, how = None, "failed"
        with lock:
            stats[how] += 1
            if t:
                f.write(json.dumps({"id": r["id"], "url": r["url"], "text": t}) + "\n"); f.flush()
    with open(OUT, "a") as f, ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    print(stats, flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 16)
