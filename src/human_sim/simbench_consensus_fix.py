"""Post-processing fixes for over-spread answers, on top of persona spread control. Fit on dev, score on eval.

1 calib : isotonic map  predicted top prob -> real share of that option; set top to it, rescale the rest
2 gate  : the same, with separate curves when the sources agree / disagree on the top answer
3 evid  : ridge regression predicts the real share of our top option from evidence + agreement signals
4 shape : like 3, but extra mass for the top comes from tail options first, keeping runner-up / ordinal neighbors"""

from __future__ import annotations

import json

import numpy as np
from sklearn.isotonic import IsotonicRegression

from human_sim import simbench_mass_levers as M
from human_sim import simbench_persona_control as P


def _neighbors(q, top):
    parts = M._ord_parts(q["roles"], q["keys"])
    if not parts:
        return set()
    idx = list(parts[0])
    if top not in idx:
        return set()
    j = idx.index(top)
    return {idx[k] for k in (j - 1, j + 1) if 0 <= k < len(idx)}


def set_top(p, target, keep=None):
    """Return p with p[top] = target. Others rescaled proportionally, or (keep given) drained tail-first."""
    p = np.asarray(p, float)
    top = int(np.argmax(p))
    target = float(np.clip(target, 1e-3, 0.999))
    rest = np.delete(np.arange(len(p)), top)
    out = p.copy()
    out[top] = target
    need = target - p[top]
    if keep is None or need <= 0:
        out[rest] = p[rest] * (1 - target) / max(p[rest].sum(), 1e-9)
        return out
    protected = [i for i in rest if i in keep]
    tail = [i for i in rest if i not in keep]
    take_tail = min(need, p[tail].sum()) if tail else 0.0
    if tail:
        out[tail] = p[tail] * (1 - take_tail / max(p[tail].sum(), 1e-9))
    left = need - take_tail
    if left > 1e-12 and protected:
        out[protected] = p[protected] * (1 - left / max(p[protected].sum(), 1e-9))
    out = np.clip(out, 0, None)
    return out / out.sum()


def signals(q, p):
    top = int(np.argmax(p))
    mix = q["w"] @ q["D"]
    tops = {int(np.argmax(q["anchor"])), int(np.argmax(q["pl"])), int(np.argmax(mix)), top}
    return {
        "p_top": p[top], "agree": float(len(tops) == 1), "n_tops": float(len(tops)),
        "anchor_top": float(q["anchor"][top]), "anchor_max": float(q["anchor"].max()),
        "plain_top": float(q["pl"][top]), "mix_top": float(mix[top]), "persona_top_votes": float(q["w"][np.argmax(q["D"], 1) == top].sum()),
        "h_anchor": M.Hn(q["anchor"]), "nbr_h": q["x"]["nbr_h"], "nbr_missing": q["x"]["nbr_missing"],
        "has_evidence": q["x"]["has_evidence"], "log_k": q["x"]["log_k"], "ordinal": q["x"]["ordinal"], "binary": q["x"]["binary"],
        "task": q["x"]["task"],
    }


def run(use_evidence):
    dev, ev = P.prep("dev", use_evidence), P.prep("eval", use_evidence)
    Xd, mu, sd = P.design(dev)
    Xe, _, _ = P.design(ev, mu, sd)
    th = P.fit(dev, Xd, "dyn")
    pd_ = [P.predict(q, Xd[i], th, "dyn")[0] for i, q in enumerate(dev)]
    pe = [P.predict(q, Xe[i], th, "dyn")[0] for i, q in enumerate(ev)]
    sig_d, sig_e = [signals(q, p) for q, p in zip(dev, pd_)], [signals(q, p) for q, p in zip(ev, pe)]
    y = np.array([q["h"][int(np.argmax(p))] for q, p in zip(dev, pd_)])  # real share of OUR top option

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit([s["p_top"] for s in sig_d], y)
    gate = {}
    for a in (0.0, 1.0):
        m = np.array([s["agree"] == a for s in sig_d])
        gate[a] = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(np.array([s["p_top"] for s in sig_d])[m], y[m])
    feats = list(sig_d[0])
    F = lambda ss: np.array([[s[f] for f in feats] for s in ss])  # noqa: E731
    Fd, Fe = F(sig_d), F(sig_e)
    fm, fs = Fd.mean(0), Fd.std(0) + 1e-9
    Zd, Ze = np.c_[np.ones(len(Fd)), (Fd - fm) / fs], np.c_[np.ones(len(Fe)), (Fe - fm) / fs]
    beta = np.linalg.solve(Zd.T @ Zd + 3.0 * np.eye(Zd.shape[1]), Zd.T @ y)
    yhat_e = Ze @ beta
    r2 = lambda yh, yt: 1 - np.mean((yh - yt) ** 2) / np.var(yt)  # noqa: E731
    y_e = np.array([q["h"][int(np.argmax(p))] for q, p in zip(ev, pe)])

    def keep(q, p):
        top = int(np.argmax(p))
        runner = int(np.argsort(-p)[1]) if len(p) > 1 else top
        return {runner} | _neighbors(q, top)

    fixes = {
        "baseline (personas + per-question control)": lambda i, q, p: p,
        "1 calibration": lambda i, q, p: set_top(p, iso.predict([sig_e[i]["p_top"]])[0]),
        "2 calibration + top-answer gate": lambda i, q, p: set_top(p, gate[sig_e[i]["agree"]].predict([sig_e[i]["p_top"]])[0]),
        "3 agreement predicted from evidence": lambda i, q, p: set_top(p, yhat_e[i]),
        "4 = 3 + shape-aware sharpening": lambda i, q, p: set_top(p, yhat_e[i], keep(q, p)),
    }
    S = P.S
    base = np.array([S(q, p) for q, p in zip(ev, pe)])
    out = {"N_eval": len(ev), "top_share_R2": {"p_top as is": r2(np.array([s["p_top"] for s in sig_e]), y_e),
                                              "calibration": r2(iso.predict([s["p_top"] for s in sig_e]), y_e),
                                              "evidence regression": r2(yhat_e, y_e)},
           "agree_rate": float(np.mean([s["agree"] for s in sig_e])),
           "top_right_when_agree": float(np.mean([np.argmax(p) == np.argmax(q["h"]) for q, p, s in zip(ev, pe, sig_e) if s["agree"]])),
           "top_right_when_disagree": float(np.mean([np.argmax(p) == np.argmax(q["h"]) for q, p, s in zip(ev, pe, sig_e) if not s["agree"]])),
           "coef": dict(zip(["icpt"] + feats, map(float, beta))), "fixes": {}}
    tag = "WITH no-overlap evidence" if use_evidence else "BENCHMARK-VALID (no evidence)"
    print(f"\n==== {tag}: eval {len(ev)}")
    print(f"sources agree on top answer for {out['agree_rate']:.0%} of questions; top right {out['top_right_when_agree']:.0%} when they agree, "
          f"{out['top_right_when_disagree']:.0%} when they don't")
    print("how well we predict the real share of our top answer (R2):", {k: round(v, 2) for k, v in out["top_share_R2"].items()})
    print(f"{'fix':46s}{'S':>6s}{'vs baseline':>19s}   consensus / mixed / divided   spread on consensus (true {np.mean([q['Hn'] for q in ev if P.band(q)=='consensus']):.2f})")
    for nm, f in fixes.items():
        ps = [f(i, q, p) for i, (q, p) in enumerate(zip(ev, pe))]
        s = np.array([S(q, p) for q, p in zip(ev, ps)])
        d = s - base
        bands = {b: float(d[[P.band(q) == b for q in ev]].mean()) for b in ("consensus", "mixed", "divided")}
        hc = float(np.mean([M.Hn(p) for q, p in zip(ev, ps) if P.band(q) == "consensus"]))
        out["fixes"][nm] = {"S": float(s.mean()), "vs_base": float(d.mean()), "ci": P.ci(d), "by_band": bands, "spread_consensus": hc}
        print(f"{nm:46s}{s.mean():6.1f}{d.mean():+7.2f} {str(P.ci(d)):>11s}   " + " / ".join(f"{v:+.1f}" for v in bands.values()) + f"   {hc:.2f}")
    return out


def main():
    out = {"valid": run(False), "evidence": run(True)}
    (M.OUT / "consensus_fix_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
