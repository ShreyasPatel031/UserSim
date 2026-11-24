"""taste-v1: a learned person x item model on history features (simharness.features.TASTE_NAMES).

Training rows come from the train split only (item day <= train_end): per item, up to `max_pos` positives, the same
number of activity-matched negatives (hard: nearest rw30 among non-voters of that item) and `k_rand` random pool
negatives. Every feature of a row is computed from history before that row's day. The fitted model is frozen and
applied to validation and test days unchanged (no refit on later days). Learner: LightGBM or logistic regression,
chosen by the caller on validation.

Weights (`pool_weights`): random negatives stand for the item's whole non-voting pool, sampled positives for all of
the item's voters, and the hard negatives carry `hard_share` of the item's negative mass. Unweighted rows (hard
negatives = half the data) rank matched pairs about as well but give a full-pool ranking worse than random, because
the model learns "light users with concentrated topics vote"; choose `hard_share` on validation.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from simharness.features import TASTE_NAMES, TasteFeatures, matched_negatives
from simharness.models.base import VoteModel


def training_rows(bench, days, max_pos=60, k_rand=20, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for d in days:
        pool = bench.pool(d)
        for it in bench.items_on(d):
            allpos = bench.positives(d, it)
            if len(allpos) == 0:
                continue
            sub = rng.choice(allpos, max_pos, replace=False) if len(allpos) > max_pos else allpos
            pos, hard = matched_negatives(bench, d, it, rng, 1, positives=sub)
            rest = np.setdiff1d(np.setdiff1d(pool, allpos), hard)
            rnd = rng.choice(rest, min(k_rand, len(rest)), replace=False)
            out.append(pd.DataFrame({"day": d, "item_idx": int(it), "person_idx": np.r_[pos, hard, rnd].astype(np.int64),
                                     "y": np.r_[np.ones(len(pos)), np.zeros(len(hard) + len(rnd))].astype(np.int8),
                                     "neg_kind": ["pos"] * len(pos) + ["hard"] * len(hard) + ["rand"] * len(rnd)}))
    return pd.concat(out, ignore_index=True)


def pool_weights(bench, rows: pd.DataFrame, hard_share: float = 0.1) -> np.ndarray:
    g = rows.groupby(["day", "item_idx"])
    npool = rows["day"].map({d: len(bench.pool(d)) for d in rows["day"].unique()}).to_numpy()
    npos = np.array([len(bench.positives(d, i)) for d, i in zip(rows["day"], rows["item_idx"])])
    count = lambda kind: g["neg_kind"].transform(lambda s: (s == kind).sum()).to_numpy()  # noqa: E731
    nr, nh, ns = count("rand"), count("hard"), count("pos")
    k = rows["neg_kind"].to_numpy()
    tot = (npool - npos).astype(float)
    w = np.where(k == "rand", tot / np.maximum(nr, 1), np.where(k == "pos", npos / np.maximum(ns, 1), 1.0))
    return np.where(k == "hard", hard_share * tot / np.maximum(nh, 1), w)


def featurize(tf: TasteFeatures, rows: pd.DataFrame) -> np.ndarray:
    rows = rows.reset_index(drop=True)
    X = np.zeros((len(rows), len(TASTE_NAMES)), np.float32)
    for d, g in rows.groupby("day"):
        persons = np.unique(g["person_idx"].to_numpy())
        blk = tf.person_block(d, persons)
        loc = {p: k for k, p in enumerate(persons)}
        for it, gi in g.groupby("item_idx"):
            k = np.array([loc[p] for p in gi["person_idx"]])
            sub = {key: v[k] for key, v in blk.items()}
            X[gi.index.to_numpy()] = tf.features(d, persons[k], int(it), block=sub)
    return X


class TasteVote(VoteModel):
    def __init__(self, tf: TasteFeatures, learner: str = "lgbm", name: str | None = None, **params):
        self.tf, self.learner, self.params = tf, learner, params
        self.name = name or f"taste-v1 ({learner})"
        self._blk_key, self._blk = None, None

    def fit(self, X: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "TasteVote":
        if self.learner == "lgbm":
            import lightgbm as lgb
            p = dict(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=100, subsample=0.8,
                     subsample_freq=1, colsample_bytree=0.8, verbose=-1)
            p.update(self.params)
            self.clf = lgb.LGBMClassifier(**p).fit(X, y, sample_weight=sample_weight)
        else:
            from sklearn.linear_model import LogisticRegression
            self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
            self.clf = LogisticRegression(max_iter=2000, C=self.params.get("C", 1.0)).fit(
                (X - self.mu) / self.sd, y, sample_weight=sample_weight)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.learner == "lgbm":
            return self.clf.predict_proba(X)[:, 1]
        return self.clf.predict_proba((X - self.mu) / self.sd)[:, 1]

    def score(self, histories, item) -> np.ndarray:
        key = (histories.day, hashlib.md5(histories.person_idx.tobytes()).hexdigest())
        if key != self._blk_key:
            self._blk_key, self._blk = key, self.tf.person_block(histories.day, histories.person_idx)
        X = self.tf.features(histories.day, histories.person_idx, item.item_idx, block=self._blk)
        return self.predict(X)
