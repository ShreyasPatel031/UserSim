"""Build Product Hunt comment-thread URLs (the page's own persisted query) for launches, and parse the results.
Fetching runs on the VM via vmfetch.py; this file only builds URLs and parses."""
import json, urllib.parse as U

HASH = "371bc2e82f8e978eae612e9d6320b87dbbef33b497edcc918b7254a628396bd5"


def url(slug, page=1, limit=50):
    v = {"commentsListSubjectThreadsCursor": "", "commentsListSubjectThreadsPage": page, "commentsThreadRepliesCursor": "",
         "order": "VOTES", "slug": slug, "includeThreadForCommentId": None, "commentsListSubjectThreadsLimit": limit,
         "commentsListSubjectFilter": None, "excludeThreadForCommentId": None}
    e = {"persistedQuery": {"version": 1, "sha256Hash": HASH}}
    return ("https://www.producthunt.com/frontend/graphql?operationName=PostPageComments&variables="
            + U.quote(json.dumps(v, separators=(",", ":"))) + "&extensions=" + U.quote(json.dumps(e, separators=(",", ":"))))


def parse(body):
    """-> launch info + one row per comment (thread or reply): user, time, votes, depth."""
    post = ((body or {}).get("data") or {}).get("post") or {}
    out = []

    def walk(node, depth):
        u = node.get("user") or {}
        out.append({"comment_id": node.get("id"), "user_id": u.get("id"), "username": u.get("username"),
                    "prominent": u.get("isProminent"), "verified": u.get("isAccountVerified"),
                    "created": node.get("createdAt"), "votes": node.get("votesCount"), "depth": depth,
                    "is_maker": node.get("isMaker") if "isMaker" in node else None})
        for e in ((node.get("replies") or {}).get("edges") or []):
            walk(e["node"], depth + 1)
    th = post.get("threads") or {}
    for e in th.get("edges") or []:
        walk(e["node"], 0)
    return {"post_id": post.get("id"), "slug": post.get("slug"), "comments_count": post.get("commentsCount"),
            "threads_total": th.get("totalCount"), "has_next": (th.get("pageInfo") or {}).get("hasNextPage")}, out
