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
    global SRC, MAN
    W = sys.argv[1]
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10 ** 9
    T = f"{W}/ingest_incomplete"
    # 01:0xZ Nov 22: --failed NAMES_FILE ingests staged saves that FAILED the audit (raw/_pacetest/shared/<h>.json) the
    # same lossless way. A failed upvote refresh can carry new items (7 at 00:51Z: +146 upvotes) that were in no store
    # record, because a fail was only requeued. Store record stays the base; the save's extra items go to items_earlier.
    names = None
    tag = "INGEST_INCOMPLETE"
    if "--failed" in sys.argv:
        names = {l.split()[0] for l in open(sys.argv[sys.argv.index("--failed") + 1]) if l.strip()}
        SRC, MAN, T, tag = f"{R}/_pacetest/shared", f"{R}/_cursor/ingested_failed.tsv", f"{W}/ingest_failed", "INGEST_FAILED"
    for sub in ("src", "cur", "out"):
        d = f"{T}/{sub}"
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    gen = {}
    for l in sh("gcloud", "storage", "objects", "list", f"{SRC}/*.json", "--format=value(name,generation)").stdout.splitlines():
        p = l.split("\t")
        if len(p) == 2:
            k = p[0].rsplit("/", 1)[-1][:-5]
            if names is None or k in names:
                gen[k] = p[1]
    done = {}
    for l in sh("gsutil", "cat", MAN).stdout.splitlines():
        p = l.split("\t")
        if len(p) == 2:
            done[p[0]] = p[1]
    todo = [n for n, g in sorted(gen.items()) if done.get(n) != g][:mx]
    print(f"{tag} files={len(gen)} already={len(gen) - len([n for n in gen if done.get(n) != gen[n]])} todo={len(todo)}", flush=True)
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
            # orchestrator 01:05Z Nov 22 (failed saves) and 19:05Z Nov 22 (this _incomplete ingest too; TARGET_SCHEMA: a
            # person less than whole is not written): a partial pull of a person with NO store record is never written to
            # the store. It stays staged and is copied to people_live/incomplete_failed/. People already in the store still
            # gain extra items through items_earlier (above).
            sh("gcloud", "storage", "cp", f"{SRC}/{n}.json", f"{VM.rsplit('/', 1)[0]}/incomplete_failed/{'' if names is not None else '_incomplete/'}{n}.json")
            c["kept_outside_store"] = c.get("kept_outside_store", 0) + 1
            ok.append(n)
            continue
        json.dump(m, open(f"{T}/out/{n}.json", "w"))
        up.append(n)
        ok.append(n)
    if up:
        sh("gcloud", "storage", "cp", "-I", f"{VM}/_bak_cursor/{os.path.basename(T)}/", input="".join(f"{VM}/{n}.json\n" for n in up if n in in_store))
        for i in range(0, len(up), 2000):
            sh("gcloud", "storage", "cp", "-I", f"{VM}/", input="".join(f"{T}/out/{n}.json\n" for n in up[i:i + 2000]))
    old = sh("gsutil", "cat", MAN).stdout
    open(f"{T}/man.tsv", "w").write(old + "".join(f"{n}\t{gen[n]}\n" for n in ok))
    sh("gsutil", "-q", "cp", f"{T}/man.tsv", MAN)
    print(f"{tag} {c}", flush=True)


if __name__ == "__main__":
    main()
