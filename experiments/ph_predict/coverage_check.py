"""Check the inputs are actually fetched before any model or ranking runs. Per launch month: share of launches with
  page score, real images seen by Gemini (logo / gallery), website text, first comment, video link, video watched
Exits non-zero (and says which) when any month is below its floor, so a chained job stops instead of ranking on zeros.
usage: python coverage_check.py [--floor images=0.8,website=0.5,...] -> prints a table; exit 1 if a floor is missed"""
import glob, json, os, sys
from collections import defaultdict

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FLOORS = {"page_score": 0.95, "images": 0.80, "website": 0.50, "first_comment": 0.60, "video_watched_of_links": 0.70}


def jl(fn):
    p = f"{D}/{fn}"
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def main(argv):
    floors = dict(FLOORS)
    for a in argv:
        if a.startswith("--floor"):
            for kv in a.split("=", 1)[1].split(","):
                k, v = kv.split("="); floors[k] = float(v)
    month = {}
    for f in glob.glob(f"{D}/days/*.json"):
        for p in json.load(open(f)):
            month[str(p["id"])] = f[-15:-5][:7]
    ps = {r["id"]: r for r in jl(os.environ.get("PS_OUT", "page_scores_v2.jsonl"))}
    web = {r["id"] for r in jl("sites_text.jsonl")}
    media = {str(r["id"]): r for r in jl("page_media.jsonl")}
    vids = {i for i, r in media.items() if any(m.get("type") == "video" and m.get("videoUrl") for m in r.get("media") or [])}
    watched = {r["id"] for r in jl("video_scores.jsonl") if "error" not in (r.get("result") or {})}
    n = defaultdict(lambda: defaultdict(int))
    for i, m in month.items():
        c = n[m]; c["launches"] += 1
        r = ps.get(i)
        c["page_score"] += r is not None
        c["images"] += bool(r and r.get("n_images", 0) > 0)
        c["website"] += i in web
        c["first_comment"] += bool(r and r.get("has_first_comment"))
        c["video_links"] += i in vids
        c["video_watched"] += i in watched
    cols = ["page_score", "images", "website", "first_comment", "video_watched_of_links"]
    print("month    launches " + " ".join(f"{c:>22s}" for c in cols))
    bad = []
    for m in sorted(n):
        c = n[m]; L = c["launches"]
        share = {"page_score": c["page_score"] / L, "images": c["images"] / L, "website": c["website"] / L,
                 "first_comment": c["first_comment"] / L, "video_watched_of_links": c["video_watched"] / max(c["video_links"], 1)}
        print(f"{m}  {L:8d} " + " ".join(f"{100 * share[k]:21.0f}%" for k in cols))
        bad += [f"{m} {k} {100 * share[k]:.0f}% < {100 * floors[k]:.0f}%" for k in cols if share[k] < floors[k]]
    if bad:
        print("MISSING DATA, do not rank on this:\n  " + "\n  ".join(bad)); sys.exit(1)
    print("COVERAGE OK")


if __name__ == "__main__":
    main(sys.argv[1:])
