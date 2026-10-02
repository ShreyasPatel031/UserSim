"""Personas on every question, spread controlled per question. Offline on logged persona outputs.

Each persona's distribution is pulled toward an anchor by lam, persona shares are sharpened by gamma, and the
merged answer is tempered by t. lam and t are set per question from truth-free signals, fit on dev, scored on eval.
Every final answer stays a weighted mix of named personas, so each one remains inspectable."""

from __future__ import annotations

import ast
import json
import math

import numpy as np
from scipy.optimize import minimize

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M

ARMS = {"plain": ("retr6_rev2", M.HAIKU), "panel": ("P_groundall5", M.HAIKU), "pstrict": ("P_strict5", M.HAIKU)}
FEATS = ["h_plain", "maxp_plain", "h_anchor", "h_panel", "persona_spread", "persona_to_anchor", "top_share",
         "nbr_h", "nbr_missing", "has_evidence", "rel_disjoint", "rel_country", "log_k", "ordinal", "binary", "task",
         "other_pop"]
EPS = 1e-6


def _norm(v):
    v = np.asarray(v, float) + EPS
    return v / v.sum()


def _personas(trace, keys):
    segs = ast.literal_eval(trace) if isinstance(trace, str) else trace
    D = np.array([_norm([s["dist"].get(k, 0.0) for k in keys]) for s in segs])
    w = np.array([float(s["share"]) for s in segs])
    return D, w / w.sum(), [s.get("desc", "") for s in segs]


def _evidence(row, keys):
    src = A._leak_sources(row, A._NO_OVERLAP)
    if not src:
        return None, None
    rel = src[0][0]
    V = [_norm([float(a.get(k, 0.0)) for k in keys]) for r, _, _, a in src if r == rel]
    W = np.array([s or 1.0 for r, _, s, _ in src if r == rel])
    return rel, (W / W.sum()) @ np.array(V)


def prep(which, use_evidence):
    M.EVAL_ARMS = ARMS
    M.DEV_ARMS = ARMS
    sample, _, _ = A.build_env(25, 100, 7, which)
    out = []
    for q in M.load(which):
        if "plain" not in q["preds"] or "panel" not in q.get("traces", {}):
            continue
        keys = q["keys"]
        pl = _norm(q["preds"]["plain"])
        rel, data = _evidence(sample.loc[q["i"]], keys) if use_evidence else (None, None)
        src = "pstrict" if (data is not None and "pstrict" in q.get("traces", {})) else "panel"
        if data is not None and src == "panel":
            rel, data = None, None  # evidence only counts where the evidence panel ran
        D, w, desc = _personas(q["traces"][src], keys)
        anchor = data if data is not None else pl
        mix = w @ D
        q.update(D=D, w=w, desc=desc, anchor=anchor, pl=pl, rel=rel, src=src)
        q["x"] = {
            "h_plain": M.Hn(pl), "maxp_plain": pl.max(), "h_anchor": M.Hn(anchor), "h_panel": M.Hn(mix),
            "persona_spread": float(w @ (np.abs(D - mix).sum(1) / 2)),
            "persona_to_anchor": float(w @ (np.abs(D - anchor).sum(1) / 2)), "top_share": w.max(),
            "nbr_h": 0.0 if math.isnan(q["nbr_h"]) else q["nbr_h"], "nbr_missing": float(math.isnan(q["nbr_h"])),
            "has_evidence": float(data is not None), "rel_disjoint": float(rel == "disjoint_subgroup"),
            "rel_country": float(rel == "other_countries"), "log_k": math.log(len(keys)),
            "ordinal": float(q["format"] == "ordinal"), "binary": float(q["format"] == "binary"),
            "task": float(q["group3"] == "pop_only_task"), "other_pop": float(q["group3"] == "other_pop_only"),
        }
        out.append(q)
    return out


def design(qs, mu=None, sd=None):
    X = np.array([[q["x"][f] for f in FEATS] for q in qs])
    if mu is None:
        mu, sd = X.mean(0), X.std(0) + 1e-9
    return np.c_[np.ones(len(X)), (X - mu) / sd], mu, sd


def controls(xrow, th, mode):
    k = len(xrow)
    if mode == "raw":
        return 0.0, 1.0, 1.0
    if mode == "global":
        return 1 / (1 + math.exp(-th[0])), math.exp(np.clip(th[1], -3, 3)), math.exp(th[2])
    lam = 1 / (1 + math.exp(-float(xrow @ th[:k])))
    t = math.exp(np.clip(float(xrow @ th[k:2 * k]), -3, 3))
    return lam, t, math.exp(th[2 * k])


def predict(q, xrow, th, mode):
    lam, t, g = controls(xrow, th, mode)
    Dp = lam * q["anchor"] + (1 - lam) * q["D"]  # each persona pulled toward the anchor
    w = np.power(q["w"], g)
    w = w / w.sum()
    p = np.power(w @ Dp, t)
    return p / p.sum(), Dp, w, (lam, t, g)


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def scores(qs, X, th, mode):
    return np.array([S(q, predict(q, X[i], th, mode)[0]) for i, q in enumerate(qs)])


def fit(qs, X, mode, lam_reg=0.02):
    k = X.shape[1]
    th0 = np.zeros({"global": 3, "dyn": 2 * k + 1}[mode])

    def loss(th):
        reg = lam_reg * float(np.sum(th[1:k] ** 2) + np.sum(th[k + 1:2 * k] ** 2)) if mode == "dyn" else 0.0
        return -scores(qs, X, th, mode).mean() + reg

    best = None
    for meth in ("Powell", "Nelder-Mead", "Powell"):
        r = minimize(loss, th0 if best is None else best.x, method=meth, options={"maxiter": 6000})
        best = r if best is None or r.fun < best.fun else best
    return best.x


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def band(q):
    return "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided")


def run(use_evidence):
    tag = "with no-overlap evidence" if use_evidence else "benchmark-valid (no evidence)"
    dev, ev = prep("dev", use_evidence), prep("eval", use_evidence)
    Xd, mu, sd = design(dev)
    Xe, _, _ = design(ev, mu, sd)
    plain = np.array([S(q, q["pl"]) for q in ev])
    res = {"N_dev": len(dev), "N_eval": len(ev), "arms": {}}
    print(f"\n==== {tag}: dev {len(dev)}, eval {len(ev)}")
    cand = {"plain (no personas)": plain,
            "anchor alone (no personas)": np.array([S(q, q["anchor"]) for q in ev]),
            "50/50 plain+panel": np.array([S(q, (q["pl"] + q["w"] @ q["D"]) / 2) for q in ev])}
    ths = {}
    for mode in ("raw", "global", "dyn"):
        th = fit(dev, Xd, mode) if mode != "raw" else np.zeros(1)
        ths[mode] = th
        cand[f"personas, {mode} control"] = scores(ev, Xe, th, mode)
        if mode != "raw":
            res["arms"][f"personas, {mode} control (dev in-sample)"] = float(scores(dev, Xd, th, mode).mean())
    print(f"{'setup':38s}{'S':>6s}{'vs plain':>17s}   consensus / mixed / divided (vs plain)")
    for nm, s in cand.items():
        d = s - plain
        bands = {b: float(d[[band(q) == b for q in ev]].mean()) for b in ("consensus", "mixed", "divided")}
        res["arms"][nm] = {"S": float(s.mean()), "vs_plain": float(d.mean()), "ci": ci(d), "by_band": bands}
        print(f"{nm:38s}{s.mean():6.1f}{d.mean():+6.1f} {str(ci(d)):>10s}   " + " / ".join(f"{v:+.1f}" for v in bands.values()))
    # how the dynamic controls move with the (unseen) true band and with evidence
    ctl = [controls(Xe[i], ths["dyn"], "dyn") for i in range(len(ev))]
    summ = {}
    for b in ("consensus", "mixed", "divided"):
        m = [band(q) == b for q in ev]
        L = np.array([c[0] for c, mm in zip(ctl, m) if mm])
        T = np.array([c[1] for c, mm in zip(ctl, m) if mm])
        Hp = np.mean([M.Hn(predict(q, Xe[i], ths["dyn"], "dyn")[0]) for i, q in enumerate(ev) if m[i]])
        Ht = np.mean([q["Hn"] for q, mm in zip(ev, m) if mm])
        Hr = np.mean([M.Hn(q["w"] @ q["D"]) for q, mm in zip(ev, m) if mm])
        summ[b] = {"pull_to_anchor": float(L.mean()), "sharpen_t": float(T.mean()), "spread_raw_personas": float(Hr),
                   "spread_controlled": float(Hp), "spread_true": float(Ht)}
    res["dyn_controls_by_band"] = summ
    res["share_exponent"] = float(math.exp(ths["dyn"][-1]))
    print("dynamic controls by true band (pull toward anchor, sharpening, spread raw -> controlled vs true):")
    for b, v in summ.items():
        print(f"   {b:10s} pull {v['pull_to_anchor']:.2f}  t {v['sharpen_t']:.2f}  spread {v['spread_raw_personas']:.2f} -> "
              f"{v['spread_controlled']:.2f} (true {v['spread_true']:.2f})")
    k = Xd.shape[1]
    res["coefs"] = {"pull": dict(zip(["icpt"] + FEATS, map(float, ths["dyn"][:k]))),
                    "log_t": dict(zip(["icpt"] + FEATS, map(float, ths["dyn"][k:2 * k])))}
    # one worked example per band for observability
    ex = {}
    for b in ("consensus", "divided"):
        i = next(i for i, q in enumerate(ev) if band(q) == b and q["src"] == ("pstrict" if use_evidence else "panel"))
        q = ev[i]
        p, Dp, w, (lam, t, g) = predict(q, Xe[i], ths["dyn"], "dyn")
        ex[b] = {"dataset": q["dataset"], "question": q["question"][:300], "truth": q["h"].round(3).tolist(),
                 "final": p.round(3).tolist(), "pull": lam, "t": t,
                 "personas": [{"desc": d[:160], "share_raw": float(wr), "share_used": float(wu),
                               "dist_raw": r.round(3).tolist(), "dist_used": u.round(3).tolist()}
                              for d, wr, wu, r, u in zip(q["desc"], q["w"], w, q["D"], Dp)]}
    res["examples"] = ex
    return res


def main():
    out = {"valid": run(False), "evidence": run(True)}
    (M.OUT / "persona_control_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
