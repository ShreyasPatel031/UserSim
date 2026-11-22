"""Hourly audit of Cursor staging (raw/_pacetest/shared/). Bucket only; prints counts only.

Usage: cursor_audit.py WORK [--dry-run]

For each staged <name>.json written after START and not yet in raw/_cursor/audited.tsv:
  1. strict whole-person check (quality.person_complete; short Upvotes are incomplete since Nov 17, no signed-in pass)
  2. build gate: run.pkg_md5 must be in AUDITED_BUILDS (full18d is added only after its first-run audit passes)
  3. VM gate: the producing VM's status logs must show no IP/port rotation, recreate or byte-stop bypass events
Pass -> copied into people_live/vm/ (an existing vm/ file is replaced only for a rerun_whole request with a newer
         staged copy; the old one is set aside as .bak_cursor) and appended to raw/_pacetest/merged_ledger.txt.
Fail -> raw/_cursor/requeue.txt (back on the queue) unless it is a follow-list-only fail (held for the offset re-page).
Per-handle reasons go only to raw/_cursor/audit_<stamp>.tsv. mailbox/to_cursor/audit_<stamp>.md gets counts only.
"""
import collections, contextlib, glob, io, json, os, re, runpy, subprocess, sys, time

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
REFRESH_FIX_STAMP = "20261120T2245Z"  # audits from here on merge newer upvote refreshes (see the already_in_vm rule)
REFRESH_FIX2_STAMP = "20261121T1850Z"  # audits from here on compare refreshes to the store copy's read time, not write time
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
    rr = sys.argv[sys.argv.index("--reaudit-fail-reason") + 1] if "--reaudit-fail-reason" in sys.argv else None
    if "--reaudit-held" in sys.argv or "--reaudit-already-incomplete" in sys.argv or "--reaudit-already-refresh" in sys.argv or rr:
        # --reaudit-held: re-score people whose latest audit result was held_gate (whole, blocked only by a gate)
        last, last_why, last_stamp = {}, {}, {}
        # 04:5xZ Nov 13: one bulk copy, not one gsutil cat per audit file (105 files)
        AC = f"{W}/cursor_audit_cache/audits"
        os.makedirs(AC, exist_ok=True)
        sh("gcloud", "storage", "rsync", f"{CUR}/", f"{AC}/", "--exclude", r"^(?!audit_.*\.tsv$).*")
        for u in sorted(glob.glob(f"{AC}/audit_*.tsv")):
            for l in [x for x in open(u).read().splitlines() if x.strip() and not x.startswith("#")]:
                f = l.split("\t")
                if len(f) >= 3:
                    last[f"{f[0]}@{f[1]}"] = f[2]
                    last_why[f"{f[0]}@{f[1]}"] = f[5] if len(f) > 5 else ""
                    last_stamp[f"{f[0]}@{f[1]}"] = os.path.basename(u)[6:-4]
        if rr:  # 19:1xZ Nov 17 (Shreyas rule change): re-score fails whose ONLY gate reason was a reverted rule
            again_ = set()
            for k, v in last.items():
                ws = [w for w in re.split(r"[;, |]+", last_why.get(k, "")) if w and not w.startswith("vm_")]
                if v == "fail" and ws and all(w in rr.split(",") for w in ws):  # rr: comma-separated reasons
                    again_.add(k)
            print(f"REAUDIT_FAIL_REASON={len(again_)} ({rr})")
            done -= again_
        if "--reaudit-held" in sys.argv:
            held = {k for k, v in last.items() if v == "held_gate"}
            print(f"REAUDIT_HELD={len(held)}")
            done -= held
        if "--reaudit-already-incomplete" in sys.argv:  # whole saves skipped as already_in_vm while the store copy was incomplete
            cf_ = sorted(glob.glob(f"{W}/quality_*_complete.txt"))
            comp_ = {l.split("\t")[0].strip().lower() for l in open(cf_[-1]) if l.strip()}
            again = {k for k, v in last.items() if v == "already_in_vm" and k.rsplit("@", 1)[0].lower() not in comp_}
            print(f"REAUDIT_ALREADY_INCOMPLETE={len(again)}")
            done -= again
        if "--reaudit-already-refresh" in sys.argv:
            # 22:4xZ Nov 20: one-time backfill. Upvote refreshes of complete people were scored already_in_vm and never
            # merged (the refresh keeps the old run.finished_utc; the new read is upvotes_refreshed_at). Re-score every
            # already_in_vm row audited before the fix; once re-scored its newest stamp is past the fix and it drops out.
            # staged since Nov 18 only: older already_in_vm rows predate the refresh overlay (sampled: no
            # upvotes_refreshed_at) and re-scoring them oldest-first would starve new saves under the per-run cap
            # 18:3xZ Nov 21: widened to rows audited before REFRESH_FIX2_STAMP: between the two fixes a refresh read
            # before the store's last write (but after the store copy's own read) was still scored already_in_vm.
            again = {k for k, v in last.items() if v == "already_in_vm" and last_stamp.get(k, "") < REFRESH_FIX2_STAMP
                     and k.rsplit("@", 1)[-1] >= "2026-11-18"}
            print(f"REAUDIT_ALREADY_REFRESH={len(again)}")
            done -= again
    st = lsl(f"{STAGE}/*.json")
    todo = sorted(n for n, t in st.items() if t >= START and f"{n}@{t}" not in done)
    if os.environ.get("CURSOR_AUDIT_ONLY"):
        # 20:0xZ Nov 21: one-off re-score of a named list (e.g. already_in_vm saves read after the store copy),
        # run between scheduled cycles so the backlog does not take the per-run cap from new saves
        only = {l.strip() for l in open(os.environ["CURSOR_AUDIT_ONLY"]) if l.strip()}
        todo = sorted(n for n in only if n in st and st[n] >= START)
        print(f"AUDIT_ONLY={len(todo)} of {len(only)}", flush=True)
    print(f"STAGED_NEW={len(todo)}")
    # 07:5xZ Nov 15: cap one run's batch (oldest saves first) so the cycle finishes inside its time limit at 18 VMs; the
    # rest stay un-audited and are taken by the next run (nothing is dropped)
    cap = int(os.environ.get("CURSOR_AUDIT_MAX", "0") or 0)
    if cap and len(todo) > cap:
        todo = sorted(todo, key=lambda n: st[n])[:cap]
        print(f"CAPPED to {cap} oldest; the rest go to the next run", flush=True)
    if not todo:
        return
    D = f"{W}/cursor_audit"
    # 02:2xZ Nov 13: keep downloaded saves between runs (manifest name -> staged time), so a run cut off by a machine restart
    # resumes instead of re-downloading ~19k files; a save re-staged since (new time) is fetched again
    man_f = f"{D}/manifest.tsv"
    man = dict(l.rstrip("\n").split("\t", 1) for l in open(man_f)) if os.path.exists(man_f) else {}
    for p in ("people_live/vm", "people_live/deep_list", "signedin_upvotes"):
        os.makedirs(f"{D}/{p}", exist_ok=True)
    keep = set(todo)
    for fn in os.listdir(f"{D}/people_live/vm"):  # only this run's people are scored (quality.py reads the whole dir)
        if fn.endswith(".json") and fn[:-5] not in keep:
            os.remove(f"{D}/people_live/vm/{fn}")
    need = [n for n in todo if man.get(n) != st[n] or not os.path.exists(f"{D}/people_live/vm/{n}.json")]
    print(f"DOWNLOAD need={len(need)} cached={len(todo) - len(need)}", flush=True)
    import threading
    from concurrent.futures import ThreadPoolExecutor as _TPE
    lock = threading.Lock()

    def _dl(b):  # gcloud storage, 4 batches of 500 at once; the manifest is saved after each batch (restarts lose <=2k files)
        subprocess.run(["gcloud", "storage", "cp", "-I", f"{D}/people_live/vm/"], input="".join(f"{STAGE}/{n}.json\n" for n in b),
                       capture_output=True, text=True)
        with lock:
            for n in b:
                if os.path.exists(f"{D}/people_live/vm/{n}.json"):
                    man[n] = st[n]
            open(man_f + ".tmp", "w").write("".join(f"{k}\t{v}\n" for k, v in man.items() if k in keep))
            os.replace(man_f + ".tmp", man_f)
    with _TPE(4) as ex:
        list(ex.map(_dl, [need[i:i + 500] for i in range(0, len(need), 500)]))
    # 04:1xZ Nov 13: incremental sync (11.9k files; gsutil -m cp re-copied all of them, ~15 min, on every run)
    sh("gcloud", "storage", "rsync", f"{STAGE}/_signedin_upvotes/", f"{D}/signedin_upvotes/")
    sys.argv = ["quality.py", D, "2026-11-05T00:00:00Z", "/dev/null", "/dev/null"]
    with contextlib.redirect_stdout(io.StringIO()):
        g = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "quality.py"))
    vm_t = lsl(f"{VM}/*.json")

    def store_read_t(n, fallback):
        for f in (f"{W}/cursor_audit_cache/store_current/{n}.json", f"{W}/raw/people_live/vm/{n}.json"):
            try:
                sd = json.load(open(f))
            except Exception:
                continue
            return max(str(sd.get("upvotes_refreshed_at") or ""), str((sd.get("run") or {}).get("finished_utc") or ""))
        return fallback
    rerun = set()
    for u in sh("gsutil", "ls", f"{R}/population/requests/rerun_whole_*.txt").stdout.split():
        rerun |= {l.split()[0].lstrip("@").lower() for l in lines(u)}
    # 17:3xZ Nov 16: a whole save of a person whose store record is NOT complete always replaces it (lossless union).
    # Before, only rerun_whole lists could replace, so completion-queue pulls that came back whole were marked
    # already_in_vm and never merged (169 at 17:22Z). Store completeness = the newest quality_*_complete.txt.
    cf = sorted(glob.glob(f"{W}/quality_*_complete.txt"))
    store_complete = {l.split("\t")[0].strip().lower() for l in open(cf[-1]) if l.strip()} if cf else None
    print(f"STORE_COMPLETE_SET={len(store_complete) if store_complete is not None else 'missing'}", flush=True)
    vm_clean = {}
    SC = f"{W}/cursor_audit_cache/status"  # 04:5xZ Nov 13: one incremental sync of all status logs (277 files, ~185 MB)
    for sub, src in (("stage", f"{STAGE}/status/"), ("vm", f"{R}/ph_population/people_live/vm/status/")):
        os.makedirs(f"{SC}/{sub}", exist_ok=True)
        sh("gcloud", "storage", "rsync", src, f"{SC}/{sub}/")
    print("STATUS_SYNCED", time.strftime("%H:%M:%SZ", time.gmtime()), flush=True)

    def clean(vm):
        if vm not in vm_clean:
            # 20:1xZ Nov 12: "{vm}.*", not "{vm}*": the bare glob also read VMs -10..-19 for VM -1 (-40..-49 for -4, ...),
            # so a VM was judged on other VMs' rotation/block events. Logs are {vm}.jsonl and {vm}.supervisor.jsonl.
            logs = sorted(glob.glob(f"{SC}/stage/{vm}.*") + glob.glob(f"{SC}/vm/{vm}.*"))  # local status mirror, synced once per run
            txt = "".join(open(u, errors="replace").read() for u in logs)
            lines = txt.splitlines()
            vm_clean[vm] = (not any(EVASION.search(_strip_person(l)) for l in lines), _block_evasion(lines))
            vm_ips[vm] = sorted((str(d.get("utc") or ""), d.get("exit_ip")) for d in map(_js, lines)
                                if isinstance(d, dict) and d.get("event") == "exit_ip" and d.get("exit_ip"))
            vm_blocks[vm] = sorted(str(d.get("utc") or d.get("ts") or "") for d in map(_js, lines)
                                   if isinstance(d, dict) and d.get("event") == "stopped_on_block")
        return vm_clean[vm]

    vm_ips = {}
    vm_blocks = {}
    vm_rot = collections.defaultdict(list)
    for l in sh("gsutil", "cat", f"{CUR}/iproyal_rotate/rotate.jsonl").stdout.splitlines():
        try:
            x = json.loads(l)
            vm_rot[x["vm"]].append((str(x["utc"]), str(x.get("reason"))))
        except Exception:
            continue
    print(f"ROTATE_LOG rotations={sum(len(v) for v in vm_rot.values())} vms={len(vm_rot)}", flush=True)

    def post_block_ip_change_60m(vm, t, ip_override=None):
        """orchestrator 19:50Z Nov 20: save-local test, kept apart from the history-wide flags. True when the same VM logged
        a stopped_on_block within 60 min before the save (staged time) AND its exit IP at the save differs from its exit IP
        just before that block. None when the VM is unknown or the IPs are not logged; False otherwise."""
        if vm == "unknown" or not t:
            return None
        clean(vm)
        import datetime
        try:
            t0 = (datetime.datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S") - datetime.timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
        # 00:0xZ Nov 21 (orchestrator): proxy-side rotations are not in the VM status logs; a block-triggered rotation
        # in raw/_cursor/iproyal_rotate/rotate.jsonl within the window is a post-block IP change by itself
        if any(t0 <= u <= t and r in ("sustained_block", "vm_block_request") for u, r in vm_rot.get(vm, [])):
            return True
        near = [b for b in vm_blocks.get(vm, []) if t0 <= b <= t]
        if not near:
            return False
        before = [ip for u, ip in vm_ips.get(vm, []) if u < near[-1]]
        at = ip_override or ip_at(vm, t)
        if not before or not at:
            return None
        return at != before[-1]

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
    pb60_c, pb60_vms, reupload_c, pb60_recent = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    refresh_c = collections.Counter()
    def store_doc(n):
        for f in (f"{W}/cursor_audit_cache/store_current/{n}.json", f"{W}/raw/people_live/vm/{n}.json"):
            try:
                return json.load(open(f))
            except Exception:
                continue
        return None

    def overlay_to_held(n, d):
        """02:3xZ Nov 22: the fleet's patch_repull_upvotes_to_held (slots 9/27, ~01:15Z) re-reads upvotes only down to the
        first upvote the store already holds (paging.ended=first_held_upvote, usually 1 item), so every refresh failed
        upvotes:FAIL_short (96 at 01:51Z, 192 at 02:21Z). Rebuild the full list: the refresh's items on top (their
        votes/comments are newer), then every store item not re-read. The list end is the store read's PH end. Only when
        the refresh actually reached a held item and the store read ended at a PH end; otherwise left as is."""
        u = d.get("upvotes")
        if not isinstance(u, dict) or not u.get("refresh_to_held"):
            return False
        sd = store_doc(n)
        su = (sd or {}).get("upvotes")
        if not isinstance(su, dict):
            return False
        # 07:0xZ Nov 22: older store records carry no paging.ended (11 of 16 FAIL_short at 06:51Z); a store copy that the
        # newest quality run counts complete reached PH's end by the quality rules, so it is a valid base too
        at_end = str((su.get("paging") or {}).get("ended")) in g.get("SERVER_END", set())
        if not at_end and not (store_complete is not None and n.lower() in store_complete):
            return False
        key = lambda i: str(i.get("post_id") or i.get("url") or "")
        new_items = list(u.get("items") or [])
        new_keys = {key(i) for i in new_items}
        held = {key(i) for i in su.get("items") or []}
        if not new_keys & held:
            return False  # never reached a held item: not a to-held read
        items = new_items + [i for i in su.get("items") or [] if key(i) not in new_keys]
        u["refresh_read"] = {"paging": u.get("paging"), "count": u.get("count"), "status": u.get("status")}
        u["items"], u["count"] = items, len(items)
        u["paging"] = dict(su.get("paging") or {}, refreshed_to_held=True)
        u["ph_list_end"] = (su.get("paging") or {}).get("ended")
        u.pop("status", None)
        if su.get("status"):
            u["status"] = su["status"]
        for k in ("upvotes_capped", "cap", "complete_not_visible", "limit_owner"):
            if k in su and k not in u:
                u[k] = su[k]
        json.dump(d, open(f"{D}/people_live/vm/{n}.json", "w"))
        return True

    for n in todo:
        d = json.load(open(f"{D}/people_live/vm/{n}.json"))
        if overlay_to_held(n, d):
            refresh_c["overlay_to_held"] += 1
        md5 = (d.get("run") or {}).get("pkg_md5")
        m = re.search(r"\((feeder-[^)]+)\)", str(d.get("method", "")))
        vm = m.group(1) if m else "unknown"
        # 00:0xZ Nov 22: an upvote refresh of a person first pulled by an unowned writer keeps that writer's method string
        # (no VM), so the VM gate saw "unknown" and held it (13 slot27 refreshes at 23:51Z). The refreshing fleet VM
        # (upvotes_refreshed_by) wrote this save; judge that VM. The rest of the record is already in the store.
        if vm == "unknown" and str(d.get("upvotes_refreshed_by") or "").startswith("feeder-fleet"):
            vm = str(d["upvotes_refreshed_by"])
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
        # 21:3xZ Nov 20: test the pull's own finish time; the staged time is the upload time, and re-uploaded old saves
        # (128 at 21:21Z, finished Nov 8-17) would otherwise be tested against today's logs
        fin = str((d.get("run") or {}).get("finished_utc") or "")
        # 22:4xZ Nov 20 (orchestrator, fleet RCA): a refresh save keeps the old finished_utc; its read time (and the IP
        # it used) is upvotes_refreshed_at
        fin = max(fin, str(d.get("upvotes_refreshed_at") or ""))
        if d.get("upvotes_refreshed_at"):
            refresh_c["fresh24h" if fin >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400)) else "older"] += 1
            ia = (((d.get("upvotes") or {}).get("refresh") or {}).get("delta") or {}).get("items_added")
            refresh_c["items_added>0" if (ia or 0) > 0 else "items_added=0"] += 1
        # 01:3xZ Nov 21: refresh saves now name the refreshing VM and its exit IP (fleet 58fb544c); test that VM, not
        # the original pull's VM label the overlay keeps
        tvm = str(d.get("upvotes_refreshed_by") or "") or vm
        pb60 = post_block_ip_change_60m(tvm, fin or st[n], d.get("upvotes_refreshed_exit_ip"))
        if fin and fin[:10] < st[n][:10]:
            reupload_c[vm] += 1
        pb60_c[str(pb60)] += 1
        if pb60:
            pb60_vms[tvm] += 1
            # orchestrator 22:00Z Nov 20: alert only when the pull itself finished within the last 24 h
            if (fin or st[n]) >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400)):
                pb60_recent[tvm] += 1
        vm_only = bool(gate) and all(x.startswith("vm_") for x in gate)
        if ok and vm_only and MERGE_VM_HELD and vm != "unknown":
            # 23:1xZ Nov 12 (Shreyas via orchestrator): a whole person held only by the VM/IP gate is good data; merge it
            # with a provenance flag so these saves stay distinguishable. The gate still governs fleet behaviour.
            prov[n] = {"vm": vm, "exit_ip_at_save": ip_at(vm, st[n]), "gate_reasons": gate,
                       "saved_after_post_block_ip_change": "vm_after_block_new_vm_or_ip" in gate,
                       "vm_rotation_evidence": "vm_evasion_or_unknown" in gate, "post_block_ip_change_60m": pb60,
                       "merged_by": f"cursor_audit {stamp} --merge-vm-held"}
            gate = []
        if ok and not gate:
            stored_incomplete = store_complete is not None and n.lower() not in store_complete
            # 22:4xZ Nov 20: an upvote refresh read after the store copy was written is new data, not a duplicate:
            # merge it (the union is lossless). The refresh overlay keeps the old run.finished_utc, so test
            # upvotes_refreshed_at against the store object's write time.
            # 18:3xZ Nov 21: the store write time is the wrong reference. The :50 merge writes the store minutes
            # after the refresh was read, so a second refresh read in between (e.g. read 17:53, store written 17:58
            # from a 17:40 refresh) was judged older and dropped as already_in_vm (7 at 18:21Z). Compare against
            # the store copy's own read time (max of upvotes_refreshed_at and run.finished_utc) from the local
            # mirror; fall back to the write time only when no local copy can be read.
            # 18:4xZ Nov 21: any newer READ, not only an upvote refresh: a whole re-pull of a complete person read after
            # the store copy carries newer data too (18 Nov 18 re-pulls were still already_in_vm at 18:31Z). The union
            # is lossless (older items go to items_earlier), so merging a newer read never loses anything.
            rt = max(str(d.get("upvotes_refreshed_at") or ""), str((d.get("run") or {}).get("finished_utc") or ""))
            newer_refresh = bool(rt) and n in vm_t and rt > store_read_t(n, vm_t[n])
            if n in vm_t and not stored_incomplete and not newer_refresh and not (n.lower() in rerun and st[n] > vm_t[n]):
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
    print(f"POST_BLOCK_IP_CHANGE_60M {stamp}: true={pb60_c['True']} false={pb60_c['False']} unknown={pb60_c['None']} "
          f"vms={','.join(f'{v}:{k}' for v, k in sorted(pb60_vms.items()))}", flush=True)
    print(f"POST_BLOCK_IP_CHANGE_60M_RECENT24H {stamp}: true={sum(pb60_recent.values())} "
          f"vms={','.join(f'{v}:{k}' for v, k in sorted(pb60_recent.items()))}", flush=True)
    print(f"UPVOTE_REFRESHES {stamp}: fresh24h={refresh_c['fresh24h']} older={refresh_c['older']} "
          f"items_added>0={refresh_c['items_added>0']} items_added=0={refresh_c['items_added=0']} "
          f"overlay_to_held={refresh_c['overlay_to_held']}", flush=True)
    print(f"REUPLOADED_OLD_SAVES {stamp}: {sum(reupload_c.values())} of {len(todo)} (pull finished on an earlier day than staged) "
          f"vms={len(reupload_c)}", flush=True)
    print(f"AUDIT {stamp}: {dict(c)} builds={dict(builds)} vms={len(vms)} reasons={dict(reasons.most_common(8))}")
    if dry:
        return
    # 01:5xZ Nov 13: write the decision list first, so an interrupted run leaves a record of what it was merging, then copy
    # in parallel (one gsutil per file ran ~1 file/s: 18.6k people would take ~5 h)
    open(f"{W}/audit.tsv", "w").write("# name\tstaged_utc\tresult\tpkg_md5\tvm\treasons\n" + "".join(rows))
    sh("gsutil", "-q", "cp", f"{W}/audit.tsv", f"{CUR}/audit_{stamp}.tsv")
    from concurrent.futures import ThreadPoolExecutor
    # 12:1xZ Nov 13: backups go to vm/_bak_cursor/<stamp>/<n>.json in one bulk server-side copy (a rename per file ran
    # ~3 files/s; with hundreds of re-pulls per hour the backup step outlived the run)
    if replace:
        subprocess.run(["gcloud", "storage", "cp", "-I", f"{VM}/_bak_cursor/{stamp}/"], input="".join(f"{VM}/{n}.json\n" for n in replace),
                       capture_output=True, text=True)
    for n in merge + replace:
        if n in prov:  # provenance flag written into the audited local copy before it is merged
            f = f"{D}/people_live/vm/{n}.json"
            d = json.load(open(f))
            d["provenance"] = prov[n]
            json.dump(d, open(f, "w"))
    # 12:3xZ Nov 13: lossless merge: union each audited copy with the person's current store record before upload
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import union_merge
    if merge + replace:
        print(f"UNION {union_merge.union_with_store(f'{D}/people_live/vm', VM, merge + replace, f'{W}/cursor_audit_cache/store_current')}", flush=True)
    # 07:5xZ Nov 10: merge the exact file audited (local copy), never the live staged object, which the fleet may have
    # overwritten since the download (an unaudited incomplete save reached vm/ that way at 06:42Z). Batches of 200, same names.
    todo_cp = [f"{D}/people_live/vm/{n}.json" for n in merge + replace]
    for i in range(0, len(todo_cp), 2000):
        subprocess.run(["gcloud", "storage", "cp", "-I", f"{VM}/"], input="".join(f + "\n" for f in todo_cp[i:i + 2000]),
                       capture_output=True, text=True)
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
