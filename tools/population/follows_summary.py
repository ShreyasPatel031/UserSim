#!/usr/bin/env python3
"""Per-person follow-list summary from whole-person pulls, for the Data Feeder master (hashed ids only, no handles).

Reads the latest quality rows (quality_<UTC>.jsonl from quality_run.sh) for tab states and the local people_live/vm
mirror for list sizes. Writes one JSON line per PH person:
  {person_id, followers_state, following_state, followers_n, following_n, followers_header, following_header,
   full, finished_utc, source}
full = both lists read to PH's end (state complete or ph_limit). person_id uses the master's rule
'p_'+sha256(salt+'producthunt:'+lower(u).lstrip('@'))[:16].
Usage: follows_summary.py SALT_FILE QUALITY_JSONL VM_DIR OUT_JSONL   (counts only to stdout)
"""
import collections
import hashlib
import json
import os
import sys

END = {"complete", "ph_limit"}


def main():
    salt_f, qrows, vm, out = sys.argv[1:5]
    salt = open(salt_f).read().strip()
    pid = lambda u: "p_" + hashlib.sha256((salt + "producthunt:" + u.lower().lstrip("@")).encode()).hexdigest()[:16]
    assert pid("example_user") == "p_97eb5d57c445ef1f", "salt/rule test vector failed"
    q = {}
    for l in open(qrows):
        d = json.loads(l)
        h = d["handle"].lower().lstrip("@")
        if h not in q or (d.get("finished") or "") > (q[h].get("finished") or ""):
            q[h] = d
    files = {}
    for fn in sorted(os.listdir(vm)):  # file names keep the handle's case; "_f1fix" copies only as a fallback
        if fn.endswith(".json"):
            k = fn[:-5].replace("_f1fix", "").lower().lstrip("@")
            if k not in files or "_f1fix" in files[k]:
                files[k] = fn
    # cache of list sizes per file, keyed by (name, size, mtime): reading ~80k records each cycle took ~10 min and pushed
    # the :20/:50 cycle past its time limit (Nov 14 00:1xZ); only changed files are re-read
    cache_f = os.path.join(os.path.dirname(os.path.abspath(vm)), ".follows_cache.json")
    try:
        cache = json.load(open(cache_f))
    except Exception:
        cache = {}
    new_cache = {}
    c = collections.Counter()
    with open(out, "w") as o:
        for h, r in q.items():
            st = r.get("states") or {}
            fo, fi = st.get("followers"), st.get("following")
            if not fo and not fi:
                continue
            n = {"followers": None, "following": None}
            hd = dict(n)
            try:
                fp = os.path.join(vm, files[h])
                stt = os.stat(fp)
                key = f"{files[h]}|{stt.st_size}|{stt.st_mtime_ns}"
                if key in cache:
                    n, hd = cache[key]
                else:
                    d = json.load(open(fp))
                    for k in n:
                        t = d.get(k) or {}
                        n[k] = len(t.get("items") or [])
                        hd[k] = (d.get("header") or {}).get(k)
                new_cache[key] = [n, hd]
            except Exception:
                pass
            full = fo in END and fi in END
            c["full" if full else "partial"] += 1
            o.write(json.dumps({"person_id": pid(h), "followers_state": fo, "following_state": fi,
                                "followers_n": n["followers"], "following_n": n["following"],
                                "followers_header": hd["followers"], "following_header": hd["following"],
                                "full": full, "finished_utc": r.get("finished"),
                                "source": "people_live_whole"}) + "\n")
    tmp = cache_f + ".tmp"
    json.dump(new_cache, open(tmp, "w"))
    os.replace(tmp, cache_f)
    print(f"FOLLOWS_SUMMARY cache_hits={sum(1 for k in new_cache if k in cache)} people={sum(c.values())} full={c['full']} partial={c['partial']}")


if __name__ == "__main__":
    main()
