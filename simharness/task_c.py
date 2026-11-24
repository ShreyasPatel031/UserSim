"""Task C (what they say): score simulated comments against the real comment of the same person on the same item.

Rows are (person, item, real comment text), kept only when the comment was written on the item's own day. A model
writes one comment per row from the person's history (before the day) and the item as known at the day's start.

Scoring uses sentence embeddings (default: a small local model, no cloud dependency). Per row:

  sim           cosine(simulated comment, this person's real comment)
  match         sim >= tau. tau is fixed on TRAINING comments so that a real comment taken from a different item
                matches `floor` (5%) of the time: the chance level is known by construction.
  own_vs_other  is the simulated comment closer to this person's real comment than to another person's real comment
                on the same item? 0.5 = no person-specific signal (a prompt that ignores the person scores 0.5).

References scored on the same rows without any model call, so every model number has a floor and a human yardstick:

  floor_other_item   a real comment by someone else on a different item           (floor: matches ~5%)
  own_past_comment   the person's most recent earlier comment                     (people repeat themselves)
  same_item_other    a real comment by someone else on the same item              (what any commenter there says)

Models are compared with the item-only prompt (`PlainComment`): a history-built model has to beat it on the same rows,
paired, with a day-clustered interval.

Leak rules: the history is `HistoryBatch.render` (items of earlier days, written before the day starts); the item is
title / summary / description / topics only; no counts, ranks or other comments of the day reach the prompt.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from simharness.bench import KIND_CODE, _day_bounds_utc, day_ord
from simharness.schema import MAKE

HISTORY_PROMPT = """You write the comment one real Product Hunt member leaves on a launch.

THIS MEMBER'S HISTORY (everything known before today):
{history}

TODAY'S LAUNCH:
Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}

This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and
kind of question or praise, as their past comments show. Plain text, no hashtags, no quotation marks around it.
Reply with JSON only: {{"comment": "<the comment>"}}"""

PLAIN_PROMPT = """You write a comment a Product Hunt member leaves on a launch.

TODAY'S LAUNCH:
Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}

Write one comment a typical member would leave on this launch today. Plain text, no hashtags, no quotation marks
around it.
Reply with JSON only: {{"comment": "<the comment>"}}"""


def _item_fields(item) -> dict:
    return {"title": item.title, "summary": item.summary,
            "description": " ".join((item.description or "").split())[:600] or "(none)",
            "tags": ", ".join(item.tags) or "(none)"}


def parse_comment(text: str) -> str:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return str(json.loads(m.group(0)).get("comment", "")) if m else ""
    except ValueError:
        return ""


# ------------------------------------------------------------------------------------------ embedders
class LocalEmbedder:
    """Sentence embeddings from a local open model (unit-length rows)."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", batch_size: int = 64, max_tokens: int = 256):
        from sentence_transformers import SentenceTransformer
        self._m, self.batch_size, self.name = SentenceTransformer(model), batch_size, model
        self._m.max_seq_length = max_tokens  # comments are short; this bounds the cost of the rare long one
        self._cache: dict[str, np.ndarray] = {}

    def encode(self, texts: list[str]) -> np.ndarray:
        texts = [t or " " for t in texts]
        new = sorted({t for t in texts if t not in self._cache}, key=len)  # the same real comments are scored often
        if new:
            vecs = self._m.encode(new, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False)
            self._cache.update(zip(new, np.asarray(vecs, dtype=np.float32)))
        return np.stack([self._cache[t] for t in texts])


# ------------------------------------------------------------------------------------------ comment models
class CommentModel:
    """Writes one comment per row. Subclasses implement `write(batch, j, item) -> str`."""
    name = "comment-model"
    cost_usd = 0.0

    def write(self, batch, j: int, item) -> str:
        raise NotImplementedError


class PromptComment(CommentModel):
    """History-built comment: the person's rendered history plus the item, through any text backend
    (`simharness.models.llm.Backend`)."""

    def __init__(self, backend, max_items: int = 30, max_comments: int = 10):
        self.backend, self.max_items, self.max_comments = backend, max_items, max_comments
        self.name = f"history-prompt[{backend.name}]"

    @property
    def cost_usd(self) -> float:
        return self.backend.cost_usd

    def write(self, batch, j: int, item) -> str:
        hist = batch.render(j, self.max_items, self.max_comments)
        return parse_comment(self.backend.call(HISTORY_PROMPT.format(history=hist, **_item_fields(item))))


class PlainComment(CommentModel):
    """Item-only prompt: the baseline a history-built model has to beat."""

    def __init__(self, backend):
        self.backend = backend
        self.name = f"plain-prompt[{backend.name}]"

    @property
    def cost_usd(self) -> float:
        return self.backend.cost_usd

    def write(self, batch, j: int, item) -> str:
        return parse_comment(self.backend.call(PLAIN_PROMPT.format(**_item_fields(item))))


# ------------------------------------------------------------------------------------------ the task
class TaskC:
    def __init__(self, bench, embedder=None, floor: float = 0.05, min_chars: int = 15, seed: int = 0,
                 tau_pairs: int = 5000):
        self.bench, self.floor, self.min_chars, self.seed = bench, floor, min_chars, seed
        self._emb, self._tau, self._tau_pairs = embedder, None, tau_pairs
        self._day_of = self._day_of_comments()

    @property
    def emb(self):
        """The embedder, loaded on first use (building rows or exporting needs none)."""
        if self._emb is None:
            self._emb = LocalEmbedder()
        return self._emb

    @property
    def tau(self) -> float:
        """The match threshold, fitted on training comments on first use."""
        if self._tau is None:
            self._tau = self._fit_tau(self._tau_pairs)
        return self._tau

    @tau.setter
    def tau(self, value: float) -> None:
        self._tau = float(value)

    # -- rows
    def _day_of_comments(self) -> pd.DataFrame:
        """Comments written during the item's own day, one per (person, item): the first of that day."""
        b = self.bench
        c = b.comments.merge(b.items[["item_idx", "day"]], on="item_idx")
        bounds = {d: _day_bounds_utc(d, b.cfg.day_tz) for d in c["day"].unique()}
        start = c["day"].map(lambda d: bounds[d][0]); end = c["day"].map(lambda d: bounds[d][1])
        ts = c["ts"].dt.tz_convert("UTC")
        c = c[(ts >= start) & (ts < end) & (c["text"].str.len() >= self.min_chars)]
        c = c.sort_values("ts").drop_duplicates(["person_idx", "item_idx"])
        mk = b.hist[b.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx"]].drop_duplicates()
        mk["is_maker"] = True
        c = c.merge(mk, on=["person_idx", "item_idx"], how="left")
        c["is_maker"] = c["is_maker"].fillna(False).astype(bool)
        c["split"] = c["day"].map(b.cfg.split_of)
        return c.reset_index(drop=True)

    def _fit_tau(self, n_pairs: int) -> float:
        """Similarity that a real comment from a DIFFERENT item reaches only `floor` of the time (training rows)."""
        tr = self._day_of[(self._day_of["split"] == "train") & ~self._day_of["is_maker"]]
        if len(tr) < 100:
            raise ValueError("too few training comments to set the match threshold")
        rng = np.random.default_rng(self.seed)
        a = rng.integers(0, len(tr), n_pairs); b = rng.integers(0, len(tr), n_pairs)
        items = tr["item_idx"].to_numpy(); people = tr["person_idx"].to_numpy()
        ok = (items[a] != items[b]) & (people[a] != people[b])
        a, b = a[ok], b[ok]
        need = np.unique(np.r_[a, b])
        E = dict(zip(need, self.emb.encode(tr["text"].iloc[need].tolist())))
        sims = np.array([float(E[i] @ E[j]) for i, j in zip(a, b)])
        return float(np.quantile(sims, 1.0 - self.floor))

    def rows(self, split: str, include_makers: bool = False, max_rows: int | None = None) -> pd.DataFrame:
        """Rows of one split with the three reference texts attached (NaN where a reference does not exist)."""
        b = self.bench
        r = self._day_of[self._day_of["split"] == split]
        if not include_makers:
            r = r[~r["is_maker"]]
        r = r.reset_index(drop=True)
        rng = np.random.default_rng(self.seed)
        if max_rows and len(r) > max_rows:
            r = r.iloc[np.sort(rng.choice(len(r), max_rows, replace=False))].reset_index(drop=True)
        allc = self._day_of[self._day_of["split"] == split]
        if not include_makers:  # a maker's launch post is not what "another commenter" says
            allc = allc[~allc["is_maker"]]
        by_item = {k: g for k, g in allc.groupby("item_idx")}
        floor_txt, same_txt, past_txt = [], [], []
        for row in r.itertuples():
            other = allc[(allc["item_idx"] != row.item_idx) & (allc["person_idx"] != row.person_idx)]
            floor_txt.append(other["text"].iloc[int(rng.integers(0, len(other)))] if len(other) else None)
            same = by_item[row.item_idx]; same = same[same["person_idx"] != row.person_idx]
            same_txt.append(same["text"].iloc[int(rng.integers(0, len(same)))] if len(same) else None)
            start, _ = _day_bounds_utc(row.day, b.cfg.day_tz)
            past = b.comments[(b.comments["person_idx"] == row.person_idx) & (b.comments["day_ord"] < day_ord(row.day))]
            past = past[past["ts"].isna() | (past["ts"] < start)].sort_values("ts")
            past_txt.append(past["text"].iloc[-1] if len(past) else None)
        r["floor_other_item"], r["same_item_other"], r["own_past_comment"] = floor_txt, same_txt, past_txt
        return r

    # -- generation and scoring
    def generate(self, model: CommentModel, rows: pd.DataFrame, workers: int = 8, cache: dict | None = None) -> list:
        b = self.bench
        cache = cache if cache is not None else {}

        def one(row):
            key = (model.name, int(row.person_idx), int(row.item_idx))
            if key not in cache:
                try:
                    cache[key] = model.write(b.batch(row.day, np.array([row.person_idx])), 0, b.item(row.item_idx))
                except Exception:  # noqa: BLE001 - a failed call is scored as an empty comment, never dropped
                    cache[key] = ""
            return cache[key]

        with ThreadPoolExecutor(workers) as ex:
            return list(ex.map(one, list(rows.itertuples())))

    def score(self, rows: pd.DataFrame, texts: list) -> pd.DataFrame:
        """Per-row scores of `texts` (one per row; None or '' = no comment, scored as a miss)."""
        has = np.array([bool(t) and isinstance(t, str) for t in texts])
        E_real = self.emb.encode(rows["text"].tolist())
        E_sim = self.emb.encode([t if h else " " for t, h in zip(texts, has)])
        sim = np.where(has, np.einsum("ij,ij->i", E_real, E_sim), np.nan)
        other = rows["same_item_other"]
        has_o = other.notna().to_numpy() & has
        E_oth = self.emb.encode([t if isinstance(t, str) else " " for t in other])
        sim_o = np.einsum("ij,ij->i", E_oth, E_sim)
        own = np.where(has_o, (sim > sim_o) + 0.5 * (sim == sim_o), np.nan)
        return pd.DataFrame({"day": rows["day"].to_numpy(), "person_idx": rows["person_idx"].to_numpy(),
                             "item_idx": rows["item_idx"].to_numpy(), "has": has, "sim": sim,
                             "match": np.where(has, sim >= self.tau, False).astype(float), "own_vs_other": own,
                             "len_ratio": [len(t) / max(len(r), 1) if h else np.nan
                                           for t, r, h in zip(texts, rows["text"], has)]})

    def score_reference(self, rows: pd.DataFrame, name: str) -> pd.DataFrame:
        """Score one of the reference columns; rows without that reference are left out (NaN), not counted as misses."""
        s = self.score(rows, [t if isinstance(t, str) else None for t in rows[name]])
        return s[s["has"]].reset_index(drop=True)


# ------------------------------------------------------------------------------------------ summaries
def _agg(df: pd.DataFrame) -> dict:
    return {"match": float(df["match"].mean()), "sim": float(df["sim"].mean()),
            "own_vs_other": float(df["own_vs_other"].mean()), "len_ratio_median": float(df["len_ratio"].median())}


def summarize(df: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """Point values with a day-clustered bootstrap 95% interval."""
    point = _agg(df)
    days = df["day"].unique(); groups = {d: g for d, g in df.groupby("day")}
    rng = np.random.default_rng(seed)
    boots = {k: [] for k in point}
    for _ in range(n_boot):
        a = _agg(pd.concat([groups[d] for d in rng.choice(days, len(days), replace=True)]))
        for k in point:
            boots[k].append(a[k])
    out = {"rows": int(len(df)), "days": int(len(days)), "rows_with_same_item_other": int(df["own_vs_other"].notna().sum())}
    for k, v in point.items():
        lo, hi = np.nanpercentile(boots[k], [2.5, 97.5])
        out[k] = {"value": round(v, 4), "ci95": [round(float(lo), 4), round(float(hi), 4)]}
    return out


def paired_diff(a: pd.DataFrame, b: pd.DataFrame, metric: str = "match", n_boot: int = 2000, seed: int = 0) -> dict:
    """a - b on the same rows, day-clustered bootstrap."""
    m = a.merge(b, on=["day", "person_idx", "item_idx"], suffixes=("_a", "_b"))
    m = m[m[f"{metric}_a"].notna() & m[f"{metric}_b"].notna()]
    d = (m[f"{metric}_a"] - m[f"{metric}_b"]).to_numpy(); day = m["day"].to_numpy()
    days = np.unique(day); idx = {x: np.flatnonzero(day == x) for x in days}
    rng = np.random.default_rng(seed)
    bs = [d[np.concatenate([idx[x] for x in rng.choice(days, len(days), replace=True)])].mean() for _ in range(n_boot)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"metric": metric, "rows": int(len(m)), "diff": round(float(d.mean()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)]}
