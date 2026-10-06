"""Bracket-by-bracket tuning on the full benchmark with 5-fold cross-validation (no model calls).

Each question's parameters are chosen on the OTHER four folds and then applied to it, so every reported score is
out-of-sample. A bracket = the questions currently served by one source (optionally one dataset). For each bracket a
small family of candidate predictors is tried (blend weight with the model answer, offset weight, label prior, exponent).
Usage: python -m human_sim.simbench_tune ROUND   (writes tuned predictions and a report per round)"""

from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from human_sim import simbench_mass_levers as M
from human_sim.simbench_structure_sharp import ci

COMP = M.OUT / "fullrule_components.pkl"
TUNED = M.OUT / "tuned_predictions.pkl"


def temper(p, t):
    r = np.power(np.clip(np.asarray(p, float), 1e-9, None), t)
    return r / r.sum()


def S(c, p):
    return 100 * (1 - M.tvd(np.asarray(p), c["h"]) / c["norm"])


def norm(p):
    p = np.clip(np.asarray(p, float), 1e-9, None)
    return p / p.sum()


def cv_tune(cs, fn, grid, k=5):
    """5-fold CV: parameters chosen on 4 folds, applied to the 5th. Returns out-of-sample predictions and choices."""
    idx = np.arange(len(cs))
    preds, chosen = [None] * len(cs), []
    if len(cs) < 10:
        best = max(grid, key=lambda g: np.mean([S(c, fn(c, g)) for c in cs]))
        return [fn(c, best) for c in cs], [best]
    table = np.array([[S(c, fn(c, g)) for g in grid] for c in cs])  # questions x params
    for tr, te in KFold(k, shuffle=True, random_state=0).split(idx):
        gi = int(np.argmax(table[tr].mean(0)))
        chosen.append(grid[gi])
        for i in te:
            preds[i] = fn(cs[i], grid[gi])
    return preds, chosen


# ---------------------------------------------------------------- candidate families
def fam_decomp_blend(key):
    """w * decomposition (offset weight via key 'xd' or 'xd0') + (1 - w) * model, optional label prior v, exponent t."""
    grid = [(xk, w, v, t) for xk in ("xd", "xd0") for w in (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0) for v in (0.0, 0.2, 0.4) for t in (0.8, 0.9, 1.0, 1.15)]

    def fn(c, g):
        xk, w, v, t = g
        x = c.get(xk) if c.get(xk) is not None else c.get(key)
        b = w * norm(x) + (1 - w) * norm(c["plain"]) if x is not None else norm(c["plain"])
        if v and c.get("prior") is not None:
            b = (1 - v) * b + v * norm(c["prior"])
        return temper(b, t)
    return fn, grid


def fam_source_blend(key):
    """w * source + (1 - w) * model, exponent t."""
    grid = [(w, t) for w in (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0) for t in (0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5)]

    def fn(c, g):
        w, t = g
        x = c.get(key)
        b = w * norm(x) + (1 - w) * norm(c["plain"]) if x is not None else norm(c["plain"])
        return temper(b, t)
    return fn, grid


def fam_plain_calib():
    """model answer with label prior v and exponent t."""
    grid = [(v, t) for v in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5) for t in (0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75)]

    def fn(c, g):
        v, t = g
        b = norm(c["plain"])
        if v and c.get("prior") is not None:
            b = (1 - v) * b + v * norm(c["prior"])
        return temper(b, t)
    return fn, grid


def fam_dd(key):
    grid = [(w, t) for w in (0.6, 0.8, 0.9, 1.0) for t in (0.8, 0.9, 1.0, 1.1, 1.25, 1.5)]

    def fn(c, g):
        w, t = g
        x = c.get(key) if c.get(key) is not None else c.get("dd2")
        b = w * norm(x) + (1 - w) * norm(c["plain"]) if x is not None else norm(c["plain"])
        return temper(b, t)
    return fn, grid


def fam_cog_choice():
    """choose between the logistic cognitive model and the gradient-boosted one (key cog_gbm), blended with the model."""
    grid = [(k, w, t) for k in ("cog", "cog_gbm") for w in (0.6, 0.8, 0.9, 1.0) for t in (0.8, 0.9, 1.0, 1.15, 1.3)]

    def fn(c, g):
        k, w, t = g
        x = c.get(k) if c.get(k) is not None else c.get("cog")
        b = w * norm(x) + (1 - w) * norm(c["plain"]) if x is not None else norm(c["plain"])
        return temper(b, t)
    return fn, grid


def fam_source_prior(key):
    """w * source + v * label prior + (1 - w - v) * model, exponent t (three-way, weights on a coarse grid)."""
    grid = [(w, v, t) for w in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0) for v in (0.0, 0.2, 0.4, 0.6) if w + v <= 1.0 for t in (0.8, 0.9, 1.0, 1.15, 1.3)]

    def fn(c, g):
        w, v, t = g
        x, pr = c.get(key), c.get("prior")
        b = (1 - v) * norm(c["plain"]) if pr is not None else norm(c["plain"])
        if x is not None:
            b = b - w * norm(c["plain"]) + w * norm(x)
        if pr is not None:
            b = b + v * norm(pr)
        return temper(norm(b), t)
    return fn, grid


def fam_prior_wide():
    """model answer with a label-prior weight up to 1 (prior alone) and exponent t."""
    grid = [(v, t) for v in (0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0) for t in (0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5)]

    def fn(c, g):
        v, t = g
        b = norm(c["plain"])
        if c.get("prior") is not None:
            b = (1 - v) * b + v * norm(c["prior"])
        return temper(b, t)
    return fn, grid


SHARED = ("ESS", "ISSP", "Afrobarometer", "LatinoBarometro", "OpinionQA")

ROUNDS = {
    1: [("same-group-abroad decomposition + model", None, fam_decomp_blend("xd")),
        ("country-level decomposition + model", None, fam_decomp_blend("xd")),
        ("cognitive model (Choices13k)", None, fam_source_blend("cog")),
        ("cognitive model (NumberGame)", None, fam_source_blend("cog")),
        ("cognitive model (MoralMachine)", None, fam_source_blend("cog")),
        ("other countries, identical question", "GlobalOpinionQA", fam_source_blend("others")),
        ("other countries, identical question", "TISP", fam_source_blend("others")),
        ("other countries, identical question", "ConspiracyCorr", fam_source_blend("others"))],
    2: [("cognitive model (Choices13k)", None, fam_cog_choice()),
        ("cognitive model (NumberGame)", None, fam_cog_choice()),
        *[("plain (other datasets)", ds, fam_plain_calib()) for ds in ("ChaosNLI", "Jester", "DICES", "WisdomOfCrowds", "OSPsychRWAS", "GlobalOpinionQA", "OSPsychMGKT", "MoralMachine")],
        *[("plain + label prior (no decomposition)", ds, fam_plain_calib()) for ds in ("ESS", "ISSP", "Afrobarometer", "LatinoBarometro", "OpinionQA")],
        *[("plain (no decomposition)", ds, fam_plain_calib()) for ds in ("ESS", "ISSP", "Afrobarometer", "LatinoBarometro", "OpinionQA")]],
    3: [*[("same-group-abroad decomposition + model", ds, fam_decomp_blend("xd")) for ds in SHARED],
        *[("country-level decomposition + model", ds, fam_decomp_blend("xd")) for ds in SHARED],
        *[("decomposition", ds, fam_dd("dd3")) for ds in SHARED],
        *[("other countries, identical question", ds, fam_source_prior("others")) for ds in ("ConspiracyCorr", "GlobalOpinionQA", "TISP")],
        ("cognitive model (NumberGame)", None, fam_source_prior("cog")),
        ("cognitive model (Choices13k)", None, fam_source_prior("cog_gbm")),
        *[("plain (other datasets)", ds, fam_prior_wide()) for ds in ("ChaosNLI", "GlobalOpinionQA")],
        *[("plain + label prior (no decomposition)", ds, fam_prior_wide()) for ds in ("ESS", "ISSP", "LatinoBarometro")]],
}


def main():
    rnd = int(sys.argv[1])
    comps = pd.read_pickle(COMP)
    gbm = M.OUT / "cogmodels_full_gbm.pkl"
    if gbm.exists():
        g = pd.read_pickle(gbm)
        for c in comps:
            if c["qid"] in g:
                c["cog_gbm"] = g[c["qid"]] if c["keys"] == ["A", "B"] else g[c["qid"]][::-1]
    tuned = pd.read_pickle(TUNED) if TUNED.exists() else {}
    cur = {c["qid"]: tuned.get(c["qid"], c["final"]) for c in comps}
    N = len(comps)
    base_total = np.mean([S(c, cur[c["qid"]]) for c in comps])
    print(f"round {rnd}: starting full score {base_total:.2f}")
    report = []
    for src, ds, (fn, grid) in ROUNDS[rnd]:
        cs = [c for c in comps if c["source"] == src and (ds is None or c["dataset"] == ds)]
        if not cs:
            continue
        before = np.array([S(c, cur[c["qid"]]) for c in cs])
        preds, chosen = cv_tune(cs, fn, grid)
        after = np.array([S(c, p) for c, p in zip(cs, preds)])
        d = after - before
        lo = ci(d)[0] if len(d) >= 5 else None
        keep = d.mean() > 0 and lo is not None and lo > 0  # keep only changes whose CV interval is above zero
        if keep:
            for c, p in zip(cs, preds):
                tuned[c["qid"]] = p
        mode = max(set(map(tuple, chosen)), key=list(map(tuple, chosen)).count) if chosen else None
        name = src + (f" [{ds}]" if ds else "")
        print(f"   {name:58s} N {len(cs):5d}  {before.mean():5.1f} -> {after.mean():5.1f}  {d.mean():+5.2f} {ci(d)}  {'KEPT' if keep else 'not kept'}  typical params {mode}  full +{d.sum() / N if keep else 0:.2f}")
        report.append({"bracket": name, "N": len(cs), "before": float(before.mean()), "after": float(after.mean()), "diff": float(d.mean()), "ci": ci(d), "kept": bool(keep), "typical": mode})
    pd.to_pickle(tuned, TUNED)
    total = np.mean([S(c, tuned.get(c["qid"], c["final"])) for c in comps])
    print(f"round {rnd}: full score {base_total:.2f} -> {total:.2f}")
    rp = M.OUT / "tune_report.json"
    old = json.loads(rp.read_text()) if rp.exists() else {}
    old[str(rnd)] = {"start": float(base_total), "end": float(total), "brackets": report}
    rp.write_text(json.dumps(old, indent=2, default=str))


if __name__ == "__main__":
    main()
