"""Interpretable cognitive models for two datasets where the LLM is near chance (no model calls).

Choices13k (choices between two gambles): share choosing A = logistic(features of the two gambles): expected-value
  difference, scaled EV difference, spread difference, chance-of-loss difference, prospect-theory value difference
  (alpha 0.88, lambda 2.25, probability weighting gamma 0.61), certainty of each machine.
NumberGame ("is this number likely next?"): Bayesian concept learning with the size principle. Hypotheses = number
  rules on 1..100 (even, odd, multiples of 3..12, ends in d, squares, cubes, powers of 2/3, primes, same decade) plus
  numeric intervals containing the examples. P(target fits) = sum over hypotheses consistent with the examples of
  (1/|h|)^n [target in h] / sum of (1/|h|)^n. Then a logistic calibration on that and simple distance features.
Fitted on training rows only (eval/dev rows excluded); a question's own answer is never used. For the full benchmark,
5-fold cross-fitting: each row is predicted by a model that did not see it.
Output: results/simbench_ablate/cogmodels_{eval,full}.pkl {qid: prediction} + report."""

from __future__ import annotations

import json
import re
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_structure_sharp import ci

# ---------------------------------------------------------------- Choices13k
GAMBLE = re.compile(r"Machine ([AB]):(.*?)(?=Machine [AB]:|Which machine)", re.S)
OUTCOME = re.compile(r"\$(-?[\d.]+) with ([\d.]+)% chance")


def pt_value(outs, a=0.88, lam=2.25, g=0.61):
    w = lambda p: p ** g / (p ** g + (1 - p) ** g) ** (1 / g) if 0 < p < 1 else p  # noqa: E731
    return sum(w(p) * (x ** a if x >= 0 else -lam * (-x) ** a) for x, p in outs)


def gamble_features(text):
    g = {m.group(1): [(float(x), float(p) / 100) for x, p in OUTCOME.findall(m.group(2))] for m in GAMBLE.finditer(text)}
    if "A" not in g or "B" not in g:
        return None
    f = []
    stats = {}
    for k in ("A", "B"):
        outs = [(x, p) for x, p in g[k] if p > 0] or g[k]
        ev = sum(x * p for x, p in outs)
        sd = np.sqrt(sum(p * (x - ev) ** 2 for x, p in outs))
        stats[k] = (ev, sd, sum(p for x, p in outs if x < 0), pt_value(outs), float(len(outs) == 1 or max(p for _, p in outs) >= 0.999), min(x for x, _ in outs), max(x for x, _ in outs))
    (evA, sdA, plA, ptA, cA, mnA, mxA), (evB, sdB, plB, ptB, cB, mnB, mxB) = stats["A"], stats["B"]
    scale = abs(evA) + abs(evB) + 1
    f = [evA - evB, (evA - evB) / scale, sdA - sdB, plA - plB, (ptA - ptB) / (abs(ptA) + abs(ptB) + 1), cA - cB, (mnA - mnB) / scale, (mxA - mxB) / scale]
    return f


# ---------------------------------------------------------------- NumberGame
NUMS = re.compile(r"following numbers:\s*(.*?)\.\s*\n", re.S)
TARGET = re.compile(r"generates this number next:\s*(\d+)")


def hypotheses():
    U = range(1, 101)
    hs = {"even": {x for x in U if x % 2 == 0}, "odd": {x for x in U if x % 2 == 1},
          "squares": {x * x for x in range(1, 11)}, "cubes": {x ** 3 for x in range(1, 5)},
          "powers of 2": {2 ** k for k in range(0, 7)}, "powers of 3": {3 ** k for k in range(0, 5)},
          "primes": {x for x in U if x > 1 and all(x % d for d in range(2, int(x ** 0.5) + 1))}}
    for k in range(3, 13):
        hs[f"multiples of {k}"] = {x for x in U if x % k == 0}
    for d in range(10):
        hs[f"ends in {d}"] = {x for x in U if x % 10 == d}
    for t in range(10):
        hs[f"decade {t}0s"] = {x for x in U if x // 10 == t}
    return hs


HYP = hypotheses()


def number_features(text):
    m, t = NUMS.search(text), TARGET.search(text)
    if not m or not t:
        return None, None
    ex = [int(x) for x in re.findall(r"\d+", m.group(1))]
    y = int(t.group(1))
    if not ex:
        return None, None
    n = len(ex)
    num, den, best = 0.0, 0.0, ("", 0.0)
    for name, h in HYP.items():
        if all(e in h for e in ex):
            w = (1 / len(h)) ** n
            den += w
            num += w * (y in h)
            if w > best[1]:
                best = (name, w)
    lo, hi = min(ex), max(ex)
    for a in range(1, lo + 1):  # intervals [a, b] containing all examples (rule-free similarity)
        for b in range(hi, 101):
            w = 0.5 * (1 / (b - a + 1)) ** n / 50  # intervals share prior mass
            den += w
            num += w * (a <= y <= b)
    p = num / den if den > 0 else 0.5
    dist = min(abs(y - e) for e in ex) / 100
    feats = [np.log(np.clip(p, 1e-4, 1 - 1e-4) / np.clip(1 - p, 1e-4, 1)), dist, float(lo <= y <= hi), n, float(y % 2 == ex[0] % 2)]
    return feats, {"examples": ex, "target": y, "bayes_p_fit": round(p, 3), "strongest_rule": best[0]}


# ---------------------------------------------------------------- fitting
def rows_for(ds, which):
    sample, _, _ = A.build_env(25, 100, 7, which)
    return sample[sample.dataset_name == ds]


def fit_predict(Xtr, ytr, Xte):
    Xtr, Xte = np.array(Xtr, float), np.array(Xte, float)
    sc = StandardScaler().fit(Xtr)
    X2 = np.vstack([sc.transform(Xtr)] * 2)
    yb = np.r_[np.ones(len(ytr)), np.zeros(len(ytr))]
    w = np.r_[ytr, 1 - np.array(ytr)]
    clf = LogisticRegression(C=1.0, max_iter=5000).fit(X2, yb, sample_weight=w)
    return clf.predict_proba(sc.transform(Xte))[:, 1], clf.coef_[0]


def main():
    held = L.held_rows()
    pop = A.load_split("Pop")
    report = {}
    preds_eval, preds_full = {}, {}
    for ds, featfn in (("Choices13k", lambda t: (gamble_features(t), None)), ("NumberGame", number_features)):
        d = pop[pop.dataset_name == ds]
        feats, ys, keys, ok_rows = [], [], [], []
        for _, r in d.iterrows():
            f, _ = featfn(r.input_template)
            if f is None:
                continue
            tot = sum(r.human_answer.values()) or 1.0
            feats.append(f); ys.append(r.human_answer.get("A", 0.0) / tot); ok_rows.append(r)
        train = [i for i, r in enumerate(ok_rows) if (r.dataset_name, A._filled_persona(r), r.input_template) not in held]
        print(f"{ds}: parsed {len(ok_rows)} of {len(d)} rows; training rows (eval/dev excluded) {len(train)}", flush=True)
        # eval: fit on training rows, predict eval questions
        M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
        for which, store in (("eval", preds_eval),):
            sample, _, _ = A.build_env(25, 100, 7, which)
            qs = [q for q in M.load(which) if q["dataset"] == ds and "plain" in q["preds"]]
            Xte, qq = [], []
            for q in qs:
                f, _ = featfn(sample.loc[q["i"]].input_template)
                if f is not None:
                    Xte.append(f); qq.append(q)
            pA, coef = fit_predict([feats[i] for i in train], [ys[i] for i in train], Xte)
            S = lambda q, p: 100 * (1 - M.tvd(np.asarray(p), q["h"]) / q["norm"])  # noqa: E731
            s_new = np.array([S(q, np.array([a, 1 - a]) if q["keys"] == ["A", "B"] else np.array([1 - a, a])) for q, a in zip(qq, pA)])
            s_old = np.array([S(q, q["preds"]["plain"]) for q in qq])
            for q, a in zip(qq, pA):
                store[q["qid"]] = np.array([a, 1 - a])
            print(f"   {which}: N {len(qq)}  plain {s_old.mean():.1f} -> cognitive model {s_new.mean():.1f} ({(s_new - s_old).mean():+.1f} {ci(s_new - s_old)})", flush=True)
            report[ds] = {"eval_N": len(qq), "plain": float(s_old.mean()), "model": float(s_new.mean()), "ci": ci(s_new - s_old), "coef": np.round(coef, 3).tolist()}
        # full: 5-fold cross-fitting over every parsed row
        sample_f, _, _ = A.build_env(25, 100, 7, "full")
        qs_f = [q for q in M.load("full") if q["dataset"] == ds and "plain" in q["preds"]]
        Xf, qf = [], []
        for q in qs_f:
            f, _ = featfn(sample_f.loc[q["i"]].input_template)
            if f is not None:
                Xf.append(f); qf.append(q)
        tf = {sample_f.loc[q["i"]].input_template: q for q in qf}
        yf = [q["h"][q["keys"].index("A")] for q in qf]
        pf = np.zeros(len(qf))
        for tr, te in KFold(5, shuffle=True, random_state=0).split(Xf):
            pf[te], _ = fit_predict([Xf[i] for i in tr], [yf[i] for i in tr], [Xf[i] for i in te])
        S = lambda q, p: 100 * (1 - M.tvd(np.asarray(p), q["h"]) / q["norm"])  # noqa: E731
        s_new = np.array([S(q, np.array([a, 1 - a])) for q, a in zip(qf, pf)])
        s_old = np.array([S(q, q["preds"]["plain"]) for q in qf])
        for q, a in zip(qf, pf):
            preds_full[q["qid"]] = np.array([a, 1 - a])
        print(f"   full (5-fold cross-fitted): N {len(qf)}  plain {s_old.mean():.1f} -> cognitive model {s_new.mean():.1f} ({(s_new - s_old).mean():+.1f} {ci(s_new - s_old)})", flush=True)
        report[ds].update({"full_N": len(qf), "full_plain": float(s_old.mean()), "full_model": float(s_new.mean()), "full_ci": ci(s_new - s_old)})
    pd.to_pickle(preds_eval, M.OUT / "cogmodels_eval.pkl")
    pd.to_pickle(preds_full, M.OUT / "cogmodels_full.pkl")
    (M.OUT / "cogmodels_report.json").write_text(json.dumps(report, indent=2, default=float))


if __name__ == "__main__":
    main()
