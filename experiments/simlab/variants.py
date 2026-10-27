"""Quick screen: which extra evidence makes persona taste better? Each variant = the v1 card + one kind of evidence
(only what is dated before the day), rated on the same 600 Sep + 600 Oct person-days, all variants in parallel.
  comments  the person's own comment texts      xposts   up to 10 recent X posts
  reviews   reviews they wrote (pros / cons)     built    launches they made or posted
  history   their 15 most recent backed launches (v1 shows 6)
  all       everything above
Score (Oct half): persona taste alone, and popularity + relationships + simple taste + persona (trees, trained on
the Sep half) — compared with the v1 card on the same person-days.
usage: python -m simlab.variants run [threads_each]; python -m simlab.variants score"""
import json, os, random, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
from . import store, choice
from .persona import CACHE, card, gemini
from .taste import PROMPT, x_posts

VARIANTS = ["comments", "xposts", "reviews", "built", "history", "all"]
lock = threading.Lock()


def sample(seed=1, n=600):
    R = {}
    for l in open(f"{CACHE}/taste_ratings.jsonl"):
        r = json.loads(l); R[(r["person"], r["day"])] = 1
    keys = sorted(R); rng = random.Random(seed)
    return rng.sample([k for k in keys if k[1] < "2026-10-01"], n) + rng.sample([k for k in keys if k[1] >= "2026-10-01"], n)


def run(threads=16):
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); names = {r.id: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    slug2name = {r.slug: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    pdict = P.set_index("person").to_dict("index"); X = x_posts()
    C = pd.read_parquet(f"{store.OUT}/comment_text.parquet").sort_values("date")
    Cg = C.groupby("person").apply(lambda g: list(zip(g.date, g.slug, g.text)), include_groups=False).to_dict()
    Rv = pd.read_parquet(f"{store.OUT}/review_text.parquet").sort_values("date")
    Rg = Rv.groupby("person").apply(lambda g: list(zip(g.date, g["product"], g.rating, g.pros, g.cons)), include_groups=False).to_dict()
    built = {}
    for r in I.itertuples():
        for u in set(json.loads(r.makers)) | {r.poster}:
            built.setdefault(u, []).append((r.day, names[r.id]))
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    lineups = {}
    for i, dd in day.items():
        lineups.setdefault(dd, []).append(i)
    S = sample()

    def extra(kind, u, d, p, h):
        out = []
        if kind in ("comments", "all"):
            cs = [(dt, s, t) for dt, s, t in Cg.get(u, []) if dt < d][-5:]
            if cs:
                out.append("their comments: " + " / ".join(f"on {slug2name.get(s, s)[:40]}: \"{t[:160]}\"" for dt, s, t in cs))
        if kind in ("xposts", "all"):
            ps = [q for q in X.get(str(p.get("twitter") or "").lower(), []) if (q.get("created_at") or "9") < d][:10]
            if ps:
                out.append("recent X posts: " + " / ".join((q.get("text") or "")[:120].replace("\n", " ") for q in ps))
        if kind in ("reviews", "all"):
            rv = [x for x in Rg.get(u, []) if x[0] < d][-5:]
            if rv:
                out.append("reviews written: " + "; ".join(f"{x[1]} {x[2]}/5 (likes: {x[3][:80]}; dislikes: {x[4][:60]})" for x in rv))
        if kind in ("built", "all"):
            b = [n for dt, n in built.get(u, []) if dt < d][-5:]
            if b:
                out.append("products they built or posted: " + "; ".join(b))
        if kind in ("history", "all"):
            if len(h) > 6:
                out.append("more launches they backed: " + "; ".join(names[i] for i in h[-15:-6]))
        return (" | " + " | ".join(out)) if out else ""

    def one(args):
        kind, (u, d) = args
        p = pdict[u]; line = sorted(lineups[d])
        h = [it for dt, it in hist.get(u, []) if dt < d]
        c = card(p, list(range(len(h))), {k: names[it] for k, it in enumerate(h)}, d) + extra(kind, u, d, p, h)
        txt = gemini(PROMPT.format(card=c, lineup="\n".join(f"{k + 1}. {names[x]}" for k, x in enumerate(line)), n=len(line)))
        try:
            rt = [float(v) for v in json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["ratings"]]
        except Exception:  # noqa: BLE001
            rt = []
        if len(rt) == len(line):
            with lock, open(f"{CACHE}/variant_{kind}.jsonl", "a") as f:
                f.write(json.dumps({"person": u, "day": d, "ratings": dict(zip(line, rt))}) + "\n")

    jobs = [(k, s) for k in VARIANTS for s in S]
    print("requests", len(jobs), flush=True)
    with ThreadPoolExecutor(threads * len(VARIANTS)) as ex:
        list(ex.map(one, jobs))


def score():
    import lightgbm as lgb
    def load(path):
        R = {}
        if os.path.exists(path):
            for l in open(path):
                r = json.loads(l); R[r["person"] + "|" + r["day"]] = r["ratings"]
        return R
    Rs = {"v1": load(f"{CACHE}/taste_ratings.jsonl"), **{k: load(f"{CACHE}/variant_{k}.jsonl") for k in VARIANTS}}
    S = {u + "|" + d for u, d in sample()}
    D = choice.rows(); D = D[D.g.isin(S)].copy()
    for k, R in Rs.items():
        D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]
        D[k] = D.groupby("g")[k].rank(pct=True)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    base = ["pop", "follow", "backed", "topic", "meaning"]
    def gbm(c):
        t = tr.dropna(subset=c); e = te.dropna(subset=c)
        p = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=7, min_child_samples=40, verbose=-1).fit(t[c], t.y).predict_proba(e[c])[:, 1]
        return choice.person_metrics(e, p)
    rows = [{"variant": "no persona", "alone AUC": None, "with factors AUC": round(gbm(base)[1], 3)}]
    for k in ["v1"] + VARIANTS:
        if D[k].notna().any():
            rows.append({"variant": k, "alone AUC": round(gbm([k])[1], 3), "with factors AUC": round(gbm(base + [k])[1], 3),
                         "rated": int(te.dropna(subset=[k]).g.nunique())})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    run(int(sys.argv[2]) if len(sys.argv) > 2 else 16) if sys.argv[1] == "run" else score()
