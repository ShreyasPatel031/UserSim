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
TASTE = os.environ.get("TASTE") == "1"  # + each person's taste for page traits (page_taste.py), implies PAGE
HERD = os.environ.get("HERD") == "1"    # + how popular the taste simulation's first pass made each launch that day (implies TASTE)
TASTE = TASTE or HERD
PAGE = PAGE or TASTE
PRESENCE = os.environ.get("PRESENCE") == "1"   # + when the person is usually active (presence.py)
TWIN = os.environ.get("TWIN") == "1"           # + vector twin: recency-weighted taste vector vs the launch (presence.py)
TIE2 = os.environ.get("TIE2") == "1"           # + tie extensions: return rate to the team, team turnout, recency decay (implies TIE)
TIE = os.environ.get("TIE") == "1" or TIE2     # + tie strength: makers vs hunter, recency, comments, share of history (tie_features)
LAG = int(os.environ.get("UPV_LAG", "0"))      # live-data test: hide upvotes from the LAG days before each scored day (comments kept)
TAG = "herd" if HERD else "page_taste" if TASTE else "page" if PAGE else ""
if PRESENCE or TWIN or TIE:
    TAG = (TAG + "_" if TAG else "") + ("pres" if PRESENCE else "") + ("twin" if TWIN else "") + ("tie2" if TIE2 else "tie" if TIE else "")
if LAG:
    TAG += f"_lag{LAG}"
WORK = os.path.join(HERE, "cache", "popscore_" + TAG if TAG else "popscore")
PREFIX = f"pl{LAG}{'x' if TIE2 else ''}_" if LAG else "psx_" if TIE2 else "psr_" if TIE else "psq_" if (PRESENCE or TWIN) else "psh_" if HERD else "pst_" if TASTE else "psp_" if PAGE else "psn_"
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


RECIP = os.environ.get("RECIP") == "1"   # + reciprocity: the launch team engaged with this person's own launches before
if RECIP:
    FEATS = FEATS + ["recip_team", "recip_n"]


if PRESENCE:
    FEATS = FEATS + ["pres_early2", "pres_early6", "pres_late", "pres_n"]
if TWIN:
    FEATS = FEATS + ["twin_cos", "twin_rank"]
TIE_COLS = ["tie_maker", "tie_hunter", "tie_maker_comments", "tie_makers_n", "tie_days", "tie_share", "tie_mutual", "tie_rank", "tie_rel_rank"]
TIE2_COLS = ["tie_return_mk", "tie_opps_mk", "tie_return_hu", "tie_opps_hu", "team_turnout_mk", "team_turnout_hu", "team_backers_mk", "tie_decay"]
if TIE2:
    TIE_COLS = TIE_COLS + TIE2_COLS
if TIE:
    FEATS = FEATS + TIE_COLS


def tie_features(D):
    """Tie strength, all from the person's actions before the day (rel_split.py: a line-up holds ~9 tied launches; the
    model knew a tie existed but not which one the person acts on).
      tie_maker           log count of the person's past upvotes/comments on launches MADE by this launch's makers
      tie_hunter          log count on launches HUNTED by this launch's hunter (when the hunter is not a maker)
      tie_maker_comments  log count of past comments on the makers' launches (a stronger act than an upvote)
      tie_makers_n        how many of this launch's makers the person has backed
      tie_days            days since the person last engaged with a maker's launch (999 = never)
      tie_share           share of the person's past actions that went to these makers
      tie_mutual          both ways: tie_maker x log(1 + the makers' engagement with the person's own launches)
      tie_rank            standing of tie_maker within the person's line-up that day (1 = strongest)
      tie_rel_rank        standing of tie_maker - 0.3 x tie_days/30 within the line-up (strong and recent first)"""
    g = load()
    if "tie_hist" not in G:
        I, E = g["I"], g["E"]
        mk = {r.id: set(json.loads(r.makers)) - {""} for r in I.itertuples()}
        hu = {r.id: r.poster for r in I.itertuples()}
        Es = E[E.item.isin(mk)].sort_values("date")
        G["tie_hist"] = {u: (gg.date.values, gg.item.values, (gg.kind == "comment").values) for u, gg in Es.groupby("person")}
        G["tie_mk"], G["tie_hu"] = mk, hu
        made = defaultdict(list)
        for x, ms in mk.items():
            for m in ms:
                made[m].append(x)
        eng = defaultdict(list)   # person -> [(date, engager)] on the person's own launches
        own = E[E.item.isin(mk)]
        for it, who, dt in zip(own.item, own.person, own.date):
            for m in mk.get(it, ()):
                if m != who:
                    eng[m].append((dt, who))
        G["tie_eng"] = eng
    H, mk, hu, eng = G["tie_hist"], G["tie_mk"], G["tie_hu"], G["tie_eng"]
    cache = {}
    out = {c: [] for c in TIE_COLS[:7]}
    for u, d, x in zip(D.person, D.day, D.id):
        k = (u, d)
        if k not in cache:
            h = H.get(u)
            cm, cc, ch, last = Counter(), Counter(), Counter(), {}
            tot = 0
            if h is not None:
                n = int(np.searchsorted(h[0], d)); tot = n
                for dt, it, isc in zip(h[0][:n], h[1][:n], h[2][:n]):
                    for m in mk.get(it, ()):
                        cm[m] += 1; last[m] = dt
                        if isc:
                            cc[m] += 1
                    p = hu.get(it)
                    if p and p not in mk.get(it, ()):
                        ch[p] += 1
            back = Counter(w for dt, w in eng.get(u, []) if dt < d)
            cache[k] = (cm, cc, ch, last, tot, back, pd.Timestamp(d))
        cm, cc, ch, last, tot, back, td = cache[k]
        ms = mk.get(x, set()); p = hu.get(x)
        a = sum(cm[m] for m in ms)
        out["tie_maker"].append(np.log1p(a))
        out["tie_hunter"].append(np.log1p(ch[p]) if p and p not in ms else 0.0)
        out["tie_maker_comments"].append(np.log1p(sum(cc[m] for m in ms)))
        out["tie_makers_n"].append(float(sum(cm[m] > 0 for m in ms)))
        ls = [last[m] for m in ms if m in last]
        out["tie_days"].append(float((td - pd.Timestamp(max(ls))).days) if ls else 999.0)
        out["tie_share"].append(a / tot if tot else 0.0)
        out["tie_mutual"].append(np.log1p(a) * np.log1p(sum(back[m] for m in ms)))
    for c, v in out.items():
        D[c] = v
    gp = D.groupby(["person", "day"])
    D["tie_rank"] = gp.tie_maker.rank(ascending=False, method="average")
    D["_s"] = D.tie_maker - 0.3 * np.minimum(D.tie_days, 360) / 30
    D["tie_rel_rank"] = D.groupby(["person", "day"])._s.rank(ascending=False, method="average")
    D = D.drop(columns="_s")
    return tie2_features(D) if TIE2 else D


def tie2_features(D):
    """Tie extensions (agenda item 2), all from actions before the day. Computed separately for the makers (_mk: launches
    made by any of this launch's makers) and the hunter (_hu: launches hunted by this launch's hunter, when not a maker),
    because a prolific hunter has hundreds of launches and swamps the makers' signal.
      tie_return_*    of the team's launches after the person first engaged with that team, the share the person engaged
                      with again (NaN if the person never engaged or the team has not launched since)
      tie_opps_*      how many such later launches there were (log)
      team_turnout_*  for the team as a whole: across its past launches in order, the share of earlier backers who came
                      back to each next launch (NaN with fewer than 2 past launches)
      team_backers_mk log count of distinct people who ever engaged with the makers' past launches
      Makers listed on more than 30 launches (platform or agency accounts) are left out of the makers' team.
      tie_decay       recency-weighted engagement with the makers' launches, each action weighted exp(-age / 60 days)"""
    g = load()
    if "tie_made" not in G:
        made, hunted = defaultdict(list), defaultdict(list)
        for r in g["I"].itertuples():
            ms = set(json.loads(r.makers)) - {""}
            for m in ms:
                made[m].append(r.id)
            if r.poster and r.poster not in ms:
                hunted[r.poster].append(r.id)
        G["tie_made"] = (made, hunted)
        E = g["E"]; Es = E[E.item.isin(G["tie_mk"])]
        G["tie_backers"] = {it: (np.array(q.date.values, dtype=object), np.array(q.person.values, dtype=object)) for it, q in Es.groupby("item")}
        G["tie_c2"] = ({}, {})
    (made, hunted), backers, day = G["tie_made"], G["tie_backers"], g["day"]
    H, mk, hu = G["tie_hist"], G["tie_mk"], G["tie_hu"]
    cu, cx = G["tie_c2"]

    def team_l(x, d):
        ms = mk.get(x, set()); p = hu.get(x)
        # makers listed on more than 30 launches act like hunters (platform or agency accounts): left out of the makers' team
        lm = sorted({l for m in ms if len(made.get(m, ())) <= 30 for l in made.get(m, ()) if day.get(l, "9") < d}, key=lambda l: day[l])
        lh = sorted({l for l in hunted.get(p, ()) if day.get(l, "9") < d}, key=lambda l: day[l]) if p and p not in ms else []
        return lm, lh

    def turnout(L, d):
        seen, num, den = set(), 0, 0
        for l in L:
            b = backers.get(l)
            B = set(b[1][b[0] < d]) if b is not None else set()
            den += len(seen); num += len(B & seen); seen |= B
        return (num / den if den else np.nan), len(seen)

    def ret(L, eng):
        f = min((day[l] for l in L if l in eng), default=None)
        opps = [l for l in L if f is not None and day[l] > f]
        return (sum(l in eng for l in opps) / len(opps) if opps else np.nan), np.log1p(len(opps))
    out = {c: [] for c in TIE2_COLS}
    for u, d, x in zip(D.person, D.day, D.id):
        if x not in cx:
            lm, lh = team_l(x, d); tm, nm = turnout(lm, d); th, _ = turnout(lh, d)
            cx[x] = (lm, lh, tm, th, np.log1p(nm))
        k = (u, d)
        if k not in cu:
            if len(cu) > 200000:
                cu.clear()
            h = H.get(u)
            if h is None:
                cu[k] = (set(), Counter())
            else:
                n = int(np.searchsorted(h[0], d)); age = (np.datetime64(d) - np.array(h[0][:n], dtype=object).astype("datetime64[D]")).astype(int)
                dec = Counter()
                for it, a in zip(h[1][:n], age):
                    for m in mk.get(it, ()):
                        dec[m] += float(np.exp(-a / 60))
                cu[k] = (set(h[1][:n]), dec)
        eng, dec = cu[k]
        lm, lh, tm, th, nb = cx[x]
        rm, om = ret(lm, eng); rh, oh = ret(lh, eng)
        for c, v in zip(TIE2_COLS, (rm, om, rh, oh, tm, th, nb, sum(dec[m] for m in mk.get(x, ())))):
            out[c].append(v)
    for c, v in out.items():
        D[c] = v
    return D


def recip_features(D):
    """recip_team: upvotes/comments by the launch's team on launches this person made, before the day (log).
    recip_n: how many distinct people engaged with this person's launches before the day (log; a maker's own reach)."""
    g = load()
    if "recip" not in G:
        I, E = g["I"], g["E"]
        made = defaultdict(list)
        for r in I.itertuples():
            for m in set(json.loads(r.makers)) | {r.poster}:
                made[str(r.id)].append(m)
        E2 = E.assign(item=E.item.astype(str)); E2 = E2[E2.item.isin(made)]
        rec = defaultdict(list)   # maker -> [(date, engager)]
        for it, who, dt in zip(E2.item, E2.person, E2.date):
            for m in made[it]:
                if m != who:
                    rec[m].append((dt, who))
        G["recip"] = {m: sorted(v) for m, v in rec.items()}
    rec, team = G["recip"], g["team"]
    rt, rn = [], []
    cache = {}
    for u, d, x in zip(D.person, D.day, D.id):
        k = (u, d)
        if k not in cache:
            v = rec.get(u, [])
            cache[k] = Counter(w for dt, w in v if dt < d)
        c = cache[k]
        rt.append(np.log1p(sum(c.get(m, 0) for m in team.get(x, ()))))
        rn.append(np.log1p(len(c)))
    D["recip_team"], D["recip_n"] = rt, rn
    return D


COMP = os.environ.get("COMP") == "1"   # + did this person already use this launch's competitors (nearest earlier launches)
if COMP:
    FEATS = FEATS + ["comp_used5", "comp_n20", "comp_best"]


def comp_features(D):
    """Competitors of a launch = its 20 nearest earlier Product Hunt launches by meaning (name, tagline, description).
    comp_used5: the person upvoted or commented on one of the 5 nearest before the day; comp_n20: how many of the 20;
    comp_best: rank of the nearest one they used (21 = none)."""
    g = load()
    if "comp_nb" not in G:
        Z = np.load(f"{store.RAW}/emb.npz"); ids = [str(x) for x in Z["launch_ids"]]
        V = Z["launch"] / np.linalg.norm(Z["launch"], axis=1, keepdims=True)
        day = {str(k): v for k, v in g["day"].items()}; zday = np.array([day.get(x, "9999") for x in ids])
        G["comp_nb"] = (ids, V, zday, {x: k for k, x in enumerate(ids)}, {})
        E = g["E"]; first = E.assign(item=E.item.astype(str)).groupby(["person", "item"]).date.min()
        hist = {}
        for (u, it), dt in first.items():
            hist.setdefault(u, {})[it] = dt
        G["comp_hist"] = hist
    ids, V, zday, ix, cache = G["comp_nb"]; hist = G["comp_hist"]

    def nb(x):
        if x not in cache:
            k = ix.get(x)
            if k is None:
                cache[x] = []
            else:
                s = V @ V[k]; s[zday >= zday[k]] = -9
                cache[x] = [ids[j] for j in np.argsort(-s)[:20]]
        return cache[x]
    u5, n20, best = [], [], []
    for u, d, x in zip(D.person, D.day, D.id.astype(str)):
        h = hist.get(u, {}); used = [k for k, c in enumerate(nb(x)) if h.get(c, "9999") < d]
        u5.append(float(any(k < 5 for k in used))); n20.append(float(len(used))); best.append(float(used[0] + 1) if used else 21.0)
    D["comp_used5"], D["comp_n20"], D["comp_best"] = u5, n20, best
    return D


def featurize(D, cf, prior_cut):
    g = load()
    D = seq_features(D, g["I"], g["E"])
    D = apply_cf(D, cf)
    D = cat_features(D, prior_cut)
    D = recip_features(D) if RECIP else D
    D = comp_features(D) if COMP else D
    D = tie_features(D) if TIE else D
    if PRESENCE or TWIN:
        from . import presence
        D = presence.add_presence(D) if PRESENCE else D
        D = presence.add_twin(D) if TWIN else D
    return D


# ---- phase A: per month, train the person model on the previous month
def page_cols(D):
    """Join the launch-page inputs (ps_ Gemini element scores, pf_ page facts, vs_ video) when PAGE is on."""
    if not PAGE:
        return D, []
    from .page_choice import page_table
    T = G.setdefault("page", page_table())
    D = D.copy(); D["id"] = D.id.astype(str)
    tc = []
    if TASTE:
        from .page_taste import add_taste
        D, tc = add_taste(D)
    hc = []
    if HERD:   # simulated popularity, never real votes: first-pass simulation scores, ranked within the day
        P1 = os.path.join(HERE, "cache", "popscore_page_taste")
        H = []
        for d in D.day.unique():
            f = f"{P1}/day_{d}.parquet"
            if os.path.exists(f):
                h = pd.read_parquet(f)[["id", "day", "psn_ev", "psn_top1"]]
                for c in ("psn_ev", "psn_top1"):
                    h["herd_" + c[4:]] = h[c].rank(pct=True)
                h["herd_rank"] = h.psn_ev.rank(ascending=False)
                H.append(h[["id", "day", "herd_ev", "herd_top1", "herd_rank"]])
        hc = ["herd_ev", "herd_top1", "herd_rank"]
        if H:
            H = pd.concat(H); H["id"] = H.id.astype(str); D = D.merge(H, on=["id", "day"], how="left")
        else:
            for c in hc:
                D[c] = np.nan
    return D.join(T, on="id"), list(T.columns) + tc + hc


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


def lag_view(d):
    """UPV_LAG: what a live run would see on day d when upvote pages are refreshed only every LAG days. Upvotes dated in
    [d - LAG, d) are dropped from every feature (ties, history, activity weights, taste); comments are kept (they arrive
    daily); day-d events stay for the labels. Person models are trained on complete earlier months, as they would be live."""
    g = load()
    E = G.setdefault("E_full", g["E"])
    cut = (pd.Timestamp(d) - pd.Timedelta(days=LAG)).strftime("%Y-%m-%d")
    G["E"] = E[(E.kind != "upvote") | (E.date < cut) | (E.date >= d)]
    for k in ("tie_hist", "tie_mk", "tie_hu", "tie_eng", "recip", "comp_nb", "comp_hist", "tie_made", "tie_backers", "tie_c2"):
        G.pop(k, None)
    if TASTE:
        from . import page_taste
        page_taste.traits()
        Z = page_taste.G["Z"]; Ev = G["E"][G["E"].item.astype(str).isin(Z.index)].copy(); Ev["item"] = Ev.item.astype(str)
        page_taste.G["hist"] = {u: (q.date.values, q.item.values) for u, q in Ev.sort_values("date").groupby("person")}
    store.load = lambda: (G["P"], G["I"], G["E"])   # choice.rows reads the store itself


# ---- phase B: per day, score the population and sum per launch
def score_day(d):
    path = f"{WORK}/day_{d}.parquet"
    if os.path.exists(path):
        return d, -1
    if LAG:
        lag_view(d)
    art = pickle.load(open(f"{WORK}/model_{d[:7]}.pkl", "rb"))
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    if not len(D):
        return d, 0
    D = featurize(D, art["cf"], art["prior_cut"])
    D, pc = page_cols(D)
    D["p"] = art["model"].predict_proba(D[FEATS + pc])[:, 1]; D["wp"] = D.w * D.p
    # choice-style: each person splits their expected picks over the day's line-up (relative taste, not activity)
    by = D.groupby("person").p
    D["ws"] = D.w * D.p / by.transform("sum") * by.transform("sum").clip(upper=3)
    rk = by.rank(ascending=False, method="first")
    D["w1"] = D.w * (rk == 1); D["w3"] = D.w * (rk <= 3)
    out = []
    for x, g in D.groupby("id"):
        out.append({"id": x, "day": d, "psn_ev": g.wp.sum(), "psn_fans": np.sort(g.wp.values)[-100:].sum(),
                    "psn_ev_ties": g.wp[g.backed > 0].sum(), "psn_reach": g.w.sum(), "psn_pmax": g.p.max(),
                    "psn_share": g.ws.sum(), "psn_top1": g.w1.sum(), "psn_top3": g.w3.sum()})
    pd.DataFrame(out).to_parquet(path)
    return d, len(D)


def main(workers):
    os.makedirs(WORK, exist_ok=True); load()
    if TASTE:
        from .page_taste import traits
        traits()   # build once before forking
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
    S.to_parquet(os.path.join(HERE, "cache", f"popscore_{TAG}.parquet" if TAG else "popscore.parquet"))
    S = S.rename(columns={c: PREFIX + c[4:] for c in S.columns if c.startswith("psn_")})
    cols = [c for c in S.columns if c.startswith(PREFIX)]
    json.dump({str(r["id"]): {c: float(r[c]) for c in cols} for r in S.to_dict("records")},
              open(os.path.join(store.RAW, PREFIX + "features.json"), "w"))
    print("saved", len(S), "launches")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else os.cpu_count())
