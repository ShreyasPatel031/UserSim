"""Like-for-like: plain vs earlier routed method (entropy labels) vs principled routed method (top share >= 70%) vs v4.

Same questions for every method (the shared-survey questions the demographic panel covers), on dev AND eval. Dev is where
every method was fitted, so dev is in-sample for all of them; eval is the fair comparison."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_mass_levers as M
from human_sim import simbench_panel_offsets as V  # fits v4 on dev at import
from human_sim.simbench_structure_sharp import CACHE
from human_sim.simbench_structure_sharpdef import sub_shares

TOOL = ("dmm", 10, 3)
W = 0.25
NUM = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]


def ci(d):
    d = np.asarray(d, float)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def band(q):
    return "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided")


def main():
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl")
    ds = sorted(l1.dataset.unique())
    X = lambda d: np.c_[d[NUM].fillna(l1[NUM].mean()).values, np.array([[float(x == k) for k in ds] for x in d.dataset]),  # noqa: E731
                        np.array([[float(t == k) for k in range(20)] for t in d.topic])]
    top = {}
    for q in V.dev + V.ev:
        top[q["qid"]] = sub_shares(q["keys"], q["roles"], q["h"])[0]
    M.EVAL_ARMS = M.DEV_ARMS = {}
    for w in ("dev", "eval"):
        for q in M.load(w):
            top.setdefault(q["qid"], sub_shares(q["keys"], q["roles"], q["h"])[0])
    tr = l1[l1.set == "dev"]
    sc = StandardScaler().fit(X(tr))

    def probs(labels):
        clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(X(tr)), np.array([labels(r) for _, r in tr.iterrows()], int))
        return dict(zip(l1.qid, clf.predict_proba(sc.transform(X(l1)))[:, 1]))

    p_early = probs(lambda r: r.Hn < 0.65)
    p_prin = probs(lambda r: top[r.qid] >= 0.70)
    tool = pd.read_pickle(CACHE)[TOOL]
    S = lambda q, p: 100 * (1 - M.tvd(p, q["h"]) / q["norm"])  # noqa: E731

    def routed(q, p_sharp, cut):
        p = np.asarray(q["preds"]["plain (retr6_rev2)"])
        x = tool.get(q["qid"])
        return p if (x is None or p_sharp[q["qid"]] >= cut) else W * x + (1 - W) * p

    methods = {"plain (retr6_rev2)": lambda q: np.asarray(q["preds"]["plain (retr6_rev2)"]),
               "earlier routed (entropy labels, shallow if P(sharp) < 0.6)": lambda q: routed(q, p_early, 0.6),
               "principled routed (top share >= 70%, shallow if P(sharp) < 0.3)": lambda q: routed(q, p_prin, 0.3),
               "v4 persona offsets": lambda q: V.predict(q, V.th, V.mu, V.sd)}
    out = {}
    for name, qs in (("dev (in-sample for all)", V.dev), ("eval (fair)", V.ev)):
        S_ = {m: np.array([S(q, f(q)) for q in qs]) for m, f in methods.items()}
        base = S_["plain (retr6_rev2)"]
        out[name] = {"N": len(qs), "methods": {}}
        print(f"\n== {name}: {len(qs)} shared-survey questions covered by every method")
        print(f"{'method':66s}{'S':>6s}{'vs plain':>16s}   consensus / mixed / divided (vs plain)")
        for m, s in S_.items():
            d = s - base
            bands = {b: float(d[[band(q) == b for q in qs]].mean()) for b in ("consensus", "mixed", "divided")}
            out[name]["methods"][m] = {"S": float(s.mean()), "vs_plain": float(d.mean()), "ci": ci(d) if m != "plain (retr6_rev2)" else None, "bands": bands}
            print(f"{m:66s}{s.mean():6.1f}{d.mean():+7.1f} {str(ci(d) if m != 'plain (retr6_rev2)' else ''):>10s}   " + " / ".join(f"{v:+.1f}" for v in bands.values()))
        a, b = S_["v4 persona offsets"], S_["principled routed (top share >= 70%, shallow if P(sharp) < 0.3)"]
        e = S_["earlier routed (entropy labels, shallow if P(sharp) < 0.6)"]
        out[name]["v4_minus_principled"] = {"diff": float((a - b).mean()), "ci": ci(a - b)}
        out[name]["earlier_minus_principled"] = {"diff": float((e - b).mean()), "ci": ci(e - b)}
        print(f"   v4 - principled routed: {(a - b).mean():+.1f} {ci(a - b)} | earlier routed - principled routed: {(e - b).mean():+.1f} {ci(e - b)}")
    (M.OUT / "compare_methods_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
