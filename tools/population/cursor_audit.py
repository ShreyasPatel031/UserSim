"""Hourly audit of Cursor staging (raw/_pacetest/shared/). Bucket only; prints counts only.

Usage: cursor_audit.py WORK [--dry-run]

For each staged <name>.json written after START and not yet in raw/_cursor/audited.tsv:
  1. strict whole-person check (quality.person_complete; whole_signed_out needs a signed-in queue entry)
  2. build gate: run.pkg_md5 must be in AUDITED_BUILDS (full18d is added only after its first-run audit passes)
  3. VM gate: the producing VM's status logs must show no IP/port rotation, recreate or byte-stop bypass events
Pass -> copied into people_live/vm/ (an existing vm/ file is replaced only for a rerun_whole request with a newer
         staged copy; the old one is set aside as .bak_cursor) and appended to raw/_pacetest/merged_ledger.txt.
Fail -> raw/_cursor/requeue.txt (back on the queue) unless it is a follow-list-only fail (held for the offset re-page).
Per-handle reasons go only to raw/_cursor/audit_<stamp>.tsv. mailbox/to_cursor/audit_<stamp>.md gets counts only.
"""
import collections, contextlib, io, json, os, re, runpy, subprocess, sys, time

G = "gs://usersim-bakeoff-347838016394/usersim_sim"
R = f"{G}/raw"
STAGE = f"{R}/_pacetest/shared"
VM = f"{R}/ph_population/people_live/vm"
CUR = f"{R}/_cursor"
START = os.environ.get("CURSOR_AUDIT_START", "2026-11-08T18:20:00Z")  # protocol start; older staged files belong to the pace test (merge_list.py)
FULL18D = "T3OI+xr3iAvoMDMZrdryhA=="
FULL18F = "uYYdW17hoPBJjpMGoR7lKw=="  # full18e + paging_v2.py:210 fix (no 98% / header-2 complete label); population agent 03:5xZ Nov 10
AUDITED_BUILDS = {FULL18D, FULL18F}  # orchestrator 20:46Z Nov 8: the person-level check (full18e rule) is the gate; full18d first-run audit FAILED on >1k lists (98% shortcut), and those people fail person_complete and stay held
EVASION = re.compile(r"rotat|portscreen|soft_open|soft_block|recreat|week_bytes|byte_stop_bypass|keeper", re.I)
MERGE_VM_HELD = False
BLOCK_SINCE = os.environ.get("CURSOR_BLOCK_SINCE", "2026-11-10T09:15:00Z")  # fleet-wide PH block start (status logs)
FOLLOW_ONLY = re.compile(r"^(followers|following):FAIL_(repeat|no_offset_end)$")
sh = lambda *a: subprocess.run(a, capture_output=True, text=True)


def lsl(pat):
    o = {}
    for l in sh("gsutil", "ls", "-l", pat).stdout.splitlines():
        f = l.split()
        if len(f) == 3 and f[2].endswith(".json"):
            o[f[2].rsplit("/", 1)[-1][:-5]] = f[1]
    return o


def lines(url):
    return [l for l in sh("gsutil", "cat", url).stdout.splitlines() if l.strip() and not l.startswith("#")]


def main():
    W, dry = sys.argv[1], "--dry-run" in sys.argv
    global MERGE_VM_HELD
    MERGE_VM_HELD = "--merge-vm-held" in sys.argv
    prov = {}
    stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
    done = {l.split("\t")[0] for l in lines(f"{CUR}/audited.tsv")}
    if "--reaudit-held" in sys.argv:  # re-score people whose latest audit result was held_gate (whole, blocked only by a gate)
        last = {}
        for u in sorted(sh("gsutil", "ls", f"{CUR}/audit_*.tsv").stdout.split()):
            for l in lines(u):
                f = l.split("\t")
                if len(f) >= 3: last[f"{f[0]}@{f[1]}"] = f[2]
        held = {k for k, v in last.items() if v == "held_gate"}
        print(f"REAUDIT_HELD={len(held)}")
        done -= held
    st = lsl(f"{STAGE}/*.json")
    todo = sorted(n for n, t in st.items() if t >= START and f"{n}@{t}" not in done)
    print(f"STAGED_NEW={len(todo)}")
    if not todo:
        return
    D = f"{W}/cursor_audit"
    sh("rm", "-rf", D)
    for p in ("people_live/vm", "people_live/deep_list", "signedin_upvotes"):
        os.makedirs(f"{D}/{p}", exist_ok=True)
    sh("gsutil", "-q", "-m", "cp", *[f"{STAGE}/{n}.json" for n in todo], f"{D}/people_live/vm/")
    sh("gsutil", "-q", "-m", "cp", f"{STAGE}/_signedin_upvotes/*.json", f"{D}/signedin_upvotes/")
    sys.argv = ["quality.py", D, "2026-11-05T00:00:00Z", "/dev/null", "/dev/null"]
    with contextlib.redirect_stdout(io.StringIO()):
        g = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "quality.py"))
    vm_t = lsl(f"{VM}/*.json")
    rerun = set()
    for u in sh("gsutil", "ls", f"{R}/population/requests/rerun_whole_*.txt").stdout.split():
        rerun |= {l.split()[0].lstrip("@").lower() for l in lines(u)}
    vm_clean = {}

    def clean(vm):
        if vm not in vm_clean:
            # 20:1xZ Nov 12: "{vm}.*", not "{vm}*": the bare glob also read VMs -10..-19 for VM -1 (-40..-49 for -4, ...),
            # so a VM was judged on other VMs' rotation/block events. Logs are {vm}.jsonl and {vm}.supervisor.jsonl.
            logs = sh("gsutil", "ls", f"{STAGE}/status/{vm}.*", f"{R}/ph_population/people_live/vm/status/{vm}.*").stdout.split()
            txt = "".join(sh("gsutil", "cat", u).stdout for u in logs)
            lines = txt.splitlines()
            vm_clean[vm] = (not any(EVASION.search(_strip_person(l)) for l in lines), _block_evasion(lines))
            vm_ips[vm] = sorted((str(d.get("utc") or ""), d.get("exit_ip")) for d in map(_js, lines)
                                if isinstance(d, dict) and d.get("event") == "exit_ip" and d.get("exit_ip"))
        return vm_clean[vm]

    vm_ips = {}

    def _js(l):
        try:
            return json.loads(l)
        except Exception:
            return None

    def ip_at(vm, t):
        ips = [ip for u, ip in vm_ips.get(vm, []) if u <= t]
        return ips[-1] if ips else None

    def _block_evasion(lines):
        """orchestrator 10:25Z Nov 10. Returns the UTC time from which this VM's saves are held, or None:
        - a VM whose first log line is at/after BLOCK_SINCE (created during/after the PH block): held from its first line;
        - a VM with a stopped_on_block at/after BLOCK_SINCE that then shows an exit IP it never used before that block:
          held from that new-IP event. Earlier blocks are ignored (the residential proxy changes exit IPs on its own)."""
        recs = []
        for l in lines:
            try:
                d = json.loads(l)
            except Exception:
                continue
            if isinstance(d, dict):
                recs.append((str(d.get("utc") or d.get("ts") or ""), d))
        recs.sort(key=lambda x: x[0])
        times = [t for t, _ in recs if t]
        if times and times[0] >= BLOCK_SINCE:
            return times[0]
        blocked = next((t for t, d in recs if d.get("event") == "stopped_on_block" and t >= BLOCK_SINCE), None)
        if blocked is None:
            return None
        before = {d.get("exit_ip") for t, d in recs if d.get("event") == "exit_ip" and t < blocked}
        return next((t for t, d in recs if d.get("event") == "exit_ip" and t >= blocked and d.get("exit_ip") not in before), None)

    def _strip_person(l):
        """05:5xZ Nov 10: match rotation evidence only in VM fields, never in a person's handle/url (a handle such as
        '...keeper...' flagged 5 clean VMs: 8, 11, 24, 36, 56)."""
        try:
            d = json.loads(l)
        except Exception:
            return l
        if not isinstance(d, dict):
            return l
        for k in ("handle", "h", "user", "username", "name", "url", "profile_url"):
            d.pop(k, None)
        return json.dumps(d)


    c, reasons, builds, vms = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    rows, merge, replace, requeue = [], [], [], []
    for n in todo:
        d = json.load(open(f"{D}/people_live/vm/{n}.json"))
        md5 = (d.get("run") or {}).get("pkg_md5")
        m = re.search(r"\((feeder-[^)]+)\)", str(d.get("method", "")))
        vm = m.group(1) if m else "unknown"
        builds[md5 or "none"] += 1
        vms[vm] += 1
        ok, why = g["person_complete"](d, g["handle_of"](d, f"{n}.json"))
        gate = []
        if md5 not in AUDITED_BUILDS:
            gate.append("build_not_audited")
        if vm == "unknown" or not clean(vm)[0]:
            gate.append("vm_evasion_or_unknown")
        elif clean(vm)[1] and st[n] >= clean(vm)[1]:
            gate.append("vm_after_block_new_vm_or_ip")
        vm_only = bool(gate) and all(x.startswith("vm_") for x in gate)
        if ok and vm_only and MERGE_VM_HELD and vm != "unknown":
            # 23:1xZ Nov 12 (Shreyas via orchestrator): a whole person held only by the VM/IP gate is good data; merge it
            # with a provenance flag so these saves stay distinguishable. The gate still governs fleet behaviour.
            prov[n] = {"vm": vm, "exit_ip_at_save": ip_at(vm, st[n]), "gate_reasons": gate,
                       "saved_after_post_block_ip_change": "vm_after_block_new_vm_or_ip" in gate,
                       "vm_rotation_evidence": "vm_evasion_or_unknown" in gate, "merged_by": f"cursor_audit {stamp} --merge-vm-held"}
            gate = []
        if ok and not gate:
            if n in vm_t and not (n.lower() in rerun and st[n] > vm_t[n]):
                res = "already_in_vm"
            else:
                res = "replace" if n in vm_t else "merge"
                (replace if n in vm_t else merge).append(n)
        elif ok:
            res = "held_gate"  # whole but not mergeable yet: not re-pulled, re-audited once the gate clears
        else:
            res = "fail"
            if not all(FOLLOW_ONLY.match(w) for w in why):
                requeue.append((n, why))
        c[res] += 1
        for w in why + gate:
            reasons[w] += 1
        rows.append(f"{n}\t{st[n]}\t{res}\t{md5}\t{vm}\t{','.join(why + gate)}\n")
    if prov:
        print(f"VM_HELD_FLAGGED={sum(1 for n in merge + replace if n in prov)} post_block_ip={sum(1 for n in merge + replace if n in prov and prov[n]['saved_after_post_block_ip_change'])} "
              f"rotation={sum(1 for n in merge + replace if n in prov and prov[n]['vm_rotation_evidence'])} exit_ip_known={sum(1 for n in merge + replace if n in prov and prov[n]['exit_ip_at_save'])}")
    print(f"AUDIT {stamp}: {dict(c)} builds={dict(builds)} vms={len(vms)} reasons={dict(reasons.most_common(8))}")
    if dry:
        return
    # 01:5xZ Nov 13: write the decision list first, so an interrupted run leaves a record of what it was merging, then copy
    # in parallel (one gsutil per file ran ~1 file/s: 18.6k people would take ~5 h)
    open(f"{W}/audit.tsv", "w").write("# name\tstaged_utc\tresult\tpkg_md5\tvm\treasons\n" + "".join(rows))
    sh("gsutil", "-q", "cp", f"{W}/audit.tsv", f"{CUR}/audit_{stamp}.tsv")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(24) as ex:  # backups need a rename per file
        list(ex.map(lambda n: sh("gsutil", "-q", "cp", f"{VM}/{n}.json", f"{VM}/{n}.json.bak_cursor"), replace))
    for n in merge + replace:
        if n in prov:  # provenance flag written into the audited local copy before it is merged
            f = f"{D}/people_live/vm/{n}.json"
            d = json.load(open(f))
            d["provenance"] = prov[n]
            json.dump(d, open(f, "w"))
    # 07:5xZ Nov 10: merge the exact file audited (local copy), never the live staged object, which the fleet may have
    # overwritten since the download (an unaudited incomplete save reached vm/ that way at 06:42Z). Batches of 200, same names.
    todo_cp = [f"{D}/people_live/vm/{n}.json" for n in merge + replace]
    batches = [todo_cp[i:i + 200] for i in range(0, len(todo_cp), 200)]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda b: sh("gsutil", "-q", "-m", "cp", *b, f"{VM}/"), batches))
    if merge + replace:
        old = sh("gsutil", "cat", f"{R}/_pacetest/merged_ledger.txt").stdout
        open(f"{W}/ledger.txt", "w").write(old + f"# cursor {stamp}\n" + "".join(x + "\n" for x in merge + replace))
        sh("gsutil", "-q", "cp", f"{W}/ledger.txt", f"{R}/_pacetest/merged_ledger.txt")
    old = sh("gsutil", "cat", f"{CUR}/audited.tsv").stdout
    open(f"{W}/audited.tsv", "w").write(old + "".join(f"{n}@{st[n]}\t{stamp}\n" for n in todo))
    sh("gsutil", "-q", "cp", f"{W}/audited.tsv", f"{CUR}/audited.tsv")
    if requeue:
        oldq = sh("gsutil", "cat", f"{CUR}/requeue.txt").stdout
        open(f"{W}/requeue.txt", "w").write(oldq + "".join(f"{n}\t{','.join(w)}\n" for n, w in requeue))
        sh("gsutil", "-q", "cp", f"{W}/requeue.txt", f"{CUR}/requeue.txt")
    md = [f"# Audit {stamp} (population agent)", "",
          f"Staged since last audit: {len(todo)}. Merged: {len(merge)}. Replaced: {len(replace)}. "
          f"Whole but held by a gate: {c['held_gate']}. Failed: {c['fail']} (re-queued {len(requeue)}; "
          f"follow-list-only fails held for the offset re-page). Already in the store: {c['already_in_vm']}.", "",
          "Reasons (people can have more than one): " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()), "",
          "Builds (run.pkg_md5): " + ", ".join(f"{k} {v}" for k, v in builds.items()), "",
          f"VMs: {len(vms)}. Per-handle reasons, build and VM: `raw/_cursor/audit_{stamp}.tsv` "
          "(handles stay under raw/).", "",
          "Gates: only `full18d` (md5 T3OI+xr3iAvoMDMZrdryhA==) and `full18f` (md5 uYYdW17hoPBJjpMGoR7lKw==) saves are mergeable, "
          "and every person must pass the whole-person check (full header or PH's own end on every list). Saves from any VM whose status logs show IP/port rotation, VM recreation or a byte-stop bypass "
          "are never merged, nor saves from VMs created during/after a PH block or whose exit IP changed after a block."]
    open(f"{W}/audit.md", "w").write("\n".join(md) + "\n")
    sh("gsutil", "-q", "cp", f"{W}/audit.md", f"{G}/mailbox/to_cursor/audit_{stamp}.md")
    print(f"wrote mailbox/to_cursor/audit_{stamp}.md and raw/_cursor/audit_{stamp}.tsv")


if __name__ == "__main__":
    main()
