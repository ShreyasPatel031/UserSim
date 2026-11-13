import json, glob, sys, re, html
R = sys.argv[1]; clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
for d in ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]:
    LU = json.load(open(f"{R}/{d}/{d}.json")); com = {}
    for sub in ("api_comments", "api_replies", "api_comments_catchup", "api_fills"):
        for f in glob.glob(f"{R}/{d}/pal/{sub}/*.jsonl"):
            for l in open(f):
                x = json.loads(l)
                if x.get("post_id") and x.get("comment_id") and x.get("body") is not None and x.get("createdAt"): com.setdefault(str(x["post_id"]), {}).setdefault(x["comment_id"], x)
    old = new = 0
    for x in LU:
        cs = list(com.get(str(x["id"]), {}).values()); tops = sorted([(c["createdAt"], c.get("commenter_user_id")) for c in cs if not c.get("parentId")]); first = tops[0][1] if tops else None
        tn = {str(u.get("username", "")).lower() for u in [x.get("user") or {}] + (x.get("makers") or []) if u.get("username")}
        ti = {str(u.get("id")) for u in [x.get("user") or {}] + (x.get("makers") or []) if u.get("id")}
        ac = [c for c in cs if c.get("_s") != 1]
        old += sum(1 for c in cs if str(c.get("username", "")).lower() not in tn and c.get("commenter_user_id") != first and len(clean(c["body"])) > 15) >= 5
        new += sum(1 for c in cs if str(c.get("commenter_user_id")) not in ti and c.get("commenter_user_id") != first and len(clean(c["body"])) > 15) >= 5
    print(d, "lineup", len(LU), "judged old rule", old, "fixed rule", new)
