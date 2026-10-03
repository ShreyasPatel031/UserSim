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
for _a in sys.argv:
    if _a.startswith("--xs=") or _a.startswith("--xn="):
        _n, _k, _r = _a[5:].split(",")
        if _a.startswith("--xs="):
            XS_CFG = (_n, int(_k), int(_r))
        else:
            XN_CFG = (_n, int(_k), int(_r))
A_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
T_GRID = (1.0, 1.25, 1.5, 1.75, 2.0)
TU_GRID = (1.0, 1.1, 1.25, 1.5)  # sharpening on the sharp side when no factor completion exists
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


def sides(q, a, t, b, tu=None):
    sh = temper(a * q["xn"] + (1 - a) * q["base"], t) if q["xn"] is not None else temper(q["base"], t if tu is None else tu)
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
    split_t = "--split-t" in sys.argv
    tus = TU_GRID if split_t else (None,)
    SHd = {(a, t, tu): [sides(q, a, t, 0, tu)[0] for q in dev] for a in A_GRID for t in T_GRID for tu in tus}
    OTd = {b: [sides(q, 0, 1, b)[1] for q in dev] for b in B_GRID}
    Sd = {}
    best = None
    for key, b, (ra, rb) in itertools.product(SHd, B_GRID, R_GRID):
        pi = 1 / (1 + np.exp(-(ra * logit(ps_d) + rb)))
        s = np.mean([V2.S(q, w * sh + (1 - w) * ot) for q, w, sh, ot in zip(dev, pi, SHd[key], OTd[b])])
        if best is None or s > best[0]:
            best = (s, key, b, ra, rb)
    _, (a, t, tu), b, ra, rb = best
    pi = 1 / (1 + np.exp(-(ra * logit(ps_e) + rb)))
    preds = {}
    for q, w in zip(ev, pi):
        sh, ot = sides(q, a, t, b, tu)
        preds[q["qid"]] = w * sh + (1 - w) * ot
    cfg = {"base": base, "factor_weight_sharp": a, "sharpen": t, "sharpen_without_factor": tu, "segment_weight_other": b, "router": (ra, rb), "dev_S": best[0]}
    return preds, cfg, ev


def select():
    """Plug each segmentation tool into the method, fit on dev, report dev score (selection) and eval vs D3dyn."""
    global XS_CFG
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    cands = [c for c in x if isinstance(c, tuple) and len(c) == 3 and not (isinstance(c[0], str) and c[0] == "why")]
    rows = []
    for c in cands:
        if c[0].split(":")[0].split("_")[0].split("+")[0] not in ("segsoft", "seg", "knn", "hier", "kmeans", "gmm", "mean", "dmm"):
            continue
        XS_CFG = c
        preds, cfg, ev = run("D3dyn")
        dev = load("dev", "D3dyn")
        # dev score of the fitted config (in-sample selection score)
        evs = {}
        for nm, sel in (("shallow", lambda q: q["top_share"] < 0.7), ("no majority", lambda q: q["top_share"] < 0.5), ("all", lambda q: True)):
            qs = [q for q in ev if sel(q)]
            o = np.array([V2.S(q, preds[q["qid"]]) for q in qs]); d = np.array([V2.S(q, q["d3dyn"]) for q in qs])
            evs[nm] = (o.mean(), (o - d).mean(), ci(o - d))
        rows.append((c, cfg["dev_S"], evs))
        print(f"{str(c):32s} dev {cfg['dev_S']:.2f} | eval " + " | ".join(f"{k} {v[0]:.1f} vs D3dyn {v[1]:+.1f} {v[2]}" for k, v in evs.items()), flush=True)


def main():
    if "--select" in sys.argv:
        return select()
    out = {}
    allp = {}
    for base in ("D3dyn", "plain"):
        preds, cfg, ev = run(base)
        allp[base] = preds
        out[base] = cfg
        print(f"fitted on dev: {cfg}", flush=True)
    pd.to_pickle(allp["D3dyn"], M.OUT / ("structure_seg2_eval_preds.pkl" if "--split-t" in sys.argv else "structure_seg_eval_preds.pkl"))
    shape = lambda q: "sharp (top>=70%)" if q["top_share"] >= 0.7 else ("moderate (50-70%)" if q["top_share"] >= 0.5 else "no majority (<50%)")  # noqa: E731
    split = "--split-t" in sys.argv
    sys.argv = ["x"]
    from human_sim import simbench_panel_offsets as V  # noqa: E402  (fits v4 on dev)
    v4 = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    rep = {"config": out, "slices": {}}
    for nm, sel, only411 in [(s, (lambda s: lambda q: shape(q) == s)(s), o) for s in ("sharp (top>=70%)", "moderate (50-70%)", "no majority (<50%)") for o in (False, True)] + \
                            [("SHALLOW (top<70%)", lambda q: q["top_share"] < 0.7, True), ("all", lambda q: True, False), ("all", lambda q: True, True)]:
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
    (M.OUT / ("structure_seg2_report.json" if split else "structure_seg_report.json")).write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
