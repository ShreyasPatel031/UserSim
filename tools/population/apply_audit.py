#!/usr/bin/env python3
"""Finish (or redo) the merge step of one cursor_audit run from its written decision list, resumably.

cursor_audit.py writes raw/_cursor/audit_<STAMP>.tsv before it copies anything. If the run is cut off (machine restart)
during backups or uploads, re-running cursor_audit is not safe: those people's latest audit result is already
merge/replace, so --reaudit-held no longer picks them up. This script applies that audit instead:
  1. backup: every `replace` person's current store file -> <name>.json.bak_cursor (skipped if a backup from this
     stamp's run already exists, i.e. newer than the audit file);
  2. provenance: for saves from a VM with rotation or post-block new-IP evidence (recomputed from the VM's own status
     logs, same rules as cursor_audit), writes the provenance block into the audited local copy if it is missing;
  3. upload: the audited local copies (W/cursor_audit/people_live/vm/<name>.json) to the store, in parallel batches;
  4. ledger + audited.tsv: appends this stamp once (idempotent).
Then run merge_verify.py W STAMP. Counts only to stdout.
Usage: apply_audit.py W STAMP
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

G = "gs://usersim-bakeoff-347838016394/usersim_sim"
R = f"{G}/raw"
VM = f"{R}/ph_population/people_live/vm"
STAGE = f"{R}/_pacetest/shared"
CUR = f"{R}/_cursor"
EVASION = re.compile(r"rotat|portscreen|soft_open|soft_block|recreat|week_bytes|byte_stop_bypass|keeper", re.I)
BLOCK_SINCE = os.environ.get("CURSOR_BLOCK_SINCE", "2026-11-10T09:15:00Z")
sh = lambda *a, **k: subprocess.run(a, capture_output=True, text=True, **k)


def js(l):
    try:
        return json.loads(l)
    except Exception:
        return None


def strip(l):
    d = js(l)
    if not isinstance(d, dict):
        return l
    for k in ("handle", "h", "user", "username", "name", "url", "profile_url"):
        d.pop(k, None)
    return json.dumps(d)


def vm_evidence(SC, vm):
    files = [f"{SC}/{sub}/{fn}" for sub in ("stage", "vm") if os.path.isdir(f"{SC}/{sub}")
             for fn in os.listdir(f"{SC}/{sub}") if fn.startswith(vm + ".")]
    lines = "".join(open(f, errors="replace").read() for f in files).splitlines()
    rot = any(EVASION.search(strip(l)) for l in lines)
    recs = sorted((str(d.get("utc") or d.get("ts") or ""), d) for d in map(js, lines) if isinstance(d, dict))
    times = [t for t, _ in recs if t]
    held = None
    if times and times[0] >= BLOCK_SINCE:
        held = times[0]
    else:
        b = next((t for t, d in recs if d.get("event") == "stopped_on_block" and t >= BLOCK_SINCE), None)
        if b:
            before = {d.get("exit_ip") for t, d in recs if d.get("event") == "exit_ip" and t < b}
            held = next((t for t, d in recs if d.get("event") == "exit_ip" and t >= b and d.get("exit_ip") not in before), None)
    ips = [(t, d.get("exit_ip")) for t, d in recs if d.get("event") == "exit_ip" and d.get("exit_ip")]
    return rot, held, ips


def main():
    W, stamp = sys.argv[1], sys.argv[2]
    D = f"{W}/cursor_audit/people_live/vm"
    SC = f"{W}/cursor_audit_cache/status"
    for sub, src in (("stage", f"{STAGE}/status/"), ("vm", f"{VM}/status/")):
        os.makedirs(f"{SC}/{sub}", exist_ok=True)
        sh("gcloud", "storage", "rsync", src, f"{SC}/{sub}/")
    rows = [l.rstrip("\n").split("\t") for l in sh("gsutil", "cat", f"{CUR}/audit_{stamp}.tsv").stdout.splitlines()
            if l.strip() and not l.startswith("#")]
    todo = [r for r in rows if len(r) >= 5 and r[2] in ("merge", "replace")]
    missing = [r[0] for r in todo if not os.path.exists(f"{D}/{r[0]}.json")]
    print(f"APPLY {stamp}: merge={sum(r[2] == 'merge' for r in todo)} replace={sum(r[2] == 'replace' for r in todo)} "
          f"missing_local={len(missing)}", flush=True)
    if missing:
        sys.exit("audited local copies missing; not applying")
    # 1. backups (only those not yet made by this run)
    audit_t = sh("gsutil", "ls", "-l", f"{CUR}/audit_{stamp}.tsv").stdout.split()[1]
    have = {}
    for l in sh("gsutil", "ls", "-l", f"{VM}/*.bak_cursor").stdout.splitlines():
        p = l.split()
        if len(p) == 3 and p[2].startswith("gs://"):
            have[p[2].rsplit("/", 1)[1][:-len(".json.bak_cursor")]] = p[1]
    need = [r[0] for r in todo if r[2] == "replace" and have.get(r[0], "") < audit_t]
    with ThreadPoolExecutor(32) as ex:
        list(ex.map(lambda n: sh("gsutil", "-q", "cp", f"{VM}/{n}.json", f"{VM}/{n}.json.bak_cursor"), need))
    print(f"BACKUPS made={len(need)} already={sum(r[2] == 'replace' for r in todo) - len(need)}", flush=True)
    # 2. provenance
    ev, added = {}, 0
    for n, st_utc, res, md5, vm = (r[:5] for r in todo):
        if vm not in ev:
            ev[vm] = vm_evidence(SC, vm)
        rot, held, ips = ev[vm]
        post = bool(held and st_utc >= held)
        if not (rot or post):
            continue
        f = f"{D}/{n}.json"
        d = json.load(open(f))
        if "provenance" in d:
            continue
        ip = [i for t, i in ips if t <= st_utc]
        d["provenance"] = {"vm": vm, "exit_ip_at_save": ip[-1] if ip else None,
                           "gate_reasons": (["vm_evasion_or_unknown"] if rot else []) + (["vm_after_block_new_vm_or_ip"] if post else []),
                           "saved_after_post_block_ip_change": post, "vm_rotation_evidence": rot,
                           "merged_by": f"cursor_audit {stamp} --merge-vm-held (apply_audit)"}
        json.dump(d, open(f, "w"))
        added += 1
    print(f"PROVENANCE added={added}", flush=True)
    # 3. upload, 4 batches of 1000 at once
    files = [f"{D}/{r[0]}.json" for r in todo]
    batches = [files[i:i + 1000] for i in range(0, len(files), 1000)]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda b: sh("gcloud", "storage", "cp", "-I", f"{VM}/", input="".join(f + "\n" for f in b)), batches))
    print(f"UPLOADED {len(files)} {time.strftime('%H:%M:%SZ', time.gmtime())}", flush=True)
    # 4. ledger + audited.tsv, once per stamp
    led = sh("gsutil", "cat", f"{R}/_pacetest/merged_ledger.txt").stdout
    if f"# cursor {stamp}\n" not in led:
        open(f"{W}/ledger.txt", "w").write(led + f"# cursor {stamp}\n" + "".join(r[0] + "\n" for r in todo))
        sh("gsutil", "-q", "cp", f"{W}/ledger.txt", f"{R}/_pacetest/merged_ledger.txt")
    aud = sh("gsutil", "cat", f"{CUR}/audited.tsv").stdout
    if f"\t{stamp}\n" not in aud:
        open(f"{W}/audited.tsv", "w").write(aud + "".join(f"{r[0]}@{r[1]}\t{stamp}\n" for r in rows))
        sh("gsutil", "-q", "cp", f"{W}/audited.tsv", f"{CUR}/audited.tsv")
    print(f"APPLIED {stamp}", flush=True)


if __name__ == "__main__":
    main()
