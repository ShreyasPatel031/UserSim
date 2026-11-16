#!/usr/bin/env python3
"""Map E5's daily refresh-priority list to fleet handles (population agent; orchestrator 18:08Z Nov 16).

Input : tmp/e5/private/refresh_priority/<day>.tsv  (person_id, ph_user_id; sorted by predicted vote chance)
Output: raw/_cursor/refresh_priority_<day>.txt     (one handle per line, same order; the fleet's upvote_refresh reads it)
Rows match on ph_user_id first, then the salted person_id, through have_index.jsonl (handle, person_id, ph_user_id).
Duplicate handles keep their first (highest-priority) position. Counts only to stdout; handles stay in raw/.
Usage: refresh_priority_map.py HAVE_INDEX IN_TSV OUT_TXT
"""
import json
import sys


def main():
    have, src, out = sys.argv[1:4]
    by_uid, by_pid = {}, {}
    for l in open(have):
        r = json.loads(l)
        h = r.get("handle")
        if not h:
            continue
        if r.get("ph_user_id") not in (None, ""):
            by_uid.setdefault(str(r["ph_user_id"]), h)
        if r.get("person_id"):
            by_pid.setdefault(r["person_id"], h)
    rows = [l.rstrip("\n").split("\t") for l in open(src) if l.strip()]
    if rows and rows[0][0] == "person_id":
        rows = rows[1:]
    handles, seen, miss, via_pid = [], set(), 0, 0
    for r in rows:
        pid = r[0] if r else ""
        uid = r[1] if len(r) > 1 else ""
        h = by_uid.get(uid)
        if h is None:
            h = by_pid.get(pid)
            via_pid += h is not None
        if h is None:
            miss += 1
            continue
        if h.lower() not in seen:
            seen.add(h.lower())
            handles.append(h)
    open(out, "w").write("".join(f"{h}\n" for h in handles))
    drop = round(100 * miss / max(len(rows), 1), 2)
    print(json.dumps({"rows": len(rows), "mapped": len(rows) - miss, "via_person_id": via_pid, "unmapped": miss,
                      "unmapped_pct": drop, "handles_written": len(handles)}))


if __name__ == "__main__":
    main()
