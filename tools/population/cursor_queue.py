"""Build the Cursor extraction queue (raw/_cursor/queue.txt). Bucket only; prints counts only.

Usage: cursor_queue.py WORK [--dry-run]

queue = priority_lastweek.txt (file order = tier order)
      + rerun_whole_* requests (oldest file first, not already listed)
      + audit fails returned by cursor_audit.py (raw/_cursor/requeue.txt)
      - latest_complete.txt (whole / whole_signed_out)
      - held: priority_lastweek_needs_full18c.txt, pending_offset_repage_latest.tsv
Handles never leave raw/; nothing here is committed with handles.
"""
import os, subprocess, sys, time

R = "gs://usersim-bakeoff-347838016394/usersim_sim/raw"
SRC = {
    "priority": f"{R}/_cursor/priority_lastweek_order_0230Z.txt",  # 09:1xZ Nov 10: own copy; _pacetest/priority_lastweek.txt was rewritten by another agent
    "complete": f"{R}/_babysitter/quality/latest_complete.txt",
    "held_18c": f"{R}/_pacetest/priority_lastweek_needs_full18c.txt",
    "held_offset": f"{R}/population/requests/pending_offset_repage_latest.tsv",
    "requeue": f"{R}/_cursor/requeue.txt",
}
OUT = f"{R}/_cursor/queue.txt"


def cat(url, required=True):
    r = subprocess.run(["gsutil", "cat", url], capture_output=True, text=True)
    if r.returncode != 0:
        if required:
            sys.exit(f"missing input: {url.rsplit('/', 1)[-1]}")
        return []
    return r.stdout.splitlines()


def handles(lines):
    out = []
    for l in lines:
        l = l.strip()
        if l and not l.startswith("#"):
            out.append(l.split("\t")[0].split()[0].lower())
    return out


def main():
    W = sys.argv[1]
    dry = "--dry-run" in sys.argv
    pri = handles(cat(SRC["priority"]))
    complete = set(handles(cat(SRC["complete"])))
    held = set(handles(cat(SRC["held_18c"]))) | set(handles(cat(SRC["held_offset"])))
    ls = subprocess.run(["gsutil", "ls", f"{R}/population/requests/rerun_whole_*.txt"],
                        capture_output=True, text=True).stdout.split()
    reruns = []
    for u in sorted(ls):
        reruns += handles(cat(u, required=False))
    requeue = handles(cat(SRC["requeue"], required=False))

    q, seen, drop = [], set(), {"complete": 0, "held": 0, "dup": 0}
    for src, hs in (("priority", pri), ("rerun", reruns), ("requeue", requeue)):
        for h in hs:
            if h in seen:
                drop["dup"] += 1
                continue
            seen.add(h)
            if h in complete:
                drop["complete"] += 1
                continue
            if h in held:
                drop["held"] += 1
                continue
            q.append((src, h))
    by = {s: sum(1 for x, _ in q if x == s) for s in ("priority", "rerun", "requeue")}
    stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
    local = os.path.join(W, "cursor_queue.txt")
    with open(local, "w") as f:
        f.write(f"# built {stamp} by population agent; highest priority first\n")
        f.writelines(h + "\n" for _, h in q)
    print(f"QUEUE {stamp}: {len(q)} people (priority_lastweek {by['priority']}, rerun_whole {by['rerun']}, "
          f"requeue {by['requeue']}); dropped complete {drop['complete']}, held {drop['held']}, dup {drop['dup']}; "
          f"inputs: priority {len(pri)}, rerun files {len(ls)}, complete {len(complete)}, held {len(held)}")
    if not dry:
        subprocess.run(["gsutil", "-q", "-h", "Content-Type:text/plain", "cp", local, OUT], check=True)
        print("uploaded raw/_cursor/queue.txt")


if __name__ == "__main__":
    main()
