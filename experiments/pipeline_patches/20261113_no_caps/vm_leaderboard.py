"""Runs on the VM: Product Hunt daily leaderboard page for each day -> ~/php/lb/<date>.json (featured launches with
ranks, tagline, topics, product id/slug, comments, shortened url), through the Apify datacenter proxy
(~/php/proxy.txt). Approved by the user to run this way; 4 pages at a time.

usage: python vm_leaderboard.py 2026-01-01 2026-10-24"""
import datetime as dt, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as R

P = open(os.path.expanduser("~/php/proxy.txt")).read().strip()
RESI = P.replace("//auto:", "//groups-RESIDENTIAL,country-US:")  # used once the datacenter IPs get 403s
OUT = os.path.expanduser("~/php/lb"); os.makedirs(OUT, exist_ok=True)


def posts_from(html):
    h = html.replace('\\"', '"')
    out = {}
    for m in re.finditer(r'\{"__typename":"Post","id":"(\d+)"', h):
        s = h[m.start():m.start() + 6000]
        g = lambda k: (re.search(k, s) or [None, None])[1]
        if g(r'"dailyRank":"?(\d+)') is None:
            continue
        pid = m.group(1)
        out[pid] = {"id": pid, "name": g(r'"name":"((?:[^"\\]|\\.)*)"'), "slug": g(r'"slug":"([^"]*)"'),
                    "tagline": g(r'"tagline":"((?:[^"\\]|\\.)*)"'),
                    "product_id": g(r'"redirectToProduct":\{"__typename":"Product","id":"(\d+)"'),
                    "product_slug": g(r'"redirectToProduct":\{"__typename":"Product","id":"\d+","slug":"([^"]*)"'),
                    "featuredAt": g(r'"featuredAt":"([^"]*)"'), "shortenedUrl": g(r'"shortenedUrl":"([^"]*)"'),
                    "dailyRank": g(r'"dailyRank":"?(\d+)'), "weeklyRank": g(r'"weeklyRank":"?(\d+)'),
                    "monthlyRank": g(r'"monthlyRank":"?(\d+)'), "commentsCount": g(r'"commentsCount":(\d+)'),
                    "topics": re.findall(r'"__typename":"Topic","id":"\d+","slug":"[^"]*","name":"([^"]*)"',
                                         s.split('"contest"')[0])}
    return list(out.values())


def posts_json(html):
    """Bundle 11: parse each embedded Post object as JSON (balanced decode) instead of a fixed 6,000-character regex window,
    which missed posts whose dailyRank sat further into the object. Falls back to posts_from() for anything not decodable."""
    h = html.replace('\\"', '"'); dec = json.JSONDecoder(); out = {}
    for m in re.finditer(r'\{"__typename":"Post","id":"(\d+)"', h):
        try:
            obj, _ = dec.raw_decode(h[m.start():])
        except ValueError:
            continue
        if obj.get("dailyRank") is None:
            continue
        rp = obj.get("redirectToProduct") or {}
        out[str(obj["id"])] = {"id": str(obj["id"]), "name": obj.get("name"), "slug": obj.get("slug"), "tagline": obj.get("tagline"),
                               "product_id": rp.get("id"), "product_slug": rp.get("slug"), "featuredAt": obj.get("featuredAt"),
                               "shortenedUrl": obj.get("shortenedUrl"), "dailyRank": obj.get("dailyRank"), "weeklyRank": obj.get("weeklyRank"),
                               "monthlyRank": obj.get("monthlyRank"), "commentsCount": obj.get("commentsCount"),
                               "topics": [((e or {}).get("node") or e or {}).get("name") for e in ((obj.get("topics") or {}).get("edges") or [])]}
    for p in posts_from(html):
        out.setdefault(p["id"], p)
    return list(out.values())


def fetch(url):
    for i in range(4):
        px = P if i == 0 else RESI
        try:
            x = R.get(url, impersonate="chrome", proxies={"https": px}, timeout=60)
            if x.status_code == 200:
                return x.text
            print(url[-40:], "status", x.status_code, "resi" if px == RESI else "dc", flush=True)
        except Exception as e:  # noqa: BLE001
            print(url[-40:], "err", str(e)[:120], flush=True)
        time.sleep(3 * (i + 1))
    return None


def day(d):
    """Every page of the day's /all leaderboard (was page 1 only): ?page=2, 3, ... until a page adds no new post; written to a
    temp file and moved into place, with complete=false recorded when a page failed."""
    f = f"{OUT}/{d}.json"
    if os.path.exists(f) and not os.environ.get("LB_REREAD"):
        return
    base = f"https://www.producthunt.com/leaderboard/daily/{d.year}/{d.month}/{d.day}/all"
    got, complete = {}, True
    for page in range(1, 51):
        html = fetch(base if page == 1 else f"{base}?page={page}")
        if html is None:
            complete = False; break
        new = [p for p in posts_json(html) if p["id"] not in got]
        if not new:
            break
        got.update({p["id"]: p for p in new})
    if not got:
        print(d, "no posts read", flush=True); return
    json.dump(list(got.values()), open(f + ".tmp", "w")); os.replace(f + ".tmp", f)
    if not complete:
        open(f + ".incomplete", "w").write("a page failed; re-run with LB_REREAD=1\n")
    print(d, len(got), "complete" if complete else "INCOMPLETE", flush=True)


if __name__ == "__main__":
    a, b = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(day, [b - dt.timedelta(days=i) for i in range((b - a).days + 1)]))
