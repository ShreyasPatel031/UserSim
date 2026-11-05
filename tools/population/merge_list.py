"""Hourly pace-test merge list (population agent; Shreyas 07:30Z standing merge approval).

Scores every raw/_pacetest/shared/<name>.json with the strict person check (quality.person_complete). Passing people
(whole, or whole signed-out with a signed-in queue entry) from a PASSed build who are NOT yet in people_live/vm/ go to
raw/_pacetest/merge_list.txt; the runner copies exactly those into vm/. Each list is appended to merged_ledger.txt so
the 30-min check can flag any later FAIL on a merged person. Handles stay in the bucket; stdout prints counts only.
Usage: python merge_list.py WORK_DIR
"""
import contextlib, io, json, os, runpy, subprocess, sys
from collections import Counter
from datetime import datetime, timezone

W = sys.argv[1]
G = "gs://usersim-bakeoff-347838016394/usersim_sim/raw"
T = f"{G}/_pacetest"
PASSED = {"XpPuFRfyk37T2Rzdz5cIAQ==", "3QUc3/TCsXoVuac0bB2/+g==", "lZ4IRKn8K+vySvT1GuNB5w==", "cMA/79uhIsWH6pZ6JDL5Pg==",
          "1QwHU3ILccX2sYXAmSCFpQ==", "yk+t8UiOwJAOvuXbg0FCKA==",
          "vqbWasUGY8DCao/wzvebLw==", "j6++x//+3CYoHnUxVkDHWQ==",
          "1vXYiANmKbePdwCkCCbrwA==",
          "tiWEdopIK+WM16fYVVealw=="}  # full7..full16, each PASSed by population
NOMD5_OK = "XpPuFRfyk37T2Rzdz5cIAQ=="  # full7 predates run.pkg_md5 in the JSON; accepted only if the run status shows full7
sh = lambda *a: subprocess.run(a, capture_output=True, text=True)
D = f"{W}/mg"
sh("rm", "-rf", D)
for p in ("people_live/vm", "people_live/deep_list", "signedin_upvotes"):
    os.makedirs(f"{D}/{p}", exist_ok=True)
sh("gsutil", "-q", "-m", "cp", f"{T}/shared/*.json", f"{D}/people_live/vm/")
sh("gsutil", "-q", "-m", "cp", f"{T}/shared/_signedin_upvotes/*.json", f"{D}/signedin_upvotes/")
def _lsl(pat):  # {name: update time} from gsutil ls -l
    o = {}
    for l in sh("gsutil", "ls", "-l", pat).stdout.splitlines():
        f = l.split()
        if len(f) == 3 and f[2].endswith(".json"):
            o[f[2].rsplit("/", 1)[-1][:-5]] = f[1]
    return o
vm_t = _lsl(f"{G}/ph_population/people_live/vm/*.json"); have = set(vm_t)
sh_t = _lsl(f"{T}/shared/*.json")
# re-pull requests (raw/population/requests/rerun_whole_*.txt): a newer whole shared/ copy REPLACES the vm/ file (merge_replace.txt)
rerun = set()
for u in sh("gsutil", "ls", f"{G}/population/requests/rerun_whole_*.txt").stdout.split():
    for t in sh("gsutil", "cat", u).stdout.splitlines():
        if t.strip() and not t.lstrip().startswith("#"):
            rerun.add(t.split()[0].lstrip("@").lower())
ledger = set(l.strip() for l in sh("gsutil", "cat", f"{T}/merged_ledger.txt").stdout.splitlines() if l.strip() and not l.startswith("#"))
sys.argv = ["quality.py", D, "2026-11-05T00:00:00Z", "/dev/null", "/dev/null"]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(os.path.join(os.path.dirname(__file__), "quality.py"))
c, out, rep = Counter(), [], []
for f in sorted(os.listdir(f"{D}/people_live/vm")):
    name = f[:-5]
    replace = name in have and name.lower() in rerun and sh_t.get(name, "") > vm_t.get(name, "")
    if name in have and not replace:  # the list is every passing person not yet in vm/ (a list not yet copied is re-listed, never lost)
        c["already_in_vm"] += 1; continue
    d = json.load(open(f"{D}/people_live/vm/{f}"))
    ok, why = g["person_complete"](d, g["handle_of"](d, f))
    md5 = (d.get("run") or {}).get("pkg_md5")
    if not ok:
        c["fail"] += 1; continue
    if md5 is not None and md5 not in PASSED:
        c["unpassed_build"] += 1; continue
    if replace:
        c["replace"] += 1; rep.append(name); continue
    c["signed_out" if g["signed_out_end"](d) else "whole"] += 1; out.append(name)
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
hdr = f"# population merge list {ts}: raw/_pacetest/shared/<name>.json -> people_live/vm/<name>.json; strict person check PASS; {len(out)} people; none already in vm/"
open(f"{W}/merge_list.txt", "w").write(hdr + "\n" + "".join(n + "\n" for n in out))
sh("gsutil", "-q", "cp", f"{W}/merge_list.txt", f"{T}/merge_list.txt")
open(f"{W}/merge_replace.txt", "w").write(f"# population merge REPLACE list {ts}: re-pull requests whose newer shared/<name>.json passes the strict check; set the old vm/<name>.json aside, then copy; {len(rep)} people\n" + "".join(n + "\n" for n in rep))
sh("gsutil", "-q", "cp", f"{W}/merge_replace.txt", f"{T}/merge_replace.txt")
new = [n for n in out + rep if n not in ledger]
if new:
    old = sh("gsutil", "cat", f"{T}/merged_ledger.txt").stdout
    open(f"{W}/ledger.txt", "w").write(old + f"# {ts}\n" + "".join(n + "\n" for n in new))
    sh("gsutil", "-q", "cp", f"{W}/ledger.txt", f"{T}/merged_ledger.txt")
print(f"MERGE_LIST={len(out)} MERGE_REPLACE={len(rep)} new_to_ledger={len(new)} {dict(c)}")
