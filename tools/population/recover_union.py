#!/usr/bin/env python3
"""One-off recovery (Nov 13): union every older copy of a person still held anywhere into their current store record.

Before 12:3xZ Nov 13 a newer pull REPLACED the stored record, dropping what only the older pull had. Older copies that
survive: vm/<h>.json.bak_cursor (single slot), vm/_bak_cursor/<stamp>/<h>.json, raw/_pacetest/feeder-pace32-*/<h>.json,
people_live/vm_pgql/_run_*/<h>.json (local mirror). Each person's current record stays the base (keep_base=True); every
older copy is unioned in (union_merge), with zero-loss checks against both. The current record is first copied to
vm/_bak_cursor/recover_<stamp>/, then the unioned record is uploaded. Counts only to stdout.
Usage: recover_union.py W SOURCES_REMOTE SOURCES_PGQL STAMP [--dry-run] [--max-batches N]
"""
import collections
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import union_merge as U

R = "gs://usersim-bakeoff-347838016394/usersim_sim/raw"
VM = f"{R}/ph_population/people_live/vm"


def nm(u):
    b = u.rstrip().rsplit("/", 1)[-1]
    for suf in (".json.bak_cursor", ".json"):
        if b.endswith(suf):
            b = b[:-len(suf)]
    return b.replace("_f1fix", "").lower()


def bulk(urls, dst):
    os.makedirs(dst, exist_ok=True)
    for i in range(0, len(urls), 2000):
        subprocess.run(["gcloud", "storage", "cp", "-I", f"{dst}/"], input="".join(u + "\n" for u in urls[i:i + 2000]),
                       capture_output=True, text=True)


def main():
    W, src_remote, src_pgql, stamp = sys.argv[1:5]
    dry = "--dry-run" in sys.argv
    T = f"{W}/recover/work"
    by = collections.defaultdict(list)  # name -> [(kind, local path)]
    remote = [l.strip() for l in open(src_remote) if l.strip()]
    groups = collections.defaultdict(list)
    for u in remote:
        kind = "bak_single" if u.endswith(".bak_cursor") else ("bak_" + u.split("/_bak_cursor/")[1].split("/")[0] if "/_bak_cursor/" in u
                                                              else "pace_" + u.split("/_pacetest/")[1].split("/")[0])
        groups[kind].append(u)
    for kind, urls in groups.items():
        d = f"{T}/src/{kind}"
        if not os.path.isdir(d) or len(os.listdir(d)) < len(urls):
            bulk(urls, d)
        for u in urls:
            p = f"{d}/{u.rsplit('/', 1)[-1]}"
            if os.path.exists(p):
                by[nm(u)].append((kind, p))
    for l in open(src_pgql):
        p = l.strip()
        if p:
            by[nm(p)].append(("pgql_run", p))
    vm_names = {}
    for fn in os.listdir(f"{W}/raw/people_live/vm"):
        if fn.endswith(".json"):
            k = fn[:-5].replace("_f1fix", "").lower()
            if k not in vm_names or "_f1fix" in vm_names[k]:
                vm_names[k] = fn[:-5]
    have = [n for n in by if n in vm_names]
    print(f"RECOVER people_with_copies={len(by)} in_store={len(have)} not_in_store={len(by) - len(have)}", flush=True)
    done_f = f"{W}/recover/done_{stamp}.txt"
    done = set(open(done_f).read().split()) if os.path.exists(done_f) else set()
    todo = [n for n in have if n not in done]
    print(f"RECOVER todo={len(todo)} already_done={len(have) - len(todo)}", flush=True)
    import multiprocessing as mp
    tot = collections.Counter()
    tabs_tot = collections.Counter()
    mb = int(sys.argv[sys.argv.index("--max-batches") + 1]) if "--max-batches" in sys.argv else 10 ** 6
    for i in range(0, min(len(todo), mb * 1000), 1000):
        batch = todo[i:i + 1000]
        cur_d = f"{T}/current"
        if os.path.isdir(cur_d):
            for f in os.listdir(cur_d):
                os.remove(os.path.join(cur_d, f))
        bulk([f"{VM}/{vm_names[n]}.json" for n in batch], cur_d)  # fresh: the record as it is right now
        out_d = f"{T}/out_{i}"
        os.makedirs(out_d, exist_ok=True)
        args = [(vm_names[n], f"{cur_d}/{vm_names[n]}.json", by[n], out_d) for n in batch]
        with mp.get_context("fork").Pool(4) as pool:
            res = pool.map(_one, args, chunksize=20)
        changed = [fn for fn, st, tabs in res if st == "changed"]
        for fn, st, tabs in res:
            tot[st] += 1
            tabs_tot.update(tabs)
        if changed and not dry:
            subprocess.run(["gcloud", "storage", "cp", "-I", f"{VM}/_bak_cursor/recover_{stamp}/"],
                           input="".join(f"{VM}/{fn}.json\n" for fn in changed), capture_output=True, text=True)
            subprocess.run(["gcloud", "storage", "cp", "-I", f"{VM}/"], input="".join(f"{out_d}/{fn}.json\n" for fn in changed),
                           capture_output=True, text=True)
        if not dry:
            open(done_f, "a").write("".join(n + "\n" for n in batch))
        print(f"RECOVER batch {i // 1000 + 1}: {dict(tot)} items_recovered_by_tab={dict(tabs_tot)}", flush=True)


def _one(a):
    fn, cp, copies_paths, out_d = a
    try:
        cur = json.load(open(cp))
    except Exception:
        return fn, "current_unreadable", {}
    copies = []
    for kind, p in copies_paths:
        try:
            copies.append(json.load(open(p)))
        except Exception:
            pass
    m = cur
    for o in copies:
        m = U.union(m, o, keep_base=True)
    if U.lost(cur, m) != (0, 0) or any(U.lost(o, m) != (0, 0) for o in copies):
        return fn, "refused_would_lose", {}
    gained = {}
    for t in U.TABS:
        if isinstance(m.get(t), dict):
            g = len(m[t].get("items_earlier") or []) - len(((cur.get(t) or {}) if isinstance(cur.get(t), dict) else {}).get("items_earlier") or [])
            if g > 0:
                gained[t] = g
    if json.dumps(m, sort_keys=True, default=str) == json.dumps(cur, sort_keys=True, default=str):
        return fn, "unchanged", {}
    json.dump(m, open(f"{out_d}/{fn}.json", "w"))
    return fn, "changed", gained

if __name__ == "__main__":
    main()
