"""Repro A9 (bundle 12a residual, d9b9a96f): a before-reveal read older than 03:44 PT must still give hybrid_vm but with fallback_used
"stale_read" (so done_ok fails and the 03:52 slot retries), never a fresh-looking file. Also reports the case the flag cannot show:
stale read AND the 00:05 parquet missing (fallback already "no_prior", so staleness is not visible in fallback_used).
    python repro_A9.py <ph-ops checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, os, json, tempfile, importlib.util
import pandas as pd
ROOT = sys.argv[1]; P = f"{ROOT}/experiments/pipeline_patches/20261114_two_predictions/two_predictions.py"
def run(reads, fc):
    spec = importlib.util.spec_from_file_location("tp", P); tp = importlib.util.module_from_spec(spec); spec.loader.exec_module(tp)
    D = "2026-11-10"; tmp = tempfile.mkdtemp(); os.makedirs(f"{tmp}/data/vote_snapshots"); tp.PH = tmp; tp.TW = os.path.dirname(P)
    ids = [str(1000 + i) for i in range(12)]
    R = [{"day": D, "at": ts, "launch_id": i, "name": f"n{i}", "votes": 0, "comments": 1, "rank_now": k + 1} for ts in reads for k, i in enumerate(ids)]
    open(f"{tmp}/data/vote_snapshots/{D}.jsonl", "w").write("\n".join(json.dumps(r) for r in R))
    tp.forecast = (lambda d: pd.DataFrame({"id": ids, "pred": range(12), "pred_arm2": range(12)})) if fc else (lambda d: None)
    got = {}; tp.put = lambda d, kind, out: got.update(out); tp.prereveal(D)
    return {"model": got.get("model"), "fallback_used": got.get("fallback_used"), "recorder_T": got.get("inputs", {}).get("recorder_T")}
fresh = run(["2026-11-10T09:00:00Z", "2026-11-10T11:00:00Z", "2026-11-10T11:45:07Z"], True)     # 01:00, 03:00, 03:45:07 PT
stale = run(["2026-11-10T09:00:00Z", "2026-11-10T11:00:00Z"], True)                              # 03:00 read only
stale_noprior = run(["2026-11-10T09:00:00Z", "2026-11-10T11:00:00Z"], False)
ok = fresh["fallback_used"] is None and fresh["model"] == "hybrid_vm" and stale["model"] == "hybrid_vm" and stale["fallback_used"] == "stale_read"
print(json.dumps({"fresh 03:45 read": fresh, "03:00 read only": stale, "03:00 read only + no 00:05 parquet": stale_noprior, "A9 fixed": ok}))
sys.exit(0 if ok else 1)
