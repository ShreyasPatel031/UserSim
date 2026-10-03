"""P(divided) router trained on thousands of training-pool pseudo-targets with segment-derived features (no model calls).

Pseudo-target = (subgroup cell, question) from the 4 multi-country shared surveys' training rows, held out exactly like a
real target (question column blanked for the whole target country). Label = held-out answer is divided (normalized
entropy >= 0.84). Features, all computable before answering and identical for real targets:
  segment prediction's entropy and top share, how much the segments disagree on the question (spread of segment
  profiles), entropy of the other-country average on the question, how split the target group is on its neighbour
  questions (mean entropy, mean top share), number of options.
Output: structure_divrouter.pkl {qid: P(divided)} for dev/eval targets where the segment model applies."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_xnat as XN

OUT = M.OUT / "structure_divrouter.pkl"
K, NSEG, SCALE, PRIOR = 19, 8, 0.01, 2.0
N_PSEUDO = 2400


def hn(p):
    p = np.clip(np.asarray(p, float), 1e-12, None)
    p = p / p.sum()
    return float(-(p * np.log(p)).sum() / np.log(len(p))) if len(p) > 1 else 0.0


def features(sv, stem, text, rows_pick, country):
    """rows_pick(rows) -> target row indices. Returns feature vector or None."""
    nb = L.neighbours(sv, text, stem, K)
    X, rows, cols = L.local_matrix(sv, [s for s, _ in nb], (stem,))
    sl = cols[stem]
    same = np.array([c[1] == country for c in rows])
    X[same, sl] = np.nan
    obs = ~np.isnan(X[:, sl.start])
    tgt = rows_pick(rows)
    if obs.sum() < 3 or not tgt:
        return None
    nb_cols = {st: s for st, s in cols.items() if s != sl}
    Xn = np.concatenate([X[:, s] for s in nb_cols.values()], axis=1)
    sub, start = {}, 0
    for st, s in nb_cols.items():
        n = s.stop - s.start
        sub[st] = slice(start, start + n)
        start += n
    counts = np.array([min(max(sv["size"].get(c, 100), 30), 1000) for c in rows], float)
    R, _ = L.dmm(Xn, sub, counts * SCALE, max(1, min(NSEG, X.shape[0])))
    T = X[:, sl]
    g = np.nanmean(T[obs], axis=0)
    W = R[obs]
    prof = (W.T @ T[obs] + PRIOR * g) / (W.sum(0)[:, None] + PRIOR)
    p = (R[tgt] @ prof).mean(0)
    pi = R.mean(0)
    spread = float(np.sqrt((pi[:, None] * (prof - pi @ prof) ** 2).sum()))
    own = [X[i, s] for i in tgt for s in nb_cols.values() if not np.isnan(X[i, s.start])]
    own_h = np.mean([hn(v) for v in own]) if own else hn(g)
    own_top = np.mean([np.max(v) for v in own]) if own else float(np.max(g))
    return [hn(p), float(p.max()), spread, hn(g), own_h, own_top, float(len(g))]


def main():
    sv = L.build_surveys(L.held_rows())
    rng = np.random.default_rng(1)
    Xp, yp = [], []
    for ds in ("Afrobarometer", "ESS", "ISSP", "LatinoBarometro"):
        s = sv[ds]
        cand = [(c, st) for (c, st) in s["obs"] if c[1]]
        for i in rng.choice(len(cand), min(N_PSEUDO // 4, len(cand)), replace=False):
            c, st = cand[i]
            f = features(s, st, st, lambda rows: [j for j, r in enumerate(rows) if r == c], c[1])
            if f is not None:
                Xp.append(f)
                yp.append(hn(s["obs"][(c, st)]) >= 0.84)
        print(ds, "pseudo-targets so far", len(Xp), flush=True)
    Xp, yp = np.array(Xp), np.array(yp, int)
    sc = StandardScaler().fit(Xp)
    clf = LogisticRegression(C=1.0, max_iter=5000).fit(sc.transform(Xp), yp)
    out = {}
    for w in ("dev", "eval"):
        ys, ps = [], []
        for t in L.targets(w):
            s = sv[t["q"]["dataset"]]
            if t["stem"] not in s["keys"]:
                continue
            pick = (lambda rows, t=t: [j for j, r in enumerate(rows) if r[1] == t["country"] and r[2]]) if t["split"] == "Pop" else \
                   (lambda rows, t=t: [j for j, r in enumerate(rows) if r == t["cell"]])
            f = features(s, t["stem"], t["text"], pick, t["country"])
            if f is None:
                continue
            p = float(clf.predict_proba(sc.transform([f]))[0, 1])
            out[t["q"]["qid"]] = p
            ys.append(t["q"]["Hn"] >= 0.84)
            ps.append(p)
        print(f"{w}: segment-feature P(divided) on {len(ps)} targets, AUC {roc_auc_score(ys, ps):.3f}", flush=True)
    print(f"pseudo-targets {len(yp)} (divided {yp.mean():.0%}); coefficients {dict(zip(['seg_H', 'seg_top', 'seg_spread', 'other_H', 'own_H', 'own_top', 'n_opt'], clf.coef_[0].round(2)))}")
    pd.to_pickle(out, OUT)


if __name__ == "__main__":
    main()
