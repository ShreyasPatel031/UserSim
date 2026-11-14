"""Repro A15 (bundle 12a.2, orchestrator 17:40Z Nov 14): accuracy labels per producing branch, and nothing else changed vs 12a.1.
Branches: midnight arm2 / clean_nosite fallback / none_available; prereveal hybrid_vm / hidden_rank_only (weights missing) / stale_read /
no_prior / midnight_order (no recorder read). For each: run 12a.1 and 12a.2 two_predictions.py on the same fake inputs; PASS when
(a) every key except "backtest" and written_at is identical, and (b) the 12a.2 "backtest" text carries the logged figures for that branch.
    python repro_A15.py <ph-ops checkout root at f399a88e>     exit 0 = all pass"""
import sys, os, json, tempfile, importlib.util, shutil
import pandas as pd, numpy as np
ROOT = sys.argv[1]; PP = f"{ROOT}/experiments/pipeline_patches"
def load(folder, tag):
    spec = importlib.util.spec_from_file_location(f"tp_{tag}", f"{PP}/{folder}/two_predictions.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
D = "2026-11-10"; ids = [str(1000 + i) for i in range(12)]
def recorder(reads):
    tmp = tempfile.mkdtemp(); os.makedirs(f"{tmp}/data/vote_snapshots")
    R = [{"day": D, "at": ts, "launch_id": i, "name": f"n{i}", "votes": 0, "comments": k % 4, "rank_now": (k + o) % 12 + 1} for ts, o in reads for k, i in enumerate(ids)]
    open(f"{tmp}/data/vote_snapshots/{D}.jsonl", "w").write("\n".join(json.dumps(r) for r in R)); return tmp
FULL = [("2026-11-10T09:00:00Z", 0), ("2026-11-10T11:45:07Z", 5)]; STALE = [("2026-11-10T09:00:00Z", 0), ("2026-11-10T11:00:00Z", 5)]
PQ = pd.DataFrame({"id": ids, "pred": np.linspace(1, 2, 12), "pred_arm2": np.linspace(2, 1, 12)})
def run(m, kind, F, reads, weights=True):
    m.PH = recorder(reads) if reads else tempfile.mkdtemp(); got = {}
    tw = os.path.dirname(m.__file__)
    if not weights: t2 = tempfile.mkdtemp(); [shutil.copy(f"{tw}/{f}", t2) for f in os.listdir(tw) if f.endswith(".py")]; tw = t2
    m.TW = tw; m.forecast = lambda d: None if F is None else F.copy(); m.put = lambda d, k, out: got.__setitem__(k, out)
    if hasattr(m, "guard"): m.guard = lambda d: {}
    (m.midnight if kind == "0005" else m.prereveal)(D); o = got.get(kind, {})
    return {k: v for k, v in o.items() if k != "written_at"}
CASES = {"midnight arm2": ("0005", PQ, None, True, ["58.1 / 65.2 / 76.9", "183", "arm 2"]),
         "midnight clean_nosite fallback": ("0005", PQ.assign(pred_arm2=np.nan), None, True, ["54.5 / 64.7 / 76.0", "183", "clean_nosite"]),
         "midnight none_available": ("0005", None, None, True, ["no model"]),
         "prereveal hybrid_vm": ("prereveal", PQ, FULL, True, ["72.2 / 75.0 / 77.5", "leave-one-day-out", "12 days", "+4.2 [0.0, +8.3]", "not yet established"]),
         "prereveal hidden_rank_only": ("prereveal", PQ, FULL, False, ["72.2 / 75.0 / 73.3", "hidden order alone"]),
         "prereveal stale_read": ("prereveal", PQ, STALE, True, ["72.2 / 75.0 / 73.3", "older than 03:44"]),
         "prereveal no_prior": ("prereveal", None, FULL, True, ["72.2 / 75.0 / 73.3"]),
         "prereveal midnight_order": ("prereveal", PQ, [], True, ["58.1 / 65.2 / 76.9", "00:05 order"])}
old, new = load("20261114_two_predictions_12a1", "a1"), load("20261114_two_predictions_12a2", "a2"); res = {}
for nm, (kind, F, reads, w, want) in CASES.items():
    a, b = run(old, kind, F, reads, w), run(new, kind, F, reads, w)
    same = {k: v for k, v in a.items() if k != "backtest"} == {k: v for k, v in b.items() if k != "backtest"}
    lab = str(b.get("backtest")); ok_lab = all(x in lab for x in want)
    res[nm] = {"model": b.get("model"), "fallback_used": b.get("fallback_used"), "label": lab, "rest identical to 12a.1": same, "label has logged figures": ok_lab, "PASS": same and ok_lab}
ok = all(v["PASS"] for v in res.values()); print(json.dumps({**res, "A15 pass": ok})); sys.exit(0 if ok else 1)
