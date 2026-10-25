"""Runs on the VM, slowly (Wayback bans bursts): for each (id, url, day-before-launch) find the last capture on/before
that day (CDX, fastLatest), then fetch that snapshot. Output wb_snap.jsonl (resumable)."""
import json, os, sys, threading, time, re
from concurrent.futures import ThreadPoolExecutor
import requests

UA = {"User-Agent": "Mozilla/5.0 (research; ph-predict backtest)"}
lock = threading.Lock()
GAP = 1.0  # seconds between requests per worker


def get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=40, **kw)
            time.sleep(GAP)
            if r.status_code == 429:
                time.sleep(60); continue
            return r
        except Exception:  # noqa: BLE001
            time.sleep(5 * (i + 1))
    return None


def one(t, f):
    host = re.sub(r"^https?://", "", t["url"]).split("/")[0]
    rec = {"id": t["id"], "wb_n_before": None, "wb_ts": "", "html": ""}
    r = get("https://web.archive.org/cdx/search/cdx", params={"url": host, "to": t["eve"], "fl": "timestamp",
                                                             "filter": "statuscode:200", "limit": "-1", "fastLatest": "true"})
    if r is not None and r.status_code == 200:
        rows = r.text.split()
        rec["wb_n_before"], rec["wb_ts"] = len(rows), (rows[-1] if rows else "")
        if rows:
            s = get(f"https://web.archive.org/web/{rows[-1]}id_/{t['url']}")
            if s is not None and s.status_code == 200:
                rec["html"] = s.text[:300000]
    with lock:
        f.write(json.dumps(rec) + "\n"); f.flush()


if __name__ == "__main__":
    inp, out = sys.argv[1], sys.argv[2]
    done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
    todo = [json.loads(l) for l in open(inp) if json.loads(l)["id"] not in done]
    print("todo", len(todo), flush=True)
    with open(out, "a") as f, ThreadPoolExecutor(3) as ex:
        for i, _ in enumerate(ex.map(lambda t: one(t, f), todo)):
            if i % 50 == 0:
                print(i, time.strftime("%H:%M:%S"), flush=True)
