"""The trained person model, applied to the whole population and summed per launch (an input for the launch model).
For each month m (Apr-Oct):
  1. person model: LightGBM on the PREVIOUS month's active person-days (up to 300 people a day), personal signals only
     (no popularity, no follows, no personas): past backing of the team, topic, meaning, people-like-you backing
     (collaborative filtering, fitted on events before the previous month), sequence signals, category signals.
  2. population: every day of m, everyone active in the 30 days before the day (weight = share of those days active),
     scored on every launch that day with the same features.
  3. per launch: psn_ev (sum of weight x p), psn_fans (top-100 sum), psn_ev_ties (from people who backed the team before),
     psn_reach (sum of weights), psn_pmax.
Everything is dated before the launch. Parallel: months train in parallel, then every (month, day) scores in parallel.
usage: SIMLAB_DATA=data_v2 python -m simlab.popscore [workers] -> cache/popscore.parquet + ph_predict/data/psn_features.json"""
import json, os, pickle, sys
from collections import Counter, defaultdict
import multiprocessing as mp
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from . import store, choice
from .seq import features as seq_features

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.environ.get("PAGE") == "1"   # page-aware people: every launch-page input added to the person model
WORK = os.path.join(HERE, "cache", "popscore_page" if PAGE else "popscore")
PREFIX = "psp_" if PAGE else "psn_"
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
FEATS = ["backed", "topic", "meaning", "cf_team", "nbr_team", "nbr_pop", "seq_last10", "seq_decay", "seq_nn", "team_recent",
         "cat_rate_max", "cat_rate_mean", "cat_prior", "cat_n"]
G = {}   # loaded once per process (fork shares it)


def load():
    if not G:
        P, I, E = store.load()
        G.update(P=P, I=I, E=E, day=dict(zip(I.id, I.day)), topics={r.id: json.loads(r.topics) for r in I.itertuples()},
                 team={r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()},
                 lineup=I.groupby("day").id.apply(list).to_dict())
    return G


def month_start(m, back=0):
    return (pd.Timestamp(m + "-01") - pd.DateOffset(months=back)).strftime("%Y-%m-%d")


def month_end(m):
    return (pd.Timestamp(m + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")


# ---- people-like-you backing (collaborative filtering), fitted on events before `cut`
def fit_cf(cut):
    g = load(); E, team = g["E"], g["team"]
    ev = E[(E.date < cut) & E.item.isin(team)]
    people = sorted(set(ev.person)); pix = {u: k for k, u in enumerate(people)}
    members = sorted({m for t in team.values() for m in t if m}); mix = {m: k for k, m in enumerate(members)}
    r, c = [], []
    for u, it in zip(ev.person, ev.item):
        for m in team[it]:
            if m in mix:
                r.append(pix[u]); c.append(mix[m])
    M = sparse.csr_matrix((np.ones(len(r), np.float32), (r, c)), shape=(len(people), len(members))); M.data = np.log1p(M.data)
    svd = TruncatedSVD(32, random_state=0); U = svd.fit_transform(M); V = svd.components_.T
    Un = U / (np.linalg.norm(U, axis=1, keepdims=True) + 1e-9)
    active = np.where(np.asarray(M.sum(1)).ravel() > 0)[0]
    return {"pix": pix, "mix": mix, "U": U, "V": V, "Un": Un, "active": active, "Mb": (M > 0).astype(np.float32).tocsr()}


def apply_cf(D, cf):
    team = load()["team"]; pix, mix, U, V, Un, act, Mb = (cf[k] for k in ("pix", "mix", "U", "V", "Un", "active", "Mb"))
    nbv = {}
    for u in set(D.person):
        i = pix.get(u)
        if i is None:
            nbv[u] = None; continue
        nb = act[np.argsort(-(Un[act] @ Un[i]))[1:51]]
        nbv[u] = np.asarray(Mb[nb].sum(0)).ravel()
    cft, nt, npop = [], [], []
    for u, it in zip(D.person, D.id):
        i = pix.get(u); t = [mix[m] for m in team.get(it, ()) if m in mix]
        cft.append(float(max((U[i] @ V[c] for c in t), default=0.0)) if i is not None else 0.0)
        v = nbv.get(u)
        if t and v is not None:
            nt.append(float(v[t].max() / 50)); npop.append(float(v[t].sum()))
        else:
            nt.append(0.0); npop.append(0.0)
    D["cf_team"], D["nbr_team"], D["nbr_pop"] = cft, nt, np.log1p(npop)
    for c in ("cf_team", "nbr_team", "nbr_pop"):
        D[c] = D.groupby("g")[c].rank(pct=True)
    return D


# ---- category signals (as push.build2, without the popularity-based rank), dated before each day
def cat_features(D, prior_cut):
    g = load(); E, day, topics, lineup = g["E"], g["day"], g["topics"], g["lineup"]
    ev = E[E.item.isin(day)]; real = ev[ev.item.map(day) == ev.date]
    shown, picked = Counter(), Counter()
    for d0, ids in lineup.items():
        if d0 < prior_cut:
            for x in ids:
                shown.update(topics[x])
    for it in real[real.date < prior_cut].item:
        picked.update(topics[it])
    prior = {t: picked[t] / max(shown[t], 1) for t in shown}; pm = float(np.mean(list(prior.values()) or [0.05]))
    cn = {}
    for d0, ids in lineup.items():
        by_t = defaultdict(int)
        for x in ids:
            for t in topics[x]:
                by_t[t] += 1
        for x in ids:
            cn[x] = min((by_t[t] for t in topics[x]), default=30)
    people = set(D.person)
    picks = real[real.person.isin(people)].groupby("person").apply(lambda q: sorted(set(zip(q.date, q.item))), include_groups=False).to_dict()
    cols = {c: np.zeros(len(D)) for c in ("cat_rate_max", "cat_rate_mean", "cat_prior", "cat_n")}
    for gk, idx in D.groupby("g").indices.items():
        u, d = gk.split("|")
        sh, pk = Counter(), Counter()
        for d0 in sorted({d0 for d0, _ in picks.get(u, []) if d0 < d}):
            for x in lineup.get(d0, ()):
                sh.update(topics[x])
        for d0, it in picks.get(u, []):
            if d0 < d:
                pk.update(topics[it])
        for j, x in zip(idx, D.id.values[idx]):
            ts = topics.get(x, [])
            r = [(pk[t] + 5 * prior.get(t, pm)) / (sh[t] + 5) for t in ts] or [pm]
            cols["cat_rate_max"][j] = max(r); cols["cat_rate_mean"][j] = float(np.mean(r))
            cols["cat_prior"][j] = max((prior.get(t, pm) for t in ts), default=pm); cols["cat_n"][j] = cn.get(x, 30)
    for c, v in cols.items():
        D[c] = v
    return D


def featurize(D, cf, prior_cut):
    g = load()
    D = seq_features(D, g["I"], g["E"])
    D = apply_cf(D, cf)
    return cat_features(D, prior_cut)


# ---- phase A: per month, train the person model on the previous month
def page_cols(D):
    """Join the launch-page inputs (ps_ Gemini element scores, pf_ page facts, vs_ video) when PAGE is on."""
    if not PAGE:
        return D, []
    from .page_choice import page_table
    T = G.setdefault("page", page_table())
    D = D.copy(); D["id"] = D.id.astype(str)
    return D.join(T, on="id"), list(T.columns)


def train_month(m):
    prev = month_start(m, 1)
    cf = fit_cf(prev)
    D = choice.rows(day_from=prev, day_to=month_end(prev[:7]))
    rng = np.random.default_rng(0)
    keep = set()
    for d, g in D.groupby("day"):
        ppl = list(g.person.unique()); keep |= {u + "|" + d for u in rng.permutation(ppl)[:300]}
    D = D[D.g.isin(keep)].copy()
    D = featurize(D, cf, prev)
    mdl = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=1)
    D, pc = page_cols(D)
    mdl.fit(D[FEATS + pc], D.y)
    pickle.dump({"model": mdl, "cf": cf, "prior_cut": prev}, open(f"{WORK}/model_{m}.pkl", "wb"))
    return m, len(D), float(D.y.mean())


# ---- phase B: per day, score the population and sum per launch
def score_day(d):
    path = f"{WORK}/day_{d}.parquet"
    if os.path.exists(path):
        return d, -1
    art = pickle.load(open(f"{WORK}/model_{d[:7]}.pkl", "rb"))
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    if not len(D):
        return d, 0
    D = featurize(D, art["cf"], art["prior_cut"])
    D, pc = page_cols(D)
    D["p"] = art["model"].predict_proba(D[FEATS + pc])[:, 1]; D["wp"] = D.w * D.p
    out = []
    for x, g in D.groupby("id"):
        out.append({"id": x, "day": d, "psn_ev": g.wp.sum(), "psn_fans": np.sort(g.wp.values)[-100:].sum(),
                    "psn_ev_ties": g.wp[g.backed > 0].sum(), "psn_reach": g.w.sum(), "psn_pmax": g.p.max()})
    pd.DataFrame(out).to_parquet(path)
    return d, len(D)


def main(workers):
    os.makedirs(WORK, exist_ok=True); load()
    from . import harness
    harness.baseline()   # cache the launch model's predictions now: worker processes cannot start their own pools
    ctx = mp.get_context("fork")
    with ctx.Pool(min(workers, len(MONTHS))) as pool:
        for r in pool.imap_unordered(train_month, [m for m in MONTHS if not os.path.exists(f"{WORK}/model_{m}.pkl")]):
            print("trained", r, flush=True)
    days = sorted(d for d in G["lineup"] if d[:7] in MONTHS and d <= "2026-10-24")
    with ctx.Pool(workers) as pool:
        for k, r in enumerate(pool.imap_unordered(score_day, days)):
            if k % 20 == 0:
                print("scored", k, "of", len(days), r, flush=True)
    S = pd.concat([pd.read_parquet(f"{WORK}/day_{d}.parquet") for d in days if os.path.exists(f"{WORK}/day_{d}.parquet")])
    S.to_parquet(os.path.join(HERE, "cache", "popscore_page.parquet" if PAGE else "popscore.parquet"))
    S = S.rename(columns={c: PREFIX + c[4:] for c in S.columns if c.startswith("psn_")})
    cols = [c for c in S.columns if c.startswith(PREFIX)]
    json.dump({str(r["id"]): {c: float(r[c]) for c in cols} for r in S.to_dict("records")},
              open(os.path.join(store.RAW, PREFIX + "features.json"), "w"))
    print("saved", len(S), "launches")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else os.cpu_count())
