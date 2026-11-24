"""Tie features: is the person tied to the team behind the item?

Domain-neutral inputs (a domain adapter builds them; see domains/producthunt.build_tie_tables):
  launch_day     day (ordinal) of every launch; the first n_items launches are the benchmark items, in order
  team           (launch, entity): who made or posted each EARLIER launch (every source)
  target_team    (item_idx, entity): the team of the item being predicted, as listed at the start of its day
  made           (person_idx, launch): launches a held person made or posted
  back           (person_idx, launch, event_day, endorse): the person endorsed or commented on the launch;
                 event_day = launch day (endorsements are undated) or the later comment day
  follows_*      undated follow edges person -> entity and entity -> person
  ent_person     entity -> person_idx (or -1 when the team member is not a held person)

DATED features (leak rule: only launches and events with day < D; the target team comes from the day's own list):
  self_team      the person is on the item's team
  back_n / back_rw / back_recent   earlier launches by anyone on the team that the person backed: count,
                 recency-weighted count (90-day half-life), 1 / (1 + days since the last one / 30)
  co_n / co_cos  overlap of the person's earlier endorsements with those of a held team member (max over members):
                 count and cosine
  recip_n        earlier launches the person made that a held team member backed
UNDATED features (snapshot follow edges; a follow made after D can leak, so these are an upper bound):
  fol_p2t        team members the person follows
  fol_t2p        team members who follow the person
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from simharness.bench import day_ord

DATED = ("self_team", "back_any", "back_n", "back_rw", "back_recent", "co_n", "co_cos", "recip_any", "recip_n")
UNDATED = ("fol_p2t_any", "fol_p2t_n", "fol_t2p_any")


def _csr(rows, cols, shape, data=None):
    d = np.ones(len(rows), np.float32) if data is None else data
    m = sp.csr_matrix((d, (rows, cols)), shape=shape)
    m.sum_duplicates()
    return m


class TieData:
    def __init__(self, n_people: int, n_items: int, t: dict):
        self.n_people, self.n_items = n_people, n_items
        self.launch_day = np.asarray(t["launch_day"], dtype=np.int64)
        nl, ne = len(self.launch_day), len(t["ent_person"])
        self.ent_person = np.asarray(t["ent_person"], dtype=np.int64)
        team = t["team"]
        self.ent_launch = _csr(team["entity"].to_numpy(), team["launch"].to_numpy(), (ne, nl))
        self.target = {int(k): g["entity"].to_numpy() for k, g in t["target_team"].groupby("item_idx")}
        # one backing per (person, launch), dated by its earliest event
        ba = t["back"].groupby(["person_idx", "launch"], as_index=False)["event_day"].min()
        b = ba.sort_values("launch")
        self._b_p, self._b_d = b["person_idx"].to_numpy(), b["event_day"].to_numpy().astype(np.int64)
        self._b_ptr = np.searchsorted(b["launch"].to_numpy(), np.arange(nl + 1))
        b = ba.sort_values("person_idx")
        self._pb_l, self._pb_d = b["launch"].to_numpy(), b["event_day"].to_numpy().astype(np.int64)
        self._pb_ptr = np.searchsorted(b["person_idx"].to_numpy(), np.arange(n_people + 1))
        e = t["back"][t["back"]["endorse"]]
        self.endorse = _csr(e["person_idx"].to_numpy(), e["launch"].to_numpy(), (n_people, nl))
        self.endorse.data[:] = 1.0
        self.made = _csr(t["made"]["person_idx"].to_numpy(), t["made"]["launch"].to_numpy(), (n_people, nl))
        self.made.data[:] = 1.0
        fp, fe = t["follows_person_entity"], t["follows_entity_person"]
        self.fol_ep = _csr(fp["entity"].to_numpy(), fp["person_idx"].to_numpy(), (ne, n_people))   # followers of e
        self.fol_e2p = _csr(fe["entity"].to_numpy(), fe["person_idx"].to_numpy(), (ne, n_people))  # e follows p
        self._n_before = {}

    def _n_end_before(self, o: int) -> np.ndarray:
        if o not in self._n_before:
            self._n_before = {o: np.asarray(self.endorse @ (self.launch_day < o).astype(np.float32)).ravel()}
        return self._n_before[o]

    def item_vectors(self, day: str, item_idx: int) -> dict | None:
        """Per-person vectors (length n_people) of every tie feature for one item. None when the team is unknown."""
        E = self.target.get(int(item_idx))
        if E is None or len(E) == 0:
            return None
        o = day_ord(day)
        n = self.n_people
        before = self.launch_day < o
        out = {k: np.zeros(n, np.float32) for k in DATED + UNDATED}
        members = self.ent_person[E]
        members = members[members >= 0]
        out["self_team"][members] = 1.0
        # earlier launches of anyone on the team, and who backed them (event day before D)
        J = np.unique(self.ent_launch[E].indices)
        J = J[(J != item_idx) & before[J]]
        last = np.full(n, -1, np.int64)
        for j in J:
            sl = slice(self._b_ptr[j], self._b_ptr[j + 1])
            ok = self._b_d[sl] < o
            p, d = self._b_p[sl][ok], self._b_d[sl][ok]
            if len(p) == 0:
                continue
            out["back_n"][p] += 1.0
            out["back_rw"][p] += 0.5 ** ((o - self.launch_day[j]) / 90.0)
            last[p] = np.maximum(last[p], d)
        has = last >= 0
        out["back_any"][has] = 1.0
        out["back_recent"][has] = 1.0 / (1.0 + (o - last[has]) / 30.0)
        # co-endorsement with held team members, and reciprocity
        if len(members):
            n_p = self._n_end_before(o)
            bm = np.zeros(len(self.launch_day), np.float32)
            for m in members:
                um = np.zeros(len(self.launch_day), np.float32)
                idx = self.endorse[m].indices
                idx = idx[before[idx]]
                um[idx] = 1.0
                ov = np.asarray(self.endorse @ um).ravel()
                ov[m] = 0.0
                cos = ov / np.sqrt(np.maximum(n_p, 1.0) * max(len(idx), 1))
                out["co_n"] = np.maximum(out["co_n"], ov)
                out["co_cos"] = np.maximum(out["co_cos"], cos.astype(np.float32))
                sl = slice(self._pb_ptr[m], self._pb_ptr[m + 1])
                jb, db = self._pb_l[sl], self._pb_d[sl]
                bm[jb[(db < o) & before[jb]]] += 1.0
            bm[item_idx] = 0.0
            rec = np.asarray(self.made @ bm).ravel()
            rec[members] = 0.0  # backing your own team's launch is not reciprocity
            out["recip_n"] = rec.astype(np.float32)
            out["recip_any"] = (rec > 0).astype(np.float32)
        # undated follows
        f = np.asarray(self.fol_ep[E].sum(axis=0)).ravel()
        out["fol_p2t_n"] = f.astype(np.float32)
        out["fol_p2t_any"] = (f > 0).astype(np.float32)
        out["fol_t2p_any"] = (np.asarray(self.fol_e2p[E].sum(axis=0)).ravel() > 0).astype(np.float32)
        return out

    def features(self, day: str, item_idx: int, persons: np.ndarray, names=DATED + UNDATED) -> np.ndarray:
        v = self.item_vectors(day, item_idx)
        if v is None:
            return np.zeros((len(persons), len(names)), np.float32)
        X = np.column_stack([v[k][persons] for k in names])
        for k in ("back_n", "co_n", "recip_n", "fol_p2t_n"):
            if k in names:
                X[:, names.index(k)] = np.log1p(X[:, names.index(k)])
        return X


def featurize_rows(td: TieData, rows: pd.DataFrame, names=DATED + UNDATED) -> np.ndarray:
    rows = rows.reset_index(drop=True)
    X = np.zeros((len(rows), len(names)), np.float32)
    for (d, it), g in rows.groupby(["day", "item_idx"], sort=True):
        X[g.index.to_numpy()] = td.features(d, int(it), g["person_idx"].to_numpy(), names)
    return X


def save_tables(t: dict, out_dir: str) -> list[str]:
    import json
    import os
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for k in ("team", "target_team", "made", "back", "follows_person_entity", "follows_entity_person"):
        f = f"{out_dir}/{k}.parquet"
        t[k].to_parquet(f)
        files.append(f)
    np.save(f"{out_dir}/launch_day.npy", t["launch_day"])
    np.save(f"{out_dir}/ent_person.npy", t["ent_person"])
    json.dump(t["coverage"], open(f"{out_dir}/coverage.json", "w"), indent=1)
    return files + [f"{out_dir}/launch_day.npy", f"{out_dir}/ent_person.npy", f"{out_dir}/coverage.json"]


def load_tables(out_dir: str) -> dict:
    import json
    t = {k: pd.read_parquet(f"{out_dir}/{k}.parquet")
         for k in ("team", "target_team", "made", "back", "follows_person_entity", "follows_entity_person")}
    t["launch_day"], t["ent_person"] = np.load(f"{out_dir}/launch_day.npy"), np.load(f"{out_dir}/ent_person.npy")
    t["coverage"] = json.load(open(f"{out_dir}/coverage.json"))
    return t
