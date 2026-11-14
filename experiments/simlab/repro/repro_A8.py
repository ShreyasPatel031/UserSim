"""Repro A8 (stability review Nov 14): the 03:45 prereveal writer must use a recorder read stamped 03:45:07 PT (the recorder stamps after
its imports), not silently fall back to the 03:00 read. No network: fake recorder file, forecast() and put() patched.
    python repro_A8.py <ph-ops checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, os, json, tempfile, importlib.util
import pandas as pd
ROOT = sys.argv[1]; P = f"{ROOT}/experiments/pipeline_patches/20261114_two_predictions/two_predictions.py"
spec = importlib.util.spec_from_file_location("tp", P); tp = importlib.util.module_from_spec(spec); spec.loader.exec_module(tp)
D = "2026-11-10"; tmp = tempfile.mkdtemp(); os.makedirs(f"{tmp}/data/vote_snapshots"); tp.PH = tmp
ids = [str(1000 + i) for i in range(12)]
def rows(ts, order):
    return [{"day": D, "at": ts, "launch_id": i, "name": f"n{i}", "votes": 0, "comments": 1, "rank_now": order.index(i) + 1} for i in ids]
o300 = ids[:]; o345 = ids[::-1]                                    # the 03:45 hidden order differs completely from 03:00
R = rows("2026-11-10T09:00:00Z", o300) + rows("2026-11-10T11:00:00Z", o300) + rows("2026-11-10T11:45:07Z", o345)   # 01:00, 03:00, 03:45:07 PT (PST = UTC-8)
open(f"{tmp}/data/vote_snapshots/{D}.jsonl", "w").write("\n".join(json.dumps(r) for r in R))
tp.forecast = lambda d: pd.DataFrame({"id": ids, "pred": range(12), "pred_arm2": range(12)})
got = {}; tp.put = lambda d, kind, out: got.update(out)
tp.prereveal(D)
top5 = [r["id"] for r in got.get("ranking", [])[:5]]
ok = top5 == o345[:5] and "11:45" in str(got.get("inputs", {}).get("recorder_T"))
print(json.dumps({"recorder_T": got.get("inputs", {}).get("recorder_T"), "fallback_used": got.get("fallback_used"), "top5": top5, "want (03:45 order)": o345[:5], "A8 fixed": ok}))
sys.exit(0 if ok else 1)
