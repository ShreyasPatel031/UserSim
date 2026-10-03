"""Layer 2 step A/B: how many retr6 demos? Free sweep with a stand-in predictor (no model calls).

Stand-in at k = plain average of the top-k demos that share the target's option count (matched by position); if none
of the top k does, the first aligned demo further down the ranking. Signals per k use only demos, never the target."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_divided_anatomy import option_roles, parse_options

KS = (1, 2, 3, 4, 6, 8, 12, 16, 24)
POOL = 24


def rep(d):
    """Position-normalized summary: mean, SD, entropy, top share, mass on first / last third."""
    keys = list(d["human_answer"])
    tot = sum(d["human_answer"].values()) or 1.0
    h = np.array([d["human_answer"][k] / tot for k in keys])
    roles = option_roles(keys, parse_options(d["input_template"]), "")
    parts = M._ord_parts(roles, keys)
    if parts:
        idx, pos = parts
        m = h[idx] / max(h[idx].sum(), 1e-9)
    else:
        m, pos = h, np.linspace(0, 1, len(h))
    mu = float((m * pos).sum())
    sd = float(np.sqrt((m * (pos - mu) ** 2).sum()))
    return np.array([mu, sd, M.Hn(h), h.max(), float(m[pos < 1 / 3].sum()), float(m[pos > 2 / 3].sum())])


def ranked_pool(row, ctx):
    pool = A._demo_pool(row, ctx)
    if not pool:
        return [], np.array([])
    ranked = A._rank_by_similarity(row, pool, ctx)[:POOL]
    sims = A._similarities(row, pool, ctx, "tfidf")
    sim_of = {id(d): float(s) for d, s in zip(pool, sims)}
    return ranked, np.array([sim_of[id(d)] for d in ranked])


def build(which):
    sample, _, ctx = A.build_env(25, 100, 7, which)
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    rows = []
    for q in M.load(which):
        r = sample.loc[q["i"]]
        ranked, sims = ranked_pool(r, ctx)
        if not ranked:
            continue
        nk = len(q["keys"])
        aligned = [i for i, d in enumerate(ranked) if len(d["human_answer"]) == nk]
        vecs = {i: (lambda d: (lambda v: v / v.sum())(np.array(list(d["human_answer"].values()), float)))(ranked[i]) for i in aligned}
        R = np.array([rep(d) for d in ranked])
        rows.append({"qid": q["qid"], "q": q, "ranked_n": len(ranked), "sims": sims, "R": R, "aligned": aligned, "vecs": vecs,
                     "bucket": l1.loc[q["qid"], "label"], "band": l1.loc[q["qid"], "band"], "group3": q["group3"]})
    return rows


def standin(row, k):
    al = row["aligned"]
    if not al:
        return None
    use = [i for i in al if i < k] or [al[0]]
    return np.mean([row["vecs"][i] for i in use], axis=0)


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def signals(row, scale):
    """Per k: convergence of the running mean in the pool's top-2 PC space, similarity of the k-th / next demo, spread."""
    R = (row["R"] - scale[0]) / scale[1]
    n = len(R)
    mean_all = R.mean(0)
    C = R - mean_all
    if n >= 3:
        _, _, vt = np.linalg.svd(C, full_matrices=False)
        P = vt[:2]
    else:
        P = np.eye(R.shape[1])
    Z = C @ P.T
    tot = float((Z ** 2).sum(1).mean()) + 1e-9
    out = {}
    for k in KS:
        kk = min(k, n)
        mk = Z[:kk].mean(0)
        ev = 1 - float((mk ** 2).sum()) / tot
        nxt = row["sims"][kk] if kk < n else 0.0
        sp = float(np.mean([np.abs(R[i] - R[j]).sum() for i in range(kk) for j in range(i + 1, kk)])) if kk > 1 else 0.0
        out[k] = {"ev": ev, "sim_k": float(row["sims"][kk - 1]), "sim_next": float(nxt), "spread": sp}
    return out


def pick_k(sig, rule):
    kind, tau, sigma = rule
    for k in KS:
        a = sig[k]["ev"] >= tau
        b = sig[k]["sim_next"] < sigma
        if (kind == "ev" and a) or (kind == "sim" and b) or (kind == "or" and (a or b)) or (kind == "and" and a and b):
            return k
    return KS[-1]


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def main():
    dev, ev = build("dev"), build("eval")
    allR = np.vstack([r["R"] for r in dev])
    scale = (allR.mean(0), allR.std(0) + 1e-9)
    for rows in (dev, ev):
        for r in rows:
            r["sig"] = signals(r, scale)
            r["Sk"] = {k: (S(r["q"], standin(r, k)) if r["aligned"] else np.nan) for k in KS}
    rep_ = {"definition": {
        "standin": "mean of top-k demos with the target's option count (position-matched); first aligned demo if none in top k",
        "common_representation": ["mean position", "SD", "normalized entropy", "top share", "mass first third", "mass last third"],
        "ev": "1 - |running mean of first k demos|^2 / mean |demo|^2, in the pool's top-2 PC space (centred on the pool mean)"}}
    out = {}
    for name, rows in (("dev", dev), ("eval", ev)):
        cov = [r for r in rows if r["aligned"]]
        d = {"N": len(rows), "covered": len(cov), "coverage": len(cov) / len(rows)}
        for grp, sel in (("all", lambda r: True), ("consensus", lambda r: r["band"] == "consensus"),
                         ("divided", lambda r: r["band"] == "divided"), ("Pop", lambda r: r["q"]["split"] == "Pop"),
                         ("Grouped", lambda r: r["q"]["split"] == "Grouped")):
            sub = [r for r in cov if sel(r)]
            d[grp] = {"N": len(sub), **{str(k): float(np.mean([r["Sk"][k] for r in sub])) for k in KS}}
        out[name] = d
    rep_["fixed_k"] = out
    print("== stand-in S by fixed k (covered rows)")
    for name in ("dev", "eval"):
        print(f"-- {name}: coverage {out[name]['coverage']:.0%} ({out[name]['covered']}/{out[name]['N']})")
        for grp in ("all", "consensus", "divided", "Pop", "Grouped"):
            g = out[name][grp]
            print(f"   {grp:10s} N {g['N']:4d} " + " ".join(f"k{k}:{g[str(k)]:5.1f}" for k in KS))

    covd = [r for r in dev if r["aligned"]]
    rules = [("ev", t, 0) for t in (0.6, 0.7, 0.8, 0.9)]
    sims_all = np.concatenate([r["sims"] for r in covd])
    sig_grid = sorted(set(np.round(np.quantile(sims_all, [0.1, 0.25, 0.4, 0.55, 0.7, 0.85]), 3)))
    rules += [("sim", 0, s) for s in sig_grid]
    rules += [(kind, t, s) for kind in ("or", "and") for t in (0.6, 0.7, 0.8, 0.9) for s in sig_grid]
    score = lambda rows, rule: np.mean([r["Sk"][pick_k(r["sig"], rule)] for r in rows])  # noqa: E731
    best = max(rules, key=lambda ru: score(covd, ru))
    fixed_best = max(KS, key=lambda k: np.mean([r["Sk"][k] for r in covd]))
    cove = [r for r in ev if r["aligned"]]
    s_rule = np.array([r["Sk"][pick_k(r["sig"], best)] for r in cove])
    s6 = np.array([r["Sk"][6] for r in cove])
    s_fb = np.array([r["Sk"][fixed_best] for r in cove])
    ks = [pick_k(r["sig"], best) for r in cove]
    rep_["rule"] = {"best_rule": {"kind": best[0], "tau": best[1], "sigma": best[2]}, "dev_S_rule": score(covd, best),
                    "dev_S_k6": float(np.mean([r["Sk"][6] for r in covd])), "dev_best_fixed_k": fixed_best,
                    "eval_S_rule": float(s_rule.mean()), "eval_S_k6": float(s6.mean()), "eval_rule_vs_k6": float((s_rule - s6).mean()),
                    "eval_rule_vs_k6_ci": ci(s_rule - s6), "eval_S_best_fixed": float(s_fb.mean()),
                    "eval_k_distribution": {str(k): int(ks.count(k)) for k in KS},
                    "dev_rules_top5": sorted(((score(covd, ru), ru) for ru in rules), reverse=True)[:5]}
    print(f"\n== dev-fitted stopping rule: {best} (dev stand-in S {score(covd, best):.1f} vs k6 {rep_['rule']['dev_S_k6']:.1f}; best fixed k on dev = {fixed_best})")
    print(f"   eval: rule {s_rule.mean():.1f} vs k6 {s6.mean():.1f} ({(s_rule - s6).mean():+.1f} {ci(s_rule - s6)}); best fixed k{fixed_best}: {s_fb.mean():.1f}")
    print("   eval k chosen:", rep_["rule"]["eval_k_distribution"])
    (M.OUT / "structure_l2_retr_sweep.json").write_text(json.dumps(rep_, indent=2, default=float))
    pd.to_pickle({"rule": best, "scale": scale}, M.OUT / "structure_l2_retr_rule.pkl")


if __name__ == "__main__":
    main()
