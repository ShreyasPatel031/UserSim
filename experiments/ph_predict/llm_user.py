"""LLM-as-the-user (orchestrator, Nov 11): product-only user simulation.

For a sample of voting person-days of complete people, Gemini sees the person's past upvoted products (name, tagline;
launches dated before the test day only) and the test day's line-up (name, tagline, description, topics; shuffled; no
votes, ranks, makers or hunters) and returns the products this person is most likely to upvote, in order.

Scored per person-day: Hit@1, Hit@3 (a real pick in the top 1 / 3), against random and against an embedding-centroid
baseline on the same person-days. Also split by whether the real pick shares a maker with a launch in the person's
history ("tied") or not ("untied"): untied is the clean product-understanding number.

Inputs (local dir LLMU_DIR): events.parquet, persons.parquet (store_v3), launches.parquet (warehouse launches).
Usage: python3 llm_user.py sample | run | score          env: LLMU_N (person-days, default 400), LLMU_HIST (default 40)
"""
import json, os, random, sys, hashlib
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd

DIR = os.environ.get("LLMU_DIR", ".")
N = int(os.environ.get("LLMU_N", "400")); HIST = int(os.environ.get("LLMU_HIST", "40"))
D0, D1 = os.environ.get("LLMU_FROM", "2026-10-20"), os.environ.get("LLMU_TO", "2026-11-08")
TAG = os.environ.get("LLMU_TAG", "v1")
OUT = os.path.join(DIR, f"llmu_{TAG}"); os.makedirs(OUT, exist_ok=True)


def load():
    L = pd.read_parquet(os.path.join(DIR, "launches.parquet"))
    L["mk"] = L.makers.map(lambda s: set(json.loads(s)) if s else set()) if "makers" in L else [set()] * len(L)
    E = pd.read_parquet(os.path.join(DIR, "events.parquet"), columns=["person_id", "kind", "target_id", "fetched_at"])
    E = E[E.kind == "upvote"]
    P = pd.read_parquet(os.path.join(DIR, "persons.parquet"))
    E = E[E.person_id.isin(set(P[P.complete].person_id))]
    E = E.merge(L[["id", "day"]], left_on="target_id", right_on="id")          # upvotes on launches we hold text for
    last = E.groupby("person_id").fetched_at.max().dt.strftime("%Y-%m-%d")      # label filter: list read at d+2 or later
    return L.set_index("id"), E, last


def sample():
    L, E, last = load()
    lineup = {d: g.index.tolist() for d, g in L[(L.day >= D0) & (L.day <= D1) & L.daily_rank.notna()].groupby("day")}
    T = E[(E.day >= D0) & (E.day <= D1) & E.target_id.isin({i for v in lineup.values() for i in v})]
    rows = []
    for (p, d), g in T.groupby(["person_id", "day"]):
        if last.get(p, "") < (pd.Timestamp(d) + pd.Timedelta(days=2)).strftime("%Y-%m-%d"):
            continue
        h = E[(E.person_id == p) & (E.day < d)].sort_values("day", ascending=False)
        if len(h) < 10:
            continue
        rows.append({"person": p, "day": d, "picks": sorted(set(g.target_id)), "hist": h.target_id.tolist()[:HIST],
                     "hist_all": h.target_id.tolist()})
    random.Random(7).shuffle(rows)
    rows = rows[:N]
    for r in rows:
        hm = set().union(*[L.mk.get(i, set()) for i in r["hist_all"]]) if r["hist_all"] else set()
        r["tied"] = [bool(L.mk.get(i, set()) & hm) for i in r["picks"]]
        r["lineup"] = lineup[r["day"]]; del r["hist_all"]
    json.dump(rows, open(os.path.join(OUT, "sample.json"), "w"))
    print("person-days", len(rows), "days", len({r["day"] for r in rows}), "mean line-up", np.mean([len(r["lineup"]) for r in rows]).round(1),
          "mean picks", np.mean([len(r["picks"]) for r in rows]).round(2))


def prompt(r, L, order):
    def one(i, n=None, desc=False):
        x = L.loc[i]; s = f"{x['name']} — {x.tagline}"
        if desc:
            tp = ", ".join(json.loads(x.topics)[:4]) if x.topics else ""
            s += f"\n   {str(x.description or '')[:320]}\n   Topics: {tp}"
        return (f"{n}. " if n else "- ") + s
    hist = "\n".join(one(i) for i in r["hist"])
    cand = "\n".join(one(i, n + 1, True) for n, i in enumerate(order))
    return (f"You are simulating one real Product Hunt user. Below are products this person upvoted in the past "
            f"(most recent first). Then today's launches. Decide which of today's launches THIS person would upvote, "
            f"based only on what the products are and what this person has liked.\n\nPAST UPVOTES:\n{hist}\n\n"
            f"TODAY'S LAUNCHES:\n{cand}\n\nReturn JSON: {{\"ranking\": [the numbers of the 5 launches this person is most "
            f"likely to upvote, most likely first], \"why\": \"one short sentence about this person's taste\"}}")


def run():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import llm
    L, _, _ = load()
    rows = json.load(open(os.path.join(OUT, "sample.json")))
    def do(k):
        r = rows[k]; f = os.path.join(OUT, f"r_{k}.json")
        if os.path.exists(f):
            return
        order = list(r["lineup"]); random.Random(int(hashlib.md5(f"{r['person']}{r['day']}".encode()).hexdigest(), 16)).shuffle(order)
        txt = llm.gemini_call(prompt(r, L, order), 400)
        try:
            j = json.loads(txt); rk = [order[int(n) - 1] for n in j["ranking"] if 1 <= int(n) <= len(order)]
        except Exception:  # noqa: BLE001
            j, rk = {"raw": str(txt)[:200]}, []
        json.dump({"k": k, "rank": rk, "why": j.get("why", "")}, open(f, "w"))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(do, range(len(rows))))
    print("done", len(rows), "usage", getattr(llm, "USAGE", None))


def score():
    L, _, _ = load()
    rows = json.load(open(os.path.join(OUT, "sample.json")))
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-en-v1.5")
    ids = sorted({i for r in rows for i in r["hist"] + r["lineup"]})
    V = dict(zip(ids, m.encode([f"{L.loc[i]['name']}. {L.loc[i].tagline}. {str(L.loc[i].description or '')[:400]}" for i in ids],
                               normalize_embeddings=True, batch_size=128)))
    out = []
    for k, r in enumerate(rows):
        f = os.path.join(OUT, f"r_{k}.json")
        if not os.path.exists(f):
            continue
        rk = json.load(open(f))["rank"]
        if not rk:
            continue
        c = np.mean([V[i] for i in r["hist"]], 0)
        emb = sorted(r["lineup"], key=lambda i: -float(V[i] @ c))
        P = set(r["picks"]); n = len(r["lineup"]); kk = len(P)
        untied = {p for p, t in zip(r["picks"], r["tied"]) if not t}
        row = {"day": r["day"], "n": n,
               "llm1": rk[0] in P, "llm3": bool(set(rk[:3]) & P), "emb1": emb[0] in P, "emb3": bool(set(emb[:3]) & P),
               "rnd1": kk / n, "rnd3": 1 - np.prod([(n - kk - j) / (n - j) for j in range(3)]),
               "has_untied": bool(untied), "all_untied": len(untied) == kk}
        if untied:
            row.update({"u_llm1": rk[0] in untied, "u_llm3": bool(set(rk[:3]) & untied), "u_emb1": emb[0] in untied,
                        "u_emb3": bool(set(emb[:3]) & untied), "u_rnd3": 1 - np.prod([(n - len(untied) - j) / (n - j) for j in range(3)])})
        out.append(row)
    D = pd.DataFrame(out)
    rng = np.random.default_rng(0); days = D.day.unique()
    def ci(col, sub=None):
        X = D if sub is None else D[sub]
        X = X.dropna(subset=[col]); by = {d: g[col].astype(float).values for d, g in X.groupby("day")}
        bs = [np.concatenate([by[d] for d in rng.choice(list(by), len(by))]).mean() for _ in range(2000)]
        return f"{X[col].astype(float).mean():.3f} [{np.percentile(bs, 2.5):.3f}, {np.percentile(bs, 97.5):.3f}]"
    res = {"person_days": len(D), "days": len(days), "all": {c: ci(c) for c in ["llm1", "emb1", "rnd1", "llm3", "emb3", "rnd3"]},
           "untied_picks": {"person_days": int(D.has_untied.sum()), **{c: ci(c, D.has_untied) for c in ["u_llm1", "u_emb1", "u_llm3", "u_emb3", "u_rnd3"]}}}
    json.dump(res, open(os.path.join(OUT, "score.json"), "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"sample": sample, "run": run, "score": score}[sys.argv[1]]()
