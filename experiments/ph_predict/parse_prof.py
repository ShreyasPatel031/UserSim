"""Parse a Product Hunt profile page into the person's own fields (two user records on the page)."""
import json, re, base64, sys


def rec(h, u, after_key):
    """Text of the {"__typename":"User",...} record whose username is u and whose next key is after_key."""
    i = h.find('"username":"%s","%s"' % (u, after_key))
    if i < 0:
        i = h.find('"username":"%s"' % u)
        if i < 0:
            return ""
    st = h.rfind('{"__typename":"User"', 0, i)
    return h[st: i + 6000]


def val(seg, k):
    m = re.search(r'"' + k + r'":("(?:[^"\\]|\\.)*"|-?[\d.]+|true|false|null)', seg)
    return json.loads(m.group(1)) if m else None


def parse(u, h):
    head = rec(h, u, "headline")
    about = rec(h, u, "about")
    about_cut = about.split('"badgeGroups"')[0]
    links = []
    for name, enc, kind in re.findall(r'"name":"([^"]*)","encodedUrl":"([^"]+)","kind":"([a-z_]+)"', about_cut):
        try:
            url = base64.b64decode(enc.replace("\\n", "")).decode()
        except Exception:  # noqa: BLE001
            continue
        if url not in [x["url"] for x in links]:
            links.append({"kind": kind, "url": url})
    badges = {}
    bg = about.split('"badgeGroups"', 1)[1][:20000] if '"badgeGroups"' in about else ""
    for cnt, name in re.findall(r'"badgesCount":(\d+),"award":\{"__typename":"UserBadgeAward","id":"\d+","name":"([^"]+)"', bg):
        badges[name] = int(cnt)
    byline = re.search(r'"selectedByline":\{"__typename":"UserByline","id":"\d+","label":"([^"]*)"', head)
    vm = re.search(r'"votedPosts":\{"__typename":"PostConnection","edges":\[(.*?)\]\}', h, re.S)
    return {
        "username": u, "user_id": val(head, "id") or val(about, "id"), "name": val(head, "name") or val(about, "name"),
        "headline": val(head, "headline"), "about": val(about, "about"), "twitter": val(head, "twitterUsername"),
        "verified": val(head, "isAccountVerified"), "is_maker": val(head, "isMaker"),
        "followers": val(head, "followersCount"), "followings": val(head, "followingsCount"),
        "products_made": val(head, "productsCount"), "hunted": val(head, "submittedPostsCount"),
        "collections": val(head, "collectionsCount"), "reviews_count": val(head, "reviewsCount"),
        "stacks_count": val(head, "stacksCount"), "visit_streak_days": val(head.split('"visitStreak"', 1)[-1][:200], "duration"),
        "community_rank_year": val(head.split('"kittyCoinYear"', 1)[-1][:200], "rank"),
        "current_product": byline.group(1) if byline else None,
        "upvotes_total": val(about, "votesCount"), "joined": val(about, "createdAt"),
        "badges_total": val(about, "badgesCount"), "badges": badges, "links": links,
        "voted_recent": re.findall(r'"__typename":"Post","id":"(\d+)"', vm.group(1)) if vm else [],
    }


if __name__ == "__main__":
    out = open(sys.argv[2], "w")
    for l in open(sys.argv[1]):
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("status") != 200:
            continue
        u = r["url"].rsplit("@", 1)[-1]
        out.write(json.dumps(parse(u, r["html"].replace('\\"', '"').replace("\\/", "/"))) + "\n")
