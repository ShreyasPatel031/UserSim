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
import glob, gzip, json, multiprocessing as mp, os, sys
from collections import Counter, defaultdict
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
import commenters as K
from vote_sim import load, D, R

TRAIN = (os.environ.get("TRAIN0", "2026-03-01"), os.environ.get("TRAIN1", "2026-10-12"))
TEST = (os.environ.get("TEST0", "2026-10-13"), "2026-10-24")
PAIR = ["hunter", "team", "recip", "cocm", "f_hunter", "f_team", "topic", "text", "e_hist", "e_prof", "prior"]
PERS = ["p_age", "p_rate", "p_follow", "p_maker"]
COLS = ["dn", "launch", "person", "hunter", "team", "recip", "cocm", "topic", "text", "e_hist", "e_prof", "prior"] + PERS + ["act", "per", "y"]


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


G = {}  # shared with worker processes (fork)


def person_rows(u):
    """All (person, launch) feature rows for one person, walking days in order and using only events before each day."""
    L, Ltop, emb, topics, Pp, cms, on, built, days, day_idx, name_ix, day_n = (G[k] for k in (
        "L", "Ltop", "emb", "topics", "Pp", "cms", "on", "built", "days", "day_idx", "name_ix", "day_n"))
    BE, pv = G["BE"], G["PE"].get(u)  # meaning-based vectors: launches, and this person's profile (None if no text)
    Lday, Lhun, Lmk, Lteam = list(L.day), list(L.hunter), list(L.makers), list(L.team)
    Lpri = L.prior.fillna(0.5).tolist()
    rows = []
    p = Pp[u]
    ev = sorted([(Lday[i], "up", i) for i in p["ups"]] + [(dt, "cm", i) for dt, i in cms[u]]
                + [(dt, "sup", c) for i in built[u] for dt, c in on[i]]
                + [(max(dt, dt2), "cir", c) for dt, i in cms[u] for dt2, c in on[i] if c != u])
    hun, mk, supp, circle, vd = Counter(), Counter(), Counter(), Counter(), Counter()
    tv = np.zeros(len(topics)); xv = np.zeros(64); bv = np.zeros(BE.shape[1]); n_up = 0; e = 0
    for d in days:
        while e < len(ev) and ev[e][0] < d:
            dt, kind, x = ev[e]; e += 1
            if kind in ("up", "cm"):
                hun[Lhun[x]] += 1; mk.update(Lmk[x]); tv += Ltop[x]; xv += emb[x]; bv += BE[x]
                if kind == "up" and dt >= p["cover"]:
                    n_up += 1; vd[dt] += 1
            elif kind == "sup":
                supp[x] += 1
            else:
                circle[x] += 1
        test = d >= TEST[0]
        if test and p["cover"] > d:
            continue
        label = {i for i in p["ups"] if Lday[i] == d and d >= p["cover"]}
        if not test:  # training: only days the person picked something; comments count as picks (complete history)
            label |= {i for dt, i in cms[u] if dt == d and Lday[i] == d}
            if not label:
                continue
        tn = tv / (np.linalg.norm(tv) + 1e-9); xn = xv / (np.linalg.norm(xv) + 1e-9); bn = bv / (np.linalg.norm(bv) + 1e-9)
        cov_days = max(1, (pd.Timestamp(d) - pd.Timestamp(p["cover"])).days)
        act = (len(vd) + 1) / (cov_days + 2); per = (n_up + 1) / (len(vd) + 1)
        di = day_idx[d]; ui = name_ix[u]; dn = day_n[d]
        rows.append(np.array([(dn, i, ui, np.log1p(hun[Lhun[i]]), np.log1p(sum(mk[m] for m in Lmk[i])),
                               np.log1p(sum(supp[m] for m in Lteam[i])), np.log1p(sum(circle[m] for m in Lteam[i])),
                               float(Ltop[i] @ tn / (np.linalg.norm(Ltop[i]) + 1e-9)), float(emb[i] @ xn),
                                   float(BE[i] @ bn), float(BE[i] @ pv) if pv is not None else np.nan,
                               Lpri[i],
                               p["p_age"], p["p_rate"], p["p_follow"], p["p_maker"], act, per, int(i in label))
                              for i in di], np.float32))
    return np.concatenate(rows) if rows else np.zeros((0, len(COLS)), np.float32)


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
    # who each person follows (first page, up to 20). Read today, not dated: a follow may come after the upvote.
    follows = defaultdict(set)
    if os.path.exists(f"{D}/ph_following.jsonl.gz"):
        for l in gzip.open(f"{D}/ph_following.jsonl.gz", "rt"):
            r = json.loads(l)
            follows[r["username"]] = {x for x, _ in r.get("following") or []}
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
    cache = f"{D}/vote_sim_rows2_{TEST[0]}.npy"
    if os.path.exists(cache):  # person histories are built once and saved; later runs only retrain/score
        Xa = np.load(cache); print("loaded cached rows", Xa.shape, flush=True)
    else:
        Z = np.load(f"{D}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}
        G.update(BE=Z["launch"][[li[x] for x in L.id]], PE=dict(zip(Z["people"], Z["person"])))
        G.update(L=L, Ltop=Ltop, emb=emb, topics=topics, Pp=Pp, cms=cms, on=on, built=built, days=days,
                 day_idx={d: np.where(L.day.values == d)[0] for d in days}, name_ix={u: k for k, u in enumerate(names)},
                 day_n={d: k for k, d in enumerate(days)})
        with mp.get_context("fork").Pool(os.cpu_count()) as pool, open(cache + ".raw", "wb") as fh:
            for a in pool.imap(person_rows, names, chunksize=50):  # stream to disk: rows don't all sit in memory twice
                a.astype(np.float32).tofile(fh)
        Xa = np.fromfile(cache + ".raw", np.float32).reshape(-1, len(COLS)); np.save(cache, Xa); os.remove(cache + ".raw")
    X = pd.DataFrame(Xa, columns=COLS, copy=False); del Xa
    X["launch"] = X.launch.astype(np.int32); X["person"] = X.person.astype(np.int32); X["dn"] = X.dn.astype(np.int16)
    X["g"] = X.person.astype(np.int64) * 1000 + X.dn
    # follow features (not cached: added as the following data grows). Vectorised via (person, launch) keys.
    nix = {u: k for k, u in enumerate(names)}; fol_of = defaultdict(list)  # followed username -> sample people following
    for u, fs in follows.items():
        if u in nix:
            for f in fs:
                fol_of[f].append(nix[u])
    def keys(get):  # int64 keys person*100000+launch, counting repeats (a person following 2 builders counts 2)
        return np.array([p * 100000 + i for i in range(len(L)) for x in get(i) for p in fol_of.get(x, ())], np.int64)
    rk = X.person.values.astype(np.int64) * 100000 + X.launch.values
    hk = keys(lambda i: [L.hunter[i]] if L.hunter[i] else []); mkk = keys(lambda i: L.makers[i])
    X["f_hunter"] = np.isin(rk, hk).astype(np.float32)
    uk, cnt = np.unique(mkk, return_counts=True); pos = np.searchsorted(uk, rk).clip(0, max(len(uk) - 1, 0))
    X["f_team"] = np.where(len(uk) and True, (uk[pos] == rk) * cnt[pos], 0).astype(np.float32) if len(uk) else 0.0
    del rk
    d_tr, d_te = sum(d <= TRAIN[1] for d in days) - 1, days.index(min(d for d in days if d >= TEST[0]))
    tr = X[X.dn <= d_tr].sort_values("g"); te = X[X.dn >= d_te].copy(); del X
    print("voting person-days train:", tr.g.nunique(), "test pairs:", len(te), flush=True)
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
        # other ways to turn each person's ranking into votes: each person votes for their top-k launches
        te["r"] = te.groupby("g").s.rank(ascending=False, method="first")
        for k in (1, 3):
            L[f"sim|{name} | top{k} picks"] = L.index.map(te[te.r <= k].assign(w=lambda x: x.act * x.per).groupby("launch").w.sum())
        out[name] = {"person_top3_hit": round(float(np.mean(hits)), 3),
                     "importance": dict(zip(cols, m.booster_.feature_importance("gain").round().astype(int).tolist()))}
    T = L[(L.day >= TEST[0]) & (L.day <= TEST[1])].copy()
    T["sample_real"] = T.id.map(Counter(L.id[i] for u in names for i in Pp[u]["ups"]))
    for name, col in [("current model", "pred"), *[(f"simulated: {c[4:]}", c) for c in L.columns if c.startswith("sim|")],
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
    res.to_csv(f"{R}/vote_sim2_{TEST[0]}.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1:] or [f"{D}/ph_profiles2.jsonl.gz"])
