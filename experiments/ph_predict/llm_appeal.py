import json, os, random, sys
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
from scipy.stats import spearmanr
sys.path.insert(0, "/home/user/UserSim/experiments/ph_predict"); import llm
S = os.path.dirname(os.path.abspath(__file__)); OUT = f"{S}/appeal_v1"; os.makedirs(OUT, exist_ok=True)
L = pd.read_parquet(f"{S}/launches.parquet").set_index("id")
rows = json.load(open(f"{S}/llmu_v1/sample.json"))
days = sorted({r["day"] for r in rows}); lineup = {r["day"]: r["lineup"] for r in rows}
def one(d, s):
    f = f"{OUT}/{d}_{s}.json"
    if os.path.exists(f): return
    order = list(lineup[d]); random.Random(f"{d}{s}").shuffle(order)
    def item(n, i):
        x = L.loc[i]; tp = ", ".join(json.loads(x.topics)[:4]) if x.topics else ""
        return f"{n}. {x['name']} — {x.tagline}\n   {str(x.description or '')[:500]}\n   Topics: {tp}"
    p = ("You are simulating the Product Hunt community on one launch day. Below are all of today's launches. "
         "Product Hunt voters are mostly makers, developers, designers, founders and marketers who like useful, novel, "
         "clearly explained products. For each launch estimate what percent of today's active voters would upvote it "
         "(they upvote about 2 or 3 launches each), judging only from what the product is.\n\n"
         + "\n".join(item(n + 1, i) for n, i in enumerate(order)) +
         "\n\nReturn JSON: {\"scores\": {\"<number>\": <percent 0-100>, ...}} with every launch number.")
    t = llm.gemini_call(p, 3000)
    try: sc = {order[int(k) - 1]: float(v) for k, v in json.loads(t)["scores"].items()}
    except Exception: sc = {}
    json.dump(sc, open(f, "w"))
with ThreadPoolExecutor(6) as ex: list(ex.map(lambda a: one(*a), [(d, s) for d in days for s in range(4)]))
A = {}
for d in days:
    acc = {}
    for s in range(4):
        for i, v in json.load(open(f"{OUT}/{d}_{s}.json")).items(): acc.setdefault(i, []).append(v)
    A[d] = {i: float(np.mean(v)) for i, v in acc.items()}
json.dump(A, open(f"{OUT}/appeal.json", "w"))
sp, t3, t5, t10 = [], [], [], []
for d in days:
    ids = [i for i in lineup[d] if i in A[d]]; v = [L.votes[i] for i in ids]; a = [A[d][i] for i in ids]
    sp.append(spearmanr(a, v).correlation)
    real = sorted(ids, key=lambda i: -L.votes[i]); pred = sorted(ids, key=lambda i: -A[d][i])
    for k, t in ((3, t3), (5, t5), (10, t10)): t.append(len(set(real[:k]) & set(pred[:k])) / k)
print("days", len(days), "within-day Spearman appeal vs votes %.3f" % np.mean(sp), "top3/5/10 %.1f/%.1f/%.1f" % (100*np.mean(t3), 100*np.mean(t5), 100*np.mean(t10)))
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("BAAI/bge-small-en-v1.5")
ids = sorted({i for r in rows for i in r["hist"] + r["lineup"]})
V = dict(zip(ids, m.encode([f"{L.loc[i]['name']}. {L.loc[i].tagline}. {str(L.loc[i].description or '')[:400]}" for i in ids], normalize_embeddings=True, batch_size=128)))
res = {k: [] for k in ("app1", "app3", "mix1", "mix3", "u_app3", "u_mix3")}
for r in rows:
    P = set(r["picks"]); a = A[r["day"]]; c = np.mean([V[i] for i in r["hist"]], 0)
    lu = [i for i in r["lineup"] if i in a]
    za = pd.Series({i: a[i] for i in lu}); ze = pd.Series({i: float(V[i] @ c) for i in lu})
    z = (za - za.mean()) / (za.std() + 1e-9) + (ze - ze.mean()) / (ze.std() + 1e-9)
    oa = za.sort_values(ascending=False).index.tolist(); om = z.sort_values(ascending=False).index.tolist()
    res["app1"].append(oa[0] in P); res["app3"].append(bool(set(oa[:3]) & P)); res["mix1"].append(om[0] in P); res["mix3"].append(bool(set(om[:3]) & P))
    un = {p for p, t in zip(r["picks"], r["tied"]) if not t}
    if un: res["u_app3"].append(bool(set(oa[:3]) & un)); res["u_mix3"].append(bool(set(om[:3]) & un))
print({k: round(float(np.mean(v)), 3) for k, v in res.items()})
