"""Runs on the VM. stdin: Product Hunt usernames. Fetches every profile tab's server-rendered page (through the Apify
proxy) and keeps parsed fields only; raw pages are not stored. Each page shows the first ~20 items of its list;
`*_more` says whether the list continues past what the page shows.

  about        launches made (makerPosts), badges
  forums       forums joined, threads started
  activity     20 most recent dated events (subject type + id)
  upvotes      20 most recent upvoted launches
  submitted    launches the person posted ("hunted")
  collections  collections and the products in them
  stacks       products the person says they use (+ date added)
  reviews      reviews written (product, rating, date, pros/cons tags, alternatives, text)
  followers / following   20 most recent people (id, username, name, headline)

One JSON line per username. Person-level data: keep on the VM, out of git."""
import json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vm_profile_tabs import activity, get, reviews, stacks  # noqa: E402

lock = threading.Lock()
TABS = ["", "forums", "activity", "upvotes", "submitted", "collections", "stacks", "reviews", "followers", "following"]


def _str(seg, key):
    m = re.search(r'"' + key + r'":"((?:[^"\\]|\\.)*)"', seg)
    return m.group(1) if m else None


def _list(h, field):
    """The body of connection `field` (from its key to its pageInfo) and whether it has a next page."""
    m = re.search(r'"' + field + r'(?:\([^"]*\))?":\{"__typename":"[A-Za-z]+Connection"', h)
    if not m:
        return "", None
    body = h[m.start(): m.start() + 400000]
    pi = re.search(r'"hasNextPage":(true|false)', body)
    end = pi.end() if pi else len(body)
    return body[:end], (pi.group(1) == "true") if pi else None


def posts(h, field):
    body, more = _list(h, field)
    out = {}
    for m in re.finditer(r'"node":\{"__typename":"Post","id":"(\d+)"', body):
        seg = body[m.start(): m.start() + 3000]
        out[m.group(1)] = {"post_id": m.group(1), "name": _str(seg, "name"), "slug": _str(seg, "slug"),
                           "tagline": _str(seg, "tagline"), "created": _str(seg, "createdAt"),
                           "featured": _str(seg, "featuredAt")}
    return list(out.values()), more


def users(h, field):
    body, more = _list(h, field)
    out = {}
    for m in re.finditer(r'"node":\{"__typename":"User","id":"(\d+)"', body):
        seg = body[m.start(): m.start() + 1500]
        out[m.group(1)] = {"user_id": m.group(1), "username": _str(seg, "username"), "name": _str(seg, "name"),
                           "headline": _str(seg, "headline")}
    return list(out.values()), more


def forums(h):
    joined, _ = _list(h, "discussionForums")
    js = [{"forum_id": m.group(1), "name": _str(joined[m.start(): m.start() + 800], "name"),
           "slug": _str(joined[m.start(): m.start() + 800], "slug")}
          for m in re.finditer(r'"node":\{"__typename":"DiscussionForumType","id":"(\d+)"', joined)]
    act, more = _list(h, "forumActivity")
    threads = [{"thread_id": m.group(1), "title": _str(act[m.start(): m.start() + 2000], "title"),
                "created": _str(act[m.start(): m.start() + 2000], "createdAt")}
               for m in re.finditer(r'"__typename":"DiscussionThread","id":"(\d+)"', act)]
    return {"joined": list({x["forum_id"]: x for x in js}.values()),
            "threads": list({x["thread_id"]: x for x in threads}.values()), "threads_more": more}


def collections(h):
    body, more = _list(h, "collections")
    out = {}
    for m in re.finditer(r'"node":\{"__typename":"Collection","id":"(\d+)"', body):
        seg = body[m.start(): m.start() + 6000]
        prods = re.findall(r'"__typename":"Product","id":"(\d+)"', seg)
        out[m.group(1)] = {"collection_id": m.group(1), "name": _str(seg, "name"), "title": _str(seg, "title"),
                           "product_ids": list(dict.fromkeys(prods))}
    return list(out.values()), more


def badges(h):
    return [{"badge": m.group(1), "count": int(m.group(2)) if m.group(2) else None}
            for m in re.finditer(r'"__typename":"UserBadgeAward"[^}]*?"(?:name|type)":"([^"]+)"(?:[^}]*?"(?:count|awardsCount)":(\d+))?', h)]


def one(u):
    rec = {"username": u}
    for tab in TABS:
        st, h = get(f"https://www.producthunt.com/@{u}" + (f"/{tab}" if tab else ""))
        if st != 200:
            rec[tab or "about"] = None
            continue
        if tab == "":
            rec["made"], rec["made_more"] = posts(h, "makerPosts")
            rec["badges"] = badges(h)
        elif tab == "forums":
            rec["forums"] = forums(h)
        elif tab == "activity":
            rec["activity"] = activity(h)
            rec["activity_more"] = _list(h, "activityEvents")[1]
        elif tab == "upvotes":
            rec["upvotes"], rec["upvotes_more"] = posts(h, "votedPosts")
        elif tab == "submitted":
            rec["submitted"], rec["submitted_more"] = posts(h, "submittedPosts")
        elif tab == "collections":
            rec["collections"], rec["collections_more"] = collections(h)
        elif tab == "stacks":
            rec["stacks"] = stacks(h)
        elif tab == "reviews":
            rec["reviews"] = reviews(h)
        else:
            rec[tab], rec[tab + "_more"] = users(h, tab)
    with lock:
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    names = [l.strip() for l in sys.stdin if l.strip()]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 16) as ex:
        list(ex.map(one, names))
