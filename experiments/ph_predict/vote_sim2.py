"""Simulate who upvotes, step 2: a choice model per person, then sum over the sample.

First principles: E[votes for L] = sum over people u of P(u votes that day) x P(u picks L | u votes that day).
Ranking launches within a day only needs the second part to be right per person, weighted by the first.
  - "picks L": a ranker trained only on (person, day) groups where the person upvoted something that day
    (absent upvotes on a day they didn't vote say nothing about taste). Softmax of its scores = share of their votes.
  - "votes that day": the person's past rate of voting days (from coverage), times their past votes per voting day.
Coverage: a profile lists the latest ~20 upvotes, so labels are complete only from the oldest listed one onward
(or from the join date when the list holds all of the person's upvotes).

Pair features, all dated before the launch day:
  hunter, team     earlier upvotes/comments by u on launches by the poster / the builders
  recip            comments the builders/poster left on launches u built (they supported u before)
  cocm             launches where u and a builder/poster both commented (same circles)
  topic, text      taste overlap with u's earlier upvotes/comments
  prior            the current launch model's within-day percentile (leak-free rolling folds)
  p_*              person traits (account age, total upvotes rate, followings, maker) — interact with launch traits
Output: results/vote_sim2.csv"""
import glob, gzip, json, os, sys
from collections import Counter, defaultdict
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
import commenters as K
from vote_sim import load, D, R

TRAIN = ("2026-03-01", "2026-10-12")
TEST = ("2026-10-13", "2026-10-24")
PAIR = ["hunter", "team", "recip", "cocm", "topic", "text", "prior"]
PERS = ["p_age", "p_rate", "p_follow", "p_maker"]


def people(files, L, id2i):
    P = {}
    for fn in files:
        for l in gzip.open(fn, "rt"):
            p = json.loads(l)
            idx = [id2i[x] for x in p.get("voted_recent") or [] if x in id2i]
            if not idx:
                continue
            listed = len(p.get("voted_recent") or [])
            tot = int(p.get("upvotes_total") or listed)
            joined = (p.get("joined") or "2026-01-01")[:10]
            cover = max(joined, "2026-01-01") if 0 < tot <= listed else min(L.day[i] for i in idx)  # total 0 = not shown
            age = max(1, (pd.Timestamp("2026-10-25") - pd.Timestamp(joined)).days)
            P[p["username"]] = {"ups": idx, "cover": cover, "p_age": np.log1p(age), "p_rate": np.log1p(tot / age * 30),
                                "p_follow": np.log1p(max(0, int(p.get("followings") or 0))), "p_maker": float(p.get("is_maker") in (True, "True"))}
    return P


def main(files):
    L = load(); id2i = {pid: i for i, pid in enumerate(L.id)}; slug2i = {s: i for i, s in enumerate(L.slug)}
    L["team"] = [set(m) | ({h} if h else set()) for m, h in zip(L.makers, L.hunter)]
    emb = TruncatedSVD(64, random_state=0).fit_transform(
        TfidfVectorizer(min_df=2, max_features=40000, ngram_range=(1, 2), sublinear_tf=True).fit_transform(L.text))
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    topics = sorted({t for ts in L.topics for t in ts}); tix = {t: k for k, t in enumerate(topics)}
    Ltop = np.zeros((len(L), len(topics)), np.float32)
    for i, ts in enumerate(L.topics):
        for t in ts:
            Ltop[i, tix[t]] = 1
    Pp = people(files, L, id2i); names = sorted(Pp); print("people:", len(names), flush=True)
    cm = K.load_comments()
    cms = defaultdict(list)   # u -> [(date, launch)] u's comments (not on own launches)
    on = defaultdict(list)    # launch -> [(date, commenter)] all non-team comments
    for s, v in cm.items():
        if s not in slug2i:
            continue
        i = slug2i[s]
        for c in v["rows"]:
            u, dt = c["username"], (c["created"] or "")[:10]
            if not u or u in L.team[i]:
                continue
            on[i].append((dt, u))
            if u in Pp:
                cms[u].append((dt, i))
    built = defaultdict(list)  # u -> launches u was on the team of
    for i, t in enumerate(L.team):
        for m in t:
            if m in Pp:
                built[m].append(i)
    days = sorted(L.day[(L.day >= TRAIN[0]) & (L.day <= TEST[1])].unique())
    day_idx = {d: np.where(L.day.values == d)[0] for d in days}
    rows = []; name_ix = {u: k for k, u in enumerate(names)}; day_n = {d: k for k, d in enumerate(days)}
    for u in names:  # walk each person's days in order, adding only events dated before the day
        p = Pp[u]
        ev = sorted([(L.day[i], "up", i) for i in p["ups"]] + [(dt, "cm", i) for dt, i in cms[u]]
                    + [(dt, "sup", c) for i in built[u] for dt, c in on[i]]
                    + [(max(dt, dt2), "cir", c) for dt, i in cms[u] for dt2, c in on[i] if c != u])
        hun, mk, supp, circle, vd = Counter(), Counter(), Counter(), Counter(), Counter()
        tv = np.zeros(len(topics)); xv = np.zeros(64); n_up = 0; e = 0
        for d in days:
            while e < len(ev) and ev[e][0] < d:
                dt, kind, x = ev[e]; e += 1
                if kind in ("up", "cm"):
                    hun[L.hunter[x]] += 1; mk.update(L.makers[x]); tv += Ltop[x]; xv += emb[x]
                    if kind == "up" and dt >= p["cover"]:
                        n_up += 1; vd[dt] += 1
                elif kind == "sup":
                    supp[x] += 1
                else:
                    circle[x] += 1
            test = d >= TEST[0]
            if test and p["cover"] > d:
                continue
            label = {i for i in p["ups"] if L.day[i] == d and d >= p["cover"]}
            if not test:  # training: only days the person picked something; comments count as picks (complete history)
                label |= {i for dt, i in cms[u] if dt == d and L.day[i] == d}
                if not label:
                    continue
            tn = tv / (np.linalg.norm(tv) + 1e-9); xn = xv / (np.linalg.norm(xv) + 1e-9)
            cov_days = max(1, (pd.Timestamp(d) - pd.Timestamp(p["cover"])).days)
            act = (len(vd) + 1) / (cov_days + 2); per = (n_up + 1) / (len(vd) + 1)
            di = day_idx[d]; ui = name_ix[u]; dn = day_n[d]
            rows.append(np.array([(dn, i, ui, np.log1p(hun[L.hunter[i]]), np.log1p(sum(mk[m] for m in L.makers[i])),
                                   np.log1p(sum(supp[m] for m in L.team[i])), np.log1p(sum(circle[m] for m in L.team[i])),
                                   float(Ltop[i] @ tn / (np.linalg.norm(Ltop[i]) + 1e-9)), float(emb[i] @ xn),
                                   L.prior[i] if pd.notna(L.prior[i]) else 0.5,
                                   p["p_age"], p["p_rate"], p["p_follow"], p["p_maker"], act, per, int(i in label))
                                  for i in di], np.float32))
    X = pd.DataFrame(np.concatenate(rows), columns=["dn", "launch", "person"] + PAIR + PERS + ["act", "per", "y"]); del rows
    X["launch"] = X.launch.astype(int); X["g"] = X.person.astype(np.int64) * 1000 + X.dn.astype(np.int64)
    X["day"] = np.array(days)[X.dn.astype(int)]
    gy = X.groupby("g").y.transform("sum"); A = X[gy > 0]
    tr = A[A.day <= TRAIN[1]].sort_values("g"); te = X[X.day >= TEST[0]].copy()
    print("pairs:", len(X), "voting person-days train:", tr.g.nunique(), "test pairs:", len(te), flush=True)
    out, res = {}, []
    for name, cols in (("taste+network", PAIR[:-1] + PERS), ("taste+network+launch prior", PAIR + PERS)):
        m = lgb.LGBMRanker(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1)
        m.fit(tr[cols], tr.y, group=tr.groupby("g", sort=False).size().loc[tr.g.unique()].values)
        te["s"] = m.predict(te[cols])
        te["share"] = np.exp(te.s - te.groupby("g").s.transform("max")); te["share"] /= te.groupby("g").share.transform("sum")
        te["ev"] = te.share * te.act * te.per
        Ta = te[te.groupby("g").y.transform("sum") > 0]
        hits = [len(set(g.nlargest(3, "s").launch) & set(g[g.y == 1].launch)) / g.y.sum() for _, g in Ta.groupby("g")]
        L[f"sim|{name}"] = L.index.map(te.groupby("launch").ev.sum())
        out[name] = {"person_top3_hit": round(float(np.mean(hits)), 3),
                     "importance": dict(zip(cols, m.booster_.feature_importance("gain").round().astype(int).tolist()))}
    T = L[(L.day >= TEST[0]) & (L.day <= TEST[1])].copy()
    T["sample_real"] = T.id.map(Counter(L.id[i] for u in names for i in Pp[u]["ups"]))
    for name, col in [("current model", "pred"), *[(f"simulated: {k}", f"sim|{k}") for k in out],
                      ("ceiling: sample's real upvotes", "sample_real")]:
        r = {"score": name}
        T["_c"] = T[col].fillna(-1e3) + np.random.default_rng(0).random(len(T)) * 1e-6
        for k in (3, 5, 10):
            r[f"day@{k}"] = round(100 * np.mean([len(set(g.nsmallest(k, "rank").id) & set(g.nlargest(k, "_c").id)) / k
                                                 for _, g in T.groupby("day") if len(g) >= k]))
        r["rho"] = round(float(np.nanmean([spearmanr(g["_c"], -g["rank"])[0] for _, g in T.groupby("day")])), 3)
        res.append(r)
    res = pd.DataFrame(res)
    print(json.dumps(out, indent=1)); print(res.to_string(index=False))
    res.to_csv(f"{R}/vote_sim2.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1:] or [f"{D}/ph_profiles2.jsonl.gz"])
