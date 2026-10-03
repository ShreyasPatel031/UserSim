"""Consolidated interpretable method (no new model calls): one retrieval base + one structural layer per side + one router.

  base       = D3dyn: the model shown the target group's own answers to up to 12 same-topic questions (real survey rows)
  sharp side = temper(a * factor_completion + (1 - a) * base, t)        [factor completion where it exists, else base]
  other side = b * segments + (1 - b) * base                             [segments where they exist, else base alone]
  final      = pi * sharp side + (1 - pi) * other side,   pi = P(top answer >= 70%) from a dev-trained logistic router

factor_completion and segments are the cross-national tools (target's own country never contributes an answer to the
target question). Parameters a, t, b (and the router) fitted on dev; scored once on eval against every method by shape.
Variants: base = plain retr6_rev2 instead of D3dyn; no structural layers (base only, = D3dyn)."""

from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim import simbench_structure_v3method as V3
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_sharp import CACHE

XN_CFG, XS_CFG = ("fa", 10, 2), ("segsoft", 19, 8)
A_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
T_GRID = (1.0, 1.25, 1.5, 1.75, 2.0)
B_GRID = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8)
R_GRID = [(a, b) for a in (0.5, 1.0, 2.0, 4.0) for b in (-1.0, -0.5, 0.0, 0.5, 1.0)]


def temper(p, t):
    r = np.power(np.clip(p, 1e-9, None), t)
    return r / r.sum()


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def load(which, base):
    M.EVAL_ARMS = M.DEV_ARMS = {"D3dyn": ("D3dyn", M.HAIKU)}
    dyn = {q["qid"]: np.asarray(q["preds"]["D3dyn"]) for q in M.load(which) if "D3dyn" in q["preds"]}
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    qs = []
    for q in V2.load(which, pd.read_pickle(CACHE)):
        if q["qid"] not in dyn:
            continue
        q["base"] = dyn[q["qid"]] if base == "D3dyn" else np.asarray(q["mem"]["plain"])
        q["xn"] = None if x[XN_CFG].get(q["qid"]) is None else np.asarray(x[XN_CFG][q["qid"]])
        q["xs"] = None if x[XS_CFG].get(q["qid"]) is None else np.asarray(x[XS_CFG][q["qid"]])
        q["d3dyn"] = dyn[q["qid"]]
        qs.append(q)
    return qs


def router_X(qs, l1, ds, means):
    rows = []
    for q in qs:
        r = l1.loc[q["qid"]]
        b = q["base"]
        f = [r[c] if pd.notna(r[c]) else means[c] for c in V2.NUM] + [float(r.dataset == k) for k in ds] + [float(r.topic == k) for k in range(20)]
        f += [M.Hn(b), b.max()]
        for k in ("xn", "xs"):
            v = q[k]
            f += [float(v is not None), M.Hn(v) if v is not None else M.Hn(b), v.max() if v is not None else b.max(),
                  float(np.argmax(v) == np.argmax(b)) if v is not None else 1.0]
        rows.append(f)
    return np.array(rows, float)


def sides(q, a, t, b):
    sh = temper(a * q["xn"] + (1 - a) * q["base"], t) if q["xn"] is not None else temper(q["base"], t)
    ot = b * q["xs"] + (1 - b) * q["base"] if q["xs"] is not None else q["base"]
    return sh, ot


def run(base):
    dev, ev = load("dev", base), load("eval", base)
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    ds, means = sorted(l1.dataset.unique()), l1[V2.NUM].mean()
    Xd, Xe = router_X(dev, l1, ds, means), router_X(ev, l1, ds, means)
    yd = np.array([q["top_share"] >= 0.7 for q in dev], int)
    sc = StandardScaler().fit(Xd)
    clf = LogisticRegression(C=0.3, max_iter=5000).fit(sc.transform(Xd), yd)
    ps_d = np.zeros(len(dev))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(Xd, yd):
        s2 = StandardScaler().fit(Xd[tr])
        ps_d[te] = LogisticRegression(C=0.3, max_iter=5000).fit(s2.transform(Xd[tr]), yd[tr]).predict_proba(s2.transform(Xd[te]))[:, 1]
    ps_e = clf.predict_proba(sc.transform(Xe))[:, 1]

    # precompute side scores per (a,t) and b on dev
    def side_scores(qs):
        SH = {(a, t): np.array([sides(q, a, t, 0)[0] for q in qs], dtype=object) for a in A_GRID for t in T_GRID}
        OT = {b: np.array([sides(q, 0, 1, b)[1] for q in qs], dtype=object) for b in B_GRID}
        return SH, OT

    SHd, OTd = side_scores(dev)
    best = None
    for (a, t), (b,), (ra, rb) in itertools.product(SHd, [(b,) for b in B_GRID], R_GRID):
        pi = 1 / (1 + np.exp(-(ra * logit(ps_d) + rb)))
        s = np.mean([V2.S(q, w * sh + (1 - w) * ot) for q, w, sh, ot in zip(dev, pi, SHd[(a, t)], OTd[b])])
        if best is None or s > best[0]:
            best = (s, a, t, b, ra, rb)
    _, a, t, b, ra, rb = best
    pi = 1 / (1 + np.exp(-(ra * logit(ps_e) + rb)))
    preds = {}
    for q, w in zip(ev, pi):
        sh, ot = sides(q, a, t, b)
        preds[q["qid"]] = w * sh + (1 - w) * ot
    cfg = {"base": base, "factor_weight_sharp": a, "sharpen": t, "segment_weight_other": b, "router": (ra, rb)}
    return preds, cfg, ev


def main():
    out = {}
    allp = {}
    for base in ("D3dyn", "plain"):
        preds, cfg, ev = run(base)
        allp[base] = preds
        out[base] = cfg
        print(f"fitted on dev: {cfg}", flush=True)
    pd.to_pickle(allp["D3dyn"], M.OUT / "structure_seg_eval_preds.pkl")
    shape = lambda q: "sharp (top>=70%)" if q["top_share"] >= 0.7 else ("moderate (50-70%)" if q["top_share"] >= 0.5 else "no majority (<50%)")  # noqa: E731
    sys.argv = ["x"]
    from human_sim import simbench_panel_offsets as V  # noqa: E402  (fits v4 on dev)
    v4 = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    rep = {"config": out, "slices": {}}
    for nm, sel, only411 in [(s, (lambda s: lambda q: shape(q) == s)(s), o) for s in ("sharp (top>=70%)", "moderate (50-70%)", "no majority (<50%)") for o in (False, True)] + \
                            [("all", lambda q: True, False), ("all", lambda q: True, True)]:
        qs = [q for q in ev if sel(q) and (not only411 or q["qid"] in v4)]
        S = lambda f: np.array([V2.S(q, f(q)) for q in qs])  # noqa: E731
        ours = S(lambda q: allp["D3dyn"][q["qid"]])
        meths = {"D3dyn": S(lambda q: q["d3dyn"]), "D3": S(lambda q: q["mem"]["D3"]) if all("D3" in q["mem"] for q in qs) else None,
                 "plain": S(lambda q: q["mem"]["plain"]), "same layers on plain base": S(lambda q: allp["plain"][q["qid"]])}
        if only411:
            meths["v4"] = S(lambda q: v4[q["qid"]])
        tag = f"{nm} [{'411 with v4' if only411 else '625'}]"
        line = f"{tag:38s} N {len(qs):3d}  ours {ours.mean():5.1f} | " + " | ".join(f"{k} {v.mean():.1f} ({(ours - v).mean():+.1f} {ci(ours - v)})" for k, v in meths.items() if v is not None)
        print(line)
        rep["slices"][tag] = {"N": len(qs), "ours": float(ours.mean()), **{k: {"S": float(v.mean()), "diff": float((ours - v).mean()), "ci": ci(ours - v)} for k, v in meths.items() if v is not None}}
    (M.OUT / "structure_seg_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
