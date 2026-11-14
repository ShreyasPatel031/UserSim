"""Arm-2 top 10 for day d with the current and the fixed features.py (scratch, read-only; counts and ranks only, no names).
usage (VM, cwd ~/w/experiments/ph_predict): python3 arm2_diff.py <fixed features dir> <scratch h25 root with all today files> <d>"""
import json, os, subprocess, sys
fx, root, d = sys.argv[1:4]; PH = os.getcwd()   # subprocesses run with cwd = root's parent so `-c` cannot import ph_predict/features.py first
code = f'''
import os, sys, json; import features as F; print("features", F.__file__, file=sys.stderr); F.D = "{PH}/data"; os.environ["H25_DATA"] = "{root}"
import h25_live; PA, info = h25_live.predict("{d}"); print(json.dumps(PA.sort_values(["pred_arm2", "id"], ascending=[False, True]).id.tolist()))'''
out = {}
for nm, pp in (("current", f"/home/agent/w/arm2_live:{PH}"), ("fixed", f"{fx}:/home/agent/w/arm2_live:{PH}")):
    r = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": pp}, capture_output=True, text=True, cwd=os.path.dirname(root))
    print(nm, [l for l in r.stderr.splitlines() if l.startswith("features")], flush=True)
    out[nm] = json.loads(r.stdout.strip().splitlines()[-1])
a, b = out["current"], out["fixed"]
print(json.dumps({"day": d, "n": len(a), "top3_overlap": len(set(a[:3]) & set(b[:3])), "top5_overlap": len(set(a[:5]) & set(b[:5])),
                  "top10_overlap": len(set(a[:10]) & set(b[:10])), "same_top10_order": a[:10] == b[:10],
                  "fixed_rank_of_current_top10": [b.index(i) + 1 for i in a[:10]], "current_rank_of_fixed_top10": [a.index(i) + 1 for i in b[:10]]}))
