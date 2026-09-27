#!/usr/bin/env python3
"""Total spend of a set of run ledgers (calls copied in at $0 excluded): spend.py results/hc_* [--cap 5]."""
import json
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
cap = float(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else None
tot = 0.0
for d in args:
    f = Path(d) / "calls.jsonl"
    if not f.exists():
        continue
    c = n = e = 0
    for line in f.open():
        r = json.loads(line)
        if r.get("copied_from"):
            continue
        c += r.get("cost_usd", 0.0)
        n += 1
        e += bool(r.get("error"))
    tot += c
    print(f"{d}: ${c:.4f} ({n} calls, {e} errors)")
print(f"TOTAL ${tot:.4f}" + (f" of cap ${cap:.2f} (left ${cap - tot:.4f})" if cap else ""))
