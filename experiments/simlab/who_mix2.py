"""Backer mix per launch at 00:05 (orchestrator 19:35Z Nov 13): predict the SHARES of a launch's held backers by segment by summing
the FULL who-backs-it probabilities (who_backs2.py features, logistic, 30 prior days) within segment. Same 15 days (Oct 25 - Nov 11).
Segment families (person attributes known at 00:05):
  age      account age at the launch day from persons.joined: <30 d, 30-365 d, 1-3 y, 3 y+
  tier_k   history-predicted daily vote count (mean over active days in the 60 prior launch days): 1 (or inactive), 2-4, 5+
  tier_30  upvotes in the 30 days before the day: none, then terciles of the active population
  maker    named hunter or maker on any launch dated before the day (warehouse launches)
  topic    k-means (k=10) cluster of the person's 90-day topic-taste vector (fit on the first test day); 'none' = no taste vector
Truth: shares among the launch's actual held backers (complete persons; people outside the scored population get their attributes
from the same rules). Baselines (prior days only): DAY = pooled backer mix of all launches in the 7 launch days before; TOPIC = pooled
backer mix of launches in the 30 days before sharing a topic with the launch (falls back to DAY). Metrics per family: mean absolute
error in share points (mean over segments, per launch), model minus baseline with launch-bootstrap interval; mean Spearman across
launches of predicted vs actual share per segment. Launches with >= 20 held backers; repeated on launches with held backers /
displayed votes >= 0.5 (selection caveat). Counts only.
    python who_mix2.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); src = open(os.path.join(HERE, "who_backs2.py")).read()
exec(src[src.index("import os, sys, json, time"):src.index("ARMS = {")])
from sklearn.cluster import KMeans
from scipy.stats import spearmanr
import glob, hashlib
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pidf = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
PJ = pd.read_parquet(os.path.join(V3, "persons.parquet")).set_index("person_id"); JT = pd.to_datetime(PJ.joined, utc=True, errors="coerce")
def mk(m):
    try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
first_made = {}
for p, m, d in zip(L.poster, L.makers, L.day):
    for h in ([p] if isinstance(p, str) and p and not p.startswith("[") else []) + mk(m):
        q = pidf(h); first_made[q] = min(first_made.get(q, "9999"), d)
lday_all = sorted(L.day.unique()); dcount = U.groupby(["person_id", "lday"]).size()
def kh(people, d):
    w = set([x for x in lday_all if x < d][-60:]); sub = dcount[dcount.index.get_level_values(1).isin(w)]
    tot = sub.groupby(level=0).sum(); act = sub.groupby(level=0).size(); return {p: tot.get(p, 0) / max(act.get(p, 1), 1) for p in people}
KM = None; FAM = ["age", "tier_k", "tier_30", "maker", "topic"]
def attrs(people, d, act, tv):
    global KM
    d0 = pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC"); k = kh(people, d)
    n30 = act.n30.reindex(people).fillna(0).values; pos = act.n30[act.n30 > 0]; q1, q2 = (np.percentile(pos, [33.3, 66.7]) if len(pos) else (1, 2))
    ix = {p: j for j, p in enumerate(act.index)}
    if KM is None: KM = KMeans(10, n_init=5, random_state=0).fit(tv[tv.sum(1) > 0])
    lab = KM.predict(tv); has = tv.sum(1) > 0; out = {}
    for j, p in enumerate(people):
        a = (d0 - JT.get(p)).days if p in JT.index and pd.notna(JT.get(p)) else None
        age = "<30d" if a is not None and a < 30 else ("30-365d" if a is not None and a < 365 else ("1-3y" if a is not None and a < 1095 else "3y+"))
        kk = k.get(p, 0); tk = "1" if kk < 1.5 else ("2-4" if kk < 4.5 else "5+")
        t3 = "none" if n30[j] == 0 else ("low" if n30[j] <= q1 else ("mid" if n30[j] <= q2 else "high"))
        mkr = "maker" if first_made.get(p, "9999") < d else "non-maker"
        top = f"c{int(lab[ix[p]])}" if p in ix and has[ix[p]] else "none"
        out[p] = (age, tk, t3, mkr, top)
    return out
SEGS = {"age": ["<30d", "30-365d", "1-3y", "3y+"], "tier_k": ["1", "2-4", "5+"], "tier_30": ["none", "low", "mid", "high"], "maker": ["maker", "non-maker"],
        "topic": [f"c{j}" for j in range(10)] + ["none"]}
def mix(weights, at):
    o = {}
    for f_i, f in enumerate(FAM):
        v = {s: 0.0 for s in SEGS[f]}
        for p, w in weights.items(): v[at[p][f_i]] += w
        t = sum(v.values()) or 1; o[f] = {s: x / t for s, x in v.items()}
    return o
voters = U[U.lday.isin(DAYS)].groupby("target_id").person_id.agg(set).to_dict()
ltops = {i: set(ltop.get(i, [])) for i in L.id}; rows = []; HIST = {}   # day -> list of (launch topics, actual mix)
for d in DAYS:
    tr = [t for t in sorted(TRAIN) if t < d][-30:]; Xa = np.vstack([TRAIN[t][0] for t in tr]); ya = np.concatenate([TRAIN[t][1] for t in tr])
    m = LogisticRegression(max_iter=400).fit(Xa, ya, sample_weight=np.where(ya == 1, 1.0, 10.0))
    act, out = TEST[d]; _, tv, _ = feats(d, U); lu = set(C[C.day == d].id)
    allp = set(act.index) | set().union(*[voters.get(i, set()) for i, _ in out if i in lu]); at = attrs(list(allp), d, act, tv)
    for i, Xi in out:
        if i not in lu: continue
        v = voters.get(i, set()); p = m.predict_proba(Xi)[:, 1]
        pm = mix(dict(zip(act.index, p)), at); am = mix({q: 1.0 for q in v}, at) if v else None
        prev = [x for dd in sorted(HIST) if dd < d for x in HIST[dd]]
        p7 = [dd for dd in sorted(HIST) if dd < d][-7:]; day_pool = [x for dd in p7 for x in HIST[dd]]
        d30 = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); top_pool = [x for dd in sorted(HIST) if d30 <= dd < d for x in HIST[dd] if x[0] & ltops.get(i, set())]
        def pool(P):
            if not P: return None
            o = {}
            for f in FAM:
                tot = {s: 0.0 for s in SEGS[f]}; n = 0
                for _, mm, w in P:
                    for s in SEGS[f]: tot[s] += mm[f][s] * w
                    n += w
                o[f] = {s: x / max(n, 1) for s, x in tot.items()}
            return o
        dm_, tm_ = pool(day_pool), pool(top_pool) or pool(day_pool)
        if am: rows.append({"id": i, "day": d, "n_back": len(v), "votes": float(pd.to_numeric(L.loc[L.id == i, "votes"]).iloc[0]), "pred": pm, "act": am, "day_b": dm_, "top_b": tm_})
    HIST[d] = [(ltops.get(r["id"], set()), r["act"], r["n_back"]) for r in rows if r["day"] == d]
    print(d, len(rows), round(time.time() - t0), flush=True)
import pickle
if os.environ.get("ROWS"): pickle.dump(rows, open(os.environ["ROWS"], "wb"))   # per-launch mixes (launch ids + shares only); scratch
R = [r for r in rows if r["n_back"] >= 20 and r["day_b"] is not None]
def lb(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2), len(v)]
def score(RR):
    o = {}
    for f in FAM:
        mae = {k: [np.mean([abs(r[k][f][s] - r["act"][f][s]) * 100 for s in SEGS[f]]) for r in RR] for k in ("pred", "day_b", "top_b")}
        sp = {}
        for k in ("pred", "day_b", "top_b"):
            cs = [spearmanr([r[k][f][s] for r in RR], [r["act"][f][s] for r in RR]).correlation for s in SEGS[f]]
            sp[k] = round(float(np.nanmean(cs)), 3)
        o[f] = {"MAE share points (model / day baseline / topic baseline)": [lb(mae["pred"]), lb(mae["day_b"]), lb(mae["top_b"])],
                "model - day baseline": lb(np.array(mae["pred"]) - np.array(mae["day_b"])), "model - topic baseline": lb(np.array(mae["pred"]) - np.array(mae["top_b"])),
                "mean Spearman across launches (model / day / topic)": [sp["pred"], sp["day_b"], sp["top_b"]]}
    o["families where model beats BOTH baselines (interval < 0)"] = [f for f in FAM if o[f]["model - day baseline"][2] < 0 and o[f]["model - topic baseline"][2] < 0]
    return o
res = {"design": __doc__.split("\n    python")[0], "days": DAYS, "launches with >= 20 held backers (and a baseline)": len(R),
       "coverage held backers / displayed votes (median, IQR)": [round(float(np.median([r["n_back"] / r["votes"] for r in R])), 3), round(float(np.percentile([r["n_back"] / r["votes"] for r in R], 25)), 3), round(float(np.percentile([r["n_back"] / r["votes"] for r in R], 75)), 3)],
       "all": score(R)}
R5 = [r for r in R if r["n_back"] / r["votes"] >= 0.5]; res["coverage >= 0.5 subset"] = {"launches": len(R5), **(score(R5) if len(R5) >= 20 else {})}
json.dump(res, open(os.path.join(OUTD, "who_mix2.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
