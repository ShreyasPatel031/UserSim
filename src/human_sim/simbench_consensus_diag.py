"""Why do the routed methods not improve consensus questions? Diagnostic (uses the real answers only to pick questions).

Consensus = real normalized entropy < 0.65, shared-survey questions, eval. Part A: how good is the tool on these questions,
how often is it applied to them, what does blending it in do at every weight. Part B: does ensembling the existing
retrievals (plain, retr6, D3) with sharpening help consensus questions where the tool does not."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_structure_sharp import CACHE, ci
from human_sim.simbench_structure_sharpdef import sub_shares

H = M.HAIKU
NUM = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]


def temper(p, t):
    r = np.power(np.clip(p, 1e-9, None), t)
    return r / r.sum()


def main():
    S = L.S
    top_ok = lambda q, p: float(np.argmax(p) == np.argmax(q["h"]))  # noqa: E731
    cache = pd.read_pickle(CACHE)
    cl, dr = cache[("dmm", 10, 3)], cache[("fa", 10, 3)]
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", H), "retr6": ("retr6", H), "D3": ("D3_same_group_same_topic", H)}
    Q = {w: {q["qid"]: q for q in M.load(w)} for w in ("dev", "eval")}
    sets = {w: [t for t in L.targets(w) if "plain" in Q[w][t["q"]["qid"]]["preds"]] for w in ("dev", "eval")}
    cons = lambda t: t["q"]["Hn"] < 0.65  # noqa: E731
    out = {}

    # ---- Part A: the tool on true consensus questions
    ev = [t for t in sets["eval"] if cons(t) and cl.get(t["q"]["qid"]) is not None and dr.get(t["q"]["qid"]) is not None]
    qs = [t["q"] for t in ev]
    plain = [np.asarray(Q["eval"][q["qid"]]["preds"]["plain"]) for q in qs]
    rowsA = {"N": len(ev), "model_S": float(np.mean([S(q, p) for q, p in zip(qs, plain)])),
             "component_tool_S": float(np.mean([S(q, dr[q["qid"]]) for q in qs])),
             "clustering_tool_S": float(np.mean([S(q, cl[q["qid"]]) for q in qs])),
             "model_top_answer_right": float(np.mean([top_ok(q, p) for q, p in zip(qs, plain)])),
             "component_tool_top_right": float(np.mean([top_ok(q, dr[q["qid"]]) for q in qs])),
             "clustering_tool_top_right": float(np.mean([top_ok(q, cl[q["qid"]]) for q in qs])),
             "model_entropy": float(np.mean([M.Hn(p) for p in plain])), "true_entropy": float(np.mean([q["Hn"] for q in qs])),
             "blend_gain_by_weight": {}}
    for w in (0.05, 0.1, 0.15, 0.25, 0.4):
        d = np.array([S(q, w * cl[q["qid"]] + (1 - w) * p) - S(q, p) for q, p in zip(qs, plain)])
        rowsA["blend_gain_by_weight"][str(w)] = {"gain": float(d.mean()), "ci": ci(d)}
    out["A_tool_on_consensus"] = rowsA
    print(f"== A. clustering/component tool on {len(ev)} true-consensus shared-survey eval questions")
    print(f"   score alone: model {rowsA['model_S']:.1f} | component tool {rowsA['component_tool_S']:.1f} | clustering tool {rowsA['clustering_tool_S']:.1f}")
    print(f"   top answer right: model {rowsA['model_top_answer_right']:.0%} | component tool {rowsA['component_tool_top_right']:.0%} | clustering tool {rowsA['clustering_tool_top_right']:.0%}")
    print(f"   spread (entropy): model predicts {rowsA['model_entropy']:.2f}, real {rowsA['true_entropy']:.2f}")
    print("   blend gain on consensus by weight on the clustering tool: " + " | ".join(f"w={k}: {v['gain']:+.1f} {v['ci']}" for k, v in rowsA["blend_gain_by_weight"].items()))

    # ---- routing: how often is the tool applied to consensus questions, and with what effect
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl")
    ds = sorted(l1.dataset.unique())
    X = lambda d: np.c_[d[NUM].fillna(l1[NUM].mean()).values, np.array([[float(x == k) for k in ds] for x in d.dataset]),  # noqa: E731
                        np.array([[float(t == k) for k in range(20)] for t in d.topic])]
    top = {qid: sub_shares(q["keys"], q["roles"], q["h"])[0] for w in Q for qid, q in Q[w].items()}
    tr = l1[l1.set == "dev"]
    sc = StandardScaler().fit(X(tr))
    clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(X(tr)), np.array([top[q] >= 0.7 for q in tr.qid], int))
    ps = dict(zip(l1.qid, clf.predict_proba(sc.transform(X(l1)))[:, 1]))
    shallow = np.array([ps[q["qid"]] < 0.3 for q in qs])
    g = np.array([S(q, 0.25 * cl[q["qid"]] + 0.75 * p) - S(q, p) for q, p in zip(qs, plain)])
    out["A_routing"] = {"share_routed_shallow": float(shallow.mean()), "gain_when_routed_shallow": float(g[shallow].mean()) if shallow.any() else None,
                        "ci": ci(g[shallow]) if shallow.sum() > 4 else None, "overall_consensus_gain": float(np.where(shallow, g, 0).mean())}
    print(f"   routing (principled method): {shallow.mean():.0%} of these consensus questions are routed to 'shallow' and get the tool; "
          f"gain on those {g[shallow].mean():+.1f} {ci(g[shallow])}; the rest are untouched (0 by construction); net on consensus {np.where(shallow, g, 0).mean():+.2f}")

    # ---- Part B: ensembling existing retrievals + sharpening, Grouped shared-survey consensus
    def ens(q, w, kind):
        P = Q[w][q["qid"]]["preds"]
        parts = {"plain": P["plain"], "retr6": P["retr6"], "D3": P.get("D3")}
        use = [parts[k] for k in kind if parts[k] is not None]
        return np.mean(use, axis=0) if len(use) == len(kind) else None

    kinds = {"plain alone": ("plain",), "retr6 alone": ("retr6",), "D3 alone": ("D3",), "avg plain+retr6": ("plain", "retr6"),
             "avg plain+D3": ("plain", "D3"), "avg plain+retr6+D3": ("plain", "retr6", "D3")}
    devc = [t for t in sets["dev"] if cons(t) and t["split"] == "Grouped"]
    evc = [t for t in sets["eval"] if cons(t) and t["split"] == "Grouped"]
    rowsB = {}
    print(f"\n== B. existing retrievals, ensembled and sharpened, on Grouped shared-survey consensus questions (eval N {len(evc)}; sharpening exponent picked on {len(devc)} dev consensus questions; diagnostic: uses the true band to pick questions)")
    base = np.array([S(t["q"], ens(t["q"], "eval", ("plain",))) for t in evc])
    for nm, kind in kinds.items():
        dv = [t for t in devc if ens(t["q"], "dev", kind) is not None]
        e_ = [t for t in evc if ens(t["q"], "eval", kind) is not None]
        t_best = max(np.arange(1.0, 3.01, 0.25), key=lambda tt: np.mean([S(t["q"], temper(ens(t["q"], "dev", kind), tt)) for t in dv]))
        s0 = np.array([S(t["q"], ens(t["q"], "eval", kind)) for t in e_])
        s1 = np.array([S(t["q"], temper(ens(t["q"], "eval", kind), t_best)) for t in e_])
        b = np.array([S(t["q"], ens(t["q"], "eval", ("plain",))) for t in e_])
        rowsB[nm] = {"N": len(e_), "S": float(s0.mean()), "vs_plain": float((s0 - b).mean()), "sharpen_exponent": float(t_best),
                     "S_sharpened": float(s1.mean()), "sharpened_vs_plain": float((s1 - b).mean()), "ci": ci(s1 - b)}
        print(f"   {nm:22s} N {len(e_):3d}  S {s0.mean():5.1f} ({(s0 - b).mean():+.1f} vs plain) | sharpened x{t_best:.2f}: {s1.mean():5.1f} ({(s1 - b).mean():+.1f} {ci(s1 - b)})")
    out["B_ensembles_on_consensus"] = rowsB
    (M.OUT / "consensus_diag_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
