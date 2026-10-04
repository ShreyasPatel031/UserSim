"""Routed method on equal data (no model calls): dimension reduction for sharp, clustering for shallow.

Data for every member follows the overlap rule (no answer to the target question from any group that may contain the
target's respondents). Members:
  d3dyn   the model shown the group's own answers on same-topic questions
  sibraw  disjoint same-country groups' answer to the question (size-weighted mean)
  ocraw   the same demographic group in other countries
  fa      factor completion (dimension reduction) on groups x questions, disjoint groups + other countries visible
  seg     opinion segments (soft mixture; clustering), same visibility
Sharp side   = temper(simplex blend of {d3dyn, sibraw, ocraw, fa}, t_sharp)    fitted on dev sharp questions
Shallow side = temper(simplex blend of {sibraw, seg, d3dyn}, t_shallow)       fitted on dev shallow questions
final = pi * sharp + (1 - pi) * shallow, pi = sigmoid(a * logit(P(top answer >= 70%)) + b), router cross-fitted on dev.
Ablations: sharp side without fa; shallow side without seg. Compared with v4 refitted on the same data and with B."""

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
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_seg import load

TOOLS = {"sibraw": ("sib:0@sib", 19, 0), "ocraw": ("mean", 19, 0), "fa": ("fa@sib", 10, 2), "seg": ("segsoft@sib", 19, 8),
         "twoway": ("dd", 1.0, 0)}
SHARP = ["d3dyn", "sibraw", "ocraw", "fa", "twoway"]
SHALLOW = ["sibraw", "seg", "d3dyn"]
T_SHARP = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
T_SHALLOW = (0.8, 0.9, 1.0, 1.1, 1.2)
STEP = 0.1


def temper(p, t):
    r = np.power(np.clip(p, 1e-9, None), t)
    return r / r.sum()


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def attach(qs, x):
    for q in qs:
        q["m"] = {"d3dyn": q["d3dyn"]}
        for k, cfg in TOOLS.items():
            v = x.get(cfg, {}).get(q["qid"])
            if v is not None:
                q["m"][k] = np.asarray(v)


def blend(q, w, t):
    use = [(wi, q["m"][k]) for k, wi in w.items() if wi > 0 and k in q["m"]]
    return temper(sum(wi * v for wi, v in use) / sum(wi for wi, _ in use), t) if use else temper(q["d3dyn"], t)


def fit_side(qs, keys, temps):
    k10 = int(round(1 / STEP))
    grid = [dict(zip(keys, np.array(c) / k10)) for c in itertools.product(range(k10 + 1), repeat=len(keys)) if sum(c) == k10]
    return max(((w, t) for w in grid for t in temps), key=lambda wt: np.mean([V2.S(q, blend(q, *wt)) for q in qs]))


def router(dev, ev):
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    ds, means = sorted(l1.dataset.unique()), l1[V2.NUM].mean()

    def X(qs):
        rows = []
        for q in qs:
            r = l1.loc[q["qid"]]
            f = [r[c] if pd.notna(r[c]) else means[c] for c in V2.NUM] + [float(r.dataset == k) for k in ds] + [float(r.topic == k) for k in range(20)]
            for k in ("d3dyn", "sibraw", "ocraw", "fa", "seg"):
                v = q["m"].get(k)
                f += [float(v is not None), M.Hn(v) if v is not None else M.Hn(q["d3dyn"]), v.max() if v is not None else q["d3dyn"].max()]
            rows.append(f)
        return np.array(rows, float)

    Xd, Xe = X(dev), X(ev)
    y = np.array([q["top_share"] >= 0.7 for q in dev], int)
    sc = StandardScaler().fit(Xd)
    pe = LogisticRegression(C=0.3, max_iter=5000).fit(sc.transform(Xd), y).predict_proba(sc.transform(Xe))[:, 1]
    pd_ = np.zeros(len(dev))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(Xd, y):
        s2 = StandardScaler().fit(Xd[tr])
        pd_[te] = LogisticRegression(C=0.3, max_iter=5000).fit(s2.transform(Xd[tr]), y[tr]).predict_proba(s2.transform(Xd[te]))[:, 1]
    return pd_, pe


def build(dev, ev, sharp_keys, shallow_keys, pd_, pe):
    sh_fit = fit_side([q for q in dev if q["top_share"] >= 0.7], sharp_keys, T_SHARP)
    lo_fit = fit_side([q for q in dev if q["top_share"] < 0.7], shallow_keys, T_SHALLOW)
    grid = [(a, b) for a in (0.5, 1.0, 2.0, 4.0, 8.0) for b in (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0)]

    def final(qs, p, ab):
        pi = 1 / (1 + np.exp(-(ab[0] * logit(p) + ab[1])))
        return {q["qid"]: w * blend(q, *sh_fit) + (1 - w) * blend(q, *lo_fit) for q, w in zip(qs, pi)}

    ab = max(grid, key=lambda ab: np.mean([V2.S(q, v) for q, v in zip(dev, final(dev, pd_, ab).values())]))
    return final(ev, pe, ab), {"sharp": sh_fit, "shallow": lo_fit, "router": ab}


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    attach(dev, x)
    attach(ev, x)
    pd_, pe = router(dev, ev)
    variants = {"ROUTED (DR sharp, clustering shallow)": (SHARP, SHALLOW),
                "ablation: no decomposition at all on sharp": ([k for k in SHARP if k not in ("fa", "twoway")], SHALLOW),
                "ablation: no two-way decomposition on sharp": ([k for k in SHARP if k != "twoway"], SHALLOW),
                "variant: two-way decomposition also on shallow": (SHARP, SHALLOW + ["twoway"]),
                "ablation: no clustering on shallow": (SHARP, [k for k in SHALLOW if k != "seg"])}
    P, cfgs = {}, {}
    for nm, (a, b) in variants.items():
        P[nm], cfgs[nm] = build(dev, ev, a, b, pd_, pe)
        c = cfgs[nm]
        fmt = lambda f: ({k: round(v, 1) for k, v in f[0].items() if v > 0}, f[1])  # noqa: E731
        print(f"CFG {nm}: sharp {fmt(c['sharp'])} | shallow {fmt(c['shallow'])} | router {c['router']}", flush=True)
    v4r = pd.read_pickle(M.OUT / "v4_refit_eval_preds.pkl")
    B = pd.read_pickle(M.OUT / "structure_decomp_eval_preds.pkl")["B  D3dyn + raw extracted data"]
    pd.to_pickle(P, M.OUT / "structure_routed2_eval_preds.pkl")
    rep = {"configs": {k: {"sharp": v["sharp"], "shallow": v["shallow"], "router": v["router"]} for k, v in cfgs.items()}, "slices": {}}
    R = "ROUTED (DR sharp, clustering shallow)"
    for sl, sel in (("SHARP (top>=70%)", lambda q: q["top_share"] >= 0.7), ("SHALLOW (top<70%)", lambda q: q["top_share"] < 0.7),
                    ("  moderate", lambda q: 0.5 <= q["top_share"] < 0.7), ("  no majority", lambda q: q["top_share"] < 0.5), ("ALL", lambda q: True)):
        qs = [q for q in ev if sel(q) and q["qid"] in v4r]
        r = np.array([V2.S(q, P[R][q["qid"]]) for q in qs])
        comp = {"v4 refit (same data)": np.array([V2.S(q, v4r[q["qid"]]) for q in qs]), "B raw blend": np.array([V2.S(q, B[q["qid"]]) for q in qs]),
                "D3dyn": np.array([V2.S(q, q["d3dyn"]) for q in qs])}
        for nm in variants:
            if nm != R:
                comp[nm] = np.array([V2.S(q, P[nm][q["qid"]]) for q in qs])
        print(f"\n== {sl}: N {len(qs)} (questions where v4 exists) — ROUTED {r.mean():.1f}")
        rep["slices"][sl] = {"N": len(qs), "routed": float(r.mean())}
        for k, s in comp.items():
            print(f"   vs {k:42s} {s.mean():5.1f}   routed - it {(r - s).mean():+5.1f} {ci(r - s)}")
            rep["slices"][sl][k] = {"S": float(s.mean()), "diff": float((r - s).mean()), "ci": ci(r - s)}
    (M.OUT / "structure_routed2_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
