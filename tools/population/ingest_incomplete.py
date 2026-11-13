#!/usr/bin/env python3
"""Bring the fleet's incomplete pulls (raw/_pacetest/shared/_incomplete/<h>.json) into the store, losslessly (Nov 13).

These pulls failed the whole-person check, so the audit never merged them, and their partial lists and fields were in
no store record. Each one is now unioned into the person's store record:
  - person already in the store: the store record stays the base (union keep_base=True), so a partial pull never
    replaces a whole one; its extra items go to <tab>.items_earlier and its fields to earlier_records;
  - person not in the store yet: the partial pull becomes their record (it scores incomplete until a whole pull arrives).
Resumable and idempotent: raw/_cursor/ingested_incomplete.tsv records name<TAB>object generation already ingested.
Counts only to stdout. Usage: ingest_incomplete.py W [--max N]
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import union_merge as U

R = "gs://usersim-bakeoff-347838016394/usersim_sim/raw"
SRC = f"{R}/_pacetest/shared/_incomplete"
VM = f"{R}/ph_population/people_live/vm"
MAN = f"{R}/_cursor/ingested_incomplete.tsv"
sh = lambda *a, **k: subprocess.run(a, capture_output=True, text=True, **k)


def bulk(urls, dst):
    os.makedirs(dst, exist_ok=True)
    for i in range(0, len(urls), 2000):
        sh("gcloud", "storage", "cp", "-I", f"{dst}/", input="".join(u + "\n" for u in urls[i:i + 2000]))


def main():
    W = sys.argv[1]
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10 ** 9
    T = f"{W}/ingest_incomplete"
    for sub in ("src", "cur", "out"):
        d = f"{T}/{sub}"
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    gen = {}
    for l in sh("gcloud", "storage", "objects", "list", f"{SRC}/*.json", "--format=value(name,generation)").stdout.splitlines():
        p = l.split("\t")
        if len(p) == 2:
            gen[p[0].rsplit("/", 1)[-1][:-5]] = p[1]
    done = {}
    for l in sh("gsutil", "cat", MAN).stdout.splitlines():
        p = l.split("\t")
        if len(p) == 2:
            done[p[0]] = p[1]
    todo = [n for n, g in sorted(gen.items()) if done.get(n) != g][:mx]
    print(f"INGEST_INCOMPLETE files={len(gen)} already={len(gen) - len([n for n in gen if done.get(n) != gen[n]])} todo={len(todo)}", flush=True)
    if not todo:
        return
    bulk([f"{SRC}/{n}.json" for n in todo], f"{T}/src")
    in_store = set()
    for l in sh("gcloud", "storage", "ls", f"{VM}/*.json").stdout.splitlines():
        in_store.add(l.rsplit("/", 1)[-1][:-5])
    have = [n for n in todo if n in in_store]
    bulk([f"{VM}/{n}.json" for n in have], f"{T}/cur")
    c = {"unioned_into_store_record": 0, "new_record": 0, "refused_would_lose": 0, "unreadable": 0, "items_earlier_added": 0}
    up, ok = [], []
    for n in todo:
        try:
            inc = json.load(open(f"{T}/src/{n}.json"))
        except Exception:
            c["unreadable"] += 1
            continue
        if n in in_store and os.path.exists(f"{T}/cur/{n}.json"):
            cur = json.load(open(f"{T}/cur/{n}.json"))
            m = U.union(cur, inc, keep_base=True)
            if U.lost(cur, m) != (0, 0) or U.lost(inc, m) != (0, 0):
                c["refused_would_lose"] += 1
                continue
            before = sum(len((cur.get(t) or {}).get("items_earlier") or []) for t in U.TABS if isinstance(cur.get(t), dict))
            after = sum(len((m.get(t) or {}).get("items_earlier") or []) for t in U.TABS if isinstance(m.get(t), dict))
            c["items_earlier_added"] += after - before
            c["unioned_into_store_record"] += 1
        else:
            m = inc
            m.setdefault("provenance_incomplete", {"source": "_pacetest/shared/_incomplete", "note": "failed whole-person check; kept so nothing is lost"})
            c["new_record"] += 1
        json.dump(m, open(f"{T}/out/{n}.json", "w"))
        up.append(n)
        ok.append(n)
    if up:
        sh("gcloud", "storage", "cp", "-I", f"{VM}/_bak_cursor/ingest_incomplete/", input="".join(f"{VM}/{n}.json\n" for n in up if n in in_store))
        for i in range(0, len(up), 2000):
            sh("gcloud", "storage", "cp", "-I", f"{VM}/", input="".join(f"{T}/out/{n}.json\n" for n in up[i:i + 2000]))
    old = sh("gsutil", "cat", MAN).stdout
    open(f"{T}/man.tsv", "w").write(old + "".join(f"{n}\t{gen[n]}\n" for n in ok))
    sh("gsutil", "-q", "cp", f"{T}/man.tsv", MAN)
    print(f"INGEST_INCOMPLETE {c}", flush=True)


if __name__ == "__main__":
    main()
