"""Taste features and the activity-matched HARD evaluation rows.

Item text embedding: a local sentence-transformers model (default BAAI/bge-small-en-v1.5, CPU) over title + summary.
The description is NOT used: items listed after the store's description cut-off have none, so using it would make
train and test items look different.

Per (person, day D, item) - all from endorsements on items with day < D (bench.state / the same prefix rule):
  emb_cos      cosine between the item and the person's recency-weighted (7-day half-life) mean backed-item embedding
  emb_max30    max cosine to any of the person's last 30 backed items
  emb_mean30   mean cosine to the last 30 backed items
  tm, tm_max   mean / max over the item's topics of the share of the person's past endorsements with that topic
  ln_rw, ln_n7, ln_n30, ln_n60, ln_all   activity
  ln_com, com_rate                        comments written before D, and comments per past endorsement
Makers / hunters are not used: items after the description cut-off carry no maker list either.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import scipy.sparse as sp

from simharness.bench import day_ord

TASTE_NAMES = ("ln_rw", "ln_n7", "ln_n30", "ln_n60", "ln_all", "tm", "tm_max", "ln_rw_x_tm", "emb_cos",
               "emb_max30", "emb_mean30", "ln_com", "com_rate")


def embed_items(bench, model_name: str = "BAAI/bge-small-en-v1.5", batch_size: int = 128) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_name, device="cpu")
    texts = (bench.items["title"].fillna("") + ". " + bench.items["summary"].fillna("")).tolist()
    E = m.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(E, dtype=np.float32)


class TasteFeatures:
    def __init__(self, bench, item_emb: np.ndarray, last_k: int = 30):
        self.b, self.E, self.k = bench, item_emb.astype(np.float32), last_k
        # endorsements sorted by (person, day): each person's slice is in day order
        o = np.lexsort((bench._e_day, bench._e_p))
        self.ep, self.ed, self.ei = bench._e_p[o], bench._e_day[o], bench._e_i[o]
        self.start = np.searchsorted(self.ep, np.arange(bench.n_people))

    @lru_cache(maxsize=4)
    def _day(self, day: str):
        b, o = self.b, day_ord(day)
        st = b.state(day)
        hi = np.searchsorted(b._e_day, o)
        p, i, d = b._e_p[:hi], b._e_i[:hi], b._e_day[:hi]
        W = sp.csr_matrix((0.5 ** ((o - d) / 7.0), (p, i)), shape=(b.n_people, len(b.items)))
        return st, W

    def person_block(self, day: str, persons: np.ndarray):
        st, W = self._day(day)
        P = np.asarray(W[persons] @ self.E)
        P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-9
        cnt = st["n_all"][persons].astype(np.int64)  # endorsements before D = the first cnt of the person's slice
        last = self.start[persons] + cnt - 1
        ar = np.arange(self.k)
        pos = last[:, None] - ar[None, :]
        valid = ar[None, :] < cnt[:, None]
        idx = np.where(valid, self.ei[np.clip(pos, 0, len(self.ei) - 1)], 0)
        return {"P": P, "idx": idx, "valid": valid}

    def features(self, day: str, persons: np.ndarray, item_idx: int, block: dict | None = None) -> np.ndarray:
        b = self.b
        st, _ = self._day(day)
        blk = block or self.person_block(day, persons)
        e = self.E[item_idx]
        sims = self.E @ e
        s30 = np.where(blk["valid"], sims[blk["idx"]], 0.0)
        nv = blk["valid"].sum(1)
        any_ = nv > 0
        emb_max = np.where(any_, np.where(blk["valid"], s30, -1.0).max(axis=1), 0.0)
        emb_mean = np.where(any_, s30.sum(axis=1) / np.maximum(nv, 1), 0.0)
        l = b.item_topics[item_idx].toarray().ravel()
        n_all = st["n_all"][persons]
        T = st["topics"][persons]
        if l.sum() > 0:
            shares = np.asarray(T[:, np.flatnonzero(l)].todense()) / np.maximum(n_all, 1.0)[:, None]
            tm, tm_max = shares.mean(1), shares.max(1)
        else:
            tm = tm_max = np.zeros(len(persons))
        ln_rw = np.log1p(st["rw"][persons])
        com = st["n_comments"][persons]
        cols = {"ln_rw": ln_rw, "ln_n7": np.log1p(st["n7"][persons]), "ln_n30": np.log1p(st["n30"][persons]),
                "ln_n60": np.log1p(st["n60"][persons]), "ln_all": np.log1p(n_all), "tm": tm, "tm_max": tm_max,
                "ln_rw_x_tm": ln_rw * tm, "emb_cos": blk["P"] @ e, "emb_max30": emb_max, "emb_mean30": emb_mean,
                "ln_com": np.log1p(com), "com_rate": com / np.maximum(n_all, 1.0)}
        return np.column_stack([cols[n] for n in TASTE_NAMES]).astype(np.float32)


def _nearest_unused(x: np.ndarray, cand: np.ndarray, targets: np.ndarray, rng, ratio: int) -> np.ndarray:
    """For each target person, the not-yet-used candidate with the nearest x (random tie-break)."""
    if len(cand) == 0:
        return np.zeros(0, np.int64)
    cv = x[cand] + rng.random(len(cand)) * 1e-6
    o = np.argsort(cv)
    cand, cv = cand[o], cv[o]
    used = np.zeros(len(cand), bool)
    out = []
    for p in targets:
        for _ in range(ratio):
            j = int(np.searchsorted(cv, x[p]))
            lo, hi = j - 1, j
            while lo >= 0 and used[lo]:
                lo -= 1
            while hi < len(cand) and used[hi]:
                hi += 1
            if lo < 0 and hi >= len(cand):
                return np.array(out, dtype=np.int64)
            pick = hi if lo < 0 or (hi < len(cand) and abs(cv[hi] - x[p]) <= abs(cv[lo] - x[p])) else lo
            used[pick] = True
            out.append(cand[pick])
    return np.array(out, dtype=np.int64)


def matched_negatives(bench, day: str, item_idx: int, rng: np.random.Generator, ratio: int = 1,
                      key: str = "rw30", positives: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Positives of the item (or the given subset of them) and activity-matched pool negatives: for each positive,
    the not-yet-used pool non-voter with the nearest `key` (default rw30: recency-weighted upvotes in the 30 days
    before D, 7-day half-life). Uses only pre-D features; non-voters of this item may have voted for other items."""
    allpos = bench.positives(day, item_idx)
    pos = allpos if positives is None else positives
    cand = np.setdiff1d(bench.pool(day), allpos)
    neg = _nearest_unused(bench.state(day)[key], cand, rng.permutation(pos), rng, ratio)
    return pos, neg


def build_hard_set(bench, days: list[str], seed: int = 0, ratio: int = 1, max_pos: int | None = None,
                   items: dict | None = None):
    """HARD rows: for every item with positives on `days` (or only items[day] when given), all positives (or a
    random max_pos of them) plus `ratio` activity-matched negatives each. Columns: day, item_idx, person_idx, y."""
    import pandas as pd
    rng = np.random.default_rng(seed)
    rows = []
    for d in days:
        its = items.get(d, []) if items is not None else bench.items_on(d)
        for it in its:
            allpos = bench.positives(d, it)
            if len(allpos) == 0:
                continue
            sub = rng.choice(allpos, max_pos, replace=False) if max_pos and len(allpos) > max_pos else allpos
            pos, neg = matched_negatives(bench, d, it, rng, ratio, positives=sub)
            rows.append(pd.DataFrame({"day": d, "item_idx": int(it), "person_idx": np.r_[pos, neg].astype(np.int64),
                                      "y": np.r_[np.ones(len(pos)), np.zeros(len(neg))].astype(np.int8)}))
    return pd.concat(rows, ignore_index=True)
