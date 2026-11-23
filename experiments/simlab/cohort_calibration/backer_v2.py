"""BACKER-v2 (PREREG addendum 5). Aggregates only.
    python backer_v2.py <store dir> <out json> <first test day> <last test day> <first train day>"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP
from pipeline import warehouse
ST, OUT, T0, T1, TR0 = sys.argv[1:6]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); COMPLETE = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"])
E["ft"] = pd.to_datetime(E.fetched_at, utc=True); E["target_id"] = E.target_id.astype(str)
U = E[E.kind == "upvote"][["person_id", "target_id", "ft"]].copy(); FO = E[E.kind == "follows"][["person_id", "target_id", "ft"]].copy()
TEAM = E[E.kind.isin(["hunted", "launched"])].groupby("target_id").person_id.agg(set).to_dict(); del E
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["rank"] = pd.to_numeric(W.daily_rank, errors="coerce"); LD = dict(zip(W.id, W.day)); RANK = dict(zip(W.id, W["rank"]))
TOP = {i: (json.loads(t) if isinstance(t, str) and t.startswith("[") else []) for i, t in zip(W.id, W.topics)}
U["lday"] = U.target_id.map(LD); U = U.dropna(subset=["lday"]); first = U.groupby("person_id").ft.min(); last = U.groupby("person_id").ft.max()
TIX = {t: k for k, t in enumerate(sorted({t for v in TOP.values() for t in v}))}
def day_table(D, score_all=False):
    close = PP.close_utc(D); start = close - pd.Timedelta(days=1); Dt = pd.Timestamp(D)
    pop = sorted(p for p in COMPLETE if first.get(p, close) < start and (score_all or last.get(p, start) > close))
    if not pop: return None
    pix = {p: k for k, p in enumerate(pop)}; n = len(pop)
    H = U[(U.ft < start) & (U.lday < D) & U.person_id.isin(pix)]
    age = (Dt - pd.to_datetime(H.lday)).dt.days.values; pi = H.person_id.map(pix).values
    rw = np.bincount(pi, weights=0.5 ** (age / 7.0), minlength=n); n30 = np.bincount(pi[age <= 30], minlength=n); n7 = np.bincount(pi[age <= 7], minlength=n)
    h90 = H[age <= 90]; TM = np.zeros((n, len(TIX)), np.float32)
    for p, t in zip(h90.person_id.map(pix).values, h90.target_id.values):
        for x in TOP.get(t, []): TM[p, TIX[x]] += 1
    tot = np.maximum(np.bincount(h90.person_id.map(pix).values, minlength=n), 1)
    fo = FO[(FO.ft < start) & FO.person_id.isin(pix)]; fol = fo.groupby("target_id").person_id.agg(set).to_dict()
    lids = [l for l, d in LD.items() if d == D]
    raw = gcat(f"{B}/tmp/e5/private/backer_pred/{D}.parquet"); CF = {}
    if raw:
        C = pd.read_parquet(io.BytesIO(raw)); C["launch_id"] = C.launch_id.astype(str); CF = {l: dict(zip(g.person_id, g.p)) for l, g in C.groupby("launch_id")}
    V = U[(U.lday == D) & U.person_id.isin(pix)].groupby("target_id").person_id.agg(set).to_dict()
    out = []
    for l in lids:
        real = V.get(l, set())
        ti = [TIX[x] for x in TOP.get(l, []) if x in TIX]; tm = np.minimum(TM[:, ti].sum(1) / tot, 1.0) if ti else np.zeros(n)
        f = np.zeros(n)
        for m in TEAM.get(l, set()):
            for p in fol.get(m, ()): f[pix[p]] = 1
        y = np.zeros(n, np.int8); y[[pix[p] for p in real]] = 1
        cf = np.full(n, -1.0)
        for p, v in CF.get(l, {}).items():
            if p in pix: cf[pix[p]] = v
        out.append({"lid": l, "y": y, "X": np.column_stack([np.log1p(rw), tm, f, np.log1p(rw) * tm]), "n30": n30, "n7": n7, "cf": cf})
    return {"D": D, "n": n, "launches": out, "has_cf": bool(CF)}
if os.environ.get("BV2_LIB"): raise SystemExit
days = [str(d.date()) for d in pd.date_range(TR0, T1)]; tests = [d for d in days if d >= T0]
TAB = {}
for D in days:
    t = day_table(D)
    if t: TAB[D] = t; print(D, t["n"], len(t["launches"]), sum(int(x["y"].sum()) for x in t["launches"]), flush=True)
def topn_recall(score, y, N, tie=None):
    o = np.lexsort((-(tie if tie is not None else np.zeros_like(score)), -score))[:N]; return y[o].sum() / N
rows, coefs = [], {}
for D in tests:
    if D not in TAB: continue
    tr = [x for d in TAB if d < D for x in TAB[d]["launches"]]
    Xs, ys = [], []
    for x in tr:
        pos = np.where(x["y"] == 1)[0]; neg = np.where(x["y"] == 0)[0]; neg = rng.choice(neg, max(1, int(0.05 * len(neg))), replace=False) if len(neg) else neg
        Xs.append(x["X"][np.r_[pos, neg]]); ys.append(np.r_[np.ones(len(pos)), np.zeros(len(neg))])
    m = LogisticRegression(max_iter=1000).fit(np.vstack(Xs), np.concatenate(ys)); coefs[D] = [round(float(c), 3) for c in m.coef_[0]]
    for x in TAB[D]["launches"]:
        N = int(x["y"].sum())
        if N == 0: continue
        s3 = m.decision_function(x["X"]); s4 = s3 + 100 * (x["n7"] > 0)
        rows.append({"day": D, "lid": x["lid"], "N": N, "rank": RANK.get(x["lid"]), "has_cf": TAB[D]["has_cf"],
                     "r1": topn_recall(x["n30"].astype(float), x["y"], N), "r2": topn_recall(x["cf"], x["y"], N, x["n30"]) if TAB[D]["has_cf"] else np.nan,
                     "r3": topn_recall(s3, x["y"], N), "r4": topn_recall(s4, x["y"], N, s3),
                     "cf_listed_in_pop": float((x["cf"] >= 0).mean())})
R = pd.DataFrame(rows)
def boot(df, f):
    d = sorted(df.day.unique()); bs = [f(pd.concat([df[df.day == z] for z in rng.choice(d, len(d))])) for _ in range(2000)]
    return [round(float(f(df)), 4), round(float(np.nanpercentile(bs, 2.5)), 4), round(float(np.nanpercentile(bs, 97.5)), 4), int(len(df)), len(d)]
wm = lambda c: (lambda x: float((x[c] * x.N).sum() / x.N.sum()))
wd = lambda a, b: (lambda x: float(((x[a] - x[b]) * x.N).sum() / x.N.sum()))
def block(df):
    s = df.dropna(subset=["r2"])
    return {"launches": int(len(df)), "days": int(df.day.nunique()), "held backers": int(df.N.sum()),
            "recall@N (1) most active": boot(df, wm("r1")), "(2) frozen CF list": boot(s, wm("r2")) if len(s) else None, "(3) logistic walk-forward": boot(df, wm("r3")), "(4) (3) active-7d first": boot(df, wm("r4")),
            "(2) minus (1) paired": boot(s, wd("r2", "r1")) if len(s) else None, "(3) minus (1) paired": boot(df, wd("r3", "r1")), "(4) minus (1) paired": boot(df, wd("r4", "r1"))}
out = {"prereg": "PREREG.md addendum 5", "test days": tests, "train from": TR0, "all launches": block(R), "top-3 launches": block(R[R["rank"] <= 3]),
       "per_day": R.groupby("day").apply(lambda x: {"launches": int(len(x)), "N": int(x.N.sum()), **{c: round(wm(c)(x), 3) for c in ("r1", "r2", "r3", "r4")}, "cf_listed_share_of_pop": round(float(x.cf_listed_in_pop.mean()), 3)}).to_dict(),
       "logistic coefficients by test day [ln1p_rw, topic_match, follows_team, rw_x_topic]": coefs,
       "population per day (complete, held before start, re-read after close)": {d: TAB[d]["n"] for d in TAB},
       "note": "[value, day-bootstrap 2.5%, 97.5%, launches, days]; recall weighted by N; re-read subset is selected (mostly active people)"}
json.dump(out, open(OUT, "w"), indent=1, default=str); print(json.dumps({k: v for k, v in out.items() if k in ("all launches", "top-3 launches", "per_day")}, indent=1, default=str))
