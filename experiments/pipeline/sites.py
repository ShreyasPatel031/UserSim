"""Each launch's real website, from Product Hunt's own link (producthunt.com/r/<code>, the launch's Website button),
not guessed from the name. Product Hunt blocks routes 1 and 3 of the fetch ladder on these links (403 on 20 of 20 in
the pilot), so the link is opened on route 4 (Camoufox through the DataImpulse proxy, fetch.browser_get), which
follows the redirect to the launch's site; the site's final URL and visible text (first 4,000 characters) are kept,
and parked / for-sale pages flagged.
Resumable; bytes and dollars per launch for the spend log.
usage: [SITES_IDS=ids.txt] python -m pipeline.sites [limit] [threads] -> ph_predict/data/sites_ph.jsonl
(SITES_IDS: only the launches whose ids are listed, e.g. those without a trustworthy site)"""
import glob, json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from curl_cffi import requests as R
from . import fetch as F

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.dirname(HERE), "ph_predict", "data")
OUT = f"{D}/sites_ph.jsonl"
PARKED = re.compile(r"(?i)domain (is )?for sale|is for sale|buy this domain|this domain may be for sale|parked (free|domain)|domain parking")


def text(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html or "")
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()[:4000]


def where(url):
    """Target of a Product Hunt redirect link, climbing the ladder only when blocked."""
    rec = {"route": None, "bytes": 0, "target": None, "status": 0}
    for name, proxy in F.ROUTES:
        try:
            r = R.get(url, impersonate="chrome", proxies={"https": proxy, "http": proxy} if proxy else None, timeout=60, allow_redirects=False)
        except Exception:  # noqa: BLE001
            continue
        rec["bytes"] += len(r.content); rec.update(route=name, status=r.status_code)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            rec["target"] = urljoin(url, r.headers["location"]); return rec
        if not F.blocked(r):
            m = re.search(r"""(?i)url=['"]?([^'" >]+)|window\.location(?:\.href)?\s*=\s*['"]([^'"]+)""", r.text[:20000])
            if m:
                rec["target"] = m.group(1) or m.group(2)
            return rec
    return rec


def site_text(url):
    try:
        r = R.get(url, impersonate="chrome", timeout=30)
        return r.url, r.status_code, text(r.text), len(r.content)
    except Exception:  # noqa: BLE001
        return url, -1, "", 0


def main(limit=10**9, threads=2):   # browsers: at most a few at once
    L = {}
    for f in sorted(glob.glob(f"{D}/days/*.json")) + sorted(glob.glob(f"{D}/today/*.json")):
        for p in json.load(open(f)):
            if "producthunt.com/r/" in (p.get("website") or ""):
                L[str(p["id"])] = p["website"].split("?")[0]
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    only = set(open(os.environ["SITES_IDS"]).read().split()) if os.environ.get("SITES_IDS") else None   # fetch only these launches
    todo = sorted((i for i in L if i not in done and (only is None or i in only)), key=lambda i: -int(i))[:limit]
    print("launches", len(todo), flush=True)
    lock = threading.Lock(); tot = {"ok": 0, "no_target": 0, "parked": 0, "ph_bytes": {"direct": 0, "dataimpulse": 0}}

    def one(i):
        b = F.browser_get(L[i])
        rec = {"id": i, "ph_link": L[i], "route": b["route"], "status": b["status"], "url": None, "text": "", "parked": False, "bytes": b["bytes"]}
        if b["final_url"] and "producthunt.com" not in b["final_url"]:
            t = text(b["body"]); rec.update(url=b["final_url"], text=t, parked=bool(PARKED.search(t[:2000])))
        with lock:
            tot["ok" if rec["text"] else "no_target"] += 1; tot["parked"] += rec["parked"]
            tot["ph_bytes"]["dataimpulse"] += b["bytes"]
            f.write(json.dumps(rec) + "\n"); f.flush()
    with open(OUT, "a") as f, ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    usd = round(tot["ph_bytes"]["dataimpulse"] / 1e9 * F.USD_PER_GB["dataimpulse"], 4)
    print(json.dumps({**tot, "dataimpulse_usd": usd}), flush=True)
    return {"items": tot["ok"], "bytes": sum(tot["ph_bytes"].values()), "usd": usd}


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10**9, int(sys.argv[2]) if len(sys.argv) > 2 else 2)
