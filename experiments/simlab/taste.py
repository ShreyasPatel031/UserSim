"""Persona taste factor: for a person on a day they were active, the persona rates how well EVERY launch in that day's
line-up fits the person's own interests (1-5), told to ignore who made it and how popular it is. That rating becomes
the taste factor in the choice model, beside popularity and relationships (simlab/choice.py).
Evidence on the card, all before the day except the undated profile parts: segment labels, PH and LinkedIn
headlines, X bio and recent posts, tools used, reviews written, the launches they backed most recently.
Test: same Sep-train / Oct-test split as choice.py; does adding the persona rating beat 53.9% top-3 hit and 0.808 AUC?
usage: python -m simlab.taste run [n_per_month] [threads]; python -m simlab.taste score"""
import gzip, json, os, random, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from . import store, choice
from .persona import CACHE, card, gemini

V2 = os.environ.get("TASTE_V2") == "1"  # v2: the card also shows the person's own past choices (picked vs skipped)
V3 = os.environ.get("TASTE_V3") == "1"  # v3: the v1 card + the person's own comment texts (best in the evidence screen)
OUT = f"{CACHE}/taste_v3_ratings.jsonl" if V3 else f"{CACHE}/taste_v2_ratings.jsonl" if V2 else f"{CACHE}/taste_ratings.jsonl"
PROMPT = """Rate how well each Product Hunt launch below fits THIS person's own interests and work, from 1 (irrelevant
to them) to 5 (exactly what they care about). Judge only fit with the person: ignore who made it and how popular it is.
Use the whole scale; most launches are a poor fit for any one person.

Person: {card}

Launches:
{lineup}

Reply with JSON only: {{"ratings": [<rating for launch 1>, <launch 2>, ...]}} with exactly {n} numbers."""
lock = threading.Lock()


def x_posts():
    out = {}
    for f in ("x_people", "commenter_x"):
        p = os.path.join(store.RAW, f"{f}.jsonl.gz")
        if os.path.exists(p):
            for l in gzip.open(p, "rt"):
                r = json.loads(l)
                if r.get("posts"):
                    out[r["handle"].lower()] = r["posts"]
    return out


def run(n=1500, threads=50, seed=0):
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); names = {r.id: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    real = E[(E.item.map(day) == E.date) & E.date.between("2026-09-01", "2026-10-24")]
    pdict = P.set_index("person").to_dict("index"); X = x_posts()
    slug2name = {r.slug: f"{r.name}: {r.tagline}" for r in I.itertuples()}
    Cg = {}
    if V3:
        C = pd.read_parquet(f"{store.OUT}/comment_text.parquet").sort_values("date")
        Cg = C.groupby("person").apply(lambda g: list(zip(g.date, g.slug, g.text)), include_groups=False).to_dict()
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    pds = sorted({(u, d) for u, d in zip(real.person, real.date) if u in pdict})
    rng = random.Random(seed)
    sep = [x for x in pds if x[1] < "2026-10-01"]; octo = [x for x in pds if x[1] >= "2026-10-01"]
    pick = rng.sample(sep, min(n, len(sep))) + rng.sample(octo, min(n, len(octo)))
    by_day = {}
    for i, dd in day.items():
        by_day.setdefault(dd, []).append(i)
    picked = E[E.item.map(day) == E.date].groupby(["person", "date"]).item.apply(list).to_dict()
    past_days = {}
    for (u0, d0) in picked:
        past_days.setdefault(u0, []).append(d0)
    done = {(json.loads(l)["person"], json.loads(l)["day"]) for l in open(OUT)} if os.path.exists(OUT) else set()
    pick = [x for x in pick if x not in done]
    lineups = {d: sorted(i for i, dd in day.items() if dd == d) for d in {d for _, d in pick}}
    print("person-days", len(pick), flush=True)

    def one(ud):
        u, d = ud; p = pdict[u]; line = lineups[d]
        h = [it for dt, it in hist.get(u, []) if dt < d]
        c = card(p, list(range(len(h))), {k: names[it] for k, it in enumerate(h)}, d)
        if isinstance(p.get("x_bio"), str) and p["x_bio"]:
            c += f" | X bio: {p['x_bio'][:160]}"
        posts = [] if V3 else [q for q in X.get(str(p.get("twitter") or "").lower(), []) if (q.get("created_at") or "9") < d][:3]
        if posts:
            c += " | recent X posts: " + " / ".join((q.get("text") or "")[:120].replace("\n", " ") for q in posts)
        revs = [f"{r[0]} {r[1]}/5" for r in json.loads(p["reviews"]) if r[2] and r[2] < d][:5] if (isinstance(p.get("reviews"), str) and not V3) else []
        if revs:
            c += " | reviewed: " + ", ".join(revs)
        if V3:
            cs = [(dt, sl, t) for dt, sl, t in Cg.get(u, []) if dt < d][-5:]
            if cs:
                c += " | their comments: " + " / ".join(f"on {slug2name.get(sl, sl)[:40]}: \"{t[:160]}\"" for dt, sl, t in cs)
        if V2:  # few-shot: up to 3 earlier days this person was active, what they upvoted and some launches they skipped
            ex = []
            r2 = random.Random(hash((u, d)) & 0xFFFF)
            for d0 in sorted(x for x in past_days.get(u, []) if x < d)[-3:]:
                up = picked[(u, d0)]; sk = [i for i in by_day.get(d0, []) if i not in up]
                ex.append(f"on {d0} upvoted: " + "; ".join(names[i] for i in up[:3]) + " | skipped: " +
                          "; ".join(names[i] for i in r2.sample(sk, min(4, len(sk)))))
            if ex:
                c += "\nTheir past choices (learn their taste from these): " + " || ".join(ex)
        txt = gemini(PROMPT.format(card=c, lineup="\n".join(f"{k + 1}. {names[x]}" for k, x in enumerate(line)), n=len(line)))
        try:
            rt = [float(v) for v in json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["ratings"]]
        except Exception:  # noqa: BLE001
            rt = []
        if len(rt) == len(line):
            with lock, open(OUT, "a") as f:
                f.write(json.dumps({"person": u, "day": d, "ratings": dict(zip(line, rt))}) + "\n")

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, pick))


def score():
    R = {}
    for l in open(OUT):
        r = json.loads(l); R[r["person"] + "|" + r["day"]] = r["ratings"]
    D = choice.rows()
    D = D[D.g.isin(R)].copy()
    D["persona"] = [R[g].get(i, np.nan) for g, i in zip(D.g, D.id)]
    D = D.dropna(subset=["persona"])
    D["persona"] = D.groupby("g").persona.rank(pct=True)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    print(f"person-days with ratings: train {tr.g.nunique()}, test {te.g.nunique()}")
    rows = []
    for name, cols in [("popularity + relationships", ["pop", "follow", "backed"]),
                       ("+ taste (topic, meaning)", ["pop", "follow", "backed", "topic", "meaning"]),
                       ("+ persona taste", ["pop", "follow", "backed", "persona"]),
                       ("+ taste + persona taste", ["pop", "follow", "backed", "topic", "meaning", "persona"]),
                       ("persona taste alone", ["persona"])]:
        m = LogisticRegression(max_iter=2000).fit(tr[cols], tr.y)
        hit, auc = choice.person_metrics(te, m.predict_proba(te[cols])[:, 1])
        rows.append({"model": name, "top-3 hit": f"{hit:.1%}", "AUC": round(auc, 3), "weights": dict(zip(cols, np.round(m.coef_[0], 2)))})
    print(pd.DataFrame(rows).to_string(index=False))


def compare():
    """v1 vs v2 personas, small vs full training data, linear vs trees; same Oct test person-days for all."""
    import lightgbm as lgb
    def load(path):
        R = {}
        for l in open(path):
            r = json.loads(l); R[r["person"] + "|" + r["day"]] = r["ratings"]
        return R
    R1, R2, R3 = load(f"{CACHE}/taste_ratings.jsonl"), load(f"{CACHE}/taste_v2_ratings.jsonl"), load(f"{CACHE}/taste_v3_ratings.jsonl")
    D = choice.rows(); D = D[D.g.isin(set(R1) & set(R2) & set(R3))].copy()
    for k, R in (("p1", R1), ("p2", R2), ("p3", R3)):
        D[k] = [R[g].get(i, np.nan) for g, i in zip(D.g, D.id)]
    D = D.dropna(subset=["p1", "p2", "p3"])
    for k in ("p1", "p2", "p3"):
        D[k] = D.groupby("g")[k].rank(pct=True)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    small = tr[tr.g.isin(pd.Series(tr.g.unique()).sample(1500, random_state=0))]
    print(f"person-days: train {tr.g.nunique()} (small {small.g.nunique()}), test {te.g.nunique()}")
    base = ["pop", "follow", "backed", "topic", "meaning"]
    def gbm(t, c):
        return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1).fit(t[c], t.y).predict_proba(te[c])[:, 1]
    rows = []
    for nm, c in [("popularity + relationships + simple taste", base), ("+ persona v1", base + ["p1"]),
                  ("+ persona v2 (past choices)", base + ["p2"]), ("+ both personas", base + ["p1", "p2"]),
                  ("+ persona v3 (comments)", base + ["p3"]), ("+ all three personas", base + ["p1", "p2", "p3"]),
                  ("persona v3 alone", ["p3"]),
                  ("persona v1 alone", ["p1"]), ("persona v2 alone", ["p2"])]:
        for tn, t in (("small", small), ("full", tr)):
            hit, auc = choice.person_metrics(te, gbm(t, c))
            rows.append({"model": nm, "train": tn, "top-3 hit": f"{hit:.1%}", "AUC": round(auc, 3)})
    print(pd.DataFrame(rows).pivot(index="model", columns="train", values=["AUC", "top-3 hit"]).to_string())


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 1500, int(sys.argv[3]) if len(sys.argv) > 3 else 50)
    elif sys.argv[1] == "compare":
        compare()
    else:
        score()
