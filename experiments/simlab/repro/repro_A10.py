"""Repro A10 (d9b9a96f): the midnight retry. sched12a.txt must hold 00:20, 00:35 and 01:30 midnight slots; run.sh's done_ok must
return 0 (skip) only when model is set and fallback_used is null; none_available / stale_read / clean_nosite_fallback / no file -> retry.
The done_ok body is extracted from run.sh and run with gsutil replaced by cat of a local file.
    python repro_A10.py <ph-ops checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, os, re, json, subprocess, tempfile
ROOT = sys.argv[1]; P = f"{ROOT}/experiments/pipeline_patches/20261114_two_predictions"
sched = [l.split() for l in open(f"{P}/sched12a.txt") if l.strip()]; mid = [t for t, j in sched if j == "midnight"]
src = open(f"{P}/run.sh").read(); body = re.search(r"done_ok\(\) \{(.*?)\n?\}\n", src, re.S).group(1)
tmp = tempfile.mkdtemp(); res = {}
cases = {"arm2 normal": {"model": "arm2", "fallback_used": None}, "clean_nosite_fallback": {"model": "clean_nosite", "fallback_used": "clean_nosite_fallback"},
         "none_available": {"model": None, "fallback_used": "none_available"}, "stale_read": {"model": "hybrid_vm", "fallback_used": "stale_read"},
         "model null, no fallback": {"model": None, "fallback_used": None}, "no file": None}
for nm, c in cases.items():
    f = f"{tmp}/{D}_0005.json" if (D := "2026-11-15") else ""
    if os.path.exists(f): os.remove(f)
    if c is not None: json.dump(c, open(f, "w"))
    sh = f'gsutil() {{ cat "{tmp}/$(basename "$2")"; }}\nB=x; D={D}\ndone_ok() {{{body}\n}}\ndone_ok 0005'
    res[nm] = "skip" if subprocess.run(["bash", "-c", sh]).returncode == 0 else "retry"
want = {"arm2 normal": "skip", "clean_nosite_fallback": "retry", "none_available": "retry", "stale_read": "retry", "model null, no fallback": "retry", "no file": "retry"}
ok = res == want and {"00:20", "00:35", "01:30"} <= set(mid)
print(json.dumps({"midnight slots": mid, "done_ok": res, "A10 fixed": ok})); sys.exit(0 if ok else 1)
