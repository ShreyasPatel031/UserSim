"""Push person-level hit toward 70 / 80 / 90% (top 3 / 5 / 10). Builds one cached feature frame, then runs quick tests.
Features beyond topk.py (launch-day ones are marked; everything else is dated before the day):
  early{h}h        others' comments on the launch in the first h hours (h = 1, 3, 6, 12)            [launch day]
  early_nbr{h}h    of those early commenters, how many are the person's past co-backers (backed the same launches before)  [launch day]
usage: SIMLAB_DATA=data_v2 python -m simlab.push build ; python -m simlab.push run <name>"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd, lightgbm as lgb
from . import store
from .persona import CACHE
from .v2_compare import PERS, BASE, CF
from .topk import hits

HERE = os.path.dirname(os.path.abspath(__file__))
FRAME = f"{CACHE}/push_frame.parquet"
SEQ = ["seq_last10", "seq_decay", "seq_nn", "team_recent"]
HOURS = (1, 3, 6, 12)


def build():
    from .seq import features
    from .visit import comments
    P, I, E = store.load()
    A = pd.read_parquet(f"{CACHE}/rows_v1.parquet", columns=["g"] + list(PERS)); keep = set(A.dropna(subset=list(PERS)).g)
    D = pd.read_parquet(f"{CACHE}/rows_v2.parquet"); D = D[D.g.isin(keep)].copy()
    for k in PERS:
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = features(D, I, E)
    C = comments(I); C["t"] = C.t.dt.tz_localize(None)
    day = dict(zip(I.id, I.day))
    start = {d: pd.Timestamp(d + "T00:01:00-07:00").tz_convert("UTC").tz_localize(None) for d in I.day.unique()}
    C["h"] = (C.t - C.id.map(day).map(start)).dt.total_seconds() / 3600
    # co-backers: people who backed (upvoted/commented) the same launch, before the day; per person, a weighted set
    ev = E[E.item.isin(day)]; ev = ev.assign(day=ev.item.map(day))
    by_item = ev.groupby("item").person.apply(set).to_dict()
    people = set(D.person)
    hist = ev[ev.person.isin(people)].groupby("person").apply(lambda g: list(zip(g.day, g.item)), include_groups=False).to_dict()
    for h in HOURS:
        Ch = C[C.h < h]
        n = Ch.groupby("id").size().to_dict(); own = Ch.groupby(["id", "person"]).size().to_dict()
        D[f"early{h}h"] = np.log1p([n.get(x, 0) - own.get((x, u), 0) for x, u in zip(D.id, D.person)])
        D[f"early{h}h_r"] = D.groupby("g")[f"early{h}h"].rank(pct=True)
    early_who = {h: C[C.h < h].groupby("id").person.apply(set).to_dict() for h in (3, 6)}
    nb = {h: np.zeros(len(D)) for h in (3, 6)}
    for g, idx in D.groupby("g").indices.items():
        u, d = g.split("|")
        co = defaultdict(int)
        for d0, it in hist.get(u, []):
            if d0 < d:
                for v in by_item.get(it, ()):
                    co[v] += 1
        co.pop(u, None)
        for h in (3, 6):
            nb[h][idx] = [sum(min(co.get(v, 0), 5) for v in early_who[h].get(x, ())) for x in D.id.values[idx]]
    for h in (3, 6):
        D[f"early_nbr{h}h"] = np.log1p(nb[h]); D[f"early_nbr{h}h_r"] = D.groupby("g")[f"early_nbr{h}h"].rank(pct=True)
    D.to_parquet(FRAME)
    print("frame", D.shape, "person-days", D.g.nunique())


def build2():
    """Before-launch additions (all dated before the day):
      cat_rate_max / cat_rate_mean  the person's upvote rate on launches of this category on days they were active (smoothed)
      cat_prior                     share of everyone's past picks going to the launch's categories, per launch shown
      cat_rank                      the launch's baseline-popularity rank among same-category launches that day (best over its categories)
      cat_n                         how many same-category launches compete that day
      team_comm                     closeness to the team's community: the person's co-backers who backed this team's earlier launches"""
    P, I, E = store.load(); D = pd.read_parquet(FRAME)
    day = dict(zip(I.id, I.day)); topics = {r.id: json.loads(r.topics) for r in I.itertuples()}
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()}
    lineup = I.groupby("day").id.apply(list).to_dict()
    ev = E[E.item.isin(day)]; ev = ev.assign(day=ev.item.map(day))
    real = ev[ev.day == ev.date]
    picks = real.groupby("person").apply(lambda g: sorted(set(zip(g.day, g.item))), include_groups=False).to_dict()
    # global category prior from picks before Sep 1 (train start), per launch shown
    from collections import Counter
    shown, picked = Counter(), Counter()
    for d0, ids in lineup.items():
        if d0 < "2026-09-01":
            for x in ids:
                shown.update(topics[x])
    for it in real[real.day < "2026-09-01"].item:
        picked.update(topics[it])
    prior = {t: picked[t] / max(shown[t], 1) for t in shown}
    pm = np.mean(list(prior.values()))
    # category rank of each launch that day by baseline popularity
    pop = dict(zip(D.id, D["pop"]))
    crank, cn = {}, {}
    for d0, ids in lineup.items():
        by_t = defaultdict(list)
        for x in ids:
            for t in topics[x]:
                by_t[t].append(x)
        for x in ids:
            rs = [sorted(by_t[t], key=lambda z: -pop.get(z, 0)).index(x) + 1 for t in topics[x]]
            crank[x] = min(rs) if rs else 30; cn[x] = min((len(by_t[t]) for t in topics[x]), default=30)
    # team community: supporters of each team member's earlier launches
    by_item = ev.groupby("item").person.apply(set).to_dict()
    built = defaultdict(list)
    for it, t in team.items():
        for m in t:
            if m:
                built[m].append(it)
    sup_of = {}   # every launch shown on day d launches on d, so "earlier team launches" is fixed per launch
    for x in set(D.id):
        sup = set()
        for m in team[x]:
            for it in built.get(m, ()):
                if day[it] < day[x]:
                    sup |= by_item.get(it, set())
        sup_of[x] = sup
    hist = ev[ev.person.isin(set(D.person))].groupby("person").apply(lambda g: list(zip(g.day, g.item)), include_groups=False).to_dict()
    cols = {c: np.zeros(len(D)) for c in ("cat_rate_max", "cat_rate_mean", "cat_prior", "cat_rank", "cat_n", "team_comm")}
    for g, idx in D.groupby("g").indices.items():
        u, d = g.split("|")
        sh, pk = Counter(), Counter()
        for d0 in sorted({d0 for d0, _ in picks.get(u, []) if d0 < d}):
            for x in lineup[d0]:
                sh.update(topics[x])
        for d0, it in picks.get(u, []):
            if d0 < d:
                pk.update(topics[it])
        co = defaultdict(int)
        for d0, it in hist.get(u, []):
            if d0 < d:
                for v in by_item.get(it, ()):
                    co[v] += 1
        co.pop(u, None)
        for j, x in zip(idx, D.id.values[idx]):
            ts = topics[x]
            r = [(pk[t] + 5 * prior.get(t, pm)) / (sh[t] + 5) for t in ts] or [pm]
            cols["cat_rate_max"][j] = max(r); cols["cat_rate_mean"][j] = float(np.mean(r))
            cols["cat_prior"][j] = max((prior.get(t, pm) for t in ts), default=pm)
            cols["cat_rank"][j] = crank.get(x, 30); cols["cat_n"][j] = cn.get(x, 30)
            sx = sup_of[x]
            cols["team_comm"][j] = np.log1p(sum(min(c, 5) for v, c in co.items() if v in sx) if len(co) < len(sx)
                                            else sum(min(co.get(v, 0), 5) for v in sx))
    for c, v in cols.items():
        D[c] = v
    for c in ("cat_rate_max", "cat_rate_mean", "team_comm"):
        D[c + "_r"] = D.groupby("g")[c].rank(pct=True)
    D.to_parquet(FRAME)
    print("added", list(cols))


def fit(tr, te, cols, **kw):
    prm = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1); prm.update(kw)
    return lgb.LGBMClassifier(**prm).fit(tr[cols], tr.y).predict_proba(te[cols])[:, 1]


PRE = BASE + list(PERS) + CF + SEQ
E3 = ["early3h", "early3h_r"]
CAT = ["cat_rate_max", "cat_rate_mean", "cat_prior", "cat_rank", "cat_n", "cat_rate_max_r", "cat_rate_mean_r"]
TEAM = ["team_comm", "team_comm_r"]
TESTS = {
    "pre+cat": PRE + CAT, "pre+team": PRE + TEAM, "pre+cat+team": PRE + CAT + TEAM,
    "pre": PRE, "pre+fol": PRE + ["follow"],
    "e3": PRE + E3, "e3+fol": PRE + E3 + ["follow"],
    **{f"e{h}": PRE + [f"early{h}h", f"early{h}h_r"] for h in HOURS},
    "e3+nbr": PRE + E3 + ["early_nbr3h", "early_nbr3h_r"], "e3+nbr+fol": PRE + E3 + ["early_nbr3h", "early_nbr3h_r", "follow"],
    "e6+nbr": PRE + ["early6h", "early6h_r", "early_nbr6h", "early_nbr6h_r"],
    "e6+nbr+fol": PRE + ["early6h", "early6h_r", "early_nbr6h", "early_nbr6h_r", "follow"],
}


def run(names, big=False):
    D = pd.read_parquet(FRAME)
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"].copy(); te = te[te.g.isin(te[te.y == 1].g)]
    kw = dict(n_estimators=800, learning_rate=0.03, num_leaves=31, min_child_samples=30) if big else {}
    out = {}
    for n in names:
        out[n] = hits(te, fit(tr, te, TESTS[n], **kw)); print(n, "big" if big else "", out[n], flush=True)
    return out


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build()
    elif sys.argv[1] == "build2":
        build2()
    else:
        res = run(sys.argv[2].split(","), big=len(sys.argv) > 3 and sys.argv[3] == "big")
        p = f"{HERE}/reports/push.json"; R = json.load(open(p)) if os.path.exists(p) else {}
        R.update({k + ("|big" if len(sys.argv) > 3 else ""): v for k, v in res.items()}); json.dump(R, open(p, "w"), indent=1)
