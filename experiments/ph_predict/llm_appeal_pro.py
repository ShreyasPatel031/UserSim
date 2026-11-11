import json, os, random, sys, urllib.request, time
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
from scipy.stats import spearmanr
sys.path.insert(0, "/home/user/UserSim/experiments/ph_predict"); import llm
S = os.path.dirname(os.path.abspath(__file__)); OUT = f"{S}/appeal_pro"; os.makedirs(OUT, exist_ok=True)
URL = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-pro:generateContent"
L = pd.read_parquet(f"{S}/launches.parquet").set_index("id")
rows = json.load(open(f"{S}/llmu_v1/sample.json")); days = sorted({r["day"] for r in rows}); lineup = {r["day"]: r["lineup"] for r in rows}
def call(p):
    body = {"contents": [{"role": "user", "parts": [{"text": p}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 12000, "responseMimeType": "application/json"}}
    for i in range(4):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + llm.token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r: return json.load(r)["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e: print("retry", str(e)[:100], flush=True); time.sleep(5 * (i + 1))
    return ""
def one(d, s):
    f = f"{OUT}/{d}_{s}.json"
    if os.path.exists(f): return
    order = list(lineup[d]); random.Random(f"{d}{s}").shuffle(order)
    def item(n, i):
        x = L.loc[i]; tp = ", ".join(json.loads(x.topics)[:4]) if x.topics else ""
        return f"{n}. {x['name']} — {x.tagline}\n   {str(x.description or '')[:800]}\n   Topics: {tp}"
    p = ("You are forecasting one Product Hunt launch day. Below are all of today's launches (no vote data). Think about which "
         "products the Product Hunt community (makers, developers, designers, founders, marketers) will upvote most by the end "
         "of the day: usefulness, novelty, clarity, breadth of audience, timeliness, and how share-worthy it is. "
         "Rank ALL launches from most to fewest expected upvotes.\n\n" + "\n".join(item(n + 1, i) for n, i in enumerate(order)) +
         "\n\nReturn JSON: {\"ranking\": [launch numbers, best first, every launch exactly once]}")
    t = call(p)
    try: rk = [order[int(k) - 1] for k in json.loads(t)["ranking"]]
    except Exception: rk = []
    json.dump(rk, open(f, "w"))
with ThreadPoolExecutor(5) as ex: list(ex.map(lambda a: one(*a), [(d, s) for d in days for s in range(2)]))
sp, t3, t5, t10 = [], [], [], []
A = {}
for d in days:
    pos = {}
    for s in range(2):
        rk = json.load(open(f"{OUT}/{d}_{s}.json"))
        for n, i in enumerate(rk): pos.setdefault(i, []).append(n)
    ids = [i for i in lineup[d] if i in pos]
    if len(ids) < 5: continue
    a = {i: -float(np.mean(pos[i])) for i in ids}; A[d] = a
    sp.append(spearmanr([a[i] for i in ids], [L.votes[i] for i in ids]).correlation)
    real = sorted(ids, key=lambda i: -L.votes[i]); pred = sorted(ids, key=lambda i: -a[i])
    for k, t in ((3, t3), (5, t5), (10, t10)): t.append(len(set(real[:k]) & set(pred[:k])) / k)
json.dump(A, open(f"{OUT}/appeal.json", "w"))
print("pro days", len(sp), "Spearman %.3f" % np.mean(sp), "top3/5/10 %.1f/%.1f/%.1f" % (100*np.mean(t3), 100*np.mean(t5), 100*np.mean(t10)))
h3 = [bool(set(sorted(A[r["day"]], key=lambda i: -A[r["day"]][i])[:3]) & set(r["picks"])) for r in rows if r["day"] in A]
print("Hit@3 on person-days %.3f" % np.mean(h3))
