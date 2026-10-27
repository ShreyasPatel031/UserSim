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

# config name -> evidence added to the card (v1 profile card unless "noprofile")
CONFIGS = {"v1": set(), "c": {"comments"}, "c10": {"comments10"}, "c+r": {"comments", "reviews"},
           "c+r+b": {"comments", "reviews", "built"}, "c+x": {"comments", "xposts"}, "c+ch": {"comments", "choices"},
           "c+r+ch": {"comments", "reviews", "choices"}, "everything": {"comments10", "reviews", "built", "xposts", "history", "choices"},
           "c_noprofile": {"comments", "noprofile"}, "best4": {"comments", "reviews", "choices", "built"},
           # retrieval: the person's past comments / backed launches most related to today's line-up (not just the latest)
           "c_ret": {"comments_ret", "history_ret"},
           # ensemble members: a second Gemini sample of the comments card, and Claude on the same card
           "c_s2": {"comments"}, "c_claude": {"comments", "claude"}}
VARIANTS = list(CONFIGS)
lock = threading.Lock()


def sample(seed=1, n=1000):
    R = {}
    for l in open(f"{CACHE}/taste_ratings.jsonl"):
        r = json.loads(l); R[(r["person"], r["day"])] = 1
    keys = sorted(R); rng = random.Random(seed)
    return rng.sample([k for k in keys if k[1] < "2026-10-01"], n) + rng.sample([k for k in keys if k[1] >= "2026-10-01"], n)


def run(threads=16, only=None, full=False):
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); names = {r.id: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    slug2name = {r.slug: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    pdict = P.set_index("person").to_dict("index"); X = x_posts()
    C = pd.read_parquet(f"{store.OUT}/comment_text.parquet").sort_values("date")
    Cg = C.groupby("person").apply(lambda g: list(zip(g.date, g.slug, g.text)), include_groups=False).to_dict()
    Rv = pd.read_parquet(f"{store.OUT}/review_text.parquet").sort_values("date")
    Rg = Rv.groupby("person").apply(lambda g: list(zip(g.date, g["product"], g.rating, g.pros, g.cons)), include_groups=False).to_dict()
    import numpy as np
    Zl = np.load(f"{store.RAW}/emb.npz"); lix = {x: k for k, x in enumerate(Zl["launch_ids"])}; LE = Zl["launch"]
    CV = np.load(f"{store.OUT}/comment_vecs.npy") if os.path.exists(f"{store.OUT}/comment_vecs.npy") else None
    Cfull = pd.read_parquet(f"{store.OUT}/comment_vec_text.parquet") if os.path.exists(f"{store.OUT}/comment_vec_text.parquet") else pd.read_parquet(f"{store.OUT}/comment_text.parquet")
    Cidx = Cfull.reset_index().groupby("person").apply(lambda g: list(zip(g.date, g.slug, g.text, g["index"])), include_groups=False).to_dict()
    built = {}
    for r in I.itertuples():
        for u in set(json.loads(r.makers)) | {r.poster}:
            built.setdefault(u, []).append((r.day, names[r.id]))
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    lineups = {}
    for i, dd in day.items():
        lineups.setdefault(dd, []).append(i)
    if full:  # every person-day already rated by v1 (all Sep-Oct active person-days)
        S = sorted({(json.loads(l)["person"], json.loads(l)["day"]) for l in open(f"{CACHE}/taste_ratings.jsonl")})
    else:
        S = sample()
    out_name = (lambda k: f"{CACHE}/taste_{k}_full.jsonl") if full else (lambda k: f"{CACHE}/variant_{k}.jsonl")
    kinds = [only] if only else VARIANTS
    done = set()
    for k in kinds:
        if os.path.exists(out_name(k)):
            done |= {(k, json.loads(l)["person"], json.loads(l)["day"]) for l in open(out_name(k))}

    picked = E[E.item.map(day) == E.date].groupby(["person", "date"]).item.apply(list).to_dict()
    past_days = {}
    for (u0, d0) in picked:
        past_days.setdefault(u0, []).append(d0)

    def extra(kind, u, d, p, h):
        ev = CONFIGS[kind]; out = []
        if "comments_ret" in ev and CV is not None:
            L = LE[[lix[x] for x in lineups[d] if x in lix]]
            cs = [x for x in Cidx.get(u, []) if x[0] < d]
            if cs and len(L):
                sim = (CV[[x[3] for x in cs]].astype(np.float32) @ L.T).max(1)
                top = [cs[j] for j in np.argsort(-sim)[:5]]
                out.append("their comments most related to today's launches: " + " / ".join(f"on {slug2name.get(s2, s2)[:40]}: \"{t[:160]}\"" for _, s2, t, _ in top))
        if "history_ret" in ev and h:
            L = LE[[lix[x] for x in lineups[d] if x in lix]]
            hh = [i for i in h if i in lix]
            if hh and len(L):
                sim = (LE[[lix[i] for i in hh]] @ L.T).max(1)
                out.append("launches they backed most related to today's: " + "; ".join(names[hh[j]] for j in np.argsort(-sim)[:6]))
        if ev & {"comments", "comments10"}:
            cs = [(dt, s, t) for dt, s, t in Cg.get(u, []) if dt < d][-(10 if "comments10" in ev else 5):]
            if cs:
                out.append("their comments: " + " / ".join(f"on {slug2name.get(s, s)[:40]}: \"{t[:160]}\"" for dt, s, t in cs))
        if "xposts" in ev:
            ps = [q for q in X.get(str(p.get("twitter") or "").lower(), []) if (q.get("created_at") or "9") < d][:10]
            if ps:
                out.append("recent X posts: " + " / ".join((q.get("text") or "")[:120].replace("\n", " ") for q in ps))
        if "reviews" in ev:
            rv = [x for x in Rg.get(u, []) if x[0] < d][-5:]
            if rv:
                out.append("reviews written: " + "; ".join(f"{x[1]} {x[2]}/5 (likes: {x[3][:80]}; dislikes: {x[4][:60]})" for x in rv))
        if "built" in ev:
            b = [n for dt, n in built.get(u, []) if dt < d][-5:]
            if b:
                out.append("products they built or posted: " + "; ".join(b))
        if "history" in ev and len(h) > 6:
            out.append("more launches they backed: " + "; ".join(names[i] for i in h[-15:-6]))
        if "choices" in ev:
            r2 = random.Random(hash((u, d)) & 0xFFFF); ex = []
            for d0 in sorted(x for x in past_days.get(u, []) if x < d)[-3:]:
                up = picked[(u, d0)]; sk = [i for i in lineups.get(d0, []) if i not in up]
                ex.append(f"on {d0} upvoted: " + "; ".join(names[i] for i in up[:3]) + " | skipped: " + "; ".join(names[i] for i in r2.sample(sk, min(4, len(sk)))))
            if ex:
                out.append("their past choices: " + " || ".join(ex))
        return (" | " + " | ".join(out)) if out else ""

    def one(args):
        kind, (u, d) = args
        p = pdict[u]; line = sorted(lineups[d])
        h = [it for dt, it in hist.get(u, []) if dt < d]
        base_card = "" if "noprofile" in CONFIGS[kind] else card(p, list(range(len(h))), {k: names[it] for k, it in enumerate(h)}, d)
        c = (base_card + extra(kind, u, d, p, h)).strip(" |") or "no information"
        prompt = PROMPT.format(card=c, lineup="\n".join(f"{k + 1}. {names[x]}" for k, x in enumerate(line)), n=len(line))
        if "claude" in CONFIGS[kind]:
            sys.path.insert(0, os.path.join(os.path.dirname(store.RAW), ""))
            import llm
            txt = llm.call(prompt, max_tokens=400)
        else:
            txt = gemini(prompt)
        try:
            rt = [float(v) for v in json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["ratings"]]
        except Exception:  # noqa: BLE001
            rt = []
        if len(rt) == len(line):
            with lock, open(out_name(kind), "a") as f:
                f.write(json.dumps({"person": u, "day": d, "ratings": dict(zip(line, rt))}) + "\n")

    jobs = [(k, s) for k in kinds for s in S if (k, *s) not in done]
    print("requests", len(jobs), flush=True)
    with ThreadPoolExecutor(threads * len(kinds)) as ex:
        list(ex.map(one, jobs))


def score():
    import lightgbm as lgb
    def load(path):
        R = {}
        if os.path.exists(path):
            for l in open(path):
                r = json.loads(l); R[r["person"] + "|" + r["day"]] = r["ratings"]
        return R
    Rs = {k: load(f"{CACHE}/variant_{k}.jsonl") for k in VARIANTS}
    S = {u + "|" + d for u, d in sample()}
    D = choice.rows(); D = D[D.g.isin(S)].copy()
    for k, R in Rs.items():
        D[k] = [R.get(g, {}).get(i, np.nan) for g, i in zip(D.g, D.id)]
        D[k] = D.groupby("g")[k].rank(pct=True)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    base = ["pop", "follow", "backed", "topic", "meaning"]
    keep = te.dropna(subset=VARIANTS).g.unique(); te = te[te.g.isin(keep)]   # same test person-days for every config
    def gbm(c):
        t = tr.dropna(subset=c); e = te.dropna(subset=c)
        p = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=7, min_child_samples=40, verbose=-1).fit(t[c], t.y).predict_proba(e[c])[:, 1]
        return choice.person_metrics(e, p)
    rows = [{"variant": "no persona", "alone AUC": None, "with factors AUC": round(gbm(base)[1], 3)}]
    for k in VARIANTS:
        if D[k].notna().any():
            rows.append({"variant": k, "alone AUC": round(gbm([k])[1], 3), "with factors AUC": round(gbm(base + [k])[1], 3),
                         "rated": int(te.dropna(subset=[k]).g.nunique())})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 16)
    elif sys.argv[1] == "full":   # python -m simlab.variants full <config> [threads]
        run(int(sys.argv[3]) if len(sys.argv) > 3 else 96, only=sys.argv[2], full=True)
    else:
        score()
