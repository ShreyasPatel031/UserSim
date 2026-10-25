"""Runs on the VM. stdin: Product Hunt usernames. For each, fetches the profile's Stacks, Reviews and Activity tabs
(through the Apify proxy) and keeps only parsed fields; raw pages are not stored.
  stacks    products the person says they use      [{product_id, slug, name}]
  reviews   products they reviewed                 [{review_id, product_id?, rating, type, created}]
  activity  their most recent actions (20, dated)  [{occurred, subject_type, subject_id}]
Writes one JSON line per username."""
import json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as R

P = open(os.path.expanduser("~/php/proxy.txt")).read().strip()
ROUTES = [P, P.replace("//auto:", "//groups-RESIDENTIAL,country-US:")]
lock = threading.Lock()


def get(url):
    for px in ROUTES:
        for _ in range(2):
            try:
                r = R.get(url, impersonate="chrome", proxies={"https": px, "http": px}, timeout=60)
                if r.status_code in (200, 404):
                    return r.status_code, r.text.replace('\\"', '"')
            except Exception:  # noqa: BLE001
                pass
    return -1, ""


def stacks(h):
    """Each stack entry, in either layout; `added` is when the person added the product (when present)."""
    out = []
    for m in re.finditer(r'"__typename":"ProductStack","id":"(\d+)"', h):
        seg = h[m.start(): m.start() + 900]
        pm = re.search(r'"product":\{"__typename":"Product","id":"(\d+)"', seg)
        if not pm:
            continue
        ps = seg[pm.start(): pm.start() + 500]
        g = lambda k: (re.search(k, ps) or [None, None])[1]
        out.append({"product_id": pm.group(1), "slug": g(r'"slug":"([^"]+)"'), "name": g(r'"name":"((?:[^"\\]|\\.)*)"'),
                    "added": (re.search(r'"createdAt":"([^"]+)"', seg[:pm.start()]) or [None, None])[1]})
    best = {}
    for x in out:  # keep the richest record per product
        if x["product_id"] not in best or (x["added"] and not best[x["product_id"]]["added"]):
            best[x["product_id"]] = x
    return list(best.values())


def reviews(h):
    """Each review the person wrote: the reviewed product (short product ref inside the review), rating, date, text."""
    starts = [m.start() for m in re.finditer(r'"__typename":"DetailedReview","id":"\d+"', h)] + [len(h)]
    out = []
    for a, b in zip(starts, starts[1:]):
        seg = h[a: min(b, a + 8000)]
        g = lambda k: (re.search(k, seg) or [None, None])[1]
        prod = re.search(r'"followProduct":\{"__typename":"Product","id":"(\d+)",[^}]*?"slug":"([^"]+)","name":"((?:[^"\\]|\\.)*)"', seg)
        txt = g(r'"overallExperience":"((?:[^"\\]|\\.)*)"')
        tags = lambda key: re.findall(r'"name":"([^"]+)","type":"(?:Positive|Negative)"', (seg.split('"' + key + '":', 1) + [""])[1].split("],", 1)[0])
        alts = re.findall(r'"slug":"([^"]+)"', (seg.split('"alternativeProducts":', 1) + [""])[1].split("],", 1)[0])
        out.append({"review_id": g(r'"id":"(\d+)"'), "rating": g(r'"overallRating":(\d+)'), "type": g(r'"reviewType":"([^"]+)"'),
                    "created": g(r'"createdAt":"([^"]+)"'), "product_id": prod.group(1) if prod else None,
                    "product_slug": prod.group(2) if prod else None, "product_name": prod.group(3) if prod else None,
                    "from_launch": g(r'"fromPost":\{"__typename":"Post","slug":"([^"]+)"'),
                    "pros": tags("selectedPros"), "cons": tags("selectedCons"), "alternatives": alts, "text": (txt or "")[:600]})
    return list({x["review_id"]: x for x in out}.values())


def activity(h):
    out = []
    for m in re.finditer(r'"__typename":"UserActivityEvent","id":"(\d+)","occurredAt":"([^"]+)"', h):
        seg = h[m.start(): m.start() + 1500]
        s = re.search(r'"subject":\{"__typename":"([A-Za-z]+)","id":"(\d+)"', seg)
        out.append({"event_id": m.group(1), "occurred": m.group(2), "subject_type": s.group(1) if s else None,
                    "subject_id": s.group(2) if s else None})
    return list({x["event_id"]: x for x in out}.values())


def one(u):
    rec = {"username": u}
    for tab, fn in (("stacks", stacks), ("reviews", reviews), ("activity", activity)):
        st, h = get(f"https://www.producthunt.com/@{u}/{tab}")
        rec[tab] = fn(h) if st == 200 else None
    with lock:
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    users = [l.strip() for l in sys.stdin if l.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 32) as ex:
        list(ex.map(one, users))
