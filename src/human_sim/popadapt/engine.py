"""Interpretability + prediction engine on a ResponseTable. Nothing here knows which dataset it is looking at.

Matrix      units x (item, option) shares; missing cells NaN.
Axes        low-rank factors of that matrix (EM-PCA with missing values). An axis is reported with the item options that
            load most on each side, and is kept only if it improves held-out prediction (see evaluate.py).
Segments    k-means on unit factor scores (units described by their answers, not by their attributes); each segment is
            profiled by its over-represented attributes and its most distinctive answers.
Prediction  for a new item (e.g. a new product), given the answers of an anchor set of units that do not overlap the
            target unit: (a) anchor mean, (b) anchor regressed on axis scores, (c) anchor mean within the target's segment,
            (d) anchor mean within the target's best attribute group. (b)-(d) shrink toward (a)."""

from __future__ import annotations

import numpy as np
import pandas as pd


class Matrix:
    def __init__(self, table, items):
        self.t = table
        self.units = list(table.units.index)
        self.uidx = {u: i for i, u in enumerate(self.units)}
        self.items = list(items)
        self.cols, c = {}, 0
        for it in self.items:
            k = table.n_options(it)
            self.cols[it] = slice(c, c + k)
            c += k
        X = np.full((len(self.units), c), np.nan)
        r = table.resp[table.resp.item.isin(set(self.items))]
        for u, it, d in zip(r.unit, r.item, r.dist):
            X[self.uidx[u], self.cols[it]] = d
        self.X = X
        # each survey question counts once: a question split into m rows gets weight 1/sqrt(m) per row
        grp = table.items["group"] if "group" in table.items.columns else pd.Series(table.items.index, index=table.items.index)
        size = grp.loc[self.items].value_counts()
        self.w = np.ones(c)
        for it in self.items:
            self.w[self.cols[it]] = 1.0 / np.sqrt(size[grp.at[it]])

    def observed(self, it):
        return ~np.isnan(self.X[:, self.cols[it].start])


def fit_axes(X, rank, iters=25, seed=0, w=None):
    """EM-PCA with missing values. Returns (column means, unit scores U [n x r], loadings V [cols x r], share of
    variance of the filled matrix per axis)."""
    from sklearn.utils.extmath import randomized_svd
    w = np.ones(X.shape[1]) if w is None else w
    mask = ~np.isnan(X)
    mu = np.nanmean(X, axis=0)
    mu = np.where(np.isnan(mu), 0.0, mu)
    Z = (np.where(mask, X, mu) - mu) * w
    total = (Z ** 2).sum()
    if rank == 0:
        return mu, np.zeros((X.shape[0], 0)), np.zeros((X.shape[1], 0)), np.zeros(0)
    full_obs = mask.all()
    for _ in range(1 if full_obs else iters):
        U, s, Vt = randomized_svd(Z, rank, n_iter=4, random_state=seed)
        if full_obs:
            break
        R = (U * s) @ Vt
        Z = np.where(mask, (X - mu) * w, R)
    U, s, Vt = randomized_svd(Z, rank, n_iter=6, random_state=seed)
    var = s ** 2 / max(total, 1e-12)
    return mu, U * s, (Vt / w).T, var


def segments(scores, k, seed=0):
    from sklearn.cluster import KMeans
    if scores.shape[1] == 0 or k <= 1:
        return np.zeros(len(scores), int), None
    km = KMeans(k, n_init=10, random_state=seed).fit(scores)
    return km.labels_, km


def simplex(p):
    p = np.clip(p, 1e-4, None)
    return p / p.sum()


def _simplex_rows(P):
    P = np.clip(P, 1e-4, None)
    return P / P.sum(1, keepdims=True)


def predict_item_shared(y, anchor, targets, scores, seg, groups, shrink=5.0, ridge=1.0):
    """Fast path when every target may use the same anchor set (person-level data: units never overlap)."""
    Y = y[anchor]
    m0 = Y.mean(0)
    n_t = len(targets)
    out = {"anchor_mean": _simplex_rows(np.tile(m0, (n_t, 1)))}
    if scores.shape[1]:
        S = scores[anchor]
        Sm = S.mean(0)
        Sc = S - Sm
        B = np.linalg.solve(Sc.T @ Sc + ridge * len(S) * np.eye(S.shape[1]) * 1e-2, Sc.T @ (Y - m0))
        out["axes"] = _simplex_rows(m0 + (scores[targets] - Sm) @ B)
    else:
        out["axes"] = out["anchor_mean"].copy()
    for name, lab in (("segment", seg), ("attribute", groups)):
        if lab is None:
            out[name] = out["anchor_mean"].copy()
            continue
        la = lab[anchor]
        means = {}
        for g in np.unique(la):
            sel = la == g
            means[g] = (sel.sum() * Y[sel].mean(0) + shrink * m0) / (sel.sum() + shrink)
        out[name] = _simplex_rows(np.array([means.get(lab[t], m0) for t in targets]))
    return {k: list(v) for k, v in out.items()}


def predict_item(y, anchor, targets, scores, seg, groups, overlap_ok, shrink=5.0, ridge=1.0):
    """y: n_units x k answers to the new item (NaN rows unknown). anchor: bool mask of units whose answer is revealed.
    targets: unit indices to predict. overlap_ok(t) -> bool mask of anchor units allowed for target t.
    Returns dict method -> array [len(targets) x k]."""
    out = {m: [] for m in ("anchor_mean", "axes", "segment", "attribute")}
    for t in targets:
        a = anchor & overlap_ok(t)
        a[t] = False
        if a.sum() == 0:
            for m in out:
                out[m].append(None)
            continue
        Y = y[a]
        m0 = Y.mean(0)
        out["anchor_mean"].append(simplex(m0))
        if scores.shape[1]:
            S = scores[a]
            Sc = S - S.mean(0)
            B = np.linalg.solve(Sc.T @ Sc + ridge * len(S) * np.eye(S.shape[1]) * 1e-2, Sc.T @ (Y - m0))
            out["axes"].append(simplex(m0 + (scores[t] - S.mean(0)) @ B))
        else:
            out["axes"].append(simplex(m0))
        for name, lab in (("segment", seg), ("attribute", groups)):
            if lab is None:
                out[name].append(simplex(m0))
                continue
            same = a & (lab == lab[t])
            n = same.sum()
            g = Y[same[a]].mean(0) if n else m0
            out[name].append(simplex((n * g + shrink * m0) / (n + shrink)))
    return out


def describe_axes(table, M, V, var, top=4):
    """Each axis as its most positive and most negative item options (item text + option label)."""
    lab = []
    for it in M.items:
        for j, o in enumerate(table.items.at[it, "options"]):
            lab.append((it, str(table.items.at[it, "text"])[:140], str(o)[:40]))
    out = []
    for a in range(V.shape[1]):
        order = np.argsort(V[:, a])
        out.append({"axis": a + 1, "variance_share": round(float(var[a]), 4),
                    "high_end": [f"{lab[i][1]} -> {lab[i][2]}" for i in order[::-1][:top]],
                    "low_end": [f"{lab[i][1]} -> {lab[i][2]}" for i in order[:top]]})
    return out


def describe_segments(table, M, labels, top=5):
    """Size, over-represented attributes (lift vs everyone) and most distinctive answers of each segment."""
    U = table.units.loc[M.units]
    out = []
    for s in sorted(set(labels)):
        m = labels == s
        attrs = []
        for col in U.columns:
            base = U[col].value_counts(normalize=True)
            here = U[col][m].value_counts(normalize=True)
            for v, p in here.items():
                if base.get(v, 0) > 0.03 and m.sum() >= 20:
                    attrs.append((p / base[v], col, v, p, base[v]))
        attrs.sort(reverse=True)
        diff = np.nanmean(M.X[m], 0) - np.nanmean(M.X, 0)
        lab = [(it, str(table.items.at[it, "text"])[:100], str(o)[:40]) for it in M.items for o in table.items.at[it, "options"]]
        idx = np.argsort(-np.nan_to_num(diff))[:top]
        out.append({"segment": int(s), "size_share": round(float(m.mean()), 3),
                    "over_represented": [f"{c}={v}: {100 * p:.0f}% vs {100 * b:.0f}% overall" for _, c, v, p, b in attrs[:top]],
                    "distinctive_answers": [f"{lab[i][1]} -> {lab[i][2]} (+{100 * diff[i]:.0f} pts)" for i in idx]})
    return out
