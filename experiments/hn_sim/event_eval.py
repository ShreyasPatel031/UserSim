"""Event-level score of the September predictions (misses.py -> pred_sep.parquet): a real top-10 story counts as
found if the model's top N (near-duplicate titles collapsed) contains a story about the same news / release / article
(another submission of it counts). Gemini Flash judges, seeing only the two title lists."""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import llm
import rank as R
import store as S
import top100 as H

SAME = """Two lists of Hacker News story titles from the same day.
Actual top stories:
{a}
Predicted stories:
{p}
For each actual story, give the predicted story about the SAME specific news, release, product or article (a
different submission of the same thing counts), or null.
Return {{"matches": {{"A1": "P3" or null, ...}}}}"""   # as in llm_eval.py

P = pd.read_parquet(os.path.join(H.CACHE, "pred_sep.parquet"))
t = P.set_index("post_id").title


def dedupe(g, n):
    out, seen = [], []
    for pid in g.sort_values("score", ascending=False).post_id:
        w = {x for x in str(t[pid]).lower().split() if len(x) > 3}
        if any(len(w & s) >= 3 for s in seen):
            continue
        out.append(pid)
        seen.append(w)
        if len(out) == n:
            break
    return out


def day_hit(g, n):
    actual = g.nsmallest(10, "rk").post_id.tolist()
    pred = dedupe(g, n)
    fmt = lambda ids, k: "\n".join(f"{k}{i + 1}: {t[x]}" for i, x in enumerate(ids))  # noqa: E731
    j = llm.call("event_match", SAME.format(a=fmt(actual, "A"), p=fmt(pred, "P")), model=llm.FLASH, thinking=512)
    return sum(1 for v in (j.get("matches") or {}).values() if v) / 10


rows = []
for n in (10, 30, 100):
    with ThreadPoolExecutor(16) as ex:
        h = list(ex.map(lambda kv: day_hit(kv[1], n), P.groupby("day")))
    m, lo, hi = R.boot(h)
    exact = float(np.mean([(g.nsmallest(10, "rk").pred_rank <= n).mean() for _, g in P.groupby("day")]))
    print(f"real top 10 found in model top {n}: by event {m} ({lo}-{hi}); exact submission {exact:.3f}", flush=True)
    rows.append({"kind": "event_level", "picks": n, "event_recall": m, "lo": lo, "hi": hi, "exact_recall": round(exact, 3),
                 "month": "2026-09", "made_on": S.now()})
S.write("hn_scores", pd.DataFrame(rows))
print("judge $", round(llm.flush_spend("hn_event_match", "Sep 2026 event-level, best model"), 3))
