"""Outside-PH signals, cached per key in data/ext_<kind>.jsonl (resumable):
  x      — X/Twitter followers, tweets, account age of hunter + makers (fxtwitter; current values)
  rdap   — domain registration date (cannot see the launch)
  hn     — Hacker News stories/comments linking the domain before launch day (Algolia, date-filtered)
usage: python external.py x|rdap|hn"""
import glob, json, math, os, re, sys, time, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
lock = threading.Lock()


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return None
            time.sleep(2 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    return None


def posts():
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        for p in json.load(open(fn)):
            p["_date"] = os.path.basename(fn)[:10]
            yield p


def sites():
    f = f"{D}/sites.jsonl"
    return {r["id"]: r for r in map(json.loads, open(f))} if os.path.exists(f) else {}


def domain(url):
    h = re.sub(r"^https?://", "", url or "").split("/")[0].split(":")[0].lower()
    return h[4:] if h.startswith("www.") else h


def run(kind, keys, fn, workers):
    out = f"{D}/ext_{kind}.jsonl"
    done = {json.loads(l)["key"] for l in open(out)} if os.path.exists(out) else set()
    todo = sorted(set(keys) - done)
    print(kind, "todo", len(todo), flush=True)
    with open(out, "a") as f, ThreadPoolExecutor(workers) as ex:
        for k, v in zip(todo, ex.map(fn, todo)):
            with lock:
                f.write(json.dumps({"key": k, **(v or {})}) + "\n"); f.flush()


def x_user(u):
    d = get(f"https://api.fxtwitter.com/{urllib.parse.quote(u)}")
    u = (d or {}).get("user") or {}
    return {"followers": u.get("followers"), "tweets": u.get("tweets"), "joined": u.get("joined"),
            "verified": bool((u.get("verification") or {}).get("verified"))}


def rdap(dom):
    parts = dom.split(".")
    base = ".".join(parts[-3:] if len(parts) > 2 and parts[-2] in ("co", "com", "org", "net") else parts[-2:])
    d = get(f"https://rdap.org/domain/{base}")
    ev = {e.get("eventAction"): e.get("eventDate") for e in (d or {}).get("events", [])}
    return {"registered": ev.get("registration"), "base": base}


def hn(key):
    dom, date = key.split("|")
    ts = int(time.mktime(time.strptime(date, "%Y-%m-%d")))
    q = urllib.parse.urlencode({"query": dom, "restrictSearchableAttributes": "url", "hitsPerPage": 50,
                                "numericFilters": f"created_at_i<{ts}"})
    d = get(f"https://hn.algolia.com/api/v1/search?{q}") or {}
    hits = d.get("hits") or []
    return {"hn_n": d.get("nbHits", 0), "hn_points": sum(h.get("points") or 0 for h in hits),
            "hn_comments": sum(h.get("num_comments") or 0 for h in hits)}


if __name__ == "__main__":
    kind = sys.argv[1]
    if kind == "x":
        us = {p["user"]["twitterUsername"] for p in posts() if p["user"].get("twitterUsername")}
        us |= {m["twitterUsername"] for p in posts() for m in p["makers"] if m.get("twitterUsername")}
        run("x", {u.strip().lstrip("@") for u in us if u.strip()}, x_user, 8)
    elif kind == "rdap":
        doms = {domain(s["url"]) for s in sites().values() if s.get("url") and "producthunt.com" not in s["url"]}
        run("rdap", {d for d in doms if "." in d}, rdap, 8)
    elif kind == "hn":
        ss = sites()
        keys = {f"{domain(ss[p['id']]['url'])}|{p['_date']}" for p in posts()
                if p["id"] in ss and ss[p["id"]].get("url") and "producthunt.com" not in ss[p["id"]]["url"]}
        run("hn", keys, hn, 6)


def wb_avail(key):
    """archive.org availability API: closest snapshot to the day before launch; kept only if not after it."""
    url, eve = key.split("|")
    d = get(f"https://archive.org/wayback/available?url={urllib.parse.quote(url)}&timestamp={eve}") or {}
    c = (d.get("archived_snapshots") or {}).get("closest") or {}
    ts = c.get("timestamp", "")
    return {"wb_ts": ts if ts and ts[:8] <= eve else "", "wb_after": ts if ts and ts[:8] > eve else ""}


if __name__ == "__main__" and sys.argv[1] == "wb":
    import datetime as dt
    ss = sites()
    keys = set()
    for p in posts():
        s = ss.get(p["id"], {})
        if s.get("url"):
            eve = (dt.date.fromisoformat(p["_date"]) - dt.timedelta(days=1)).strftime("%Y%m%d")
            keys.add(f"{domain(s['url'])}|{eve}")
    run("wb", keys, wb_avail, 6)


XH = re.compile(r"(?i)(?:twitter|x)\.com/(?!intent|share|home|search|hashtag|i/)([A-Za-z0-9_]{2,15})\b")
GH = re.compile(r"(?i)github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def site_handles(html):
    xs = [h for h in XH.findall(html or "") if h.lower() not in ("producthunt", "intent", "share", "home")]
    gh = [(o, r.removesuffix(".git")) for o, r in GH.findall(html or "")
          if o.lower() not in ("sponsors", "features", "about", "orgs", "topics", "login", "apps", "marketplace")]
    return (xs[0] if xs else ""), (f"{gh[0][0]}/{gh[0][1]}" if gh else "")


def gh_api(path, accept="application/vnd.github+json"):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": accept, "User-Agent": "ph-predict"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), r.headers
    except Exception:  # noqa: BLE001
        return None, {}


def gh_stars(key):
    """Stars the repo had before launch day (stargazer timestamps, binary search over 100-per-page pages)."""
    repo, date = key.split("|")
    meta, _ = gh_api(f"/repos/{repo}")
    if not meta or "stargazers_count" not in meta:
        return {"gh_ok": False}
    n = meta["stargazers_count"]
    out = {"gh_ok": True, "gh_stars_now": n, "gh_created": meta.get("created_at"), "gh_forks_now": meta.get("forks_count")}
    acc = "application/vnd.github.star+json"
    pages = max(1, math.ceil(n / 100))
    if pages > 400:  # GitHub lists at most 40k stargazers; such repos were famous long before launch
        out["gh_stars_before"] = n; return out
    lo, hi = 1, pages
    def first_after(pg):
        d, _ = gh_api(f"/repos/{repo}/stargazers?per_page=100&page={pg}", acc)
        return [x.get("starred_at", "")[:10] for x in (d or [])]
    while lo < hi:  # find first page whose last star is on/after launch day
        mid = (lo + hi) // 2
        st = first_after(mid)
        if st and st[-1] < date:
            lo = mid + 1
        else:
            hi = mid
    st = first_after(lo)
    out["gh_stars_before"] = (lo - 1) * 100 + sum(1 for s in st if s < date)
    return out


if __name__ == "__main__" and sys.argv[1] in ("sitex", "gh"):
    import math as _m
    ss = sites()
    if sys.argv[1] == "sitex":
        hs = {site_handles(s.get("html"))[0] for s in ss.values()} - {""}
        run("x", hs, x_user, 8)
    else:
        keys = set()
        for p in posts():
            s = ss.get(p["id"], {})
            repo = site_handles(s.get("html"))[1]
            if repo:
                keys.add(f"{repo}|{p['_date']}")
        run("gh", keys, gh_stars, 6)
