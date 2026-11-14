"""Repro A12 (d9b9a96f): import_gate.py must fail on the Nov 14 case and pass on the fixed tree. Local mock of the VM layout under a temp
HOME: w/experiments/ph_predict = the branch's ph_predict code WITHOUT ctrl.py / honest.py (on the VM they lived only in ~/w/mk), plus
the branch's forecast.py; w/arm2_live = h25_live.py + history_retrain.py (pinned copies). Gate run exactly as deploy_b12.sh runs it for
the arm-2 branch: cwd w/experiments/ph_predict, env -u PYTHONPATH, HOME=<temp>, python3 import_gate.py forecast.py.
Broken = arm2_live without ctrl/honest -> want rc 1 naming ctrl; fixed = ctrl.py + honest.py copied into arm2_live -> want rc 0.
    python repro_A12.py <ph-ops checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, os, shutil, subprocess, tempfile, json, glob
ROOT = sys.argv[1]; PP = f"{ROOT}/experiments/ph_predict"; G = f"{ROOT}/experiments/pipeline_patches/20261114_two_predictions/import_gate.py"
H = tempfile.mkdtemp(); W = f"{H}/w"; PH = f"{W}/experiments/ph_predict"; A = f"{W}/arm2_live"; os.makedirs(PH); os.makedirs(A)
for f in glob.glob(f"{PP}/*.py"):
    if os.path.basename(f) not in ("ctrl.py", "honest.py"): shutil.copy(f, PH)
os.symlink(f"{PP}/data", f"{PH}/data") if os.path.isdir(f"{PP}/data") else os.makedirs(f"{PH}/data")
for f in ("h25_live.py", "history_retrain.py"): shutil.copy(f"{PP}/{f}", A)
env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}; env["HOME"] = H
gate = lambda: subprocess.run([sys.executable, G, "forecast.py"], cwd=PH, env=env, capture_output=True, text=True)
b = gate(); [shutil.copy(f"{PP}/{f}", A) for f in ("ctrl.py", "honest.py")]; f = gate()
out = {"broken rc": b.returncode, "broken says": [l for l in b.stdout.splitlines() if "FAIL" in l][:3], "fixed rc": f.returncode,
       "fixed says": f.stdout.strip().splitlines()[-1][:200] if f.stdout.strip() else f.stderr[-200:]}
ok = b.returncode == 1 and any("ctrl" in l for l in out["broken says"]) and f.returncode == 0
print(json.dumps({**out, "A12 fixed": ok})); sys.exit(0 if ok else 1)
