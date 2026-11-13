"""Re-centred / shrunk backer mix + forecast value of the mix signal (orchestrator 19:20Z Nov 13). Input: who_mix2.py per-launch rows
(ROWS=...). Arms (all known at 00:05): RAW model mix; RECENTRED = day baseline + (model mix - the model's mean mix over that day's
line-up); SHRUNK = day baseline + s x (same deviation), s per family picked walk-forward (grid 0, .1, ..., 1; minimise MAE over
launches on earlier days only; s = 0 on the first day). Same metrics and pass bar as who_mix2.py (beats day AND topic baselines on MAE
with interval < 0 in >= 2 families). Forecast value: residual = within-day rank by clean_v3_nosite minus final rank (positive = did
better than the clean forecast); correlation with the model's predicted deviation in (a) 5+ vote-tier share (skews heavy users),
(b) 1-vote-tier share, (c) <30-day account share, (d) maker share; PLACEBO row = number of held team members (all named makers);
launches with >= 20 held backers and all launches; day-bootstrap intervals. Counts only.
    python mix_eval.py <rows.pkl> <clean_live_rows_nosite.parquet> <launches dir> <store dir> <salt dir> <out dir>
"""
import glob, hashlib, json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
RP, CP, LD, ST, SD, OUT = sys.argv[1:7]; rng = np.random.default_rng(0)
rows = pickle.load(open(RP, "rb")); C = pd.read_parquet(CP); C["id"] = C.id.astype(str)
FAM = ["age", "tier_k", "tier_30", "maker", "topic"]; SEGS = {f: list(rows[0]["pred"][f].keys()) for f in FAM}
days = sorted({r["day"] for r in rows})
for d in days:   # model's own mean mix over the day's line-up
    R = [r for r in rows if r["day"] == d]
    for f in FAM:
        mu = {s: np.mean([r["pred"][f][s] for r in R]) for s in SEGS[f]}
        for r in R: r.setdefault("dev", {})[f] = {s: r["pred"][f][s] - mu[s] for s in SEGS[f]}
V = [r for r in rows if r["day_b"] is not None]
for r in V: r["rc"] = {f: {s: r["day_b"][f][s] + r["dev"][f][s] for s in SEGS[f]} for f in FAM}
mae = lambda a, b, f: np.mean([abs(a[f][s] - b[f][s]) * 100 for s in SEGS[f]])
grid = np.round(np.arange(0, 1.01, 0.1), 2); S = {}
for d in days:
    prev = [r for r in V if r["day"] < d and r["n_back"] >= 20]
    for f in FAM:
        S[(d, f)] = 0.0 if not prev else float(min(grid, key=lambda s: np.mean([mae({f: {k: r["day_b"][f][k] + s * r["dev"][f][k] for k in SEGS[f]}}, r["act"], f) for r in prev])))
for r in V: r["sh"] = {f: {s: r["day_b"][f][s] + S[(r["day"], f)] * r["dev"][f][s] for s in SEGS[f]} for f in FAM}
def lb(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2), len(v)]
def score(RR, arm):
    o = {}
    for f in FAM:
        m = np.array([mae(r[arm], r["act"], f) for r in RR]); dd = np.array([mae(r["day_b"], r["act"], f) for r in RR]); tt = np.array([mae(r["top_b"], r["act"], f) for r in RR])
        o[f] = {"MAE model / day / topic": [lb(m)[0], lb(dd)[0], lb(tt)[0]], "model - day": lb(m - dd), "model - topic": lb(m - tt)}
    o["families beating BOTH (interval < 0)"] = [f for f in FAM if o[f]["model - day"][2] < 0 and o[f]["model - topic"][2] < 0]
    return o
R20 = [r for r in V if r["n_back"] >= 20]; R5 = [r for r in R20 if r["n_back"] / r["votes"] >= 0.5]
res = {"launches >= 20 held backers": len(R20), "coverage >= 0.5 subset": len(R5),
       "walk-forward s per family (last test day)": {f: S[(days[-1], f)] for f in FAM}}
for arm, nm in (("pred", "RAW"), ("rc", "RECENTRED"), ("sh", "SHRUNK (walk-forward s)")):
    res[nm] = {"all": score(R20, arm), "coverage >= 0.5": score(R5, arm)}
# forecast value
C["crank"] = C.groupby("day").clean_v3_nosite.rank(ascending=False); C["resid"] = C.crank - C["rank"]
cr = dict(zip(C.id, C.resid))
salt = open(os.path.join(SD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
comp = set(pd.read_parquet(os.path.join(ST, "persons.parquet")).query("complete").person_id)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LD, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
def mk(m):
    try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
nt = {i: sum(pid(h) in comp for h in dict.fromkeys(([p] if isinstance(p, str) and p and not p.startswith("[") else []) + mk(m))) for i, p, m in zip(L.id, L.poster, L.makers)}
F = pd.DataFrame([{"id": r["id"], "day": r["day"], "n_back": r["n_back"], "resid": cr.get(r["id"]), "heavy": r["dev"]["tier_k"]["5+"], "one": r["dev"]["tier_k"]["1"],
                   "young": r["dev"]["age"]["<30d"], "maker": r["dev"]["maker"]["maker"], "placebo_team_held": nt.get(r["id"], 0)} for r in rows]).dropna(subset=["resid"])
def dcorr(G, c):
    ds = G.day.unique(); f = lambda X: spearmanr(X[c], X.resid).correlation
    bs = [f(pd.concat([G[G.day == x] for x in rng.choice(ds, len(ds))])) for _ in range(1000)]
    return [round(float(f(G)), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3), len(G)]
res["forecast value: Spearman(predicted mix deviation, clean-rank residual), day bootstrap"] = {
    sub: {c: dcorr(G, c) for c in ("heavy", "one", "young", "maker", "placebo_team_held")} for sub, G in (("all launches", F), (">= 20 held backers", F[F.n_back >= 20]))}
json.dump(res, open(os.path.join(OUT, "mix_eval.json"), "w"), indent=1, default=float); print(json.dumps(res, default=float))
