"""Measured cost of fine-tuning Gemini on September person-day choices.
One training example = the comment persona card (profile + last 5 own comments, as in taste v3) + the day's line-up
-> the launches the person really upvoted. Tokens are counted with Vertex countTokens on a random sample, then scaled
to every Sep active person-day. Prices are the Vertex supervised-tuning list prices (per 1M training tokens).
usage: SIMLAB_DATA=data_v2 python -m simlab.ft_cost [sample] -> simlab/reports/ft_cost.json"""
import json, os, random, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests
from . import store
from .persona import card

HERE = os.path.dirname(os.path.abspath(__file__))
COUNT = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
         "models/gemini-2.5-flash:countTokens")
PRICE = {"gemini-2.5-flash-lite": 1.5, "gemini-2.5-flash": 5.0, "gemini-3.5-flash": 10.0}   # $ / 1M training tokens
INSTR = ("You are this Product Hunt user scrolling today's launches. Which launches do you upvote? "
         'Reply with JSON only: {"upvoted": [<launch numbers>]}.')


def examples(n, seed=0):
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); names = {r.id: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    slug2name = {r.slug: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    pdict = P.set_index("person").to_dict("index")
    real = E[(E.item.map(day) == E.date) & E.date.between("2026-09-01", "2026-09-30")]
    picked = real.groupby(["person", "date"]).item.apply(set).to_dict()
    pds = sorted(k for k in picked if k[0] in pdict)
    C = pd.read_parquet(f"{store.OUT}/comment_text.parquet").sort_values("date")
    Cg = C.groupby("person").apply(lambda g: list(zip(g.date, g.slug, g.text)), include_groups=False).to_dict()
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    lineups = {}
    for i, d in day.items():
        lineups.setdefault(d, []).append(i)
    out = []
    for u, d in random.Random(seed).sample(pds, n):
        h = [it for dt, it in hist.get(u, []) if dt < d]
        c = card(pdict[u], list(range(len(h))), {k: names[it] for k, it in enumerate(h)}, d)
        cs = [(dt, sl, t) for dt, sl, t in Cg.get(u, []) if dt < d][-5:]
        if cs:
            c += " | their comments: " + " / ".join(f"on {slug2name.get(sl, sl)[:40]}: \"{t[:160]}\"" for dt, sl, t in cs)
        line = sorted(lineups[d])
        prompt = f"{INSTR}\n\nPerson: {c}\n\nLaunches:\n" + "\n".join(f"{k + 1}. {names[x]}" for k, x in enumerate(line))
        answer = json.dumps({"upvoted": [k + 1 for k, x in enumerate(line) if x in picked[(u, d)]]})
        out.append((prompt, answer))
    return out, len(pds)


def count(text, tok):
    r = requests.post(COUNT, json={"contents": [{"role": "user", "parts": [{"text": text}]}]},
                      headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    return r.json()["totalTokens"]


def main(n=200):
    ex, total_days = examples(n)
    tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
    with ThreadPoolExecutor(16) as pool:
        t = list(pool.map(lambda pa: count(pa[0], tok) + count(pa[1], tok), ex))
    mean = float(np.mean(t)); tokens = mean * total_days
    res = {"sample": n, "sep_active_person_days": total_days, "tokens_per_example_mean": round(mean),
           "tokens_per_example_p90": int(np.percentile(t, 90)), "dataset_tokens": int(tokens),
           "cost_usd_by_epochs": {m: {e: round(tokens * e * p / 1e6, 2) for e in (1, 3, 5)} for m, p in PRICE.items()}}
    json.dump(res, open(f"{HERE}/reports/ft_cost.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
