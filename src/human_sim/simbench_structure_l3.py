"""Layer 3: statistical tools on aggregate cells (no model calls).

Rule actually used (deviation from the spec, which leaves 0 training questions for subgroup cells): row-level holdout.
The target question never enters any fit for any cell; eval and dev rows never enter any matrix; other questions'
spare rows do. Units = single-attribute subgroup cells of the 5 shared surveys; variables = per-option answer shares.

New-question setting (the only one that counts as a method): the target's column is absent. A cell's prediction for
the target = the tool's fitted values for that cell on the neighbour questions with the target's option count,
weighted by text similarity (loading of the target estimated as the similarity-weighted average of its neighbours').
Seen-question setting (diagnostic ceiling): other cells' answers to the target question are in the matrix."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.decomposition import FactorAnalysis
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.mixture import GaussianMixture

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_divided_anatomy import parse_options

DR_TOOLS = ("pca", "ppca", "fa", "nmf")
CL_TOOLS = ("kmeans", "gmm", "hier", "dmm")
KS = (5, 10, 19)
RANKS = (1, 2, 3, 4, 6, 8)
EPS = 1e-9


def norm_label(t):
    return re.sub(r"[^a-z0-9]", "", str(t).lower())


# ------------------------------------------------------------------ data


def held_rows():
    ev, _, _ = A.build_env(25, 100, 7, "eval")
    dv, _, _ = A.build_env(25, 100, 7, "dev")
    return {(r.dataset_name, A._filled_persona(r), r.input_template) for _, r in pd.concat([ev, dv]).iterrows()}


def build_surveys(held, split="Grouped"):
    g = A.load_split(split)
    out = {}
    for ds in A.D_DATASETS:
        d = g[g.dataset_name == ds]
        keys, obs, size, label, labels = {}, defaultdict(list), defaultdict(list), {}, {}
        for _, r in d.iterrows():
            if (ds, A._filled_persona(r), r.input_template) in held:
                continue
            st = A._stem(r.input_template)
            k = list(r.human_answer)
            if st not in keys:
                texts = parse_options(r.input_template)
                labels[st] = [norm_label(texts.get(x, "")) for x in k]
            keys.setdefault(st, k)
            if set(k) != set(keys[st]):
                continue
            cell = A._cell_key(r)
            v = np.array([r.human_answer[x] for x in keys[st]], float)
            if not np.all(np.isfinite(v)) or v.sum() <= 0:
                continue
            obs[(cell, st)].append(v / v.sum())
            size[cell].append(float(r.get("group_size", 0) or 0))
            label[cell] = ", ".join([cell[1]] + [f"{a}={b}" for a, b in cell[2]]) or ds
        cells = sorted({c for c, _ in obs})
        stems = sorted(keys)
        vec = TfidfVectorizer(stop_words="english").fit(stems)
        out[ds] = {"cells": cells, "cidx": {c: i for i, c in enumerate(cells)}, "stems": stems, "keys": keys,
                   "obs": {k: np.mean(v, axis=0) for k, v in obs.items()},
                   "size": {c: float(np.median(v)) if v else 0.0 for c, v in size.items()}, "label": label, "labels": labels,
                   "vec": vec, "S_mat": vec.transform(stems)}
    return out


def neighbours(sv, text, own_stem, K):
    sims = (sv["S_mat"] @ sv["vec"].transform([text]).T).toarray().ravel()
    order = [i for i in np.argsort(-sims) if sv["stems"][i] != own_stem]
    return [(sv["stems"][i], float(sims[i])) for i in order[:K]]


def local_matrix(sv, nbr_stems, extra_cols=()):
    """Cells x per-option columns of the given stems; NaN where the cell did not answer."""
    stems = list(nbr_stems) + list(extra_cols)
    cols, start = {}, 0
    for st in stems:
        n = len(sv["keys"][st])
        cols[st] = slice(start, start + n)
        start += n
    rows = [c for c in sv["cells"] if any((c, st) in sv["obs"] for st in stems)]
    X = np.full((len(rows), start), np.nan)
    for i, c in enumerate(rows):
        for st in stems:
            v = sv["obs"].get((c, st))
            if v is not None:
                X[i, cols[st]] = v
    return X, rows, cols


# ------------------------------------------------------------------ tools


def iter_svd(X, r, shrink=False, iters=30):
    mask = ~np.isnan(X)
    mu = np.nanmean(X, axis=0)
    mu = np.where(np.isnan(mu), 0, mu)
    Z = np.where(mask, X, mu)
    r = max(1, min(r, min(Z.shape) - 1)) if min(Z.shape) > 1 else 1
    for _ in range(iters):
        m = Z.mean(0)
        try:
            U, s, Vt = np.linalg.svd(Z - m, full_matrices=False)
        except np.linalg.LinAlgError:
            U, s, Vt = np.linalg.svd(Z - m + 1e-9 * np.random.default_rng(0).standard_normal(Z.shape), full_matrices=False)
        sr = s[:r].copy()
        if shrink:
            resid = (((Z - m) - (U[:, :r] * sr) @ Vt[:r])[mask] ** 2).mean() if mask.any() else 0.0
            sigma2 = resid * Z.shape[0]
            sr = np.sqrt(np.clip(sr ** 2 - sigma2, 0, None))
        R = m + (U[:, :r] * sr) @ Vt[:r]
        Z = np.where(mask, X, R)
    return R, Vt[:r], U[:, :r] * s[:r]


def masked_nmf(X, r, iters=200, seed=0):
    mask = (~np.isnan(X)).astype(float)
    V = np.nan_to_num(X)
    rng = np.random.default_rng(seed)
    W = rng.random((X.shape[0], r)) + 0.1
    H = rng.random((r, X.shape[1])) + 0.1
    for _ in range(iters):
        WH = W @ H
        H *= (W.T @ (mask * V)) / (W.T @ (mask * WH) + EPS)
        WH = W @ H
        W *= ((mask * V) @ H.T) / ((mask * WH) @ H.T + EPS)
    return W @ H, H, W


def fit_dr(X, tool, r):
    if tool == "pca":
        return iter_svd(X, r)
    if tool == "ppca":
        return iter_svd(X, r, shrink=True)
    if tool == "nmf":
        return masked_nmf(X, r)
    Ximp, _, _ = iter_svd(X, r)
    Ximp = np.where(np.isnan(X), Ximp, X)
    rr = max(1, min(r, Ximp.shape[1] - 1, Ximp.shape[0] - 1))
    fa = FactorAnalysis(n_components=rr, rotation="varimax" if rr > 1 else None, random_state=0).fit(Ximp)
    Zs = fa.transform(Ximp)
    return fa.mean_ + Zs @ fa.components_, fa.components_, Zs


def dmm(X, cols, counts, k, iters=60, seed=0):
    """Dirichlet-multinomial style mixture over answer distributions (missing questions ignored): EM on multinomials."""
    rng = np.random.default_rng(seed)
    n = X.shape[0]
    R = rng.dirichlet(np.ones(k), n)
    for _ in range(iters):
        pi = R.mean(0) + EPS
        theta = {}
        for st, sl in cols.items():
            Xs = np.nan_to_num(X[:, sl]) * counts[:, None]
            th = R.T @ Xs + 0.5
            theta[st] = th / th.sum(1, keepdims=True)
        ll = np.tile(np.log(pi), (n, 1))
        for st, sl in cols.items():
            obs = ~np.isnan(X[:, sl.start])
            Xs = np.nan_to_num(X[:, sl]) * counts[:, None]
            ll[obs] += Xs[obs] @ np.log(theta[st]).T
        ll -= ll.max(1, keepdims=True)
        R = np.exp(ll)
        R /= R.sum(1, keepdims=True)
    prof = np.concatenate([theta[st] for st in cols], axis=1)
    return R, prof


def fit_cl(X, cols, counts, tool, k):
    k = max(1, min(k, X.shape[0]))
    if tool == "dmm":
        R, prof = dmm(X, cols, counts, k)
        return R @ prof, R, prof
    mu = np.nanmean(X, axis=0)
    Z = np.where(np.isnan(X), np.where(np.isnan(mu), 0, mu), X)
    if tool == "kmeans":
        lab = KMeans(n_clusters=k, n_init=5, random_state=0).fit_predict(Z)
        R = np.eye(k)[lab]
    elif tool == "hier":
        lab = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(Z) if k > 1 else np.zeros(len(Z), int)
        R = np.eye(k)[lab]
    else:
        gm = GaussianMixture(n_components=k, covariance_type="diag", random_state=0, reg_covar=1e-4).fit(Z)
        R = gm.predict_proba(Z)
    obs = ~np.isnan(X)
    prof = np.vstack([(np.nan_to_num(X) * R[:, [j]]).sum(0) / ((obs * R[:, [j]]).sum(0) + EPS) for j in range(R.shape[1])])
    empty = np.vstack([(obs * R[:, [j]]).sum(0) < EPS for j in range(R.shape[1])])
    prof = np.where(empty, np.where(np.isnan(mu), 0, mu), prof)
    return R @ prof, R, prof


# ------------------------------------------------------------------ prediction


def aligned_mix(rowvals, cols, nbrs, n_opt, tgt_labels=None, nb_labels=None, info=None):
    """Similarity-weighted average of a row's values on neighbour questions mapped onto the target's options.

    First choice: neighbours whose option labels contain every target label (columns reordered by label). Only if no
    neighbour matches by label: neighbours with the same option count, matched by position."""
    for tier in ("label", "position"):
        if tier == "label" and not (tgt_labels and nb_labels and all(tgt_labels)):
            continue
        num, den = np.zeros(n_opt), 0.0
        for st, sim in nbrs:
            sl = cols.get(st)
            if sl is None:
                continue
            v = rowvals[sl]
            if tier == "label":
                lab = nb_labels.get(st, [])
                if not all(x in lab for x in tgt_labels):
                    continue
                v = v[[lab.index(x) for x in tgt_labels]]
            elif (sl.stop - sl.start) != n_opt:
                continue
            if np.any(np.isnan(v)):
                continue
            w = max(sim, 0.01)
            num += w * np.clip(v, 0, None)
            den += w
        if den > 0 and num.sum() > 0:
            if info is not None:
                info["tier"] = tier
            return num / num.sum()
    return None


class Fitter:
    """Caches one fit per (survey, target text, K, tool, rank) and serves cell rows."""

    def __init__(self, surveys):
        self.sv, self.cache = surveys, {}

    def get(self, ds, text, own_stem, K, tool, r, seen=False):
        key = (ds, text, own_stem, K, tool, r, seen)
        if key in self.cache:
            return self.cache[key]
        sv = self.sv[ds]
        nb = neighbours(sv, text, own_stem, K)
        extra = (own_stem,) if (seen and own_stem in sv["keys"]) else ()
        X, rows, cols = local_matrix(sv, [s for s, _ in nb], extra)
        assert own_stem not in [s for s, _ in nb], "target question among neighbours"
        if not seen:
            assert own_stem not in cols, "target question column in a new-question fit"
        if len(rows) < 3:
            self.cache[key] = None
            return None
        counts = np.array([min(max(sv["size"].get(c, 100), 30), 1000) for c in rows])
        if tool == "raw":
            fitted = X
            extra_out = None
        elif tool in DR_TOOLS:
            fitted, comp, scores = fit_dr(X, tool, r)
            extra_out = (comp, scores)
        else:
            fitted, Rm, prof = fit_cl(X, cols, counts, tool, r)
            extra_out = (Rm, prof)
        res = {"nb": nb, "rows": rows, "ridx": {c: i for i, c in enumerate(rows)}, "cols": cols, "X": X, "fit": fitted,
               "extra": extra_out, "counts": counts}
        self.cache[key] = res
        return res

    def predict_cell(self, ds, text, own_stem, cell, n_opt, K, tool, r, seen=False, labels=None):
        f = self.get(ds, text, own_stem, K, tool, r, seen)
        if f is None or cell not in f["ridx"]:
            return None
        row = f["fit"][f["ridx"][cell]]
        if seen:
            sl = f["cols"].get(own_stem)
            if sl is None:
                return None
            v = np.clip(row[sl], 0, None)
            return v / v.sum() if v.sum() > 0 else None
        return aligned_mix(row, f["cols"], f["nb"], n_opt, labels, self.sv[ds]["labels"])

    def predict_pop(self, ds, text, own_stem, country, n_opt, K, tool, r, labels=None):
        """Population of a country: size-weighted mean over each attribute's cells, averaged across attributes."""
        f = self.get(ds, text, own_stem, K, tool, r)
        if f is None:
            return None
        by_attr = defaultdict(list)
        for c in f["rows"]:
            if c[1] == country and c[2]:
                p = aligned_mix(f["fit"][f["ridx"][c]], f["cols"], f["nb"], n_opt, labels, self.sv[ds]["labels"])
                if p is not None:
                    by_attr[c[2][0][0]].append((self.sv[ds]["size"].get(c, 1.0) or 1.0, p))
        if not by_attr:
            return None
        parts = [sum(w * p for w, p in v) / sum(w for w, _ in v) for v in by_attr.values()]
        p = np.mean(parts, axis=0)
        return p / p.sum()


# ------------------------------------------------------------------ evaluation


def targets(which):
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    sample, _, _ = A.build_env(25, 100, 7, which)
    out = []
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU), "D3": ("D3_same_group_same_topic", M.HAIKU)}
    for q in M.load(which):
        if q["dataset"] not in A.D_DATASETS:
            continue
        r = sample.loc[q["i"]]
        lab = l1["label"].get(q["qid"], "unknown")
        out.append({"q": q, "split": q["split"], "cell": A._cell_key(r), "country": A._country_of(r.group_prompt_variable_map),
                    "stem": A._stem(r.input_template), "text": A._stem(r.input_template), "n_opt": len(q["keys"]),
                    "labels": [norm_label(q["texts"].get(k, "")) for k in q["keys"]],
                    "bucket": "clustering" if lab == "multimodal" else "dimension-reduction", "l1": lab})
    return out


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def predict(F, t, tool, K, r, seen=False):
    ds = t["q"]["dataset"]
    if t["split"] == "Pop":
        if seen:
            return None
        return F.predict_pop(ds, t["text"], t["stem"], t["country"], t["n_opt"], K, tool, r, t.get("labels"))
    return F.predict_cell(ds, t["text"], t["stem"], t["cell"], t["n_opt"], K, tool, r, seen, t.get("labels"))


def ci(d):
    d = np.asarray(d, float)
    if len(d) < 3:
        return (None, None)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def main():
    held = held_rows()
    surveys = build_surveys(held)
    F = Fitter(surveys)
    dev, ev = targets("dev"), targets("eval")
    rep = {"rule": "row-level holdout: target question never in any fit; eval/dev rows never in any matrix",
           "fill": {ds: float(np.mean([len(sv["obs"]) / (len(sv["cells"]) * len(sv["stems"]))])) for ds, sv in surveys.items()},
           "cells": {ds: len(sv["cells"]) for ds, sv in surveys.items()}, "questions": {ds: len(sv["stems"]) for ds, sv in surveys.items()}}
    print("fill rate per survey:", {k: round(v, 3) for k, v in rep["fill"].items()}, "cells:", rep["cells"])

    # tune on dev: coverage-matched comparison against the raw same-cell average (the demo-average stand-in)
    grid = [("raw", K, 0) for K in KS] + [(tool, K, r) for tool in DR_TOOLS + CL_TOOLS for K in KS for r in RANKS]
    devS = {}
    for cfg in grid:
        vals = []
        for t in dev:
            p = predict(F, t, *cfg)
            vals.append(np.nan if p is None else S(t["q"], p))
        devS[cfg] = np.array(vals)
        print("dev", cfg, f"cov {np.mean(~np.isnan(devS[cfg])):.2f} S {np.nanmean(devS[cfg]):.1f}", flush=True) if cfg[2] in (0, 3) else None
    best = {}
    for b in ("dimension-reduction", "clustering"):
        m = np.array([t["bucket"] == b for t in dev])
        for fam, tools in (("raw", ("raw",)), ("DR", DR_TOOLS), ("CL", CL_TOOLS)):
            cands = [c for c in grid if c[0] in tools]
            # rank on rows every candidate covers, so coverage differences do not decide
            common = m & np.all([~np.isnan(devS[c]) for c in cands], axis=0)
            if common.sum() == 0:
                continue
            best[(b, fam)] = max(cands, key=lambda c: devS[c][common].mean())
    rep["dev_choice"] = {f"{b} | {fam}": list(c) for (b, fam), c in best.items()}
    print("dev choices:", rep["dev_choice"])

    # eval: chosen configs, against raw same-cell average, uniform (chance), retr6_rev2 and D3 model scores
    res = {}
    for b in ("dimension-reduction", "clustering"):
        tt = [t for t in ev if t["bucket"] == b]
        preds = {fam: [predict(F, t, *best[(b, fam)]) if (b, fam) in best else None for t in tt] for fam in ("raw", "DR", "CL")}
        cover = [all(preds[f][i] is not None for f in preds) for i in range(len(tt))]
        sub = [i for i, c in enumerate(cover) if c]
        row = {"N_bucket": len(tt), "N_covered_all_tools": len(sub), "by_split": {}}
        for split in ("Grouped", "Pop", "all"):
            idx = [i for i in sub if split == "all" or tt[i]["split"] == split]
            if not idx:
                continue
            sc = {fam: np.array([S(tt[i]["q"], preds[fam][i]) for i in idx]) for fam in preds}
            sc["chance"] = np.array([S(tt[i]["q"], np.ones(tt[i]["n_opt"]) / tt[i]["n_opt"]) for i in idx])
            sc["retr6_rev2 (model)"] = np.array([S(tt[i]["q"], tt[i]["q"]["preds"]["plain"]) if "plain" in tt[i]["q"]["preds"] else np.nan for i in idx])
            sc["D3 (model)"] = np.array([S(tt[i]["q"], tt[i]["q"]["preds"]["D3"]) if "D3" in tt[i]["q"]["preds"] else np.nan for i in idx])
            row["by_split"][split] = {"N": len(idx), **{k: float(np.nanmean(v)) for k, v in sc.items()},
                                      "DR_vs_raw": float((sc["DR"] - sc["raw"]).mean()), "DR_vs_raw_ci": ci(sc["DR"] - sc["raw"]),
                                      "CL_vs_raw": float((sc["CL"] - sc["raw"]).mean()), "CL_vs_raw_ci": ci(sc["CL"] - sc["raw"])}
        # seen-question ceiling (diagnostic): same chosen configs with other cells' answers to the target included
        seen = []
        for t in tt:
            if t["split"] != "Grouped":
                continue
            p = predict(F, t, *best.get((b, "DR"), ("pca", 19, 2)), seen=True)
            if p is not None:
                seen.append(S(t["q"], p))
        row["seen_question_ceiling_DR"] = {"N": len(seen), "S": float(np.mean(seen)) if seen else None}
        res[b] = row
    rep["eval"] = res
    for b, row in res.items():
        print(f"\n== eval {b}: {row['N_covered_all_tools']}/{row['N_bucket']} covered by every tool")
        for split, r_ in row["by_split"].items():
            print(f"   {split:8s} N {r_['N']:3d} | raw same-cell avg {r_['raw']:5.1f} | best DR {r_['DR']:5.1f} ({r_['DR_vs_raw']:+.1f} {r_['DR_vs_raw_ci']}) | "
                  f"best CL {r_['CL']:5.1f} ({r_['CL_vs_raw']:+.1f} {r_['CL_vs_raw_ci']}) | chance {r_['chance']:5.1f} | retr6_rev2 {r_['retr6_rev2 (model)']:5.1f} | D3 {r_['D3 (model)']:5.1f}")
        print(f"   seen-question ceiling (diagnostic, DR): {row['seen_question_ceiling_DR']}")
    pd.to_pickle({"best": best, "devS": {str(k): v for k, v in devS.items()}}, M.OUT / "structure_l3_tuning.pkl")
    (M.OUT / "structure_l3_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
