import json, glob, os, re, numpy as np, pandas as pd
from scipy.stats import spearmanr
SP = os.environ["SP"]; D = SP + "/a2rb/ph_predict_data"; rng = np.random.default_rng(0)
def load(dirn):
    out = {}
    for f in glob.glob(f"{D}/{dirn}/*.json"):
        day = os.path.basename(f)[:-5]
        for k, v in json.load(open(f)).items():
            out[str(k)] = (day, float(v["score"] if isinstance(v, dict) else v))
    return out
meta = {}
for f in glob.glob(f"{D}/days/*.json") + glob.glob(f"{SP}/rb/h25src/*.json"):
    for x in json.load(open(f)):
        meta[str(x["id"])] = {"name": re.sub(r"[^a-z0-9]", "", (x.get("name") or "").lower()), "tag": x.get("tagline"), "desc": (x.get("description") or "")[:400]}
res = {}
def stats(a, b, step):
    a, b = np.array(a), np.array(b); n = len(a)
    bs = [np.corrcoef(a[i], b[i])[0, 1] for i in (rng.integers(0, n, n) for _ in range(2000))]
    d = np.abs(a - b)
    return {"n": n, "pearson": [round(np.corrcoef(a, b)[0, 1], 3), *np.round(np.percentile(bs, [2.5, 97.5]), 3).tolist()],
            "spearman": round(spearmanr(a, b).correlation, 3), "share_changed_>=1_step": round(float((d >= step).mean()), 3),
            "mean_abs_diff": round(float(d.mean()), 2), "sd_of_diff/sqrt2 (per-sample noise sd)": round(float(np.std(a - b) / np.sqrt(2)), 2),
            "sd_score": round(float(np.concatenate([a, b]).std()), 2)}
for mode, step in (("pitch", 5), ("brand", 1)):
    G = load(f"llm_{mode}_gemini")
    # relaunch pairs: same normalised name, different id, both scored, consecutive launches
    by = {}
    for i, (d, s) in G.items():
        if i in meta and len(meta[i]["name"]) >= 4: by.setdefault(meta[i]["name"], []).append((d, i, s))
    A, B, A2, B2 = [], [], [], []
    for nm, L in by.items():
        L.sort()
        for (d1, i1, s1), (d2, i2, s2) in zip(L, L[1:]):
            A.append(s1); B.append(s2)
            if meta[i1]["tag"] == meta[i2]["tag"] and meta[i1]["desc"] == meta[i2]["desc"]: A2.append(s1); B2.append(s2)
    res[f"{mode}: relaunch pairs (same name, different launch)"] = stats(A, B, step)
    if len(A2) >= 10: res[f"{mode}: relaunch pairs, identical tagline+description"] = stats(A2, B2, step)
    C = load(f"llm_{mode}")
    ids = [i for i in G if i in C]
    if ids: res[f"{mode}: Claude vs Gemini, same launch (inter-model, not retest)"] = stats([C[i][1] for i in ids], [G[i][1] for i in ids], step)
print(json.dumps(res, indent=1)); json.dump(res, open(f"{SP}/rb/retest_pairs.json", "w"), indent=1)
