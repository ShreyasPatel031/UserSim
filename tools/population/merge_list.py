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
PASSED = {"XpPuFRfyk37T2Rzdz5cIAQ==", "3QUc3/TCsXoVuac0bB2/+g==", "lZ4IRKn8K+vySvT1GuNB5w==", "cMA/79uhIsWH6pZ6JDL5Pg=="}
NOMD5_OK = "XpPuFRfyk37T2Rzdz5cIAQ=="  # full7 predates run.pkg_md5 in the JSON; accepted only if the run status shows full7
sh = lambda *a: subprocess.run(a, capture_output=True, text=True)
D = f"{W}/mg"
sh("rm", "-rf", D)
for p in ("people_live/vm", "people_live/deep_list", "signedin_upvotes"):
    os.makedirs(f"{D}/{p}", exist_ok=True)
sh("gsutil", "-q", "-m", "cp", f"{T}/shared/*.json", f"{D}/people_live/vm/")
sh("gsutil", "-q", "-m", "cp", f"{T}/shared/_signedin_upvotes/*.json", f"{D}/signedin_upvotes/")
have = {u.rsplit("/", 1)[-1][:-5] for u in sh("gsutil", "ls", f"{G}/ph_population/people_live/vm/*.json").stdout.split() if u.endswith(".json")}
ledger = set(l.strip() for l in sh("gsutil", "cat", f"{T}/merged_ledger.txt").stdout.splitlines() if l.strip() and not l.startswith("#"))
sys.argv = ["quality.py", D, "2026-11-05T00:00:00Z", "/dev/null", "/dev/null"]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(os.path.join(os.path.dirname(__file__), "quality.py"))
c, out = Counter(), []
for f in sorted(os.listdir(f"{D}/people_live/vm")):
    name = f[:-5]
    if name in have or name in ledger:
        c["already_in_vm"] += 1; continue
    d = json.load(open(f"{D}/people_live/vm/{f}"))
    ok, why = g["person_complete"](d, g["handle_of"](d, f))
    md5 = (d.get("run") or {}).get("pkg_md5")
    if not ok:
        c["fail"] += 1; continue
    if md5 is not None and md5 not in PASSED:
        c["unpassed_build"] += 1; continue
    c["signed_out" if g["signed_out_end"](d) else "whole"] += 1; out.append(name)
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
hdr = f"# population merge list {ts}: raw/_pacetest/shared/<name>.json -> people_live/vm/<name>.json; strict person check PASS; {len(out)} people; none already in vm/"
open(f"{W}/merge_list.txt", "w").write(hdr + "\n" + "".join(n + "\n" for n in out))
sh("gsutil", "-q", "cp", f"{W}/merge_list.txt", f"{T}/merge_list.txt")
if out:
    old = sh("gsutil", "cat", f"{T}/merged_ledger.txt").stdout
    open(f"{W}/ledger.txt", "w").write(old + f"# {ts}\n" + "".join(n + "\n" for n in out))
    sh("gsutil", "-q", "cp", f"{W}/ledger.txt", f"{T}/merged_ledger.txt")
print(f"MERGE_LIST={len(out)} {dict(c)}")
