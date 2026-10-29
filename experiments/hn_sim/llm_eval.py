"""October 2026: model alone vs Gemini title score alone vs both (rank average, and as a model feature trained on
the first half of October and tested on the second)."""
import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T

p = T.stories()
p = p[p.created_at_i < pd.Timestamp.now(tz="UTC").timestamp() - 3 * 86400].reset_index(drop=True)
F = T.feats(p)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
L = S.read("hn_scores")
L = L[L.kind == "llm_title"].drop_duplicates("post_id", keep="last").set_index("post_id").score
tr, te = (p.month < "2026-10").to_numpy(), (p.month == "2026-10").to_numpy()
oof, txt = T.text_scores(p, y, tr, te)
c = lgb.LGBMClassifier(**{**T.GBM, "scale_pos_weight": 5}).fit(F[tr].assign(text_score=oof), (rk[tr] <= 30).astype(int))
P = pd.DataFrame({"day": p.day[te].to_numpy(), "y": y[te], "post_id": p.post_id[te].to_numpy(),
                  "model": c.predict_proba(F[te].assign(text_score=txt))[:, 1]})
P["llm"] = P.post_id.map(L).fillna(P.post_id.map(L).median()).to_numpy()
P["both"] = P.groupby("day").model.rank(pct=True) + P.groupby("day").llm.rank(pct=True)
P["both_w"] = P.groupby("day").model.rank(pct=True) + 2 * P.groupby("day").llm.rank(pct=True)
rng = np.random.default_rng(0)
for col in ("model", "llm", "both", "both_w"):
    print(col, {k: R.boot(T.day_hits(P, col, k, rng)) for k in (10, 30)})

# event-level: a hit if a predicted story is about the same news / product as an actual top-10 story
import json
from concurrent.futures import ThreadPoolExecutor

import llm

SAME = """Two lists of Hacker News story titles from the same day.
Actual top stories:
{a}
Predicted stories:
{p}
For each actual story, give the predicted story about the SAME specific news, release, product or article (a
different submission of the same thing counts), or null.
Return {{"matches": {{"A1": "P3" or null, ...}}}}"""
t = p.set_index("post_id").title


def dedupe(g, col, n):
    """Top n by score, skipping a story whose title repeats one already picked (same 3+ rare words)."""
    out, seen = [], []
    for pid in g.sort_values(col, ascending=False).post_id:
        w = {x for x in str(t[pid]).lower().split() if len(x) > 3}
        if any(len(w & s) >= 3 for s in seen):
            continue
        out.append(pid); seen.append(w)
        if len(out) == n:
            break
    return out


def event_hits(day, g, col, n=10):
    actual = g.nlargest(10, "y").post_id.tolist()
    pred = dedupe(g, col, n)
    fmt = lambda ids, k: "\n".join(f"{k}{i + 1}: {t[x]}" for i, x in enumerate(ids))  # noqa: E731
    j = llm.call("event_match", SAME.format(a=fmt(actual, "A"), p=fmt(pred, "P")), model=llm.FLASH, thinking=512)
    m = j.get("matches") or {}
    return sum(1 for v in m.values() if v) / 10


for n in (10, 30):
    for col in ("model", "llm", "both"):
        with ThreadPoolExecutor(16) as ex:
            h = list(ex.map(lambda kv: event_hits(kv[0], kv[1], col, n), P.groupby("day")))
        print(f"event-level, {n} picks, {col}:", R.boot(h))
print("judge $", round(llm.flush_spend("hn_event_match", "October event-level top-10 judge"), 3))
