"""Find each launch's own website without touching producthunt.com: candidates are the makers' websiteUrl
(from the PH API), URLs in the description, and <slug|name>.{com,ai,app,io,so,dev,co}. A candidate counts only
if its page mentions the product name. Then Wayback: captures before launch + closest snapshot the day before
launch (else the live page). Output data/sites.jsonl (resumable)."""
import datetime as dt, glob, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
SKIP = re.compile(r"(?i)producthunt|linkedin|twitter|x\.com|github\.com/?$|instagram|facebook|youtube|medium\.com|"
                  r"substack|linktr|bento\.me|notion\.site|calendly|t\.me|discord")
lock = threading.Lock()
wb = threading.Semaphore(8)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch(url, timeout=12):
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        return r.url, r.status_code, r.text[:400000]
    except Exception:  # noqa: BLE001
        return url, 0, ""


def candidates(p):
    """(url, trusted) — maker websites and description links are trusted; guessed domains need pitch overlap."""
    c = []
    for m in p.get("makers") or []:
        u = (m.get("websiteUrl") or "").strip()
        if u and not SKIP.search(u):
            c.append((u if u.startswith("http") else "https://" + u, True))
    c += [(u, True) for u in re.findall(r"https?://[^\s)\"'<>]+", p.get("description") or "") if not SKIP.search(u)]
    base = {norm(p["slug"].split("-")[0]), norm(p["name"]), norm(p["slug"])}
    for b in [x for x in base if 2 < len(x) < 30]:
        c += [(f"https://{b}.{t}", False) for t in ("com", "ai", "app", "io", "so", "dev", "co")]
    seen, out = set(), []
    for u, tr in c:
        if u not in seen:
            seen.add(u); out.append((u, tr))
    return out[:20]


STOP = set("the and for with your you that this from into are our ai app tool tools all any get make more best one new free".split())


def overlap(p, html):
    """Distinctive pitch words found on the page (guards against generic domains like <word>.com)."""
    words = {w for w in re.findall(r"[a-z]{4,}", (p["tagline"] + " " + (p.get("description") or "")[:300]).lower())
             if w not in STOP}
    page = html[:200000].lower()
    return sum(1 for w in words if w in page)


def matches(p, html):
    title = " ".join(re.findall(r"(?is)<title[^>]*>(.*?)</title>", html)[:1] +
                     re.findall(r'(?i)<meta[^>]+og:(?:title|site_name)[^>]+content="([^"]*)"', html)[:2])
    n = norm(p["name"].split(" by ")[0].split(":")[0])
    return len(n) >= 3 and (n in norm(title) or norm(p["name"])[:12] in norm(html[:20000]))


def wayback(url, eve):
    host = re.sub(r"^https?://", "", url).split("/")[0]
    with wb:
        for _ in range(3):
            try:
                r = requests.get("https://web.archive.org/cdx/search/cdx", timeout=40, params={
                    "url": host, "to": eve, "fl": "timestamp", "collapse": "timestamp:8",
                    "filter": "statuscode:200", "limit": "5000"})
                if r.status_code == 200:
                    rows = r.text.split()
                    return {"wb_n_before": len(rows), "wb_first": rows[0] if rows else "", "wb_ts": rows[-1] if rows else ""}
            except Exception:  # noqa: BLE001
                pass
            time.sleep(4)
    return {"wb_n_before": None, "wb_first": "", "wb_ts": ""}


def one(p, f):
    rec = {"id": p["id"], "url": "", "src": "unresolved"}
    for u, trusted in candidates(p):
        final, st, html = fetch(u, timeout=8)
        if st == 200 and html and matches(p, html) and (trusted or overlap(p, html) >= 3):
            rec.update(url=final, live_html=html, trusted=trusted, overlap=overlap(p, html))
            break
    if rec["url"] and os.environ.get("NO_WB"):
        rec["html"], rec["src"] = rec["live_html"], "live"
    elif rec["url"]:
        eve = (dt.date.fromisoformat(p["_date"]) - dt.timedelta(days=1)).strftime("%Y%m%d")
        rec.update(wayback(rec["url"], eve))
        html, src = "", "live"
        if rec.get("wb_ts"):
            with wb:
                _, st, h = fetch(f"https://web.archive.org/web/{rec['wb_ts']}id_/{rec['url']}", timeout=40)
            if st == 200 and len(h) > 500:
                html, src = h, "wayback"
        rec["html"], rec["src"] = (html or rec["live_html"]), src
    rec.pop("live_html", None)
    with lock:
        f.write(json.dumps(rec) + "\n"); f.flush()


def main():
    out = f"{D}/sites.jsonl"
    done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
    todo = []
    for fn in sorted(glob.glob(f"{D}/days/*.json"), reverse=True):
        for p in json.load(open(fn)):
            if p["id"] not in done:
                p["_date"] = os.path.basename(fn)[:10]; todo.append(p)
    print("todo", len(todo), flush=True)
    with open(out, "a") as f, ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 24) as ex:
        for i, _ in enumerate(ex.map(lambda p: one(p, f), todo)):
            if i % 100 == 0:
                print(i, time.strftime("%H:%M:%S"), flush=True)


if __name__ == "__main__":
    main()
