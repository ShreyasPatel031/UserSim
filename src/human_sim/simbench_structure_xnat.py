"""Cross-national factor completion (no model calls): factor analysis / PCA as low-rank matrix completion.

Matrix = subgroup cells x per-option answer shares on the target question plus its K text-nearest neighbour questions,
from the benchmark's training rows of the same survey (eval/dev rows never enter). For the TARGET question column,
every cell from the target's own country is blanked, so no respondent of the population being predicted contributes
an answer to the target question (the target cell itself is an eval/dev row, so it is never there to begin with).
The tool estimates the target question's loadings from other countries' groups and the target group's factor scores
from its own answers on the neighbour questions; the completed entry is the prediction.
Grouped targets: the target cell's completed row. Pop targets: size-weighted mean of the country's attribute cells.
Output: structure_xnat_preds.pkl {(tool, K, r): {qid: prediction or None}} + coverage/diagnostics."""

from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

OUT = M.OUT / "structure_xnat_preds.pkl"
CFGS = [("fa", 10, 2), ("fa", 10, 3), ("pca", 10, 2), ("pca", 10, 3), ("ppca", 10, 3), ("fa", 5, 2), ("mean", 0, 0)]


def complete(sv, t, tool, K, r):
    st = t["stem"]
    if st not in sv["keys"]:
        return None, "question not in training pool"
    country = t["country"]
    nb = L.neighbours(sv, t["text"], st, K) if K else []
    X, rows, cols = L.local_matrix(sv, [s for s, _ in nb], (st,))
    sl = cols[st]
    same = np.array([c[1] == country for c in rows])
    X[same, sl] = np.nan  # no answers to the target question from the target's own country
    other_obs = (~np.isnan(X[:, sl.start])).sum()
    if other_obs < 3:
        return None, "fewer than 3 other-country groups answered the question"
    if t["split"] == "Pop":
        tgt = [i for i, c in enumerate(rows) if c[1] == country and c[2]]
    else:
        tgt = [i for i, c in enumerate(rows) if c == t["cell"]]
    if not tgt:
        return None, "target group has no answers on neighbour questions"
    if tool == "mean":
        # baseline: same attribute cell in other countries (Grouped) / all other-country cells (Pop), no factors
        attrs = rows[tgt[0]][2] if t["split"] != "Pop" else None
        pick = [i for i, c in enumerate(rows) if not same[i] and not np.isnan(X[i, sl.start]) and (attrs is None or c[2] == attrs)]
        if not pick:
            pick = [i for i in range(len(rows)) if not same[i] and not np.isnan(X[i, sl.start])]
        fitted = np.full_like(X, np.nan)
        fitted[tgt] = np.nanmean(X[pick], axis=0)
    else:
        fitted = L.fit_dr(X, tool, r)[0]
    keys = sv["keys"][st]
    order = [keys.index(k) for k in t["q"]["keys"]] if set(keys) == set(t["q"]["keys"]) else None
    if order is None:
        return None, "option keys differ"
    if t["split"] == "Pop":
        by_attr = defaultdict(list)
        for i in tgt:
            v = np.clip(fitted[i, sl], 0, None)
            if v.sum() > 0:
                by_attr[rows[i][2][0][0]].append((sv["size"].get(rows[i], 1.0) or 1.0, v / v.sum()))
        if not by_attr:
            return None, "no usable cells"
        p = np.mean([sum(w * v for w, v in a) / sum(w for w, _ in a) for a in by_attr.values()], axis=0)
    else:
        p = np.clip(fitted[tgt[0], sl], 0, None)
        if p.sum() <= 0:
            return None, "degenerate"
    p = p[order]
    return p / p.sum(), "ok"


def main():
    sv = L.build_surveys(L.held_rows())
    sets = {w: L.targets(w) for w in ("dev", "eval")}
    out = {"why": {}}
    for cfg in CFGS:
        res = {}
        for w in sets:
            for t in sets[w]:
                p, why = complete(sv[t["q"]["dataset"]], t, *cfg)
                res[t["q"]["qid"]] = p
                if cfg == CFGS[0]:
                    out["why"][t["q"]["qid"]] = why
        out[cfg] = res
        ev = [t for t in sets["eval"] if res[t["q"]["qid"]] is not None]
        dv = [t for t in sets["dev"] if res[t["q"]["qid"]] is not None]
        sharp = lambda t: t["q"]["h"].max() >= 0.7  # noqa: E731  (diagnostic split only)
        s = lambda ts: np.mean([L.S(t["q"], res[t["q"]["qid"]]) for t in ts]) if ts else float("nan")  # noqa: E731
        print(f"{str(cfg):18s} coverage dev {len(dv)}/{len(sets['dev'])} eval {len(ev)}/{len(sets['eval'])}; "
              f"dev S {s(dv):.1f} (sharp {s([t for t in dv if sharp(t)]):.1f}); eval S {s(ev):.1f} (sharp {s([t for t in ev if sharp(t)]):.1f})", flush=True)
    pd.to_pickle(out, OUT)
    print(pd.Series(out["why"]).value_counts())


if __name__ == "__main__":
    main()
