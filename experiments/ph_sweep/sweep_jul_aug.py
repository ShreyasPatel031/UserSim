"""PH pre-launch mention sweep, Jul-Aug 2026 (E5 agent, taking over Data Feeder's request 20261102T2146 part A, which
finished Sep-Oct). Same routes and match rules as raw/ph_prelaunch_mentions/README.md, free public APIs only, polite
pacing, 429s honoured, no logins. Launch list and windows: launches.json from that folder (launch day 00:00 PT - 7 d,
up to launch day 00:00 PT). Output (new files, Data Feeder's are left as they are):
  mentions_jul_aug_e5.jsonl, coverage_jul_aug_e5.json in the same folder.
    python sweep_jul_aug.py <dir with launches.json> <out dir>"""
import json, os, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

UA = "usersim-research/0.1 (non-commercial research; polite)"
MONTHS = ("2026-07", "2026-08")
SUBS = ["SideProject", "ProductHunt", "startups", "SaaS", "indiehackers", "Entrepreneur"]
DEVTO_TAGS = ["producthunt", "showdev", "sideprojects", "startup", "buildinpublic", "launch", "saas", "indiehackers"]
STOP = {"the", "a", "an", "and", "of", "for", "to", "in", "on", "by", "with", "ai", "app", "your", "my", "is", "at", "io", "pro", "2", "2.0", "3", "4", "5"}
LAST = defaultdict(float)


def get(url, host, gap, tries=6):
    for k in range(tries):
        w = LAST[host] + gap - time.time()
        if w > 0:
            time.sleep(w)
        LAST[host] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504, 422):
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit() else min(120, 5 * 2 ** k)); continue
            return None
        except Exception:
            time.sleep(min(60, 3 * 2 ** k))
    return None


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def distinctive(name):
    toks = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in STOP]
    return len(name) >= 7 or len(toks) >= 2


def names_of(l):
    n = (l.get("name") or "").strip(); out = [n]
    if " by " in n:
        out.append(n.split(" by ")[0].strip())
    return [x for x in out if x]


def match(l, text):
    t = (text or "").lower()
    slug = (l.get("slug") or "").lower(); dom = (l.get("domain") or "").lower()
    if slug and re.search(r"producthunt\.com/(posts|products)/" + re.escape(slug) + r"(?![a-z0-9-])", t):
        return "ph_link"
    if dom and re.search(r"(?<![a-z0-9-])" + re.escape(dom) + r"(?![a-z0-9-])", t):
        return "domain"
    for n in names_of(l):
        if re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", t):
            if re.search(r"product ?hunt", t):
                return "name+ph"
            if distinctive(n):
                return "name"
    return None


def in_window(l, ts):
    return datetime.fromisoformat(l["window_start"]).timestamp() <= ts < datetime.fromisoformat(l["window_end"]).timestamp()


def hn(l, out):
    a, b = int(datetime.fromisoformat(l["window_start"]).timestamp()), int(datetime.fromisoformat(l["window_end"]).timestamp())
    qs = ([l["domain"]] if l.get("domain") else []) + [n for n in names_of(l) if distinctive(n)][:1]
    seen = set(); ok = True
    for q in qs:
        p = {"query": f'"{q}"', "tags": "(story,comment)", "numericFilters": f"created_at_i>={a},created_at_i<{b}", "hitsPerPage": 100}
        d = get("https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(p), "hn", 0.4)
        ok = ok and d is not None
        for h in (d or {}).get("hits", []):
            if h["objectID"] in seen:
                continue
            seen.add(h["objectID"])
            text = " ".join(str(h.get(k) or "") for k in ("title", "story_text", "comment_text", "url"))
            m = match(l, text)
            if m and in_window(l, h["created_at_i"]):
                out.append({"launch_id": l["launch_id"], "channel": "hn", "url": f"https://news.ycombinator.com/item?id={h['objectID']}", "author": h.get("author"),
                            "posted_at": iso(h["created_at_i"]), "text": re.sub(r"<[^>]+>", " ", text)[:300], "match": m, "source": "hn_algolia",
                            "fetched_at": iso(time.time()), "kind": "comment" if "comment" in h.get("_tags", []) else "story", "points": h.get("points")})
    return ok


def bluesky(l, out):
    qs = ([l["domain"]] if l.get("domain") else []) + [f'"{n}"' for n in names_of(l) if distinctive(n)][:1]
    ok = True
    for q in qs:
        cur = None
        for _ in range(3):
            p = {"q": q, "since": l["window_start"].replace("+00:00", "Z"), "until": l["window_end"].replace("+00:00", "Z"), "limit": 100}
            if cur:
                p["cursor"] = cur
            d = get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?" + urllib.parse.urlencode(p), "bsky", 0.5)
            if d is None:
                ok = False; break
            for po in d.get("posts", []):
                rec = po.get("record", {}); text = rec.get("text", "")
                for f in (rec.get("facets") or []):
                    for ft in f.get("features", []):
                        text += " " + (ft.get("uri") or "")
                emb = (rec.get("embed") or {}).get("external") or {}
                text += " " + (emb.get("uri") or "") + " " + (emb.get("title") or "")
                ts = datetime.fromisoformat(rec.get("createdAt", "1970-01-01T00:00:00Z").replace("Z", "+00:00")).timestamp()
                m = match(l, text)
                if m and in_window(l, ts):
                    a = po.get("author", {})
                    out.append({"launch_id": l["launch_id"], "channel": "bluesky", "url": f"https://bsky.app/profile/{a.get('handle')}/post/{po['uri'].split('/')[-1]}",
                                "author": a.get("handle"), "author_did": a.get("did"), "author_followers": None, "posted_at": rec.get("createdAt"),
                                "text": text[:300], "match": m, "likes": po.get("likeCount"), "reposts": po.get("repostCount"),
                                "source": "bsky_appview", "fetched_at": iso(time.time())})
            cur = d.get("cursor")
            if not cur:
                break
    return ok


def bsky_followers(rows):
    dids = sorted({r["author_did"] for r in rows if r["channel"] == "bluesky" and r.get("author_did")})
    fol = {}
    for i in range(0, len(dids), 25):
        p = urllib.parse.urlencode([("actors", d) for d in dids[i:i + 25]])
        d = get("https://api.bsky.app/xrpc/app.bsky.actor.getProfiles?" + p, "bsky", 0.5)
        for pr in (d or {}).get("profiles", []):
            fol[pr["did"]] = pr.get("followersCount")
    for r in rows:
        if r["channel"] == "bluesky":
            r["author_followers"] = fol.get(r.get("author_did"))


def reddit_posts(a, b):
    """every post in SUBS created in [a, b) (Arctic Shift archive), paged by time."""
    posts = []
    for s in SUBS:
        after = a
        while after < b:
            p = {"subreddit": s, "after": after, "before": b, "limit": 100, "sort": "asc"}
            d = get("https://arctic-shift.photon-reddit.com/api/posts/search?" + urllib.parse.urlencode(p), "arctic", 1.5)
            data = (d or {}).get("data") or []
            if not data:
                break
            posts += data
            nxt = int(max(x["created_utc"] for x in data))
            after = nxt + 1 if nxt >= after else after + 3600
            if len(data) < 100:
                break
        print("reddit", s, len(posts), flush=True)
    return posts


def devto_articles(a):
    arts = {}
    for t in DEVTO_TAGS:
        for page in range(1, 40):
            d = get(f"https://dev.to/api/articles?tag={t}&per_page=1000&page={page}", "devto", 1.0)
            if not d:
                break
            for x in d:
                arts[x["id"]] = x
            if min(datetime.fromisoformat(x["published_at"].replace("Z", "+00:00")).timestamp() for x in d) < a:
                break
        print("devto", t, len(arts), flush=True)
    return list(arts.values())


def main(src, outdir):
    L = [l for l in json.load(open(os.path.join(src, "launches.json"))) if l["launch_day"][:7] in MONTHS]
    print("launches", len(L), flush=True)
    rows, status = [], {m: {"hn": 0, "bluesky": 0} for m in MONTHS}
    for i, l in enumerate(L):
        m = l["launch_day"][:7]
        status[m]["hn"] += hn(l, rows)
        status[m]["bluesky"] += bluesky(l, rows)
        if i % 100 == 0:
            print(i, len(rows), flush=True)
    bsky_followers(rows)
    a = min(datetime.fromisoformat(l["window_start"]).timestamp() for l in L); b = max(datetime.fromisoformat(l["window_end"]).timestamp() for l in L)
    by_day = defaultdict(list)
    for l in L:
        by_day[l["launch_day"]].append(l)
    for po in reddit_posts(int(a), int(b)):
        text = " ".join(str(po.get(k) or "") for k in ("title", "selftext", "url"))
        for l in L:
            if in_window(l, po["created_utc"]):
                mt = match(l, text)
                if mt:
                    rows.append({"launch_id": l["launch_id"], "channel": "reddit", "url": "https://www.reddit.com" + (po.get("permalink") or ""), "author": po.get("author"),
                                 "posted_at": iso(po["created_utc"]), "text": text[:300], "match": mt, "source": "arctic_shift", "fetched_at": iso(time.time()),
                                 "subreddit": po.get("subreddit"), "score": po.get("score")})
    for x in devto_articles(a):
        ts = datetime.fromisoformat(x["published_at"].replace("Z", "+00:00")).timestamp()
        text = " ".join(str(x.get(k) or "") for k in ("title", "description", "url", "canonical_url"))
        for l in L:
            if in_window(l, ts):
                mt = match(l, text)
                if mt:
                    rows.append({"launch_id": l["launch_id"], "channel": "devto", "url": x.get("url"), "author": (x.get("user") or {}).get("username"),
                                 "posted_at": x["published_at"], "text": text[:300], "match": mt, "source": "devto_api_tags", "fetched_at": iso(time.time()),
                                 "reactions": x.get("public_reactions_count")})
    with open(os.path.join(outdir, "mentions_jul_aug_e5.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    cov = {"generated_at": iso(time.time()), "by": "E5 agent (sweep_jul_aug.py)", "months": {}}
    for m in MONTHS:
        n = sum(1 for l in L if l["launch_day"][:7] == m)
        cs = {"hn": "done" if status[m]["hn"] == n else f"{status[m]['hn']}/{n}", "reddit": "done", "bluesky": "done" if status[m]["bluesky"] == n else f"{status[m]['bluesky']}/{n}",
              "devto": "done", "x": "not run", "linkedin/indiehackers/medium/substack": "blocked (free search engines refuse scripted queries)"}
        ids = {l["launch_id"] for l in L if l["launch_day"][:7] == m}
        bc = {}
        for ch in ("hn", "reddit", "bluesky", "devto"):
            rr = [r for r in rows if r["channel"] == ch and r["launch_id"] in ids]
            st = {r["launch_id"] for r in rr if r["match"] in ("domain", "ph_link", "name+ph")}; an = {r["launch_id"] for r in rr}
            bc[ch] = {"mentions": len(rr), "launches_strong": len(st), "share_strong": round(len(st) / n, 4), "launches_any": len(an), "share_any": round(len(an) / n, 4)}
        cov["months"][m] = {"launches": n, "channel_status": cs, "by_channel": bc}
    json.dump(cov, open(os.path.join(outdir, "coverage_jul_aug_e5.json"), "w"), indent=1)
    print(json.dumps(cov, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
