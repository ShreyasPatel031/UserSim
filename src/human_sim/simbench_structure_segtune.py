"""Tune the cross-national opinion-segment tool on pseudo-targets from the training pool (no eval/dev data, no model calls).

Pseudo-target = a (subgroup cell, question) pair from the 4 multi-country shared surveys' training rows with a spread
answer (top answer < 70%). It is held out exactly like a real target: the question's column is blanked for every cell
of the target's country (so the target cell's own answer is gone too), memberships come from the cells' answers on the
K text-nearest other questions. Score = total variation distance to the held-out answer (lower is better).
Grid: K neighbours x k segments x membership softness (count scale) x shrinkage prior x output temperature.
Output: structure_segtune.json (ranked configs)."""

from __future__ import annotations

import itertools
import json

import numpy as np

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

KS = (10, 19, 30)
NSEG = (5, 8, 12)
SCALES = (0.003, 0.01, 0.03)
PRIORS = (0.5, 2.0, 5.0)
TEMPS = (0.8, 1.0, 1.25)
N_TARGETS = 600


def seg_profiles(X, cols, counts, k, tgt_sl, scale, seed=0):
    nb_cols = {st: sl for st, sl in cols.items() if sl != tgt_sl}
    Xn = np.concatenate([X[:, sl] for sl in nb_cols.values()], axis=1)
    sub, start = {}, 0
    for st, sl in nb_cols.items():
        n = sl.stop - sl.start
        sub[st] = slice(start, start + n)
        start += n
    R, _ = L.dmm(Xn, sub, counts * scale, max(1, min(k, X.shape[0])), seed=seed)
    return R


def predict_from_R(R, T, obs, row, prior, temp):
    g = np.nanmean(T[obs], axis=0)
    W = R[obs]
    prof = (W.T @ T[obs] + prior * g) / (W.sum(0)[:, None] + prior)
    p = np.clip(R[row] @ prof, 1e-9, None)
    p = p ** temp
    return p / p.sum()


def pseudo_targets(sv, rng):
    out = []
    for ds in ("Afrobarometer", "ESS", "ISSP", "LatinoBarometro"):
        s = sv[ds]
        cand = [(c, st) for (c, st), v in s["obs"].items() if c[1] and v.max() < 0.7]
        idx = rng.choice(len(cand), min(N_TARGETS // 4, len(cand)), replace=False)
        out += [(ds, *cand[i]) for i in idx]
    return out


def main():
    sv = L.build_surveys(L.held_rows())
    rng = np.random.default_rng(0)
    tg = pseudo_targets(sv, rng)
    cfgs = list(itertools.product(KS, NSEG, SCALES, PRIORS, TEMPS))
    err = {c: [] for c in cfgs}
    base = {"other-country mean": []}
    n_ok = 0
    for i, (ds, cell, st) in enumerate(tg):
        s = sv[ds]
        truth = s["obs"][(cell, st)]
        for K in KS:
            nb = L.neighbours(s, st, st, K)
            X, rows, cols = L.local_matrix(s, [x for x, _ in nb], (st,))
            sl = cols[st]
            same = np.array([c[1] == cell[1] for c in rows])
            X[same, sl] = np.nan
            obs = ~np.isnan(X[:, sl.start])
            if obs.sum() < 3 or cell not in rows:
                break
            row = rows.index(cell)
            counts = np.array([min(max(s["size"].get(c, 100), 30), 1000) for c in rows], float)
            T = X[:, sl]
            if K == KS[0]:
                base["other-country mean"].append(0.5 * np.abs(np.nanmean(T[obs], 0) - truth).sum())
                n_ok += 1
            for k, sc in itertools.product(NSEG, SCALES):
                R = seg_profiles(X, cols, counts, k, sl, sc)
                for pr, tp in itertools.product(PRIORS, TEMPS):
                    err[(K, k, sc, pr, tp)].append(0.5 * np.abs(predict_from_R(R, T, obs, row, pr, tp) - truth).sum())
        if i % 50 == 0:
            print(f"{i}/{len(tg)} usable {n_ok}", flush=True)
    full = [c for c in cfgs if len(err[c]) == n_ok]
    ranked = sorted(full, key=lambda c: np.mean(err[c]))
    print(f"\nusable pseudo-targets: {n_ok}; baseline other-country mean TVD {np.mean(base['other-country mean']):.4f}")
    for c in ranked[:12]:
        print(f"K {c[0]:2d} k {c[1]:2d} scale {c[2]:.3f} prior {c[3]:.1f} temp {c[4]:.2f}: TVD {np.mean(err[c]):.4f}")
    cur = (19, 8, 0.01, 2.0, 1.0)
    print("current config", cur, f"TVD {np.mean(err[cur]):.4f}")
    (M.OUT / "structure_segtune.json").write_text(json.dumps({"n": n_ok, "baseline_mean_tvd": float(np.mean(base["other-country mean"])),
                                                            "ranked": [[list(c), float(np.mean(err[c]))] for c in ranked]}, indent=1))


if __name__ == "__main__":
    main()
