"""Sequence signals: does the ORDER of a person's past picks help, beyond the all-history average ("meaning")?
Launches are new every day, so an id-based next-item model (SASRec) has nothing to learn; the sequence is used through
launch embeddings instead, all from picks dated before the day:
  seq_last10   similarity of the launch to the mean of the person's last 10 picks
  seq_decay    similarity to an exponentially recency-weighted history (half-life 10 picks)
  seq_nn       highest similarity to any of the last 50 picks (closest past pick)
  team_recent  times the person backed this team in the last 30 days
Scored like v2_compare (same v1 person-days, store v2 labels, personas + collaborative filtering), with and without follows.
usage: SIMLAB_DATA=data_v2 python -m simlab.seq -> simlab/reports/seq.json"""
import json, os
import numpy as np, pandas as pd
from . import store, choice
from .v2_compare import PERS, BASE, CF, fit

HERE = os.path.dirname(os.path.abspath(__file__))
from .persona import CACHE


def features(D, I, E):
    Z = np.load(f"{store.RAW}/emb.npz"); li = {x: k for k, x in enumerate(Z["launch_ids"])}; EM = Z["launch"]
    EM = EM / (np.linalg.norm(EM, axis=1, keepdims=True) + 1e-9)
    day = dict(zip(I.id, I.day)); team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()}
    Es = E[E.item.isin(day)].sort_values("date")
    hist = Es.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    cols = {c: np.zeros(len(D)) for c in ("seq_last10", "seq_decay", "seq_nn", "team_recent")}
    for g, idx in D.groupby("g").indices.items():
        u, d = g.split("|")
        h = [(dt, it) for dt, it in hist.get(u, []) if dt < d]
        cand = D.id.values[idx]
        cv = np.stack([EM[li[i]] if i in li else np.zeros(EM.shape[1]) for i in cand])
        hv = [li[it] for _, it in h if it in li]
        if hv:
            H = EM[hv[-50:]]
            last = H[-10:].mean(0); w = 0.5 ** (np.arange(len(H))[::-1] / 10); dec = (H * w[:, None]).sum(0) / w.sum()
            cols["seq_last10"][idx] = cv @ last / (np.linalg.norm(last) + 1e-9)
            cols["seq_decay"][idx] = cv @ dec / (np.linalg.norm(dec) + 1e-9)
            cols["seq_nn"][idx] = (cv @ H.T).max(1)
        cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        recent = [it for dt, it in h if dt >= cut]
        cols["team_recent"][idx] = [np.log1p(sum(len(team[x] & team[it]) > 0 for it in recent)) for x in cand]
    for c, v in cols.items():
        D[c] = v; D[c] = D.groupby("g")[c].rank(pct=True)
    return D


def main():
    P, I, E = store.load()
    A = pd.read_parquet(f"{CACHE}/rows_v1.parquet", columns=["g"] + list(PERS))
    keep = set(A.dropna(subset=list(PERS)).g)
    D = pd.read_parquet(f"{CACHE}/rows_v2.parquet"); D = D[D.g.isin(keep)].copy()
    for k in PERS:
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = features(D, I, E)
    SEQ = ["seq_last10", "seq_decay", "seq_nn", "team_recent"]
    tr, te = D[D.day < "2026-10-01"], D[D.day >= "2026-10-01"].copy()
    te = te[te.g.isin(te[te.y == 1].g)]
    res = []
    for fol in (False, True):
        F = ["follow"] if fol else []
        for name, cols in (("baseline (v2)", BASE + list(PERS) + CF), ("+ sequence", BASE + list(PERS) + CF + SEQ)):
            h, a = choice.person_metrics(te, fit(tr, te, cols + F))
            res.append({"follows": fol, "model": name, "top3_hit": round(h, 3), "auc": round(a, 3)}); print(res[-1], flush=True)
    json.dump(res, open(f"{HERE}/reports/seq.json", "w"), indent=1)


if __name__ == "__main__":
    main()
