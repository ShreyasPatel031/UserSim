"""Runs on the VM: Product Hunt daily leaderboard page for each day -> ~/php/lb/<date>.json (featured launches with
ranks, tagline, topics, product id/slug, comments, shortened url), through the fetch gateway (cheapest route that
gets the page); 4 pages at a time. A budget stop (FETCH_BUDGET_USD per FETCH_JOB) ends the run with exit code 3.

usage: FETCH_JOB=ph-leaderboard python3 vm_leaderboard.py 2026-01-01 2026-10-24"""
import datetime as dt, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

from _gate import fetchgate

stop = threading.Event()
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
    if os.path.exists(f) or stop.is_set():
        return
    for i in range(2):
        try:
            x = fetchgate.fetch(f"https://www.producthunt.com/leaderboard/daily/{d.year}/{d.month}/{d.day}/all")
            if x["route"] and x["status"] == 200:
                ps = posts_from(x["html"])
                json.dump(ps, open(f, "w")); print(d, len(ps), x["route"], flush=True); return
            print(d, "status", x["status"], "no route got the page", flush=True)
        except fetchgate.BudgetExceeded as e:
            stop.set(); print(f"budget stop: {e}", file=sys.stderr, flush=True); return
        except Exception as e:  # noqa: BLE001
            print(d, "err", str(e)[:120], flush=True)
        time.sleep(3 * (i + 1))


if __name__ == "__main__":
    a, b = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(day, [b - dt.timedelta(days=i) for i in range((b - a).days + 1)]))
    print(json.dumps(fetchgate.job_summary()), file=sys.stderr, flush=True)
    sys.exit(3 if stop.is_set() else 0)
