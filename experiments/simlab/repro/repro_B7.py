"""Bug sweep item 7 (orchestrator 18:35Z Nov 14): period_parts.py reads ~/.usersim_sim/launches, but bundle 12's tw.sh sets
USERSIM_CACHE=$TW/cache and warehouse.sync() writes there, so on the VM the staleness guard / period truth read a cache nobody syncs.
Puts one launches part under $USERSIM_CACHE (HOME pointed at an empty dir). PASS = period_parts sees it and agrees with warehouse.LOCAL.
    python repro_B7.py <dir holding period_parts.py> <dir holding pipeline/warehouse.py>     exit 0 = fixed"""
import sys, os, tempfile, importlib, json
t = tempfile.mkdtemp(); os.environ["HOME"] = f"{t}/home"; os.makedirs(f"{t}/home"); os.environ["USERSIM_CACHE"] = f"{t}/cache"
os.makedirs(f"{t}/cache/launches"); import pandas as pd
pd.DataFrame({"id": ["1"], "day": ["2026-11-10"], "votes": [5], "weekly_rank": [1], "monthly_rank": [1], "updated_at": ["2026-11-11T00:00:00Z"]}).to_parquet(f"{t}/cache/launches/20261111T000000.parquet")
sys.path[:0] = [sys.argv[1], sys.argv[2]]; PP = importlib.import_module("period_parts"); W = importlib.import_module("pipeline.warehouse")
n = len(PP.parts()); same = os.path.realpath(PP.LOC) == os.path.realpath(os.path.join(W.LOCAL, "launches"))
ok = n == 1 and same; print(json.dumps({"period_parts LOC": PP.LOC, "warehouse LOCAL": W.LOCAL, "parts seen": n, "same dir": same, "B7 fixed": ok})); sys.exit(0 if ok else 1)
