"""Listwise Gemini picker: Gemini sees one person's past upvotes (name + tagline, all before the day) and the day's full
line-up (shuffled, no votes or ranks shown), and names the 3 launches that person most likely upvoted. Scored on real
October person-days (people who voted that day) against the taste person model trained on September (popscore TASTE
inputs) and a random pick. Same person-days for all.
usage: python -m simlab.llm_pick [n_person_days] [workers] -> reports/llm_pick.json, cache/llm_pick.jsonl"""
import json, os, re, sys, random
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, lightgbm as lgb
from . import choice, popscore as PS
from .page_choice import page_table
from .page_taste import add_taste, traits

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ph_predict"))
import llm  # noqa: E402

CACHE = f"{HERE}/cache/llm_pick.jsonl"


def prompt(hist, line):
    h = "\n".join(f"- {n}: {t}" for n, t in hist)
    l = "\n".join(f"{k}. {n}: {t}" for k, (n, t) in enumerate(line, 1))
    return (f"A Product Hunt member upvoted these launches in the past (most recent first):\n{h}\n\n"
            f"Today's launches:\n{l}\n\nWhich 3 of today's launches did this member most likely upvote? Judge by their taste "
            'and interests from their past upvotes. Reply with JSON only: {"picks": [three numbers from the list]}')


def main(n, workers):
    PS.load(); traits()
    from . import harness
    harness.baseline()
    g = PS.load(); I = g["I"].set_index("id"); E = g["E"]
    T = page_table(); pc = list(T.columns); cf = PS.fit_cf("2026-09-01"); rng = np.random.default_rng(0)

    def sample(D, k):
        keep = set()
        for d, x in D.groupby("day"):
            keep |= {u + "|" + d for u in rng.permutation(x.person.unique())[:k]}
        return D[D.g.isin(keep)].copy()

    def prep(D):
        D = PS.featurize(D, cf, "2026-09-01"); D, tc = add_taste(D)
        return D.join(T, on="id"), tc
    tr, tc = prep(sample(choice.rows(day_from="2026-09-01", day_to="2026-09-30"), 300))
    te = choice.rows(day_from="2026-10-01", day_to="2026-10-24")
    Es = E.sort_values("date"); hist = {u: list(zip(x.date, x.item.astype(str))) for u, x in Es.groupby("person")}
    gs = [x for x, y in te.groupby("g") if 0 < y.y.sum() < len(y) and sum(1 for d, _ in hist.get(x.split("|")[0], []) if d < x.split("|")[1]) >= 5]
    pick = set(random.Random(0).sample(gs, min(n, len(gs))))
    te, _ = prep(te[te.g.isin(pick)].copy())
    cols = PS.FEATS + pc + tc
    te["s_model"] = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, colsample_bytree=0.5,
                                       verbose=-1, n_jobs=8).fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]
    done = {}
    if os.path.exists(CACHE):
        for l in open(CACHE):
            r = json.loads(l); done[r["g"]] = r["picks"]

    def ask(key):
        u, d = key.split("|")
        rows = te[te.g == key]
        ids = list(rows.id); random.Random(key).shuffle(ids)
        h = [(I.loc[i, "name"], I.loc[i, "tagline"]) for dt, i in reversed(hist[u]) if dt < d and i in I.index][:30]
        txt = llm.call(prompt(h, [(I.loc[i, "name"], I.loc[i, "tagline"]) for i in ids]), max_tokens=60)
        m = re.search(r'"picks"\s*:\s*\[([^\]]*)\]', txt or "")
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))] if m else []
        return {"g": key, "picks": [ids[k - 1] for k in nums if 1 <= k <= len(ids)][:3]}
    todo = [k for k in pick if k not in done]
    with ThreadPoolExecutor(workers) as ex, open(CACHE, "a") as f:
        for r in ex.map(ask, todo):
            done[r["g"]] = r["picks"]; f.write(json.dumps(r) + "\n"); f.flush()
    hit = {"gemini": [], "model": [], "random": [], "gemini+model": []}
    for key, x in te.groupby("g"):
        real = set(x.id[x.y == 1]); gp = done.get(key, [])
        mp_ = list(x.sort_values("s_model", ascending=False).id)
        hit["gemini"].append(bool(real & set(gp)))
        hit["model"].append(bool(real & set(mp_[:3])))
        hit["random"].append(1 - np.prod([(len(x) - len(real) - j) / (len(x) - j) for j in range(3)]))
        both = [i for i in gp if i in mp_[:6]] + [i for i in mp_ if i not in gp]   # Gemini picks the model also likes first
        hit["gemini+model"].append(bool(real & set(both[:3])))
    res = {k: round(100 * float(np.mean(v)), 1) for k, v in hit.items()}
    res.update({"person_days": len(hit["model"]), "gemini_answered": sum(1 for k in pick if done.get(k)),
                "usd": round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 3)})
    json.dump(res, open(f"{HERE}/reports/llm_pick.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20, int(sys.argv[2]) if len(sys.argv) > 2 else 8)
