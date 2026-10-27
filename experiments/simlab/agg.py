"""Launch-level reach x appeal: turn person-level signals into per-launch scores and test them on daily, weekly and
monthly lists, on top of the existing launch model (harness baseline). Everything is dated before the launch:
  population   the 20.7k people in the store
  exposure     w(u, d) = share of the 30 days before d on which u was active (upvoted or commented on that day's launches)
  person taste and ties come from events before the launch's MONTH starts (monthly snapshots):
    topic      person's topic mix . launch topics          meaning  person mean embedding . launch embedding
    backed     log(1 + times the person backed this team's earlier launches)
  appeal       logistic P(upvote | active) on those three, fitted on the PREVIOUS month's active person-days
Launch features (sums over people):
  ev_all     sum w * p(topic, meaning, backed)      ev_taste  same with backed = 0      ev_ties  ev_all - ev_taste
  reach_ties sum w * 1[backed > 0]                  taste_top  sum over the 200 people with the highest topic+meaning fit of w
usage: SIMLAB_DATA=data_v2 python -m simlab.agg build ; python -m simlab.agg eval -> reports/agg.json"""
import json, os, sys
import numpy as np, pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from . import store, harness as H

HERE = os.path.dirname(os.path.abspath(__file__))
OUTP = os.path.join(HERE, "cache", "agg_features.parquet")
MONTHS = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def build():
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); I = I[I.day >= "2026-01-01"].reset_index(drop=True)
    E = E[E.item.isin(day)].copy(); E["lday"] = E.item.map(day)
    people = sorted(set(E.person)); pix = {u: k for k, u in enumerate(people)}; NP = len(people)
    topics = sorted({t for ts in I.topics for t in json.loads(ts)}); tix = {t: k for k, t in enumerate(topics)}
    LT = np.zeros((len(I), len(topics)), np.float32)
    for r, ts in enumerate(I.topics):
        for t in json.loads(ts):
            LT[r, tix[t]] = 1
    Z = np.load(f"{store.RAW}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}; ZL = Z["launch"]  # read once
    LE = np.stack([ZL[li[i]] if i in li else np.zeros(ZL.shape[1], np.float32) for i in I.id]).astype(np.float32)
    LE /= np.linalg.norm(LE, axis=1, keepdims=True) + 1e-9
    iix = {i: k for k, i in enumerate(I.id)}
    members = sorted({m for ms, p in zip(I.makers, I.poster) for m in json.loads(ms) + [p] if m}); mix = {m: k for k, m in enumerate(members)}
    rows, cols = [], []
    for k, (ms, p) in enumerate(zip(I.makers, I.poster)):
        for m in set(json.loads(ms) + [p]) - {None}:
            rows.append(k); cols.append(mix[m])
    LM = sparse.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(I), len(members)))
    # daily activity matrix (people x days) for exposure
    days = sorted(I.day.unique()); dix = {d: k for k, d in enumerate(days)}
    act = E[E.date == E.lday][["person", "date"]].drop_duplicates()
    act = act[act.date.isin(dix)]
    A = sparse.csr_matrix((np.ones(len(act), np.float32), (act.person.map(pix), act.date.map(dix))), shape=(NP, len(days))).toarray()
    C = np.concatenate([np.zeros((NP, 1), np.float32), np.cumsum(A, 1)], 1)
    def w_on(d):
        k = dix[d]; return (C[:, k] - C[:, max(k - 30, 0)]) / 30.0
    out, prev_fit = [], None
    for m in MONTHS:
        start = m + "-01"
        Eb = E[E.lday < start]
        # person snapshots
        it_k = Eb.item.map(iix); ok = it_k.notna()
        Pi = sparse.csr_matrix((np.ones(int(ok.sum()), np.float32), (Eb.person[ok].map(pix), it_k[ok].astype(int))), shape=(NP, len(I)))
        PT = Pi @ LT; PT /= PT.sum(1, keepdims=True) + 1e-9
        PE = Pi @ LE; PE /= np.linalg.norm(PE, axis=1, keepdims=True) + 1e-9
        PM = (Pi @ LM).tocsr()
        age = (pd.Timestamp(start) - pd.to_datetime(Eb.lday[ok])).dt.days.values
        Pd = sparse.csr_matrix((0.5 ** (age / 30.0), (Eb.person[ok].map(pix), it_k[ok].astype(int))), shape=(NP, len(I)))
        PD = Pd @ LE; PD /= np.linalg.norm(PD, axis=1, keepdims=True) + 1e-9          # recency-weighted taste
        rec = Eb[ok & (Eb.lday >= (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d"))]
        Pr = sparse.csr_matrix((np.ones(len(rec), np.float32), (rec.person.map(pix), rec.item.map(iix).astype(int))), shape=(NP, len(I)))
        PMr = (Pr @ LM).tocsr()                                                           # team backing, last 60 days
        # category upvote rate: picks per topic / launches of that topic shown on the person's active days
        k0 = dix.get(min((d for d in days if d >= start), default=days[-1]), len(days))
        Aact = sparse.csr_matrix(A[:, :k0])
        DT = np.zeros((k0, len(topics)), np.float32)
        for dd, g in I[I.day < start].groupby("day").groups.items():
            if dd in dix and dix[dd] < k0:
                DT[dix[dd]] = LT[list(g)].sum(0)
        expo = Aact @ DT
        CR = (Pi @ LT + 5 * 0.05) / (expo + 5)   # smoothed toward a 5% rate
        Lm = I[I.day.str[:7] == m]
        if not len(Lm):
            continue
        ks = Lm.index.values
        topic = PT @ LT[ks].T / (LT[ks].sum(1) + 1e-9)            # people x launches
        mean = PE @ LE[ks].T
        backed = np.log1p((PM @ LM[ks].T).toarray())
        decay = PD @ LE[ks].T
        brec = np.log1p((PMr @ LM[ks].T).toarray())
        catr = CR @ LT[ks].T / (LT[ks].sum(1) + 1e-9)
        FE = [topic, mean, backed, decay, brec, catr]; TASTE = [0, 1, 3, 5]
        # appeal: logistic on the previous month's active person-days (fit from this month's snapshot of last month is a
        # leak, so the model fitted at the end of the previous iteration is used; first month gets none)
        have = prev_fit is not None
        if have:
            X = np.stack([f.ravel() for f in FE], 1)
            p_all = prev_fit.predict_proba(X)[:, 1].reshape(topic.shape)
            Xt = X.copy(); Xt[:, [2, 4]] = 0
            p_taste = prev_fit.predict_proba(Xt)[:, 1].reshape(topic.shape)
        # fit this month's appeal on this month's active person-days (used next month)
        real = E[(E.date == E.lday) & (E.lday.str[:7] == m)]
        Xs, ys = [], []
        by_day = Lm.groupby("day").groups
        for d, idx in by_day.items():
            cols_d = [list(ks).index(j) for j in idx]
            act_u = real[real.date == d].person.map(pix).dropna().astype(int).unique()
            if not len(act_u):
                continue
            sub = act_u[np.random.default_rng(0).permutation(len(act_u))[:300]]
            picked = set(zip(real[real.date == d].person.map(pix), real[real.date == d].item))
            for j, c in zip(idx, cols_d):
                Xs.append(np.stack([f[sub, c] for f in FE], 1))
                ys.append(np.array([(u, I.id[j]) in picked for u in sub], int))
        if Xs:
            import lightgbm as lgb
            prev_fit = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=100,
                                          verbose=-1).fit(np.concatenate(Xs), np.concatenate(ys))
        for c, j in enumerate(ks):
            d = I.day[j]; w = w_on(d)
            row = {"id": I.id[j], "reach_ties": float(w @ (backed[:, c] > 0)),
                   "taste_top": float(w[np.argsort(-(topic[:, c] + mean[:, c]))[:200]].sum())}
            if have:
                row.update(ev_all=float(w @ p_all[:, c]), ev_taste=float(w @ p_taste[:, c]),
                           fans=float(np.sort(w * p_all[:, c])[-100:].sum()), day_mass=float(w.sum()))
                row["ev_ties"] = row["ev_all"] - row["ev_taste"]
            out.append(row)
        print(m, len(ks), "launches", flush=True)
    pd.DataFrame(out).to_parquet(OUTP); print("saved", len(out))


def eval_():
    B = H.baseline(); F = pd.read_parquet(OUTP); F["id"] = F.id.astype(str)
    T = B.merge(F, on="id", how="inner").dropna(subset=["ev_all"])
    T = T[T.groupby("day").id.transform("count") >= 5]
    groups = (("day", "dailyRank"), ("week", "weeklyRank"), ("mon", "monthlyRank"))
    res = {"launches": int(len(T)), "window": [T.day.min(), T.day.max()]}
    for col in ["ev_all", "ev_taste", "ev_ties", "reach_ties", "taste_top", "fans"]:
        for g, rc in groups:
            T["pb"] = T.groupby(g).base.rank(pct=True); T["px"] = T.groupby(g)[col].rank(pct=True)
            blend = pd.Series(index=T.index, dtype=float)
            for m0 in sorted(T.mon.unique()):          # weight chosen on the other months
                tr, te = T[T.mon != m0], T[T.mon == m0]
                wbest = max((0, 0.1, 0.2, 0.3, 0.5, 0.75, 1), key=lambda w: np.mean(
                    [H.recall(tr.assign(s=tr.pb + w * tr.px), "s", group=g, col=rc, k=k) for k in H.KS]))
                blend[te.index] = te.pb + wbest * te.px
            T["blend"] = blend
            for k in H.KS:
                res.setdefault(f"{g}@{k}", {})["baseline"] = round(100 * H.recall(T, "base", group=g, col=rc, k=k), 1)
                res[f"{g}@{k}"][f"{col} alone"] = round(100 * H.recall(T, col, group=g, col=rc, k=k), 1)
                res[f"{g}@{k}"][f"+ {col}"] = round(100 * H.recall(T, "blend", group=g, col=rc, k=k), 1)
    # second stage: LightGBM on log votes from base + population sums, trained on earlier months only
    import lightgbm as lgb
    F2 = ["base", "ev_all", "ev_taste", "ev_ties", "reach_ties", "taste_top", "fans", "day_mass"]
    for c in F2[1:]:
        T[c + "_dr"] = T.groupby("day")[c].rank(pct=True)
    F2 += [c + "_dr" for c in F2[1:]]
    T["stack"] = np.nan
    for m0 in sorted(T.mon.unique())[2:]:
        tr, te = T[T.mon < m0], T[T.mon == m0]
        mdl = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=7, min_child_samples=30, verbose=-1)
        T.loc[te.index, "stack"] = mdl.fit(tr[F2], np.log1p(tr.votes)).predict(te[F2])
    S = T.dropna(subset=["stack"])
    for g, rc in groups:
        for k in H.KS:
            res.setdefault(f"{g}@{k}", {})["baseline (stack months)"] = round(100 * H.recall(S, "base", group=g, col=rc, k=k), 1)
            res[f"{g}@{k}"]["stacked: base + population sums"] = round(100 * H.recall(S, "stack", group=g, col=rc, k=k), 1)
    json.dump(res, open(f"{HERE}/reports/agg.json", "w"), indent=1)
    print(pd.DataFrame({k: v for k, v in res.items() if "@" in k}).T.to_string())


if __name__ == "__main__":
    build() if sys.argv[1] == "build" else eval_()
