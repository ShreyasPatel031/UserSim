"""Pool-growth candidates from data already held (no fetches), ranked by ties to Oct 1-24 voters (population agent).

Voters = people in have_index with an upvote (store events) on a launch featured Oct 1-24 PT (days/*.json).
Edges (handles, from raw pulls): followers/following lists in people_live vm/, vm_pgql/_run_*/, boxbrowser/; daily following
page 1; at-launch followers of makers/hunters. Candidate = any handle on an edge, forum-thread author/replier, or resolvable API
commenter, that is not in have_index. Score = distinct voters linked to the candidate by a follow edge in either direction.
Output (GCS only; handles never committed): JSONL {handle, score, follows_voters, followed_by_voters, sources}, ranked.
Usage: python candidates_voternet.py DATA_DIR STORE_DIR HAVE_INDEX OUT_JSONL
"""
import glob, json, os, re, sys
from collections import defaultdict
import pandas as pd

D, ST, HI, OUT = sys.argv[1:5]
norm = lambda h: (h or "").strip().lstrip("@").lower() or None
HANDLE = re.compile(r"producthunt\.com/@([A-Za-z0-9_\.\-]+)")

have = {}
for l in open(HI):
    r = json.loads(l)
    if r.get("handle"):
        have[r["person_id"]] = norm(r["handle"])
known = set(have.values())

# voters
oct_ids = set()
for p in glob.glob(f"{D}/days/2026-10-*.json"):
    day = os.path.basename(p)[:10]
    if "2026-10-01" <= day <= "2026-10-24":
        oct_ids |= {str(L["id"]) for L in json.load(open(p))}
ev = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"])
vp = set(ev[(ev.kind == "upvote") & ev.target_id.isin(oct_ids)].person_id)
voters = {have[p] for p in vp if p in have}
print(f"Oct 1-24 launches {len(oct_ids)}; voters with a known handle {len(voters):,} (of {len(vp):,} voter ids)")

follows_v = defaultdict(set)     # candidate -> voters the candidate follows
followed_by_v = defaultdict(set)  # candidate -> voters following the candidate
sources = defaultdict(set)


def edge(a, b, src):
    """a follows b"""
    a, b = norm(a), norm(b)
    if not a or not b or a == b:
        return
    for x in (a, b):
        if x not in known:
            sources[x].add(src)
    if b in voters and a not in known:
        follows_v[a].add(b)
    if a in voters and b not in known:
        followed_by_v[b].add(a)


def owner(d, path):
    for k in ("handle", "username"):
        if isinstance(d.get(k), str):
            return norm(d[k])
    m = HANDLE.search(str(d.get("profile") or ""))
    return norm(m.group(1)) if m else norm(os.path.basename(path).split(".")[0].replace("_full", "").replace("_f1fix", ""))


files = glob.glob(f"{D}/people_live/vm/*.json") + glob.glob(f"{D}/people_live/vm_pgql/_run_*/*.json") + \
    glob.glob(f"{D}/people_live/boxbrowser/*/*_full.json")
nfiles = 0
for f in files:
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if not isinstance(d, dict) or "upvotes" not in d and "header" not in d:
        continue
    nfiles += 1
    o = owner(d, f)
    for x in (d.get("followers") or {}).get("items") or []:
        edge(x.get("handle") or (HANDLE.search(x.get("url") or "") or [None, None])[1], o, "followers_list")
    for x in (d.get("following") or {}).get("items") or []:
        edge(o, x.get("handle") or (HANDLE.search(x.get("url") or "") or [None, None])[1], "following_list")
    threads = [(x, "forum") for x in (d.get("forums") or {}).get("items") or []] + \
              [((x.get("thread") or {}), "activity_thread") for x in (d.get("activity") or {}).get("items") or [] if isinstance(x.get("thread"), dict)]
    for x, src in threads:
        for h in [x.get("author")] + [r.get("handle") or r.get("author") for r in (x.get("replies") or []) if isinstance(r, dict)]:
            h = norm(h)
            if h and h not in known and re.fullmatch(r"[a-z0-9_\.\-]+", h):
                sources[h].add(src + "_participant")

for f in glob.glob(f"{D}/daily/*/following_page1.jsonl") + glob.glob(f"{D}/daily/pilot_following.jsonl"):
    for l in open(f):
        r = json.loads(l)
        edge(r.get("username"), r.get("followee"), "following_p1")
for f in glob.glob(f"{D}/ph_followers/*/*.jsonl"):
    for l in open(f):
        r = json.loads(l)
        edge(r.get("username"), r.get("of"), "team_followers")

# resolvable API commenters not yet known
if os.path.exists(f"{D}/user_id_map.jsonl"):
    m = pd.read_json(f"{D}/user_id_map.jsonl", lines=True, dtype={"user_id": str})
    uid2h = m.sort_values("last_seen").groupby("user_id").username.last()
    for f in glob.glob(f"{D}/api_comments/*/*.jsonl"):
        for l in open(f):
            r = json.loads(l)
            h = norm(uid2h.get(str(r.get("commenter_user_id"))))
            if h and h not in known:
                sources[h].add("api_commenter")

rows = []
for h in sources:
    a, b = follows_v.get(h, set()), followed_by_v.get(h, set())
    rows.append({"handle": h, "score": len(a | b), "follows_voters": len(a), "followed_by_voters": len(b), "sources": sorted(sources[h])})
rows.sort(key=lambda r: (-r["score"], -len(r["sources"]), r["handle"]))
with open(OUT, "w") as fo:
    for i, r in enumerate(rows, 1):
        fo.write(json.dumps({"rank": i, **r}) + "\n")
s = pd.Series([r["score"] for r in rows])
print(f"person files read {nfiles:,}; candidates {len(rows):,}; score>=1 {(s >= 1).sum():,}; >=3 {(s >= 3).sum():,}; >=10 {(s >= 10).sum():,}")
src = pd.Series([x for r in rows for x in r["sources"]]).value_counts()
print("by source:", src.to_dict())
