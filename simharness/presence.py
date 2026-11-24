"""Presence: will a person in day D's active pool endorse anything on D?

Features use only endorsements on items with day < D (endorsements are undated and attributed to the item's day) and
comments written before D. `known_before` (a timestamp) additionally keeps only endorsements that had been READ into
the store before that time: the "as known at the start of the day" view, which matters when people are read late.

  ln_rw        ln(1 + recency-weighted endorsements, 7-day half-life)      (the round-1 baseline, alone)
  ln_dsl       ln(1 + days since the last endorsement)
  ln_n1/3/7/30 ln(1 + endorsements in the last 1 / 3 / 7 / 30 days)
  a1, a3, a7, a30   share of the last 1 / 3 / 7 / 30 days with an endorsement
  ln_streak    ln(1 + consecutive active days ending yesterday)
  wd_share     share of the person's past active days that fell on D's weekday (smoothed)
  ln_dsc       ln(1 + days since the last comment)
  ln_hist      ln(1 + days since the first dated endorsement)
  ln_total, ln_adays   ln(1 + endorsements), ln(1 + active days), all dated history
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from simharness.bench import _day_bounds_utc, day_ord

NAMES = ("ln_rw", "ln_dsl", "ln_n1", "ln_n3", "ln_n7", "ln_n30", "a1", "a3", "a7", "a30", "ln_streak", "wd_share",
         "ln_dsc", "ln_hist", "ln_total", "ln_adays")
CAP = 400.0


class PresenceData:
    def __init__(self, bench, first_seen: np.ndarray | None = None):
        self.b = bench
        self.p, self.d = bench._e_p.astype(np.int64), bench._e_day.astype(np.int64)
        self.fs = None if first_seen is None else np.asarray(first_seen, dtype="datetime64[ns]")
        self.d0 = int(bench.items["day_ord"].min())
        self.nd = int(bench.items["day_ord"].max()) - self.d0 + 2
        # comment day = the later of the item day and the comment's own date
        cd = bench._c_day.astype(np.int64).copy()
        ts = bench._c_ts
        ok = ~np.isnat(ts)
        if ok.any():
            loc = pd.Series(ts[ok]).dt.tz_localize("UTC").dt.tz_convert(bench.cfg.day_tz).dt.strftime("%Y-%m-%d")
            cd[ok] = np.maximum(cd[ok], loc.map(day_ord).to_numpy())
        self.c_p, self.c_d = bench._c_p.astype(np.int64), cd

    def cutoff(self, day: str) -> np.datetime64:
        """The moment the day's forecast is made: 5 minutes after the day starts."""
        start, _ = _day_bounds_utc(day, self.b.cfg.day_tz)
        return np.datetime64((start + pd.Timedelta(minutes=5)).tz_localize(None))

    def labels(self, day: str) -> np.ndarray:
        """1 for every person who endorsed at least one item of the day."""
        o = day_ord(day)
        lo, hi = np.searchsorted(self.d, [o, o + 1])
        y = np.zeros(self.b.n_people, np.int8)
        y[self.p[lo:hi]] = 1
        return y

    def features(self, day: str, known_before: np.datetime64 | None = None) -> np.ndarray:
        """[n_people, len(NAMES)] for the start of `day`."""
        n, o = self.b.n_people, day_ord(day)
        t = o - self.d0
        hi = np.searchsorted(self.d, o)
        p, d = self.p[:hi], self.d[:hi] - self.d0
        if known_before is not None:
            if self.fs is None:
                raise ValueError("first_seen is needed for the as-known view")
            ok = self.fs[:hi] < known_before          # NaT compares False: unknown read time = not known
            p, d = p[ok], d[ok]
        C = np.bincount(p * t + d, minlength=n * t).reshape(n, t).astype(np.float32) if t > 0 else np.zeros((n, 1), np.float32)
        A = C > 0
        age = (t - np.arange(t)).astype(np.float32)
        rw = C @ (0.5 ** (age / 7.0))
        any_ = A.any(1)
        last = np.where(any_, t - 1 - np.argmax(A[:, ::-1], axis=1), -1)
        first = np.where(any_, np.argmax(A, axis=1), t)
        dsl = np.where(any_, t - last, CAP)
        win = lambda M, k: M[:, max(t - k, 0):].sum(1)  # noqa: E731
        streak = np.zeros(n, np.float32)
        alive = np.ones(n, bool)
        for k in range(1, min(t, 60) + 1):
            alive &= A[:, t - k]
            streak += alive
        same_wd = A[:, np.arange(t - 7, -1, -7)].sum(1) if t >= 7 else np.zeros(n)
        adays = A.sum(1)
        wd = (same_wd + 1.0) / (adays + 7.0)
        if known_before is None:
            m = self.c_d < o
            lastc = np.full(n, -1, np.int64)
            np.maximum.at(lastc, self.c_p[m], self.c_d[m])
            dsc = np.where(lastc >= 0, o - lastc, CAP)
        else:
            dsc = np.full(n, CAP)                      # read times of comments are not tracked: treated as unknown
        cols = {"ln_rw": np.log1p(rw), "ln_dsl": np.log1p(np.minimum(dsl, CAP)),
                "ln_n1": np.log1p(win(C, 1)), "ln_n3": np.log1p(win(C, 3)), "ln_n7": np.log1p(win(C, 7)),
                "ln_n30": np.log1p(win(C, 30)), "a1": win(A, 1), "a3": win(A, 3) / 3.0, "a7": win(A, 7) / 7.0,
                "a30": win(A, 30) / 30.0, "ln_streak": np.log1p(streak), "wd_share": wd,
                "ln_dsc": np.log1p(np.minimum(dsc, CAP)), "ln_hist": np.log1p(t - first),
                "ln_total": np.log1p(C.sum(1)), "ln_adays": np.log1p(adays)}
        return np.column_stack([cols[k] for k in NAMES]).astype(np.float32)


class PresenceModel:
    """kind: "baseline" (ln_rw alone, logistic), "logistic" (all features) or "lgbm"."""

    def __init__(self, kind: str):
        self.kind = kind
        self.ix = [0] if kind == "baseline" else list(range(len(NAMES)))

    def fit(self, X: np.ndarray, y: np.ndarray) -> "PresenceModel":
        X = X[:, self.ix]
        if self.kind == "lgbm":
            import lightgbm as lgb
            self.clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200,
                                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1).fit(X, y)
        else:
            from sklearn.linear_model import LogisticRegression
            self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
            self.clf = LogisticRegression(max_iter=2000).fit((X - self.mu) / self.sd, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = X[:, self.ix]
        if self.kind == "lgbm":
            return self.clf.predict_proba(X)[:, 1]
        return self.clf.predict_proba((X - self.mu) / self.sd)[:, 1]


def walk_forward(pdata: PresenceData, days: list[str], kinds=("baseline", "logistic", "lgbm"), window: int = 45,
                 refit_every: int = 2, log=print) -> tuple[pd.DataFrame, dict]:
    """Score `days` in order. A model is refit every `refit_every` scored days on the `window` benchmark days before
    the refit day (pool x features x labels of those days), so no training day is on or after a scored day.
    Returns rows (day, person_idx, y, one probability column per kind) and the fitted models per day."""
    b = pdata.b
    all_days = list(b.days_info["day"])
    cache, out, models, fitted = {}, [], {}, {}

    def day_xy(d):
        if d not in cache:
            pool = b.pool(d)
            cache[d] = (pdata.features(d)[pool], pdata.labels(d)[pool])
        return cache[d]

    for k, d in enumerate(days):
        if k % refit_every == 0:
            prev = [x for x in all_days if x < d][-window:]
            assert prev and prev[-1] < d
            X = np.vstack([day_xy(x)[0] for x in prev])
            y = np.concatenate([day_xy(x)[1] for x in prev])
            models = {kind: PresenceModel(kind).fit(X, y) for kind in kinds}
            log(f"  presence fit for {d}: {len(y)} person-days from {prev[0]} to {prev[-1]}, base rate {y.mean():.3f}")
        fitted[d] = models
        pool = b.pool(d)
        Xd, yd = pdata.features(d)[pool], pdata.labels(d)[pool]
        r = pd.DataFrame({"day": d, "item_idx": 0, "person_idx": pool, "y": yd})
        for kind, m in models.items():
            r[kind] = m.predict(Xd)
        out.append(r)
    return pd.concat(out, ignore_index=True), fitted
