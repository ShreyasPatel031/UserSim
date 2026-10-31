"""Step 1, LLM twins: does a Gemini persona built from a person's own history pick out the stories they engage with?

For PEOPLE people of the twin_test.py panel (random, fixed seed), the persona is the titles of the last 60 stories
they commented on before CUT (no later data). One call per person rates all their test items (twin_test_sets.parquet,
capped at 10 positives + 30 negatives, shuffled) 0-10 for "how likely you'd open it and comment". Per-person AUC is
compared with the vector twin and popularity on the same items. Gemini on Vertex only; cost measured and logged.

    python twin_llm.py [people=200] [model=lite]
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import emb_io
import llm
import top100 as H

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
MODEL = llm.LITE if (sys.argv[2] if len(sys.argv) > 2 else "lite") == "lite" else llm.FLASH
CUT = "2026-07-01"
t_cut = pd.Timestamp(CUT, tz="UTC").timestamp()
rng = np.random.default_rng(1)

sets = pd.read_parquet(os.path.join(H.CACHE, "twin_test_sets.parquet"))
R = pd.read_csv(os.path.join(H.CACHE, "twin_test.csv")).set_index("person")
people = rng.choice(sorted(sets.person.unique()), min(N, sets.person.nunique()), replace=False)
p = H.stories().set_index("post_id")
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[c.person.isin(people) & (c.created_at_i < t_cut)].sort_values("created_at_i")
hist = c.drop_duplicates(["person", "story_id"], keep="last").groupby("person").story_id.apply(lambda s: s.to_numpy()[-60:])
EMB, EI = emb_io.load()


class _Emb(dict):
    def __contains__(self, k):
        return k in EI.index

    def __getitem__(self, k):
        return np.asarray(EMB[EI[k]], np.float32)


emb = _Emb()

SYSTEM = ("You simulate one specific Hacker News reader, described only by the stories they chose to comment on "
          "recently. Judge each new story as that person would: would they open it and comment? Use their topics, "
          "tone and interests; do not judge general popularity.")


def title(i):
    t = p.title.get(i, "")
    u = p.url.get(i)
    dom = u.split("/")[2].removeprefix("www.") if isinstance(u, str) and u.count("/") >= 2 else "self post"
    return f"{t} ({dom})"


def one(person):
    S = sets[sets.person == person]
    pos, neg = S[S.y == 1], S[S.y == 0]
    S = pd.concat([pos.sample(min(10, len(pos)), random_state=0), neg.sample(min(30, len(neg)), random_state=0)])
    S = S.sample(frac=1, random_state=0).reset_index(drop=True)
    h = "\n".join(f"- {title(i)}" for i in hist.get(person, [])[::-1])
    items = "\n".join(f"{k + 1}. {title(i)}" for k, i in enumerate(S.story_id))
    prompt = (f"Stories this person commented on recently (newest first):\n{h}\n\nNew stories:\n{items}\n\n"
              f'Return JSON {{"scores": [{len(S)} integers 0-10, one per new story in order]}}.')
    j = llm.call("twin_llm", prompt, system=SYSTEM, model=MODEL, max_tokens=512)
    sc = j.get("scores") if isinstance(j, dict) else None
    if not isinstance(sc, list) or len(sc) != len(S):
        return None
    y = S.y.to_numpy()
    s = np.array(sc, float) + rng.random(len(S)) * 1e-3
    tv = np.array([emb[i] for i in S.story_id], np.float32)
    taste = np.array([emb[i] for i in hist.get(person, []) if i in emb], np.float32)
    taste = taste.mean(0) if len(taste) else tv.mean(0)
    s_vec = tv @ taste / (np.linalg.norm(tv, axis=1) * np.linalg.norm(taste) + 1e-9)
    s_pop = np.log1p(p.points.reindex(S.story_id).fillna(1).to_numpy())
    return {"person": person, "n_hist": len(hist.get(person, [])), "auc_llm": roc_auc_score(y, s),
            "auc_vec_same_items": roc_auc_score(y, s_vec), "auc_pop_same_items": roc_auc_score(y, s_pop),
            "auc_llm_pop": roc_auc_score(y, pd.Series(s).rank().to_numpy() + pd.Series(s_pop).rank().to_numpy())}


with ThreadPoolExecutor(8) as ex:
    rows = [r for r in ex.map(one, people) if r]
usd, meter = llm.spent(), llm.meter()
llm.flush_spend("hn_sim.twin_llm", f"{len(people)} people, {MODEL}")
D = pd.DataFrame(rows)
D.to_csv(os.path.join(H.CACHE, f"twin_llm_{N}.csv"), index=False)
print(f"{len(D)} of {len(people)} people scored; model {MODEL}; measured cost ${usd:.3f}")
for k in ("auc_llm", "auc_vec_same_items", "auc_pop_same_items", "auc_llm_pop"):
    print(f"  {k:20s} median {D[k].median():.3f}  mean {D[k].mean():.3f}  share > 0.7: {(D[k] > 0.7).mean():.1%}")
print(f"  LLM twin beats vector twin for {(D.auc_llm > D.auc_vec_same_items).mean():.1%}; beats popularity for "
      f"{(D.auc_llm > D.auc_pop_same_items).mean():.1%}")
print(json.dumps(meter))
