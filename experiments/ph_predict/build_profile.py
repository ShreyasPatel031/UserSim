"""Build one person's complete Product Hunt profile from what the VM fetched. Runs anywhere (no network).

Inputs (all for one username):
  --pages   gzipped JSON lines from vmfetch.py of the profile tab URLs: /@u, /@u/{forums,activity,upvotes,submitted,
            collections,stacks,reviews,followers,following} -> header, made, hunted, reviews, stacks, badges, links
  --scroll  one or more gzipped JSON-line outputs of vm_scroll.py for /@u/{upvotes,activity,forums} and each
            /@u/collections/<slug> page -> the full lists the page loads while scrolling
  --github / --linkedin / --x   optional JSON files (GitHub API pull, LinkedIn pilot record, fxtwitter profile)

Writes the profile as JSON (--out) and, with --md, a readable Markdown file listing every item.

    python build_profile.py alchemist_studio --pages one_raw.jsonl.gz --scroll one_scroll.jsonl.gz one_coll.jsonl.gz \
        --github one_github.json --linkedin one_li.json --x one_x.jsonl --out profile.json --md profile.md
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# vm_profile_tabs (imported by vm_profile_all) reads the VM's proxy file and curl_cffi at import; neither is
# needed for parsing, so stub them when running off the VM.
if "curl_cffi" not in sys.modules:
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        sys.modules["curl_cffi"] = types.SimpleNamespace(requests=None)
_open = open
if not os.path.exists(os.path.expanduser("~/php/proxy.txt")):
    import builtins
    builtins.open = lambda p, *a, **k: io.StringIO("http://x//auto:y@z") if str(p).endswith("proxy.txt") else _open(p, *a, **k)
import parse_prof as P  # noqa: E402
import vm_profile_all as V  # noqa: E402
if not os.path.exists(os.path.expanduser("~/php/proxy.txt")):
    builtins.open = _open


def nodes(objs, typename):
    """Every object of a GraphQL type anywhere in the responses, merged by id."""
    acc = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("__typename") == typename and o.get("id"):
                acc[o["id"]] = {**acc.get(o["id"], {}), **o}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for o in objs:
        walk(o)
    return acc


def edges(objs, field):
    """Nodes of connection `field` anywhere in the responses, by id."""
    acc = {}

    def walk(o):
        if isinstance(o, dict):
            c = o.get(field)
            if isinstance(c, dict) and "edges" in c:
                for e in c["edges"]:
                    n = e.get("node") or {}
                    acc.setdefault(n.get("id"), n)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for o in objs:
        walk(o)
    return acc


def build(u: str, pages: dict, scroll: dict) -> dict:
    raw = {k: h.replace('\\"', '"') for k, h in pages.items()}
    bodies = lambda tab, op: [x["body"] for x in (scroll.get(tab) or {}).get("responses", []) if op in x["url"]]  # noqa: E731

    # Upvotes: the first 20 are in the page, the rest arrive while scrolling (the page offers about 6 months).
    first, _ = V.posts(raw.get("upvotes", ""), "votedPosts")
    upvotes = {p["post_id"]: {"name": p["name"], "tagline": p["tagline"], "date": (p["created"] or "")[:10]} for p in first}
    for i, n in edges(bodies("upvotes", "ProfileUpvotesQuery"), "votedPosts").items():
        upvotes.setdefault(i, {"name": n.get("name"), "tagline": n.get("tagline"), "date": (n.get("createdAt") or "")[:10],
                               "daily_rank": n.get("dailyRank")})

    # Activity: every event back to the first, loaded while scrolling.
    activity = []
    for e in nodes(bodies("activity", "ProfileActivityPage"), "UserActivityEvent").values():
        s, tgt = e.get("subject") or {}, (e.get("subject") or {}).get("subject") or {}
        own = s.get("__typename") != "Comment"
        activity.append({"t": e["occurredAt"][:10], "type": s.get("__typename"),
                         "on": (s.get("name") or s.get("title")) if own else (tgt.get("name") or tgt.get("title") or tgt.get("slug")),
                         "on_type": s.get("__typename") if own else tgt.get("__typename"),
                         "on_id": s.get("id") if own else tgt.get("id"), "text": (s.get("bodyText") or "")[:500]})
    activity.sort(key=lambda a: a["t"], reverse=True)

    # Forums: forums joined from the forums tab; what they posted comes from activity (thread title + their text),
    # with the forum each thread belongs to from the forums tab.
    fb = bodies("forums", "ProfileForumsPage") + bodies("forums", "")
    forum_of = {}
    for tid, t in nodes(fb, "DiscussionThread").items():
        ns = (t.get("discussionForums") or {}).get("nodes") or []
        if ns:
            forum_of[tid] = ", ".join((n.get("subject") or {}).get("name") or n.get("path", "") for n in ns)
    joined = sorted({(f.get("subject") or {}).get("name") or f.get("slug") for f in nodes(fb, "DiscussionForumType").values()} - {None})
    forum_posts = [{"date": a["t"], "kind": "started thread" if a["type"] == "DiscussionThread" else "comment",
                    "thread": a["on"], "thread_id": a["on_id"], "forum": forum_of.get(a["on_id"], ""), "text": a["text"]}
                   for a in activity if a["on_type"] == "DiscussionThread"]

    # Collections: each collection page lists its products (more load while scrolling).
    collections = {}
    for key, rec in scroll.items():
        if not key.startswith("collections/"):
            continue
        names = {}
        for i, n in edges(bodies(key, "ProfileCollectionShowPage"), "products").items():
            names[i] = n.get("name")
        h = (rec.get("html") or "").replace('\\"', '"')
        j = h.find('"products":{"__typename":"ProductConnection"')
        for m in re.finditer(r'"node":\{"__typename":"Product","id":"(\d+)"[^{}]*?"name":"((?:[^"\\]|\\.)*)"', h[j: j + 300000] if j >= 0 else ""):
            names.setdefault(m.group(1), m.group(2))
        collections[key.split("/", 1)[1]] = [n for n in names.values() if n]

    made, _ = V.posts(raw.get("", ""), "makerPosts")
    hunted, _ = V.posts(raw.get("submitted", ""), "submittedPosts")
    return {"username": u, "profile": P.parse(u, raw.get("", "")), "made": made, "hunted": hunted, "upvotes": upvotes,
            "activity": activity, "reviews": V.reviews(raw.get("reviews", "")), "stacks": V.stacks(raw.get("stacks", "")),
            "collections": collections, "forums": {"joined": joined, "posts": forum_posts}}


def markdown(d: dict) -> str:
    p, L = d["profile"], [f"# @{d['username']}: everything pulled", ""]
    fp = d["forums"]["posts"]
    L += ["| Section | Count |", "|---|---|", f"| Activity | {len(d['activity'])} |", f"| Upvotes | {len(d['upvotes'])} |",
          f"| Made | {len(d['made'])} |", f"| Hunted | {len(d['hunted'])} |",
          "| Collections | " + ", ".join(f"{k} {len(v)}" for k, v in d["collections"].items()) + " |",
          f"| Stacks | {len(d['stacks'])} |", f"| Reviews | {len(d['reviews'])} |", f"| Forums joined | {len(d['forums']['joined'])} |",
          f"| Forum posts | {len(fp)} (in {len({r['thread_id'] for r in fp})} threads) |", "", "## About", ""]
    for k in ("name", "headline", "about", "twitter", "followers", "followings", "products_made", "hunted", "collections",
              "reviews_count", "stacks_count", "visit_streak_days", "community_rank_year", "current_product", "upvotes_total", "joined"):
        L.append(f"- **{k}**: {str(p.get(k)).replace(chr(10), ' / ')}")
    L.append("- **links**: " + ", ".join(f"{x['kind']}: {x['url']}" for x in p.get("links") or []))
    L.append("- **badges**: " + ", ".join(f"{k} ×{v}" for k, v in (p.get("badges") or {}).items()))
    cell = lambda s: (s or "").replace("|", "/").replace("\n", " ")  # noqa: E731
    L += ["", "## Made", ""] + [f"- {x['name']}: {x['tagline']} ({(x['featured'] or x['created'] or '')[:10]})" for x in d["made"]]
    L += ["", "## Hunted (posted for others)", ""] + [f"- {x['name']}: {x['tagline']} ({(x['created'] or '')[:10]})" for x in d["hunted"]]
    L += ["", "## Reviews", ""] + [f"- **{r['product_name']}** {r['rating']}★ ({(r['created'] or '')[:10]}) pros {r['pros']} "
                                   f"cons {r['cons']}: {r['text']}" for r in d["reviews"]]
    L += ["", "## Stacks", ""] + [f"- {s['name']} (added {(s['added'] or '')[:10]})" for s in d["stacks"]]
    for c, v in d["collections"].items():
        L += ["", f"## Collection: {c} ({len(v)})", ""] + [f"- {n}" for n in v]
    L += ["", "## Forums joined", "", ", ".join(d["forums"]["joined"])]
    L += ["", f"## Forum posts ({len(fp)}, newest first)", "", "| date | kind | thread | forum | what they wrote |", "|---|---|---|---|---|"]
    L += [f"| {r['date']} | {r['kind']} | {cell(r['thread'])} | {r['forum']} | {cell(r['text'])} |" for r in fp]
    up = sorted(d["upvotes"].values(), key=lambda x: x["date"], reverse=True)
    L += ["", f"## Upvotes ({len(up)}, newest first)", "", "| date | launch | tagline | daily rank |", "|---|---|---|---|"]
    L += [f"| {x['date']} | {cell(x['name'])} | {cell(x['tagline'])} | {x.get('daily_rank') or ''} |" for x in up]
    L += ["", f"## Activity ({len(d['activity'])}, newest first)", "", "| date | type | on | text |", "|---|---|---|---|"]
    L += [f"| {a['t']} | {a['type']} | {cell(a['on'])} | {cell(a['text'])} |" for a in d["activity"]]
    if d.get("github"):
        g, gu = d["github"], d["github"].get("user") or {}
        L += ["", "## GitHub", ""] + [f"- {k}: {gu.get(k)}" for k in ("login", "name", "bio", "blog", "location", "public_repos",
                                                                         "followers", "following", "created_at")]
        L += [f"- orgs: {', '.join(g.get('orgs') or [])}", "", "| repo | stars | language | last push | description |", "|---|---|---|---|---|"]
        L += [f"| {r['name']} | {r['stargazers_count']} | {r['language']} | {(r['pushed_at'] or '')[:10]} | {cell(r['description'])} |"
              for r in sorted(g.get("repos") or [], key=lambda r: -r["stargazers_count"])]
    if d.get("linkedin"):
        L += ["", "## LinkedIn", ""] + [f"### {k}\n\n{v}\n" for k, v in (d["linkedin"].get("sections") or {}).items()]
    if d.get("x"):
        xp = d["x"].get("profile") or {}
        L += ["", "## X", ""] + [f"- {k}: {xp.get(k)}" for k in ("screen_name", "name", "description", "location", "followers",
                                                                  "following", "tweets", "joined")]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--scroll", nargs="*", default=[])
    ap.add_argument("--github"); ap.add_argument("--linkedin"); ap.add_argument("--x")
    ap.add_argument("--out", required=True); ap.add_argument("--md")
    a = ap.parse_args()
    tag = "@" + a.username
    pages = {}
    for line in gzip.open(a.pages, "rt"):
        r = json.loads(line)
        pages[r["url"].split(tag, 1)[1].lstrip("/")] = r.get("html") or ""
    scroll = {}
    for f in a.scroll:
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            scroll[r["url"].split(tag + "/", 1)[1]] = r
    d = build(a.username, pages, scroll)
    if a.github:
        d["github"] = json.load(open(a.github))
    if a.linkedin:
        d["linkedin"] = json.load(open(a.linkedin))
    if a.x:
        d["x"] = json.loads(open(a.x).readline())
    json.dump(d, open(a.out, "w"))
    if a.md:
        open(a.md, "w").write(markdown(d))
    fp = d["forums"]["posts"]
    print({"upvotes": len(d["upvotes"]), "activity": len(d["activity"]), "made": len(d["made"]), "hunted": len(d["hunted"]),
           "reviews": len(d["reviews"]), "stacks": len(d["stacks"]), "collections": {k: len(v) for k, v in d["collections"].items()},
           "forums_joined": len(d["forums"]["joined"]), "forum_posts": len(fp)})


if __name__ == "__main__":
    main()
