"""Runs on the VM. For each launch: resolve the Product Hunt /r/ link to the real website (Apify datacenter proxy),
then take the Wayback snapshot closest to (and not after) launch day, else the live site. Also counts Wayback
captures before launch (a traffic/age signal that cannot see the launch result).

in: posts.jsonl {id, website, date}   out: sites.jsonl (append; resumable)"""
import datetime as dt, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

PROXY = os.environ["APIFY_PROXY"]  # http://auto:<pw>@proxy.apify.com:8000
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
lock = threading.Lock()
wb_sem = threading.Semaphore(12)


def resolve(link):
    for _ in range(3):
        try:
            r = requests.get(link, proxies={"http": PROXY, "https": PROXY}, allow_redirects=False, timeout=30,
                             headers=UA)
            loc = r.headers.get("location", "")
            if r.status_code in (301, 302, 303, 307, 308) and loc:
                return re.sub(r"[?&](ref|utm_[a-z]+)=[^&]*", "", loc).rstrip("?&")
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return ""


def wayback(url, ymd):
    out = {"wb_n_before": 0, "wb_first": "", "wb_ts": ""}
    host = re.sub(r"^https?://", "", url).split("/")[0]
    with wb_sem:
        for _ in range(3):
            try:
                r = requests.get("https://web.archive.org/cdx/search/cdx", timeout=40, params={
                    "url": host, "to": ymd, "fl": "timestamp,statuscode", "collapse": "timestamp:8",
                    "filter": "statuscode:200", "limit": "5000"})
                rows = [l.split() for l in r.text.splitlines() if l.strip()]
                out["wb_n_before"] = len(rows)
                if rows:
                    out["wb_first"], out["wb_ts"] = rows[0][0], rows[-1][0]
                break
            except Exception:  # noqa: BLE001
                time.sleep(3)
    return out


def get_html(url, ts):
    if ts:
        try:
            with wb_sem:
                r = requests.get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=40, headers=UA)
            if r.ok and len(r.text) > 500:
                return r.text, "wayback"
        except Exception:  # noqa: BLE001
            pass
    try:
        r = requests.get(url, timeout=25, headers=UA)
        return (r.text if r.ok else ""), ("live" if r.ok else f"live_{r.status_code}")
    except Exception as e:  # noqa: BLE001
        return "", "dead"


def one(p, f):
    url = resolve(p["website"]) if "producthunt.com/r/" in (p["website"] or "") else (p["website"] or "")
    rec = {"id": p["id"], "url": url}
    if url and "producthunt.com" not in url:
        eve = (dt.date.fromisoformat(p["date"]) - dt.timedelta(days=1)).strftime("%Y%m%d")
        rec.update(wayback(url, eve))  # up to the day before launch: launch-day captures already see PH traffic
        html, src = get_html(url, rec["wb_ts"])
        rec["src"], rec["html"] = src, html[:400000]
    with lock:
        f.write(json.dumps(rec) + "\n"); f.flush()


def main(inp, outp, workers=40):
    done = set()
    if os.path.exists(outp):
        done = {json.loads(l)["id"] for l in open(outp) if l.strip()}
    posts = [json.loads(l) for l in open(inp) if l.strip()]
    posts = [p for p in posts if p["id"] not in done]
    print("todo", len(posts), flush=True)
    with open(outp, "a") as f, ThreadPoolExecutor(workers) as ex:
        for i, _ in enumerate(ex.map(lambda p: one(p, f), posts)):
            if i % 100 == 0:
                print(i, time.strftime("%H:%M:%S"), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
