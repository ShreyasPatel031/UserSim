"""Offline: set spread and the plain/persona mix per question from truth-free signals. Fit on dev, score on eval."""

from __future__ import annotations

import ast
import json
import math

import numpy as np
from scipy.optimize import minimize

from human_sim import simbench_mass_levers as M

ARMS = {"plain": ("retr6_rev2", M.HAIKU), "panel": ("P_groundall5", M.HAIKU)}
FEATS = ["h_plain", "h_panel", "maxp_plain", "plain_panel_tvd", "persona_spread", "top_share",
         "nbr_h", "nbr_missing", "log_k", "ordinal", "binary", "task", "other_pop"]
EPS = 1e-6


def _personas(q):
    segs = q["traces"]["panel"]
    segs = ast.literal_eval(segs) if isinstance(segs, str) else segs
    D = np.array([[s["dist"].get(k, 0.0) for k in q["keys"]] for s in segs], float) + EPS
    D /= D.sum(1, keepdims=True)
    w = np.array([s["share"] for s in segs], float)
    return D, w / w.sum()


def prep(which):
    M.EVAL_ARMS = ARMS
    M.DEV_ARMS = ARMS
    qs = [q for q in M.load(which) if all(a in q["preds"] for a in ARMS) and "panel" in q.get("traces", {})]
    for q in qs:
        D, w = _personas(q)
        pl = np.asarray(q["preds"]["plain"], float) + EPS
        pl /= pl.sum()
        mix = w @ D
        q["D"], q["w"], q["pl"] = D, w, pl
        q["x"] = {
            "h_plain": M.Hn(pl), "h_panel": M.Hn(mix), "maxp_plain": pl.max(),
            "plain_panel_tvd": M.tvd(pl, mix), "persona_spread": float(w @ np.abs(D - mix).sum(1) / 2),
            "top_share": w.max(), "nbr_h": 0.0 if math.isnan(q["nbr_h"]) else q["nbr_h"],
            "nbr_missing": float(math.isnan(q["nbr_h"])), "log_k": math.log(len(q["keys"])),
            "ordinal": float(q["format"] == "ordinal"), "binary": float(q["format"] == "binary"),
            "task": float(q["group3"] == "pop_only_task"), "other_pop": float(q["group3"] == "other_pop_only"),
        }
    return qs


def design(qs, mu=None, sd=None):
    X = np.array([[q["x"][f] for f in FEATS] for q in qs])
    if mu is None:
        mu, sd = X.mean(0), X.std(0) + 1e-9
    return np.c_[np.ones(len(X)), (X - mu) / sd], mu, sd


def temper(p, t):
    r = np.power(p, t)
    return r / r.sum()


def predict(q, xrow, theta, mode):
    """theta layout by mode; alpha = weight on persona mixture, t = sharpening exponent, g = share exponent."""
    k = len(xrow)
    if mode == "global":
        a, lt, g = 1 / (1 + math.exp(-theta[0])), theta[1], theta[2]
    elif mode == "t_dyn":
        a, lt, g = 1 / (1 + math.exp(-theta[0])), float(xrow @ theta[1:1 + k]), theta[1 + k]
    else:  # full: alpha and t both dynamic
        a = 1 / (1 + math.exp(-float(xrow @ theta[:k])))
        lt, g = float(xrow @ theta[k:2 * k]), theta[2 * k]
    w = np.power(q["w"], math.exp(g))
    mix = (w / w.sum()) @ q["D"]
    return temper(a * mix + (1 - a) * q["pl"], math.exp(np.clip(lt, -3, 3))), a, math.exp(lt)


def score(qs, X, theta, mode):
    return np.array([100 * (1 - M.tvd(predict(q, X[i], theta, mode)[0], q["h"]) / q["norm"]) for i, q in enumerate(qs)])


def fit(qs, X, mode, lam):
    k = X.shape[1]
    n = {"global": 3, "t_dyn": k + 2, "full": 2 * k + 1}[mode]
    th0 = np.zeros(n)

    def loss(th):
        reg = lam * float(np.sum(th[1:] ** 2)) if mode != "global" else 0.0
        return -score(qs, X, th, mode).mean() + reg

    best = None
    for meth in ("Powell", "Nelder-Mead"):
        r = minimize(loss, th0 if best is None else best.x, method=meth, options={"maxiter": 4000, "xtol": 1e-3, "ftol": 1e-3})
        best = r if best is None or r.fun < best.fun else best
    return best.x


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def band(q):
    return "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided")


def main():
    dev, ev = prep("dev"), prep("eval")
    Xd, mu, sd = design(dev)
    Xe, _, _ = design(ev, mu, sd)
    S = lambda q, p: 100 * (1 - M.tvd(p, q["h"]) / q["norm"])  # noqa: E731
    base = {"plain": np.array([S(q, q["pl"]) for q in ev]),
            "panel": np.array([S(q, q["w"] @ q["D"]) for q in ev]),
            "blend50": np.array([S(q, (q["w"] @ q["D"] + q["pl"]) / 2) for q in ev])}
    out = {"N_dev": len(dev), "N_eval": len(ev), "arms": {}}
    cand = {k: v for k, v in base.items()}

    # spread target: how well can truth-free signals predict real spread?
    yd, ye = np.array([q["Hn"] for q in dev]), np.array([q["Hn"] for q in ev])
    beta = np.linalg.solve(Xd.T @ Xd + 1.0 * np.eye(Xd.shape[1]), Xd.T @ yd)
    r2 = 1 - np.mean((Xe @ beta - ye) ** 2) / np.var(ye)
    r2_plain = 1 - np.mean((np.array([q["x"]["h_plain"] for q in ev]) - ye) ** 2) / np.var(ye)
    out["spread_model"] = {"eval_R2": float(r2), "R2_using_plain_entropy_as_is": float(r2_plain),
                           "coef_std": dict(zip(["intercept"] + FEATS, map(float, beta)))}
    print(f"Real-spread prediction on eval: R2 {r2:.2f} (plain harness entropy as-is: {r2_plain:.2f})")
    print("  standardized coefs:", {f: round(float(b), 3) for f, b in zip(["icpt"] + FEATS, beta)})

    # target-spread variant: blend, then temper until entropy equals predicted spread
    def to_target(p, h):
        lo, hi = 0.05, 20.0
        for _ in range(40):
            t = (lo * hi) ** 0.5
            lo, hi = (t, hi) if M.Hn(temper(p, t)) > h else (lo, t)
        return temper(p, (lo * hi) ** 0.5)
    hp = np.clip(Xe @ beta, 0.02, 0.999)
    for nm, src in {"plain→pred spread": lambda q: q["pl"], "blend50→pred spread": lambda q: (q["w"] @ q["D"] + q["pl"]) / 2}.items():
        cand[nm] = np.array([S(q, to_target(src(q), hp[i])) for i, q in enumerate(ev)])

    fitted = {}
    for mode, lam in [("global", 0), ("t_dyn", 0.02), ("full", 0.02)]:
        th = fit(dev, Xd, mode, lam)
        fitted[mode] = th
        cand[f"learned {mode}"] = score(ev, Xe, th, mode)
        cand[f"learned {mode} (dev, in-sample)"] = score(dev, Xd, th, mode)

    print(f"\n{'arm':34s} {'S':>6s} {'vs plain':>16s} {'vs blend50':>16s}   consensus / mixed / divided")
    for nm, s in cand.items():
        if "in-sample" in nm:
            print(f"{nm:34s} {s.mean():6.1f}")
            out["arms"][nm] = {"S": float(s.mean())}
            continue
        d1, d2 = s - base["plain"], s - base["blend50"]
        bands = {b: float((s - base["plain"])[[band(q) == b for q in ev]].mean()) for b in ("consensus", "mixed", "divided")}
        out["arms"][nm] = {"S": float(s.mean()), "vs_plain": float(d1.mean()), "ci_plain": ci(d1),
                           "vs_blend50": float(d2.mean()), "ci_blend50": ci(d2), "by_band_vs_plain": bands}
        print(f"{nm:34s} {s.mean():6.1f} {d1.mean():+5.1f} {str(ci(d1)):>10s} {d2.mean():+5.1f} {str(ci(d2)):>10s}   "
              + " / ".join(f"{v:+.1f}" for v in bands.values()))

    th = fitted["global"]
    out["global_params"] = {"alpha_persona": float(1 / (1 + math.exp(-th[0]))), "t": float(math.exp(th[1])),
                            "share_exponent": float(math.exp(th[2]))}
    print("\nglobal fit:", {k: round(v, 3) for k, v in out["global_params"].items()})
    for mode in ("t_dyn", "full"):
        th = fitted[mode]
        al, ts = zip(*[predict(q, Xe[i], th, mode)[1:] for i, q in enumerate(ev)])
        al, ts = np.array(al), np.array(ts)
        summ = {b: {"alpha": float(al[m].mean()), "t": float(ts[m].mean())}
                for b in ("consensus", "mixed", "divided") for m in [np.array([band(q) == b for q in ev])]}
        out[f"{mode}_by_band"] = summ
        print(f"{mode}: mean persona weight / sharpening by true band:",
              {b: (round(v['alpha'], 2), round(v['t'], 2)) for b, v in summ.items()})
    k = Xd.shape[1]
    out["full_coefs"] = {"alpha": dict(zip(["icpt"] + FEATS, map(float, fitted["full"][:k]))),
                         "log_t": dict(zip(["icpt"] + FEATS, map(float, fitted["full"][k:2 * k])))}
    (M.OUT / "dynamic_mix_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
