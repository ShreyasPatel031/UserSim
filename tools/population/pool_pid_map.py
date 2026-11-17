#!/usr/bin/env python3
"""{person_id: handle} for need_list rows that carry no handle (pool people never saved), for fleet_work_queue.py.

Sources (all local raw copies; the map stays local, never uploaded): the Nov 2 pool persons
(people_v3g/persons.parquet ph_username), the pool additions (prov/pool/*.jsonl username) and every request list
under prov/src (first column). Only person_ids on the need list are written. Counts only to stdout.
Usage: pool_pid_map.py WORK_DIR NEED_LIST SALT_FILE OUT_JSON
"""
import glob
import hashlib
import json
import os
import re
import sys

import pandas as pd


def main():
    W, need_f, salt_f, out = sys.argv[1:5]
    salt = open(salt_f).read().strip()
    pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower().lstrip("@")).encode()).hexdigest()[:16]
    ok = lambda v: isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", v.lstrip("@"))
    need = set()
    for l in open(need_f):
        d = json.loads(l)
        if not d.get("handle") and d.get("person_id"):
            need.add(d["person_id"])
    m = {}

    def put(v):
        if ok(v):
            p = pid(v)
            if p in need:
                m.setdefault(p, v.lstrip("@"))
    pp = f"{W}/raw/people_v3g/persons.parquet"
    if os.path.exists(pp):
        for u in pd.read_parquet(pp, columns=["ph_username"]).ph_username.dropna():
            put(str(u))
    for f in glob.glob(f"{W}/prov/pool/*.jsonl"):
        for l in open(f):
            try:
                put(json.loads(l).get("username"))
            except Exception:
                pass
    for f in glob.glob(f"{W}/prov/src/**/*", recursive=True):
        if os.path.isfile(f):
            for l in open(f, errors="ignore"):
                put(l.split("\t")[0].split(",")[0].strip())
    json.dump(m, open(out, "w"))
    print(json.dumps({"need_rows_without_handle": len(need), "mapped": len(m), "unmapped": len(need) - len(m)}))


if __name__ == "__main__":
    main()
