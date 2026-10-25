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


def day(d):
    f = f"{OUT}/{d}.json"
    if os.path.exists(f):
        return
    for i in range(4):
        px = P if i == 0 else RESI
        try:
            x = R.get(f"https://www.producthunt.com/leaderboard/daily/{d.year}/{d.month}/{d.day}/all",
                      impersonate="chrome", proxies={"https": px}, timeout=60)
            if x.status_code == 200:
                ps = posts_from(x.text)
                json.dump(ps, open(f, "w")); print(d, len(ps), flush=True); return
            print(d, "status", x.status_code, "resi" if px == RESI else "dc", flush=True)
        except Exception as e:  # noqa: BLE001
            print(d, "err", str(e)[:120], flush=True)
        time.sleep(3 * (i + 1))


if __name__ == "__main__":
    a, b = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(day, [b - dt.timedelta(days=i) for i in range((b - a).days + 1)]))
