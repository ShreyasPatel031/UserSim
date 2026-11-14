#!/usr/bin/env python3
"""gsutil stand-in for the integration dry run. gs://usersim-bakeoff-347838016394/usersim_sim/<rel> maps to $FB/<rel>.
WRITES (cp/rsync to gs://) always go to $FB. READS: $FB first; paths the night's chain produces (AUTH regex) are authoritative in $FB
(missing there = missing, never read from the real bucket); everything else reads through to the real gsutil (read-only).
Every call is logged to $FB_LOG as JSON."""
import json, os, re, shutil, subprocess, sys
FB = os.environ["FB"]; REAL = os.environ["REAL_GSUTIL"]; PFX = "gs://usersim-bakeoff-347838016394/usersim_sim/"
AUTH = re.compile(os.environ.get("AUTH_RE", r"^(results/|raw/daily/|tmp/e5/website/|tmp/e5/held_team_shadow/)"))
a = [x for x in sys.argv[1:] if x not in ("-q", "-m")]; op = a[0] if a else ""; args = a[1:]
def log(**k): open(os.environ["FB_LOG"], "a").write(json.dumps({"op": op, **k}) + "\n")
rel = lambda p: p[len(PFX):] if p.startswith(PFX) else None
def local(p): return os.path.join(FB, rel(p))
def readable(p):
    r = rel(p); lp = local(p)
    if os.path.exists(lp): return "fb", lp
    if AUTH.search(r): return "missing", None
    return "real", None
if op == "cat":
    src, lp = readable(args[0]); log(path=rel(args[0]), src=src)
    if src == "fb": sys.stdout.buffer.write(open(lp, "rb").read()); sys.exit(0)
    if src == "missing": sys.exit(1)
    sys.exit(subprocess.run([REAL, "cat", args[0]]).returncode)
if op == "stat":
    src, _ = readable(args[0]); log(path=rel(args[0]), src=src)
    if src == "real": sys.exit(subprocess.run([REAL, "-q", "stat", args[0]]).returncode)
    sys.exit(0 if src == "fb" else 1)
if op == "cp":
    s, d = [x for x in args if not x.startswith("-")][-2:]
    if d.startswith(PFX):
        os.makedirs(os.path.dirname(local(d)), exist_ok=True); shutil.copy(s, local(d)); log(path=rel(d), src="write"); sys.exit(0)
    src, lp = readable(s); log(path=rel(s), src=src)
    if src == "fb": shutil.copy(lp, d); sys.exit(0)
    if src == "missing": sys.exit(1)
    sys.exit(subprocess.run([REAL, "-q", "cp", s, d]).returncode)
if op == "rsync":
    s, d = [x for x in args if not x.startswith("-")][-2:]
    if d.startswith(PFX):
        shutil.copytree(s, local(d), dirs_exist_ok=True); log(path=rel(d), src="write"); sys.exit(0)
    r = rel(s); log(path=r, src="real-rsync" if not AUTH.search(r) else "fb-rsync")
    if AUTH.search(r):
        if os.path.isdir(local(s)): shutil.copytree(local(s), d, dirs_exist_ok=True); sys.exit(0)
        sys.exit(1)
    sys.exit(subprocess.run([REAL, "-q", "-m", "rsync", "-r", s, d]).returncode)
if op == "ls":
    log(path=rel(args[-1]) if args else None, src="real-ls"); sys.exit(subprocess.run([REAL] + sys.argv[1:]).returncode)
log(path=None, src="unsupported " + " ".join(sys.argv[1:])); sys.exit(2)
