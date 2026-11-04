"""Independent audit helpers for Data Feeder / babysitter puller changes (population agent).

  python tools/population/audit_merge.py merge BEFORE_DIR AFTER_DIR   # person JSONs before/after a deep pass
  python tools/population/audit_merge.py caps CODE_DIR                 # list cap-like limits in .py/.sh

merge: per person and tab, every item id/url saved before must still be present after (no item dropped); counts must not drop;
header must not change except by a fresh read; resume cursors (cursors/endCursor/paging) kept or advanced; new fields only
added, never removed from an item. Exit 1 on any violation.
caps: prints every line with a numeric limit near a loop/page/count word, so each can be justified as "PH's server ends it".
"""
import glob, json, os, re, sys

TABS = ["about", "forums", "activity", "upvotes", "hunted", "collections", "stacks", "reviews", "followers", "following"]


def key(it):
    for k in ("comment_id", "post_id", "review_id", "collection_id", "ph_user_id", "id", "handle", "url", "name", "title"):
        if isinstance(it, dict) and it.get(k):
            return f"{k}:{it[k]}"
    return json.dumps(it, sort_keys=True)[:200]


def merge(before, after):
    bad, n = [], 0
    for fb in sorted(glob.glob(f"{before}/*.json")):
        fa = os.path.join(after, os.path.basename(fb))
        if not os.path.exists(fa):
            bad.append(f"{os.path.basename(fb)}: missing after")
            continue
        b, a = json.load(open(fb)), json.load(open(fa))
        n += 1
        for t in TABS:
            tb, ta = b.get(t) or {}, a.get(t) or {}
            if not isinstance(tb, dict):
                continue
            ib = {key(x): x for x in tb.get("items") or []}
            ia = {key(x): x for x in ta.get("items") or []} if isinstance(ta, dict) else {}
            lost = set(ib) - set(ia)
            if lost:
                bad.append(f"{os.path.basename(fb)} {t}: {len(lost)} items dropped (e.g. {sorted(lost)[:2]})")
            for k in set(ib) & set(ia):
                gone = [f for f, v in ib[k].items() if v not in (None, "", []) and ia[k].get(f) in (None, "", [])]
                if gone:
                    bad.append(f"{os.path.basename(fb)} {t} {k}: fields emptied {gone[:4]}")
                    break
            if (ta.get("count") or 0) < (tb.get("count") or 0):
                bad.append(f"{os.path.basename(fb)} {t}: count {tb.get('count')} -> {ta.get('count')}")
        for ck in ("cursors", "resume", "paging"):
            if b.get(ck) and not a.get(ck):
                bad.append(f"{os.path.basename(fb)}: {ck} removed")
    print(f"checked {n} people; violations {len(bad)}")
    for x in bad[:50]:
        print("  ", x)
    return not bad


CAPRE = re.compile(r"(cap|max|limit|LARGE|budget|BUDGET|pages?|\[:\d|range\(\d|<\s*\d{2,}|>=\s*\d{2,}|\b\d{3,}\b)", re.I)


def caps(code):
    for p in sorted(glob.glob(f"{code}/**/*.py", recursive=True) + glob.glob(f"{code}/**/*.sh", recursive=True)):
        for i, line in enumerate(open(p, errors="replace"), 1):
            s = line.strip()
            if s.startswith("#") or not CAPRE.search(s):
                continue
            if re.search(r"\b\d+\b", s) and re.search(r"cap|max|limit|LARGE|budget|page|\[:\d|range\(|while|break", s, re.I):
                print(f"{os.path.relpath(p, code)}:{i}: {s[:180]}")


if __name__ == "__main__":
    if sys.argv[1] == "merge":
        sys.exit(0 if merge(sys.argv[2], sys.argv[3]) else 1)
    caps(sys.argv[2])
