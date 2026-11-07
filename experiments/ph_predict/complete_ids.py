"""Salted ids of the population agent's COMPLETE people (whole + whole signed-out), for pool_size.py (COMPLETE_IDS).
Runs the population agent's own classifier (tools/population/quality.py on claude/population-data, person_complete over the
latest people_live/vm/<h>.json) unchanged, then hashes each COMPLETE handle with the store salt. Prints counts only; the
output file holds salted ids, never handles. The salt is read to hash and never printed.
usage: python complete_ids.py QUALITY_PY DATA_DIR OUT_IDS"""
import hashlib, json, os, subprocess, sys, tempfile

Q, D, OUT = sys.argv[1:4]
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
sl = subprocess.run(["gsutil", "cat", f"{B}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()
t = tempfile.mkdtemp(prefix="cid_")
# SINCE in the far future: skip the per-pull section (it only feeds the report); the person-level check reads every vm/ file
sys.argv = [Q, D, "2999-01-01T00:00:00Z", f"{t}/q.md", f"{t}/rows.jsonl"]
g = {"__name__": "quality"}
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(open(Q).read(), Q, "exec"), g)
latest, person_complete, signed_out_end = g["latest"], g["person_complete"], g["signed_out_end"]
ok = [h for h, d in latest.items() if person_complete(d, h)[0]]
so = sum(1 for h in ok if signed_out_end(latest[h]))
ids = sorted({"p_" + hashlib.sha256((sl + "producthunt:" + h.lower()).encode()).hexdigest()[:16] for h in ok})
open(OUT, "w").write("\n".join(ids) + "\n")
print(json.dumps({"saved": len(latest), "complete": len(ok), "whole": len(ok) - so, "whole_signed_out": so, "incomplete": len(latest) - len(ok), "ids_written": len(ids)}))
