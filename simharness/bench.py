"""Benchmark v0 builder and loader (docs/SOCIAL_SIM_PLAN.md section 3).

Task V (vote): for each item day D and item L on D, the candidates are the *active pool* of D: people held whole
(`complete`) with at least one endorsement on an item of the `active_days` (60) days before D, and observed after D
(their endorsements were read after D closed, so a missing endorsement is a real negative). Label: the person
endorsed L. History: the person's events on items with day < D only (and, when an event has an exact time, before D
starts). Final scores and ranks are never inputs.

Task C (comment): (person, item, real comment text) for comments by held people on items, with the same history
rule. Only rows whose text was recovered are kept.

Time split (by item day): train <= 2026-10-31, validation 2026-11-01..11-10, test 2026-11-11..11-22.

The full candidate x item matrix is large, so the builder stores the pool per day and the positives per item, and
the loader provides:
  * `training_sample(days, k)`: every positive plus k sampled negatives per item (with weights that undo the
    sampling, so fitted probabilities stay calibrated);
  * `HistoryBatch`: vectorised history features for a batch of people on a day, and text rendering for LLMs;
  * full-pool ranking for evaluation (score.py) on all or a fixed random subset of items.

Files written to the output directory (all private: they carry salted person ids):
  people.parquet   person_idx, person_id, observed_until
  items.parquet    item_idx, item_id, day, day_ord, title, summary, description, tags
  history.parquet  person_idx, item_idx, kind, day_ord, ts (dated events joined to items)
  comments.parquet person_idx, item_idx, day_ord, ts, text (all recovered comment texts; Task C and LLM history)
  pool.parquet     day_ord, person_idx
  positives.parquet day_ord, item_idx, person_idx
  meta.json        config, splits, sizes
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import scipy.sparse as sp

from simharness.schema import COMMENT, ENDORSE, KINDS, DomainTables

EPOCH = dt.date(1970, 1, 1)
KIND_CODE = {k: i for i, k in enumerate(KINDS)}


_HANDLE = re.compile(r"@[A-Za-z0-9_.-]+")


def scrub(text: str) -> str:
    """Remove @handles (usernames) from free text before it reaches a prompt or a log."""
    return _HANDLE.sub("@someone", text or "")


def day_ord(day: str) -> int:
    return (dt.date.fromisoformat(str(day)[:10]) - EPOCH).days


def ord_day(o: int) -> str:
    return (EPOCH + dt.timedelta(days=int(o))).isoformat()


@dataclass
class BenchConfig:
    active_days: int = 60
    train_end: str = "2026-10-31"
    val: tuple = ("2026-11-01", "2026-11-10")
    test: tuple = ("2026-11-11", "2026-11-22")
    first_day: str | None = None           # default: first item day + active_days (full look-back window)
    day_tz: str = "America/Los_Angeles"    # the domain's competition day
    require_observed: bool = True          # drop people not read after D closed
    forward_from: str | None = None        # set when forward-day overlays are loaded: days from here are "forward"

    def split_of(self, day: str) -> str | None:
        if day <= self.train_end:
            return "train"
        if self.val[0] <= day <= self.val[1]:
            return "val"
        if self.test[0] <= day <= self.test[1]:
            return "test"
        if self.forward_from and day >= self.forward_from:
            return "forward"
        return None


def _day_bounds_utc(day: str, tz: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    z = ZoneInfo(tz)
    d = dt.date.fromisoformat(day)
    start = dt.datetime(d.year, d.month, d.day, tzinfo=z)
    end = start + dt.timedelta(days=1)
    return pd.Timestamp(start).tz_convert("UTC"), pd.Timestamp(end).tz_convert("UTC")


def build(tables: DomainTables, out_dir: str, cfg: BenchConfig | None = None) -> dict:
    cfg = cfg or BenchConfig()
    os.makedirs(out_dir, exist_ok=True)
    people = tables.people[tables.people["complete"]].reset_index(drop=True)
    people = people.sort_values("person_id").reset_index(drop=True)
    people["person_idx"] = np.arange(len(people), dtype=np.int32)
    pidx = dict(zip(people["person_id"], people["person_idx"]))

    items = tables.items.sort_values(["day", "item_id"]).reset_index(drop=True).copy()
    items["item_idx"] = np.arange(len(items), dtype=np.int32)
    items["day_ord"] = items["day"].map(day_ord).astype(np.int32)
    iidx = dict(zip(items["item_id"], items["item_idx"]))

    ev = tables.events[tables.events["person_id"].isin(pidx)].copy()
    ev["person_idx"] = ev["person_id"].map(pidx).astype(np.int32)
    ev["item_idx"] = ev["item_id"].map(iidx)
    ev = ev.dropna(subset=["item_idx"])
    ev["item_idx"] = ev["item_idx"].astype(np.int32)
    ev["day_ord"] = ev["day"].map(day_ord).astype(np.int32)
    ev["kind"] = ev["kind"].map(KIND_CODE).astype(np.int8)
    ev["ts"] = pd.to_datetime(ev["ts"], utc=True)
    hist = ev[["person_idx", "item_idx", "kind", "day_ord", "ts"]].sort_values(["day_ord", "person_idx"])
    hist = hist.reset_index(drop=True)
    com = ev[(ev["kind"] == KIND_CODE[COMMENT]) & ev["text"].notna()]
    com = com[["person_idx", "item_idx", "day_ord", "ts", "text"]].reset_index(drop=True)

    # Pool per day and positives per item.
    first = cfg.first_day or ord_day(int(items["day_ord"].min()) + cfg.active_days)
    days = sorted(d for d in items["day"].unique() if d >= first and cfg.split_of(d))
    end = hist[hist["kind"] == KIND_CODE[ENDORSE]]
    e_day, e_p, e_i = end["day_ord"].to_numpy(), end["person_idx"].to_numpy(), end["item_idx"].to_numpy()
    obs = people["observed_until"].to_numpy(dtype="datetime64[ns]")
    item_day = items["day_ord"].to_numpy()
    pools, poss, info = [], [], []
    for d in days:
        o = day_ord(d)
        lo, hi = np.searchsorted(e_day, [o - cfg.active_days, o])
        act = np.unique(e_p[lo:hi])
        _, close = _day_bounds_utc(d, cfg.day_tz)
        if cfg.require_observed:
            seen = obs[act] >= np.datetime64(close.tz_localize(None).to_datetime64())
            act = act[seen]
        pools.append(pd.DataFrame({"day_ord": np.int32(o), "person_idx": act.astype(np.int32)}))
        a, b = np.searchsorted(e_day, [o, o + 1])
        dp, di = e_p[a:b], e_i[a:b]
        m = item_day[di] == o
        dp, di = dp[m], di[m]
        inpool = np.isin(dp, act)
        poss.append(pd.DataFrame({"day_ord": np.int32(o), "item_idx": di[inpool], "person_idx": dp[inpool]}))
        info.append({"day": d, "split": cfg.split_of(d), "pool": int(len(act)),
                     "items": int((item_day == o).sum()), "positives": int(inpool.sum()),
                     "held_backers_outside_pool": int((~inpool).sum())})
    pool = pd.concat(pools, ignore_index=True)
    pos = pd.concat(poss, ignore_index=True)

    people[["person_idx", "person_id", "observed_until"]].to_parquet(f"{out_dir}/people.parquet")
    items[["item_idx", "item_id", "day", "day_ord", "title", "summary", "description", "tags"]].to_parquet(
        f"{out_dir}/items.parquet")
    hist.to_parquet(f"{out_dir}/history.parquet")
    com.to_parquet(f"{out_dir}/comments.parquet")
    pool.to_parquet(f"{out_dir}/pool.parquet")
    pos.to_parquet(f"{out_dir}/positives.parquet")
    di = pd.DataFrame(info)
    sizes = {}
    for s in ("train", "val", "test"):
        g = di[di["split"] == s]
        cd = com.merge(items[["item_idx", "day"]], on="item_idx")
        cd = cd[cd["day"].map(cfg.split_of) == s]
        sizes[s] = {"days": int(len(g)), "items": int(g["items"].sum()), "positives": int(g["positives"].sum()),
                    "pool_mean": round(float(g["pool"].mean()), 1) if len(g) else 0,
                    "pool_people_distinct": int(pool[pool["day_ord"].isin([day_ord(x) for x in g["day"]])]
                                                ["person_idx"].nunique()),
                    "held_backers_outside_pool": int(g["held_backers_outside_pool"].sum()),
                    "taskC_rows": int(len(cd))}
    meta = {"version": "bench_v0", "config": asdict(cfg), "first_day": first, "days": info, "sizes": sizes,
            "n_people_complete": int(len(people)), "n_items": int(len(items)), "n_history_events": int(len(hist)),
            "n_comment_texts": int(len(com)), "domain_notes": tables.notes,
            "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    with open(f"{out_dir}/meta.json", "w") as f:
        json.dump(meta, f, indent=1)
    return meta


# ----------------------------------------------------------------------------------------------- loader
@dataclass
class Item:
    item_idx: int
    item_id: str
    day: str
    title: str
    summary: str
    description: str
    tags: list = field(default_factory=list)


class Benchmark:
    def __init__(self, root: str, overlays: list[str] | None = None):
        """root: the benchmark directory. overlays: forward-day overlay directories to add (see add_overlays)."""
        self.root = root
        self.meta = json.load(open(f"{root}/meta.json"))
        self.cfg = BenchConfig(**{k: tuple(v) if isinstance(v, list) else v for k, v in self.meta["config"].items()})
        self.people = pd.read_parquet(f"{root}/people.parquet")
        self.items = pd.read_parquet(f"{root}/items.parquet")
        self.items["tags"] = self.items["tags"].map(list)
        self.hist = pd.read_parquet(f"{root}/history.parquet")
        self.comments = pd.read_parquet(f"{root}/comments.parquet")
        pool = pd.read_parquet(f"{root}/pool.parquet")
        pos = pd.read_parquet(f"{root}/positives.parquet")
        self._pool = {d: g["person_idx"].to_numpy() for d, g in pool.groupby("day_ord")}
        self._pos = {k: g["person_idx"].to_numpy() for k, g in pos.groupby(["day_ord", "item_idx"])}
        self.n_people = len(self.people)
        self.days_info = pd.DataFrame(self.meta["days"])
        self.overlays: list[dict] = []
        self._index()
        if overlays:
            self.add_overlays(overlays)

    def _index(self) -> None:
        """(Re)build everything derived from items / hist / comments. Called again after overlays are added."""
        type(self).state.cache_clear()
        # topic matrix (items x topics)
        vocab = sorted({t for tl in self.items["tags"] for t in tl})
        self.vocab = {t: i for i, t in enumerate(vocab)}
        r, c = [], []
        for i, tl in enumerate(self.items["tags"]):
            for t in set(tl):
                r.append(i); c.append(self.vocab[t])
        self.item_topics = sp.csr_matrix((np.ones(len(r), np.float32), (r, c)), shape=(len(self.items), len(vocab)))
        end = self.hist[self.hist["kind"] == KIND_CODE[ENDORSE]]
        self._e_day = end["day_ord"].to_numpy()
        self._e_p = end["person_idx"].to_numpy()
        self._e_i = end["item_idx"].to_numpy()
        self._item_day = self.items["day_ord"].to_numpy()
        com = self.hist[self.hist["kind"] == KIND_CODE[COMMENT]]
        self._c_p, self._c_day = com["person_idx"].to_numpy(), com["day_ord"].to_numpy()
        self._c_ts = com["ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        self.topic_names = np.array(sorted(self.vocab, key=self.vocab.get))

    def add_overlays(self, paths: list[str], fill_descriptions: bool = False, new_item_descriptions: bool = True) -> list[dict]:
        """Add forward-day overlays on top of the benchmark tables (nothing existing is changed or removed).

        An overlay directory holds items.parquet (the day's line-up as listed at the start of the day: item_id, day,
        title, summary, description, tags) and comments.parquet (person_idx, item_id, ts, text: comments read from
        a live stream instead of a later profile read). Loading:
          * items whose item_id is new are appended with the next item_idx (days after the test split: split
            "forward"); existing items keep their row, and only get the overlay's description when theirs is empty
            and `fill_descriptions` is set (off by default: it would change the prompts of existing rows);
          * comment rows whose (person, item) pair has no comment yet are appended to `comments` and to the history
            (kind comment), so a later day's history sees them, still only when written before that day starts.
        Task V structures (pool, positives) are untouched: forward days have no vote labels here.
        Returns one summary per overlay."""
        out = []
        for p in sorted(paths, key=lambda x: os.path.basename(os.path.normpath(x))):
            it = pd.read_parquet(f"{p}/items.parquet")
            com = pd.read_parquet(f"{p}/comments.parquet")
            known = dict(zip(self.items["item_id"].astype(str), self.items["item_idx"]))
            it["item_id"] = it["item_id"].astype(str)
            new = it[~it["item_id"].isin(known)].sort_values(["day", "item_id"]).reset_index(drop=True)
            if len(new):
                add = pd.DataFrame({
                    "item_idx": np.arange(len(self.items), len(self.items) + len(new), dtype=np.int32),
                    "item_id": new["item_id"].astype(self.items["item_id"].dtype),
                    "day": new["day"].astype(self.items["day"].dtype),
                    "day_ord": new["day"].map(day_ord).astype(np.int32),
                    "title": new["title"].astype(self.items["title"].dtype),
                    "summary": new["summary"].astype(self.items["summary"].dtype),
                    "description": (new["description"] if new_item_descriptions else "").astype(self.items["description"].dtype)
                    if new_item_descriptions else pd.Series([""] * len(new), dtype=self.items["description"].dtype),
                    "tags": new["tags"].map(list)})
                self.items = pd.concat([self.items, add], ignore_index=True)
                known.update(zip(add["item_id"].astype(str), add["item_idx"]))
            filled = 0
            if fill_descriptions:
                d = dict(zip(it["item_id"], it["description"].fillna("")))
                empty = self.items["description"].fillna("").str.len() == 0
                fill = self.items.loc[empty, "item_id"].astype(str).map(d).fillna("")
                self.items.loc[empty, "description"] = fill.astype(self.items["description"].dtype)
                filled = int((fill.str.len() > 0).sum())
            com = com.assign(item_idx=com["item_id"].astype(str).map(known)).dropna(subset=["item_idx"])
            com["item_idx"] = com["item_idx"].astype(np.int32)
            have = set(zip(self.comments["person_idx"].to_numpy().tolist(), self.comments["item_idx"].to_numpy().tolist()))
            keep = np.array([(int(a), int(b)) not in have for a, b in zip(com["person_idx"], com["item_idx"])], dtype=bool)
            add_c = com[keep].drop_duplicates(["person_idx", "item_idx"])
            item_day = self.items["day_ord"].to_numpy()
            rows = pd.DataFrame({"person_idx": add_c["person_idx"].astype(np.int32).to_numpy(),
                                 "item_idx": add_c["item_idx"].to_numpy(),
                                 "day_ord": item_day[add_c["item_idx"].to_numpy()].astype(np.int32),
                                 "ts": pd.to_datetime(add_c["ts"], utc=True).astype(self.comments["ts"].dtype).to_numpy(),
                                 "text": add_c["text"].astype(self.comments["text"].dtype).to_numpy()})
            rows["ts"] = pd.to_datetime(rows["ts"], utc=True).astype(self.comments["ts"].dtype)
            self.comments = pd.concat([self.comments, rows], ignore_index=True)
            h = rows[["person_idx", "item_idx", "day_ord", "ts"]].assign(kind=np.int8(KIND_CODE[COMMENT]))
            self.hist = pd.concat([self.hist, h[self.hist.columns]], ignore_index=True)
            info = {"overlay": os.path.basename(os.path.normpath(p)), "items_new": int(len(new)),
                    "items_already_in_benchmark": int(len(it) - len(new)), "descriptions_filled": filled,
                    "comment_rows_in_overlay": int(len(com)), "comment_rows_already_in_benchmark": int((~keep).sum()),
                    "comment_rows_added": int(len(rows))}
            self.overlays.append(info)
            out.append(info)
        self.cfg.forward_from = ord_day(day_ord(self.cfg.test[1]) + 1)
        self._index()
        return out

    # -- structure
    def days(self, split: str) -> list[str]:
        return self.days_info.loc[self.days_info["split"] == split, "day"].tolist()

    def item(self, item_idx: int) -> Item:
        r = self.items.iloc[int(item_idx)]
        return Item(int(r.item_idx), str(r.item_id), str(r.day), str(r.title), str(r.summary),
                    str(r.description or ""), list(r.tags))

    def items_on(self, day: str) -> np.ndarray:
        return np.flatnonzero(self._item_day == day_ord(day))

    def pool(self, day: str) -> np.ndarray:
        return self._pool.get(day_ord(day), np.zeros(0, np.int32))

    def positives(self, day: str, item_idx: int) -> np.ndarray:
        return self._pos.get((day_ord(day), int(item_idx)), np.zeros(0, np.int32))

    def batch(self, day: str, person_idx: np.ndarray) -> "HistoryBatch":
        return HistoryBatch(self, day, np.asarray(person_idx, dtype=np.int64))

    # -- day state (vectorised history features, leak-free: item day < D)
    @lru_cache(maxsize=64)
    def state(self, day: str) -> dict:
        o = day_ord(day)
        hi = np.searchsorted(self._e_day, o)  # endorsements on items with day < D
        p, i, d = self._e_p[:hi], self._e_i[:hi], self._e_day[:hi]
        age = (o - d).astype(np.float64)
        rw = np.bincount(p, weights=0.5 ** (age / 7.0), minlength=self.n_people)
        n_all = np.bincount(p, minlength=self.n_people).astype(np.float64)
        n60 = np.bincount(p[age <= self.cfg.active_days], minlength=self.n_people).astype(np.float64)
        n30 = np.bincount(p[age <= 30], minlength=self.n_people).astype(np.float64)
        n7 = np.bincount(p[age <= 7], minlength=self.n_people).astype(np.float64)
        rw30 = np.bincount(p[age <= 30], weights=0.5 ** (age[age <= 30] / 7.0), minlength=self.n_people)
        ind = sp.csr_matrix((np.ones(len(p), np.float32), (p, i)), shape=(self.n_people, len(self.items)))
        topics = (ind @ self.item_topics).tocsr()  # person x topic counts over past endorsed items
        # comments on items before D, written before D starts (when the time is known)
        start, _ = _day_bounds_utc(day, self.cfg.day_tz)
        c = self._c_p[(self._c_day < o) & (np.isnat(self._c_ts) | (self._c_ts < np.datetime64(start.tz_localize(None))))]
        n_comments = np.bincount(c, minlength=self.n_people).astype(np.float64)
        return {"rw": rw, "n_all": n_all, "n60": n60, "n30": n30, "n7": n7, "rw30": rw30, "topics": topics,
                "n_comments": n_comments}

    # -- training sample for walk-forward models
    def training_sample(self, days: list[str], k: int = 20, seed: int = 0) -> pd.DataFrame:
        """All positives + k uniformly sampled pool negatives per item; `w` undoes the negative sampling."""
        rng = np.random.default_rng(seed)
        out = []
        for d in days:
            pool = self.pool(d)
            if len(pool) == 0:
                continue
            for it in self.items_on(d):
                pos = self.positives(d, it)
                neg_pool = np.setdiff1d(pool, pos, assume_unique=False)
                kk = min(k, len(neg_pool))
                neg = rng.choice(neg_pool, kk, replace=False) if kk else np.zeros(0, np.int64)
                w_neg = len(neg_pool) / kk if kk else 0.0
                out.append(pd.DataFrame({"day": d, "item_idx": it,
                                         "person_idx": np.concatenate([pos, neg]).astype(np.int64),
                                         "y": np.r_[np.ones(len(pos)), np.zeros(len(neg))].astype(np.int8),
                                         "w": np.r_[np.ones(len(pos)), np.full(len(neg), w_neg)]}))
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame(
            columns=["day", "item_idx", "person_idx", "y", "w"])

    def taskc_rows(self, split: str) -> pd.DataFrame:
        c = self.comments.merge(self.items[["item_idx", "day"]], on="item_idx")
        return c[c["day"].map(self.cfg.split_of) == split].reset_index(drop=True)


class HistoryBatch:
    """A batch of people's histories as of the start of `day` (leak-free)."""

    def __init__(self, bench: Benchmark, day: str, person_idx: np.ndarray):
        self.bench, self.day, self.person_idx = bench, day, person_idx

    def __len__(self):
        return len(self.person_idx)

    @property
    def state(self) -> dict:
        return self.bench.state(self.day)

    def feature(self, name: str) -> np.ndarray:
        return self.state[name][self.person_idx]

    def topic_match(self, item: Item) -> np.ndarray:
        """Mean, over the item's topics, of the share of the person's past endorsements carrying that topic."""
        st = self.state
        l = self.bench.item_topics[item.item_idx].toarray().ravel()
        nl = max(l.sum(), 1.0)
        num = st["topics"][self.person_idx] @ l
        return np.asarray(num).ravel() / (np.maximum(st["n_all"][self.person_idx], 1.0) * nl)

    def events(self, j: int) -> pd.DataFrame:
        b = self.bench
        o = day_ord(self.day)
        start, _ = _day_bounds_utc(self.day, b.cfg.day_tz)
        h = b.hist[(b.hist["person_idx"] == self.person_idx[j]) & (b.hist["day_ord"] < o)]
        h = h[h["ts"].isna() | (h["ts"] < start)]
        return h

    def render(self, j: int, max_items: int = 30, max_comments: int = 5) -> str:
        """Text history for prompt-based models: last endorsed items and recent comments, before the day."""
        b = self.bench
        o = day_ord(self.day)
        start, _ = _day_bounds_utc(self.day, b.cfg.day_tz)
        pid = self.person_idx[j]
        st = self.state
        h = self.events(j)
        e = h[h["kind"] == KIND_CODE[ENDORSE]].sort_values("day_ord", ascending=False).head(max_items)
        tr = st["topics"][pid].toarray().ravel()
        top = [str(b.topic_names[k]) for k in np.argsort(-tr)[:5] if tr[k] > 0]
        lines = [f"Activity before this day: upvoted {int(st['n7'][pid])} launches in the last 7 days, "
                 f"{int(st['n30'][pid])} in the last 30 days, {int(st['n60'][pid])} in the last 60 days, "
                 f"{int(st['n_all'][pid])} dated upvotes in all; {int(st['n_comments'][pid])} launch comments written.",
                 f"Most-upvoted topics: {', '.join(top) or '(none)'}."]
        if len(e):
            lines.append(f"Most recent upvoted launches (newest first, up to {max_items}):")
            for r in e.itertuples():
                it = b.items.iloc[int(r.item_idx)]
                lines.append(f"- {it.day}: {scrub(it.title)} | {scrub(it.summary)} | topics: {', '.join(it.tags[:5])}")
        c = b.comments[(b.comments["person_idx"] == pid) & (b.comments["day_ord"] < o)]
        c = c[c["ts"].isna() | (c["ts"] < start)].sort_values("day_ord", ascending=False).head(max_comments)
        if len(c):
            lines.append("Recent comments they wrote:")
            for r in c.itertuples():
                it = b.items.iloc[int(r.item_idx)]
                txt = scrub(" ".join(str(r.text).split()))[:240]
                lines.append(f'- on {scrub(it.title)}: "{txt}"')
        return "\n".join(lines)
