"""Choice model: how likely each person is to upvote each launch, from three kinds of factors (all dated before the
day, except follows read today):
  popularity     the baseline model's within-day standing of the launch
  relationships  follows the poster/makers; times they backed this team before
  taste          topic overlap and pitch-meaning similarity with what they backed before
Person level: trained on Sep active person-days (they saw the list), tested on Oct ones. Scores: top-3 hit and the
average within-day AUC (does the person's real upvote outrank the launches they skipped?).
Launch level: expected votes = sum over people active in the last 30 days of P(active that day) x P(upvote),
scored in the harness against the launch baseline (experiments/choice_votes.py reads cache/choice_votes.parquet).
This is the bar the personas must beat, used as one more taste factor."""
import json, sys
from collections import Counter
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from . import store, harness
from .persona import CACHE

FACTORS = {"popularity": ["pop"], "relationships": ["follow", "backed"], "taste": ["topic", "meaning"]}


def rows(day_from="2026-09-01", day_to="2026-10-24", all_people=False):
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); topics = dict(zip(I.id, [json.loads(t) for t in I.topics]))
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()}
    fol = {r.person: set(json.loads(r.follows)) if isinstance(r.follows, str) else set() for r in P.itertuples()}
    B = harness.baseline(); B["pb"] = B.groupby("day").base.rank(pct=True); bp = dict(zip(B.id, B.pb))
    byday = B[B.day.between(day_from, day_to)].groupby("day").id.apply(list).to_dict()
    Z = np.load(f"{store.RAW}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}; EM = Z["launch"]
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    real = E[E.item.map(day) == E.date].groupby(["person", "date"]).item.apply(set).to_dict()
    out = []
    for d, line in sorted(byday.items()):
        if all_people:   # everyone active in the 30 days before d, weighted by how often they are active
            cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            who = {u: len({dt for dt, _ in h if cut <= dt < d}) / 30 for u, h in hist.items() if any(cut <= dt < d for dt, _ in h)}
        else:            # people active that day (they saw the list)
            who = {u: 1.0 for (u, dd) in real if dd == d}
        for u, w in who.items():
            h = [it for dt, it in hist.get(u, []) if dt < d]
            tc = Counter(x for it in h for x in topics.get(it, [])); tot = sum(tc.values()) or 1
            bk = Counter(m for it in h for m in team.get(it, ()))
            hv = EM[[li[i] for i in h if i in li]].mean(0) if any(i in li for i in h) else None
            t = real.get((u, d), set())
            for x in line:
                out.append((u, d, x, w, bp.get(x, 0.5), float(bool(fol.get(u, set()) & team[x])),
                            np.log1p(sum(bk[m] for m in team[x])),
                            np.mean([tc[k] / tot for k in topics.get(x, [])]) if topics.get(x) else 0.0,
                            float(EM[li[x]] @ hv / (np.linalg.norm(hv) + 1e-9)) if (hv is not None and x in li) else 0.0,
                            int(x in t)))
    D = pd.DataFrame(out, columns=["person", "day", "id", "w", "pop", "follow", "backed", "topic", "meaning", "y"])
    D["g"] = D.person + "|" + D.day
    for c in ("topic", "meaning"):  # standing within the person's line-up that day
        D[c] = D.groupby("g")[c].rank(pct=True)
    return D


def person_metrics(te, p):
    te = te.assign(p=p)
    r = te.groupby("g").p.rank(ascending=False, method="first")
    hit = te[r <= 3].groupby("g").y.any().reindex(te.g.unique(), fill_value=False).mean()
    aucs = [roc_auc_score(g.y, g.p) for _, g in te.groupby("g") if 0 < g.y.sum() < len(g)]
    return hit, float(np.mean(aucs))


def main():
    D = rows()
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"]
    print(f"person-days: train (Sep) {tr.g.nunique()}, test (Oct) {te.g.nunique()}")
    res, models = [], {}
    for name, keys in [("popularity", ["popularity"]), ("+ relationships", ["popularity", "relationships"]),
                       ("+ taste", ["popularity", "relationships", "taste"])]:
        cols = [c for k in keys for c in FACTORS[k]]
        m = LogisticRegression(max_iter=2000).fit(tr[cols], tr.y)
        hit, auc = person_metrics(te, m.predict_proba(te[cols])[:, 1])
        res.append({"model": name, "top-3 hit": f"{hit:.1%}", "within-day AUC": round(auc, 3),
                    "weights": dict(zip(cols, np.round(m.coef_[0], 2)))}); models[name] = (m, cols)
    print(pd.DataFrame(res).to_string(index=False))
    # launch level: everyone recently active, weighted by activity
    A = rows(all_people=True)
    m, cols = models["+ taste"]
    A["p"] = m.predict_proba(A[cols])[:, 1] * A.w
    out = A.groupby("id").p.sum().rename("choice_votes").reset_index()
    for name in ("popularity", "+ relationships"):
        mm, cc = models[name]
        out = out.merge((A.assign(q=mm.predict_proba(A[cc])[:, 1] * A.w).groupby("id").q.sum()
                         .rename(f"choice_votes_{name.strip('+ ').replace(' ', '_')}").reset_index()), on="id")
    out.to_parquet(f"{CACHE}/choice_votes.parquet")
    print("launch scores saved:", len(out))


if __name__ == "__main__":
    main()
