"""Non-LLM baselines: most-active and a walk-forward logistic model in the spirit of E5's BACKER-v2.

Features (all from history before the day; see bench.HistoryBatch):
  ln_rw   ln(1 + recency-weighted endorsements), 7-day half-life
  tm      topic match: mean over the item's topics of the share of the person's past endorsements with that topic
  ln_rw_x_tm  the interaction
  ln_n60  ln(1 + endorsements in the last 60 days)   (most-active uses only this)

Follow edges are not used: in the Product Hunt store they are undated snapshots, so a follow made after D would leak.

Walk-forward: before scoring day D the model is fit on a training sample (all positives + k negatives per item,
weights undo the sampling) from days strictly before D, optionally only those already closed `gap_days` earlier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from simharness.bench import day_ord, ord_day
from simharness.models.base import VoteModel


def features(batch, item, names: tuple[str, ...]) -> np.ndarray:
    cols = {}
    if any(n in names for n in ("ln_rw", "ln_rw_x_tm")):
        cols["ln_rw"] = np.log1p(batch.feature("rw"))
    if any(n in names for n in ("tm", "ln_rw_x_tm")):
        cols["tm"] = batch.topic_match(item)
    if "ln_rw_x_tm" in names:
        cols["ln_rw_x_tm"] = cols["ln_rw"] * cols["tm"]
    if "ln_n60" in names:
        cols["ln_n60"] = np.log1p(batch.feature("n60"))
    return np.column_stack([cols[n] for n in names])


class LogisticVote(VoteModel):
    def __init__(self, names=("ln_rw", "tm", "ln_rw_x_tm"), k_neg: int = 20, train_days: int | None = None,
                 gap_days: int = 1, refit_every: int = 1, C: float = 1.0, seed: int = 0, name: str | None = None):
        self.names = tuple(names)
        self.k_neg, self.train_days, self.gap_days = k_neg, train_days, gap_days
        self.refit_every, self.C, self.seed = refit_every, C, seed
        self.name = name or "logistic(" + ",".join(self.names) + ")"
        self.clf = None
        self._fit_day = None
        self._rows: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def _day_rows(self, bench, d: str):
        if d not in self._rows:
            s = bench.training_sample([d], k=self.k_neg, seed=self.seed + day_ord(d))
            X, y, w = [], [], []
            for it, g in s.groupby("item_idx"):
                b = bench.batch(d, g["person_idx"].to_numpy())
                X.append(features(b, bench.item(it), self.names)); y.append(g["y"].to_numpy()); w.append(g["w"].to_numpy())
            self._rows[d] = (np.vstack(X), np.concatenate(y), np.concatenate(w)) if X else (
                np.zeros((0, len(self.names))), np.zeros(0), np.zeros(0))
        return self._rows[d]

    def prepare(self, bench, day: str) -> None:
        o = day_ord(day)
        if self._fit_day is not None and o - day_ord(self._fit_day) < self.refit_every:
            return
        avail = [d for d in bench.days_info["day"] if day_ord(d) <= o - self.gap_days]
        if self.train_days:
            avail = [d for d in avail if day_ord(d) > o - self.gap_days - self.train_days]
        if not avail:
            raise ValueError(f"no training days before {day}")
        parts = [self._day_rows(bench, d) for d in avail]
        X = np.vstack([p[0] for p in parts]); y = np.concatenate([p[1] for p in parts])
        w = np.concatenate([p[2] for p in parts])
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        self.clf = LogisticRegression(C=self.C, max_iter=1000).fit((X - self.mu) / self.sd, y, sample_weight=w)
        self._fit_day = day
        self.fit_info = {"fit_for": day, "train_first": avail[0], "train_last": avail[-1], "rows": int(len(y)),
                         "coef": dict(zip(self.names, np.round(self.clf.coef_[0] / self.sd, 4).tolist()))}

    def score(self, histories, item) -> np.ndarray:
        X = features(histories, item, self.names)
        return self.clf.predict_proba((X - self.mu) / self.sd)[:, 1]


def most_active(**kw) -> LogisticVote:
    """Ranks by 60-day endorsement count; a 1-feature walk-forward logistic turns the count into a probability
    (monotone, so recall@N and AUC equal those of the raw count)."""
    return LogisticVote(names=("ln_n60",), name="most-active", **kw)


def backer_logistic(**kw) -> LogisticVote:
    return LogisticVote(names=("ln_rw", "tm", "ln_rw_x_tm"), name="logistic rw+topic (BACKER-v2 style)", **kw)
