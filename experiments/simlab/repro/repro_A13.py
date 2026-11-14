"""Repro A13 (bundle 12a.1, 0bc2ef0d): with a 00:05 parquet that has NO pred_arm3 column (or a partly filled one), the 12a.1
two_predictions.py must write exactly the same 0005 and prereveal JSON (every key and value except written_at) as the verified 12a
(88b350e8 folder 20261114_two_predictions). Also reports what 12a.1 writes when pred_arm3 is fully filled. No network: forecast(), names(),
guard(), put() patched; fake recorder file.
    python repro_A13.py <ph-ops checkout root at 0bc2ef0d>     exit 0 = equivalent"""
import sys, os, json, tempfile, importlib.util
import pandas as pd, numpy as np
ROOT = sys.argv[1]; PP = f"{ROOT}/experiments/pipeline_patches"
def load(folder):
    spec = importlib.util.spec_from_file_location("tp_" + folder, f"{PP}/{folder}/two_predictions.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
D = "2026-11-10"; ids = [str(1000 + i) for i in range(12)]; tmp = tempfile.mkdtemp(); os.makedirs(f"{tmp}/data/vote_snapshots")
R = [{"day": D, "at": ts, "launch_id": i, "name": f"n{i}", "votes": 0, "comments": k % 4, "rank_now": (k + o) % 12 + 1} for ts, o in (("2026-11-10T09:00:00Z", 0), ("2026-11-10T11:45:07Z", 5)) for k, i in enumerate(ids)]
open(f"{tmp}/data/vote_snapshots/{D}.jsonl", "w").write("\n".join(json.dumps(r) for r in R))
def run(m, F):
    m.PH = tmp; m.TW = os.path.dirname(m.__file__); got = {}
    m.forecast = lambda d: None if F is None else F.copy(); m.put = lambda d, kind, out: got.__setitem__(kind, out)
    if hasattr(m, "guard"): m.guard = lambda d: {}
    m.midnight(D); m.prereveal(D)
    strip = lambda o: {k: v for k, v in o.items() if k != "written_at"}
    return {k: strip(v) for k, v in got.items()}
base = pd.DataFrame({"id": ids, "pred": np.linspace(1, 2, 12), "pred_arm2": np.linspace(2, 1, 12)})
old, new = load("20261114_two_predictions"), load("20261114_two_predictions_12a1")
cases = {"no pred_arm3 column": base, "pred_arm3 partly NaN": base.assign(pred_arm3=[np.nan] + list(np.linspace(0, 1, 11))),
         "pred_arm2 all NaN, no pred_arm3": base.assign(pred_arm2=np.nan), "no parquet": None}
res = {}
for nm, F in cases.items():
    a, b = run(old, F), run(new, F); res[nm] = {"identical": a == b, "kinds": sorted(a), "model_0005 old/new": [a.get("0005", {}).get("model"), b.get("0005", {}).get("model")]}
full = run(new, base.assign(pred_arm3=np.linspace(0, 1, 12)))
res["pred_arm3 fully filled (12a.1 only)"] = {"model": full["0005"].get("model"), "fallback_used": full["0005"].get("fallback_used"), "top1": full["0005"]["ranking"][0]["id"]}
ok = all(v["identical"] for k, v in res.items() if "identical" in v)
print(json.dumps({**res, "A13 equivalent": ok})); sys.exit(0 if ok else 1)
