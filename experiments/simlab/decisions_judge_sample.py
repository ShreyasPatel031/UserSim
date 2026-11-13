"""Judge sample for the Decisions pilot: 300 predicted items already labelled by the strict gemini-2.5-pro judge in the b20 replication
(adj3 pool: b20 / deployed / constant, both paths, concerns + questions), grouped by launch with that launch's real comments. Written to
the scratchpad / bucket only (real comment text). Seed 0.
    python decisions_judge_sample.py <ph-website worktree> <scratchpad> <page_path out dir> <rr dir> <out json>
"""
import os, sys, json, random
HERE = os.path.dirname(os.path.abspath(__file__)); OUTJ = sys.argv[5]; sys.argv = sys.argv[:5]
RP = open(os.path.join(HERE, "retrieval_rep.py")).read(); exec(RP[:RP.index("async def one(x, sem, seed2=False):")])
rows = []
for x in FIRST + NEW:
    L_ = C.get(f"lists|{x['key']}") or {}
    for pre in ("RC", "RQ"):
        a = C.get(f"adj3|{pre}|{x['key']}")
        if not a: continue
        for arm, o in a.items():
            items = L_.get(f"{pre}|{arm}") or []
            for it, lab in zip(items, o["lab"]): rows.append((x["key"], it, bool(lab)))
random.Random(0).shuffle(rows); rows = rows[:300]; by = {}
com = {x["key"]: list(x["comments"])[:40] for x in FIRST + NEW}
for k, it, lab in rows: by.setdefault(k, {"key": k, "comments": com[k], "items": [], "pro_labels": []}); by[k]["items"].append(it); by[k]["pro_labels"].append(lab)
json.dump(list(by.values()), open(OUTJ, "w")); print("judge sample", len(rows), "items over", len(by), "launches; pro SAME_POINT share", round(sum(l for _, _, l in rows) / len(rows), 3))
