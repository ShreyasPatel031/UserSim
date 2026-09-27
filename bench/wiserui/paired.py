#!/usr/bin/env python3
"""Paired bootstrap difference (condition B - condition A) on CA and AA over shared pairs."""
import json, random, sys
from collections import defaultdict

run, a, b = sys.argv[1], sys.argv[2], sys.argv[3]
rows = [json.loads(l) for l in open(f"{run}/judgments.jsonl")]
P = defaultdict(dict)
for r in rows:
    want = "First" if r["order"] == "wl" else "Second"
    P[(r["condition"], r["index"])][r["order"]] = int(r["pick"] == want)
ids = sorted({i for (c, i) in P if c == a} & {i for (c, i) in P if c == b})
def ca(c, i): return P[(c, i)]["wl"] * P[(c, i)]["lw"]
def aa(c, i): return (P[(c, i)]["wl"] + P[(c, i)]["lw"]) / 2
rng = random.Random(0)
for name, f in (("CA", ca), ("AA", aa)):
    d = [f(b, i) - f(a, i) for i in ids]
    boots = sorted(sum(d[rng.randrange(len(d))] for _ in d) / len(d) for _ in range(10000))
    print(f"{b} - {a} {name}: {100*sum(d)/len(d):+.1f} pts [95% CI {100*boots[250]:+.1f}, {100*boots[9749]:+.1f}] n={len(ids)}")
