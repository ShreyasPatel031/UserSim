"""SIM-RERANK-1 Stage A, long backtest (PREREG addendum 6c). Aggregates only.
    python rerank_a_long.py <store dir> <out json> <first day> <last day>"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from pipeline import warehouse
ST, OUT, D0, D1 = sys.argv[1:5]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); C = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[(E.kind == "upvote") & E.person_id.isin(C)][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
LD = dict(zip(W.id, W.day)); TOP = {i: (json.loads(t) if isinstance(t, str) and t.startswith("[") else []) for i, t in zip(W.id, W.topics)}
U["lday"] = pd.to_datetime(U.target_id.map(LD)); U = U.dropna(subset=["lday"])
TIX = {t: k for k, t in enumerate(sorted({t for v in TOP.values() for t in v}))}
STRUCT = {}
for d in pd.date_range(pd.Timestamp(D0) - pd.Timedelta(days=15), D1):
    d = str(d.date()); raw = gcat(f"{B}/results/structural/backtest/{d}.json")
    if raw: STRUCT[d] = json.loads(raw)
print("structural days", len(STRUCT), flush=True)
def day_rows(D, ids):
    Dt = pd.Timestamp(D); H = U[(U.lday < Dt) & (U.lday >= Dt - pd.Timedelta(days=90))]
    pool = sorted(set(H[H.lday >= Dt - pd.Timedelta(days=60)].person_id)); pix = {p: k for k, p in enumerate(pool)}; n = len(pool)
    H = H[H.person_id.isin(pix)]; pi = H.person_id.map(pix).values; age = (Dt - H.lday).dt.days.values
    rw = np.bincount(pi, weights=0.5 ** (age / 7.0), minlength=n); TM = np.zeros((n, len(TIX)), np.float32)
    for p, t in zip(pi, H.target_id.values):
        for x in TOP.get(t, []): TM[p, TIX[x]] += 1
    tot = np.maximum(np.bincount(pi, minlength=n), 1); V = U[U.lday == Dt].groupby("target_id").person_id.agg(set).to_dict(); out = {}
    for l in ids:
        ti = [TIX[x] for x in TOP.get(l, []) if x in TIX]; tm = np.minimum(TM[:, ti].sum(1) / tot, 1.0) if ti else np.zeros(n)
        y = np.zeros(n, np.int8); idx = [pix[p] for p in V.get(l, ()) if p in pix]; y[idx] = 1
        out[l] = (np.column_stack([np.log1p(rw), tm, np.log1p(rw) * tm]), y)
    return out
days = sorted(STRUCT); DATA = {}
for D in days:
    ids = [str(x["id"]) for x in sorted(STRUCT[D]["launches"], key=lambda x: x["structural_rank"])[:20]]
    DATA[D] = day_rows(D, ids)
print("rows built", flush=True)
F = {}
for i, D in enumerate(days):
    if D < D0: continue
    prev = [d for d in days[:i]][-14:]
    if len(prev) < 7: continue
    Xs, ys = [], []
    for d in prev:
        for X, y in DATA[d].values():
            pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]; neg = rng.choice(neg, max(1, int(0.02 * len(neg))), replace=False) if len(neg) else neg
            Xs.append(X[np.r_[pos, neg]]); ys.append(np.r_[np.ones(len(pos)), np.zeros(len(neg))])
    m = LogisticRegression(max_iter=500).fit(np.vstack(Xs), np.concatenate(ys))
    F[D] = {}
    for l, (X, y) in DATA[D].items():
        pf = 1 / (1 + np.exp(-m.decision_function(X))); F[D][l] = float((pf / (pf + (1 - pf) / 0.02)).sum())
    if i % 20 == 0: print(D, len(F[D]), flush=True)
def z(v): v = np.asarray(v, float); return (v - v.mean()) / (v.std() + 1e-9)
TR = {D: {str(k): v["final_rank"] for k, v in (STRUCT[D].get("truth") or {}).get("by_id", {}).items() if v.get("final_rank")} for D in F}
def order(D, w, NS):
    L = sorted(STRUCT[D]["launches"], key=lambda x: x["structural_rank"])[:NS]; ids = [str(x["id"]) for x in L]; sr = np.array([x["structural_rank"] for x in L], float)
    if not w: return ids
    f = np.array([F[D].get(i, 0.0) for i in ids]); sc = z(-sr) + w * z(np.log1p(f)); return [ids[k] for k in np.argsort(-sc, kind="stable")]
def caps(D, o):
    out = {}
    for k in (3, 5, 10): rk = {i for i, r in TR[D].items() if r <= k}; out[k] = len(set(o[:k]) & rk) / k
    s3 = set(order(D, 0, 20)[:3]); t3 = {i for i, r in TR[D].items() if r <= 3}; near = set(order(D, 0, 20)[3:6]) & t3
    out["near"] = len(near); out["rec"] = len(near & set(o[:3])); out["cost"] = len((s3 & t3) - set(o[:3])); return out
GRID = [0, 0.1, 0.25, 0.5, 1, 2]; res = {}; tdays = sorted(F)
for NS in (10, 15, 20):
    rows = []
    for i, D in enumerate(tdays):
        prev = tdays[:i]
        w = 0 if len(prev) < 7 else GRID[int(np.argmax([np.mean([np.mean([caps(p, order(p, g, NS))[k] for k in (3, 5, 10)]) for p in prev[-60:]]) for g in GRID]))]
        c = caps(D, order(D, w, NS)); s = caps(D, order(D, 0, NS))
        rows.append({"day": D, "w": w, **{f"c{k}": c[k] for k in (3, 5, 10)}, **{f"s{k}": s[k] for k in (3, 5, 10)}, "near": c["near"], "rec": c["rec"], "cost": c["cost"]})
    R = pd.DataFrame(rows)
    for k in (3, 5, 10): R[f"d{k}"] = R[f"c{k}"] - R[f"s{k}"]
    def boot(col):
        d = R.day.values; bs = [R.set_index("day").loc[rng.choice(d, len(d))][col].mean() for _ in range(2000)]
        return [round(100 * float(R[col].mean()), 1), round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1), int(len(R))]
    res[f"shortlist {NS}"] = {**{f"top{k} structural": boot(f"s{k}") for k in (3, 5, 10)}, **{f"top{k} re-ranked": boot(f"c{k}") for k in (3, 5, 10)},
                              **{f"top{k} re-ranked minus structural (paired)": boot(f"d{k}") for k in (3, 5, 10)},
                              "near misses / recovered / cost": [int(R.near.sum()), int(R.rec.sum()), int(R.cost.sum())], "share of days w > 0": round(float((R.w > 0).mean()), 3),
                              "weights used": R.w.value_counts().to_dict()}
out = {"prereg": "PREREG.md addendum 6c", "days": len(tdays), "range": [tdays[0], tdays[-1]], "feature": "F6 expected voters over the active pool (lenient as-of upvote history, no follows)", "results": res,
       "note": "[value %, day-bootstrap 2.5%, 97.5%, days]; truth = final daily rank; structural = PH agent backtest files (arm 3 / arm 2)"}
json.dump(out, open(OUT, "w"), indent=1, default=str); print(json.dumps(out, indent=1, default=str))
