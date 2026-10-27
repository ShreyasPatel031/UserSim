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

OUT = f"{CACHE}/taste_ratings.jsonl"
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
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    pds = sorted({(u, d) for u, d in zip(real.person, real.date) if u in pdict})
    rng = random.Random(seed)
    pick = rng.sample([x for x in pds if x[1] < "2026-10-01"], n) + rng.sample([x for x in pds if x[1] >= "2026-10-01"], n)
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
        posts = [q for q in X.get(str(p.get("twitter") or "").lower(), []) if (q.get("created_at") or "9") < d][:3]
        if posts:
            c += " | recent X posts: " + " / ".join((q.get("text") or "")[:120].replace("\n", " ") for q in posts)
        revs = [f"{r[0]} {r[1]}/5" for r in json.loads(p["reviews"]) if r[2] and r[2] < d][:5] if isinstance(p.get("reviews"), str) else []
        if revs:
            c += " | reviewed: " + ", ".join(revs)
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


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 1500, int(sys.argv[3]) if len(sys.argv) > 3 else 50)
    else:
        score()
