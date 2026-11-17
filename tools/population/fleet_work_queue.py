#!/usr/bin/env python3
"""The fleet's work queue after every merge cycle (population agent; orchestrator 01:21Z Nov 17).

The fleet's workers checked every handle against GCS before pulling, which starved 2-vCPU VMs; this list is already
filtered, so the fleet can pull it as is. Order: saved-but-incomplete store records first (completion-queue order from
have_index), then people with no whole-person save (need_list rank order). Anyone in the newest whole-person list
(quality_*_complete.txt) is dropped. No cap.
Usage: fleet_work_queue.py COMPLETION_QUEUE NEED_LIST COMPLETE_TXT OUT_TXT [--pid-map PID_HANDLE_JSON] [--priority F ...]
  --priority: refresh_priority_<day>.txt files (newest first), put at the very top in file order whether or not the
  person is complete (orchestrator 09:27Z Nov 17: E5's named people for the last 4 closed days are re-read first).
  --pid-map: {person_id: handle} for need_list rows that carry no handle (pool people never saved; built from the
  Nov 2 pool persons, the pool additions and the request lists, kept local).
Writes one handle per line; prints counts only.
"""
import json
import sys


def main():
    a = sys.argv[1:]
    pmap = {}
    if "--pid-map" in a:
        i = a.index("--pid-map")
        pmap = json.load(open(a[i + 1]))
        a = a[:i] + a[i + 2:]
    prio = []
    while "--priority" in a:
        i = a.index("--priority")
        prio.append(a[i + 1])
        a = a[:i] + a[i + 2:]
    cq, need, comp, out = a[:4]
    done = {l.split("\t")[0].strip().lower() for l in open(comp) if l.strip()}
    order, seen = [], set()

    def add(h, src):
        k = h.strip().lstrip("@").lower()
        if k and k not in seen and k not in done:
            seen.add(k)
            order.append((h.strip().lstrip("@"), src))
    for f in prio:
        for l in open(f):
            k = l.strip().lstrip("@")
            if k and k.lower() not in seen:
                seen.add(k.lower())
                order.append((k, "priority"))
    for l in open(cq):
        if l.strip() and not l.startswith("#"):
            add(l.split("\t")[0], "incomplete")
    rows = [json.loads(l) for l in open(need) if l.strip()]
    rows.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
    unmapped = 0
    for r in rows:
        h = r.get("handle") or pmap.get(r.get("person_id") or "", "")
        unmapped += not h
        add(h, "incomplete" if r.get("reason", "").startswith("saved but incomplete") else "new")
    open(out, "w").write("".join(f"{h}\n" for h, _ in order))
    print(json.dumps({"handles": len(order), "priority": sum(1 for _, s in order if s == "priority"), "incomplete": sum(1 for _, s in order if s == "incomplete"),
                      "new": sum(1 for _, s in order if s == "new"), "complete_filtered": len(done),
                      "need_rows_without_handle": unmapped}))


if __name__ == "__main__":
    main()
