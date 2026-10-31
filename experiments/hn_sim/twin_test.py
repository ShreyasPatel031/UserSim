"""Step 1: are the twins reliable for their own person? (vector twins; LLM twins in twin_llm.py)

Panel: the N most active commenters in the 180 days before CUT. Twin = what audience.py builds, from comments before CUT
only: taste (recency-weighted mean title embedding of the stories they commented on) and hour-of-day presence.
Held out (CUT .. END): for each person, the stories on a daily list (rank <= 120, so they plausibly saw them) that
they commented on (positives) vs the listed stories of the same days they did not comment on (negatives).
Scores per person: AUC of
  twin taste      cosine(taste, story title embedding)
  popularity      the story's final points (no person model: what everyone likes)
  twin + pop      rank average of the two
Presence: share of the person's held-out comments in the 6 UTC hours the twin says they are most active (uniform = 25%).
Gate (plan): median per-person AUC > 0.7 and better than popularity. -> <cache>/twin_test.csv, and each
person's test items -> <cache>/twin_test_sets.parquet (twin_llm.py scores the same items).

    python twin_test.py [n=3000] [cut=2026-07-01] [end=2026-10-14]
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import top100 as H

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
CUT = sys.argv[2] if len(sys.argv) > 2 else "2026-07-01"
END = sys.argv[3] if len(sys.argv) > 3 else "2026-10-14"
t_cut = pd.Timestamp(CUT, tz="UTC").timestamp()
t_end = pd.Timestamp(END, tz="UTC").timestamp() + 86400
rng = np.random.default_rng(0)

E = pd.read_parquet(os.path.join(H.CACHE, "title_emb.parquet"))
emb = np.stack(E.emb.to_numpy()).astype(np.float32)
emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
ei = pd.Series(np.arange(len(E)), index=E.post_id)
p = H.stories().set_index("post_id")
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[c.story_id.isin(ei.index)]
before = c[(c.created_at_i < t_cut) & (c.created_at_i >= t_cut - 540 * 86400)]
after = c[(c.created_at_i >= t_cut) & (c.created_at_i < t_end)]
act = before[before.created_at_i >= t_cut - 180 * 86400].groupby("person").size()
panel = act[act.index.isin(after.person.unique())].nlargest(N).index
print(f"panel {len(panel)} people (180-day comments: median {act[panel].median():.0f}, min {act[panel].min()})", flush=True)

# twins from data before CUT
b = before[before.person.isin(panel)]
pi = pd.Series(np.arange(len(panel)), index=panel)
w = np.exp(-(t_cut - b.created_at_i.to_numpy()) / (180 * 86400) * np.log(2)).astype(np.float32)
taste = np.zeros((len(panel), emb.shape[1]), np.float32)
np.add.at(taste, pi[b.person].to_numpy(), emb[ei[b.story_id].to_numpy()] * w[:, None])
taste /= np.linalg.norm(taste, axis=1, keepdims=True) + 1e-9
hour = np.full((len(panel), 24), 1.0, np.float32)
rb = b[b.created_at_i >= t_cut - 180 * 86400]
np.add.at(hour, (pi[rb.person].to_numpy(), ((rb.created_at_i // 3600) % 24).to_numpy()), 1)

# held-out candidate stories: listed stories of each day
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
L = L[(L.day >= CUT) & (L.day <= END) & L.post_id.isin(ei.index)].drop_duplicates("post_id")
day_of = L.set_index("post_id").day
by_day = L.groupby("day").post_id.apply(np.array)
lp = np.log1p(L.post_id.map(p.points).fillna(1).to_numpy())
pop = pd.Series(lp, index=L.post_id)
a = after[after.person.isin(panel) & after.story_id.isin(day_of.index)]
print(f"held-out: {len(L)} listed stories over {L.day.nunique()} days; panel comments on them {len(a)}", flush=True)

rows, sets = [], []
for person, g in a.groupby("person"):
    pos = np.unique(g.story_id.to_numpy())
    if len(pos) < 5:
        continue
    days = day_of[pos].unique()
    cand = np.unique(np.concatenate([by_day[d] for d in days]))
    neg = np.setdiff1d(cand, pos)
    if len(neg) < 20:
        continue
    neg = rng.choice(neg, min(len(neg), 20 * len(pos)), replace=False)
    ids = np.concatenate([pos, neg])
    y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
    sets.append(pd.DataFrame({"person": person, "story_id": ids, "y": y}))
    i = pi[person]
    s_taste = emb[ei[ids].to_numpy()] @ taste[i]
    s_pop = pop[ids].to_numpy()
    s_both = pd.Series(s_taste).rank().to_numpy() + pd.Series(s_pop).rank().to_numpy()
    top6 = np.argsort(-hour[i])[:6]
    held_h = ((g.created_at_i // 3600) % 24).to_numpy()
    rows.append({"person": person, "pos": len(pos), "neg": len(neg), "auc_twin": roc_auc_score(y, s_taste),
                 "auc_pop": roc_auc_score(y, s_pop), "auc_twin_pop": roc_auc_score(y, s_both),
                 "presence_top6": float(np.isin(held_h, top6).mean())})
R = pd.DataFrame(rows)
R.to_csv(os.path.join(H.CACHE, "twin_test.csv"), index=False)
pd.concat(sets).to_parquet(os.path.join(H.CACHE, "twin_test_sets.parquet"), index=False)   # same items for twin_llm.py
print(f"people scored: {len(R)} (5+ held-out stories each; median {R.pos.median():.0f} positives)")
for k in ("auc_twin", "auc_pop", "auc_twin_pop"):
    print(f"  {k:13s} median {R[k].median():.3f}  mean {R[k].mean():.3f}  share > 0.7: {(R[k] > 0.7).mean():.1%}")
print(f"  twin beats popularity for {(R.auc_twin > R.auc_pop).mean():.1%} of people")
print(f"  presence: share of held-out comments in the twin's top-6 hours: median {R.presence_top6.median():.2f} (uniform 0.25)")
