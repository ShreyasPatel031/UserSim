import json, glob, sys, collections
R = sys.argv[1]
for d in ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]:
    cc, ts = {}, ""
    for f in sorted(glob.glob(f"{R}/{d}/pal/api_detail/*.jsonl")):
        for l in open(f):
            x = json.loads(l)
            if x.get("kind") == "api_post_detail" and x.get("commentsCount") is not None:
                cc[str(x["id"])] = max(cc.get(str(x["id"]), 0), int(x["commentsCount"])); ts = max(ts, x["snapshot_at"])
    if not cc:
        dj = json.load(open(f"{R}/{d}/{d}.json")); cc = {str(p["id"]): int(p.get("commentsCount") or 0) for p in dj}; ts = "daily json (early)"
    src = collections.defaultdict(lambda: collections.defaultdict(set))
    for f in glob.glob(f"{R}/{d}/pal/api_*/*.jsonl") + glob.glob(f"{R}/{d}/pal/live/comments_ts.jsonl"):
        s = f.split("/")[-2]
        for l in open(f):
            try: x = json.loads(l)
            except Exception: continue
            lid = str(x.get("post_id") or x.get("launch_id") or ""); cid = x.get("comment_id")
            if lid and cid: src[s][lid].add(str(cid))
    g = collections.defaultdict(set)
    for s in src:
        for k, v in src[s].items(): g[k] |= v
    ids = set(cc); exp = sum(cc.values()); got = sum(min(len(g[i]), cc[i]) for i in ids)
    sh = sorted(len(g[i]) / cc[i] for i in ids if cc[i] >= 5)
    print(json.dumps({"day": d, "count_ref": ts, "launches": len(ids), "PH commentsCount (max seen)": exp, "captured (capped at count)": got, "share": round(got / max(exp, 1), 3),
        "launches >=5 PH comments": sum(cc[i] >= 5 for i in ids), ">=5 captured": sum(len(g[i]) >= 5 for i in ids),
        ">=90% captured among >=5": sum(x >= .9 for x in sh), "median capture share (>=5)": round(sh[len(sh)//2], 2) if sh else None,
        "worst 3": [round(x, 2) for x in sh[:3]]}))
