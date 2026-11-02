"""Product Hunt /@<user>/upvotes page 1 for many people, via fetch-ladder route 4 (residential_camoufox):
Camoufox through DataImpulse residential, US exit. Routes 1-3 get the Cloudflare challenge / 403 since Oct 30 2026.
Never Apify. Read-only: anonymous page loads, no login.

usage: PROXY_URL=... python3 fetch_upvotes.py people.txt out.jsonl [--workers 4] [--max-usd 30]
  people.txt  one username per line (no @)
  out.jsonl   appended; usernames already in it with status 200/404 are skipped (resumable)
Row (same fields as ph_predict/parse_upvotes.py, plus metering):
  {username, status, route, votes_total, has_more, end_cursor, upvotes:[post ids, newest first, ~20],
   upvote_slugs, wire_bytes, secs, attempts, worker, fetched_at}
status: 200 ok, 404 no such user, 403 challenge after all retries, -1 error.
Each worker runs one browser (reused across people, so JS/CSS are cached); a challenge or error closes it and
opens a fresh one (new residential exit IP), with backoff 5/15/45 s, 3 attempts per person."""
import argparse, datetime, json, os, random, re, signal, sys, time
from multiprocessing import Process, Queue
from urllib.parse import urlparse

KEY = re.compile(r'"votedPosts":\{"__typename":"PostConnection","edges":')
USD_PER_GB = 1.0
LIGHT = os.environ.get("PHUP_MODE", "light") == "light"   # PHUP_MODE=goto: full navigation per person
PAGE = os.environ.get("PHUP_PAGE", "upvotes")             # PHUP_PAGE=following: /@u/following page 1 (parse as ph_predict/parse_following.py)
FKEY = re.compile(r'"profile":\{"__typename":"User","id":"(\d+)","isTrashed":\w+,"followingsCount":(\d+),"following":')


def parse_following(html):
    m = FKEY.search(html)
    if not m:
        return None
    conn, _ = json.JSONDecoder().raw_decode(html, m.end())
    pi = conn.get("pageInfo") or {}
    return {"ph_user_id": m.group(1), "followings": int(m.group(2)), "has_more": pi.get("hasNextPage"), "end_cursor": pi.get("endCursor"),
            "following": [[e["node"]["username"], e["node"].get("followersCount")] for e in conn.get("edges") or []]}


def parse(html):
    if PAGE == "following":
        return parse_following(html)
    out = {}
    m = KEY.search(html)
    if not m:
        return None
    conn, _ = json.JSONDecoder().raw_decode(html, m.start() + len('"votedPosts":'))
    edges = conn.get("edges") or []
    out["upvotes"] = [e["node"]["id"] for e in edges]
    out["upvote_slugs"] = [e["node"].get("slug") for e in edges]
    items = []
    for i, e in enumerate(edges, 1):
        n = e.get("node") or {}
        pr = n.get("product") if isinstance(n.get("product"), dict) else {}
        items.append({"position": i, "post_id": str(n.get("id")), "post_slug": n.get("slug"), "post_name": n.get("name"),
                      "product_slug": (pr or {}).get("slug"), "product_name": (pr or {}).get("name"),
                      "launched_at": n.get("featuredAt") or n.get("scheduledAt") or n.get("createdAt"),
                      "node_keys": sorted(k for k in n if not isinstance(n[k], (dict, list)))[:40] if i == 1 else None})
    out["items"] = items
    pi = conn.get("pageInfo") or {}
    out["has_more"], out["end_cursor"] = pi.get("hasNextPage"), pi.get("endCursor")
    t = re.search(r'"votesCount":(\d+)', html)
    out["votes_total"] = int(t.group(1)) if t else None
    return out


def _alarm(*a):
    raise TimeoutError("stall")


def worker(wid, q_in, out_path, lock_path):
    from camoufox.sync_api import Camoufox
    signal.signal(signal.SIGALRM, _alarm)
    u = urlparse(os.environ["PROXY_URL"])
    user = u.username if "__cr." in u.username else u.username + "__cr.us"
    meter = {"b": 0}

    def on_done(req):
        try:
            s = req.sizes()
            meter["b"] += s["requestBodySize"] + s["requestHeadersSize"] + s["responseBodySize"] + s["responseHeadersSize"]
        except Exception:  # noqa: BLE001
            pass


    warm = {"ok": False}

    def fetch_light(pg, name):
        """After one real page load, get just the HTML document through the page's own fetch (same cookies, same
        browser fingerprint): ~1/10 the bytes of a navigation, which reloads scripts and XHRs."""
        r = pg.evaluate("""async (u) => { const r = await fetch(u, {credentials: 'include'});
                           return [r.status, await r.text()]; }""", f"https://www.producthunt.com/@{name}/{PAGE}")
        code, h = r
        if code in (403, 429, 503) or "challenges.cloudflare.com" in h or "Just a moment" in h[:5000]:
            return None
        if code == 404 or "lost this page" in h:
            return {"status": 404, "via": "fetch"}
        p = parse(h)
        return {"status": 200 if p is not None else code, "via": "fetch", **(p or {})}

    def fetch_one(pg, name):
        if LIGHT and warm["ok"]:
            r = fetch_light(pg, name)
            if r is not None:
                return r
        rec = {"via": "goto"}
        resp = pg.goto(f"https://www.producthunt.com/@{name}/{PAGE}", timeout=60000, wait_until="domcontentloaded")
        for _ in range(30):
            h = pg.content()
            if "challenges.cloudflare.com" not in h and "Just a moment" not in h[:5000]:
                break
            pg.wait_for_timeout(1000)
        h = pg.content()
        code = resp.status if resp else 0
        if "challenges.cloudflare.com" in h or "Just a moment" in h[:5000]:
            rec["status"] = 403
        elif code == 404 or "lost this page" in h:
            rec["status"] = 404
        else:
            p = parse(h)
            rec["status"] = 200 if p is not None else (code or -1)
            rec.update(p or {})
        warm["ok"] = rec["status"] == 200
        return rec

    pending, berr = None, 0   # (name, rec, t0, b0) carried to a fresh browser after a failure
    while True:
        try:
            with Camoufox(headless="virtual", humanize=True, geoip=True, block_images=True, i_know_what_im_doing=True,
                          os=["windows", "macos"],
                          proxy={"server": f"http://{u.hostname}:{u.port}", "username": user, "password": u.password}) as b:
                pg = b.new_page()
                warm["ok"] = False
                pg.on("requestfinished", on_done)
                pg.on("requestfailed", on_done)
                while True:
                    if pending is None:
                        name = q_in.get()
                        if name is None:
                            return
                        pending = (name, {"username": name, "page": PAGE, "route": "residential_camoufox", "worker": wid, "attempts": 0},
                                   time.time(), meter["b"])
                    name, rec, t0, b0 = pending
                    rec["attempts"] += 1
                    signal.alarm(150)
                    try:
                        r = fetch_one(pg, name); rec.pop("err", None); rec.update(r)
                    except Exception as e:  # noqa: BLE001
                        rec.update(status=-1, err=str(e)[:200])
                    signal.alarm(0)
                    if rec["status"] in (200, 404) or rec["attempts"] >= 3:
                        rec.update(wire_bytes=meter["b"] - b0, secs=round(time.time() - t0, 1),
                                   fetched_at=datetime.datetime.utcnow().isoformat() + "Z")
                        with open(out_path, "a") as f:
                            f.write(json.dumps(rec) + "\n")
                        print(wid, name, rec["status"], rec["wire_bytes"], rec["secs"], flush=True)
                        pending = None
                        time.sleep(random.uniform(0.5, 1.5) if LIGHT else random.uniform(1, 3))
                        continue
                    warm["ok"] = False
                    time.sleep(5 * 3 ** (rec["attempts"] - 1))
                    break   # fresh browser = fresh residential exit IP
        except Exception as e:  # noqa: BLE001
            berr += 1
            print(wid, "browser err", str(e)[:200], flush=True)
            if berr > 20:
                return
            time.sleep(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("people"); ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=float(os.environ.get("PHUP_MAX_USD", 2.5)), help="stop when metered bytes reach this many dollars")
    a = ap.parse_args()
    done, spent = set(), 0
    if os.path.exists(a.out):
        for l in open(a.out):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            spent += r.get("wire_bytes") or 0
            if r.get("status") in (200, 404):
                done.add(r["username"])
    todo = [x.strip().lstrip("@") for x in open(a.people) if x.strip() and x.strip().lstrip("@") not in done]
    print(f"{len(done)} done, {len(todo)} to fetch, {a.workers} workers", flush=True)
    q = Queue()
    ps = [Process(target=worker, args=(i, q, a.out, None)) for i in range(a.workers)]
    for p in ps:
        p.start()
    for i, n in enumerate(todo):
        q.put(n)
        if i % 200 == 199:  # budget guard, checked as the queue fills
            while q.qsize() > 50:
                time.sleep(10)
            b = sum((json.loads(l).get("wire_bytes") or 0) for l in open(a.out))
            if b / 1e9 * USD_PER_GB >= a.max_usd:
                print("BUDGET STOP", b, flush=True); break
    for _ in ps:
        q.put(None)
    for p in ps:
        p.join()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
