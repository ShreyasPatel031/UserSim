"""CHOICE benchmark: given that a person endorsed something on day D, which items of the day's line-up?

One row per (person, day) where a person of the day's active pool endorsed at least one item of the line-up as it
stood at the start of the day. Candidates = that line-up. Label = the items they endorsed. A model gives every
(person, item) a score; metrics are per person-day and averaged:

  top3   at least one of the model's 3 highest-ranked items was endorsed
  mrr    1 / rank of the best-ranked endorsed item
  auc    endorsed items ranked above the others (person-days that endorsed the whole line-up are skipped)

Intervals: bootstrap over days. Ties in a model's scores are broken at random (seeded).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from simharness.bench import day_ord

SCHEMA_NOTE = ("CHOICE rows. choice_persondays: split, day, person_idx (row of bench_v0 data/people.parquet), "
               "n_upvoted (line-up launches the person upvoted that day), n_upvoted_off_lineup (their upvotes that day "
               "on launches that were not on the line-up), lineup_size. choice_labels: day, person_idx, item_idx (row "
               "of data/items.parquet) for every upvoted line-up launch. choice_lineup: day, item_idx, source (0005 = "
               "the 00:05 PT capture; same-day capture = a later capture that day, validation only), structural (the "
               "structural model's frozen 00:05 score, NaN when the day has none). Integer keys only.")


@dataclass
class ChoiceDay:
    day: str
    persons: np.ndarray   # [P]
    items: np.ndarray     # [L]
    Y: np.ndarray         # [P, L] bool
    structural: np.ndarray  # [L] (NaN when unknown)
    source: str


def build(bench, lineup: pd.DataFrame, days: list[str]) -> dict[str, ChoiceDay]:
    out = {}
    for d in days:
        lu = lineup[lineup["day"] == d]
        if lu.empty:
            continue
        items = lu["item_idx"].to_numpy().astype(np.int64)
        pool = bench.pool(d)
        loc = {int(p): k for k, p in enumerate(pool)}
        Y = np.zeros((len(pool), len(items)), bool)
        for j, it in enumerate(items):
            pos = bench.positives(d, it)
            Y[[loc[int(p)] for p in pos], j] = True
        keep = Y.any(1)
        out[d] = ChoiceDay(d, pool[keep].astype(np.int64), items, Y[keep], lu["structural"].to_numpy(dtype=float),
                           str(lu["source"].iloc[0]))
    return out


def tables(bench, cds: dict[str, ChoiceDay]) -> tuple[pd.DataFrame, pd.DataFrame]:
    pdays, labels = [], []
    for d, c in cds.items():
        allpos = np.zeros(bench.n_people, np.int32)
        for it in bench.items_on(d):
            allpos[bench.positives(d, it)] += 1
        n_on = c.Y.sum(1)
        pdays.append(pd.DataFrame({"split": bench.cfg.split_of(d), "day": d, "person_idx": c.persons, "n_upvoted": n_on,
                                   "n_upvoted_off_lineup": allpos[c.persons] - n_on, "lineup_size": len(c.items)}))
        r, j = np.nonzero(c.Y)
        labels.append(pd.DataFrame({"day": d, "person_idx": c.persons[r], "item_idx": c.items[j]}))
    return pd.concat(pdays, ignore_index=True), pd.concat(labels, ignore_index=True)


def metrics(S: np.ndarray, Y: np.ndarray, seed: int = 0) -> pd.DataFrame:
    """Per person-day metrics for a score matrix S [P, L] (higher = more likely) and labels Y [P, L]."""
    rng = np.random.default_rng(seed)
    S = np.where(np.isnan(S), -np.inf, S)
    order = np.lexsort((rng.random(S.shape), -S), axis=1)          # best first, random tie-break
    Yo = np.take_along_axis(Y, order, axis=1)
    top3 = Yo[:, :3].any(1).astype(float)
    rr = 1.0 / (np.argmax(Yo, axis=1) + 1.0)
    Sf = np.where(np.isfinite(S), S, np.nanmin(np.where(np.isfinite(S), S, np.nan)) - 1.0 if np.isfinite(S).any() else 0.0)
    r = rankdata(Sf, axis=1)                                        # average ranks: ties count half
    n1 = Y.sum(1).astype(float)
    n0 = Y.shape[1] - n1
    with np.errstate(divide="ignore", invalid="ignore"):
        auc = ((r * Y).sum(1) - n1 * (n1 + 1) / 2.0) / (n1 * n0)
    auc[(n1 == 0) | (n0 == 0)] = np.nan
    return pd.DataFrame({"top3": top3, "mrr": rr, "auc": auc})


def per_personday(scores: dict[str, np.ndarray], cds: dict[str, ChoiceDay]) -> pd.DataFrame:
    """scores: day -> S [P, L]. Returns one row per person-day with day, person_idx, top3, mrr, auc."""
    out = []
    for d, S in scores.items():
        m = metrics(S, cds[d].Y, seed=day_ord(d))
        m.insert(0, "person_idx", cds[d].persons)
        m.insert(0, "day", d)
        out.append(m)
    return pd.concat(out, ignore_index=True)


def summarize(df: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean of each metric over person-days, with a day-clustered bootstrap 95% interval."""
    g = df.groupby("day")
    sums = g[["top3", "mrr", "auc"]].sum().to_numpy()
    cnt = np.column_stack([g["top3"].count(), g["mrr"].count(), g["auc"].count()]).astype(float)
    rng = np.random.default_rng(seed)
    point = sums.sum(0) / cnt.sum(0)
    bs = []
    for _ in range(n_boot):
        k = rng.integers(0, len(sums), len(sums))
        bs.append(sums[k].sum(0) / cnt[k].sum(0))
    lo, hi = np.percentile(np.array(bs), [2.5, 97.5], axis=0)
    out = {"person_days": int(len(df)), "days": int(len(sums))}
    for i, k in enumerate(("top3", "mrr", "auc")):
        out[k] = {"value": round(float(point[i]), 4), "ci95": [round(float(lo[i]), 4), round(float(hi[i]), 4)]}
    return out


def paired(dfa: pd.DataFrame, dfb: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """a - b on the same person-days, day-clustered bootstrap."""
    m = dfa.merge(dfb, on=["day", "person_idx"], suffixes=("_a", "_b"))
    out = {"person_days": int(len(m))}
    rng = np.random.default_rng(seed)
    days = m["day"].to_numpy()
    names, inv = np.unique(days, return_inverse=True)
    picks = [rng.integers(0, len(names), len(names)) for _ in range(n_boot)]
    for k in ("top3", "mrr", "auc"):
        a, b = m[k + "_a"].to_numpy(), m[k + "_b"].to_numpy()
        ok = ~(np.isnan(a) | np.isnan(b))
        sa = np.bincount(inv[ok], weights=a[ok], minlength=len(names))
        sb = np.bincount(inv[ok], weights=b[ok], minlength=len(names))
        c = np.bincount(inv[ok], minlength=len(names)).astype(float)
        point = (sa.sum() - sb.sum()) / c.sum()
        bs = [(sa[p].sum() - sb[p].sum()) / max(c[p].sum(), 1.0) for p in picks]
        lo, hi = np.percentile(bs, [2.5, 97.5])
        out[k] = {"diff": round(float(point), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)]}
    return out


def upvotes_per_active_day(bench, day: str) -> np.ndarray:
    """Per person: mean endorsements per active day, over days before `day` (0 when there is no history)."""
    o = day_ord(day)
    hi = np.searchsorted(bench._e_day, o)
    p, d = bench._e_p[:hi].astype(np.int64), bench._e_day[:hi].astype(np.int64)
    total = np.bincount(p, minlength=bench.n_people).astype(float)
    pairs = np.unique(p * 100000 + (d - d.min() if len(d) else 0))
    adays = np.bincount(pairs // 100000, minlength=bench.n_people).astype(float)
    return np.where(adays > 0, total / np.maximum(adays, 1.0), 0.0)
