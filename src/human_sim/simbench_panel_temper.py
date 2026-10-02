import ast, math, sys
import numpy as np
from scipy.optimize import minimize
from human_sim import simbench_panel_criteria as C, simbench_mass_levers as M

PANEL = sys.argv[1] if len(sys.argv) > 1 else "C5b_demo_mix"


def personas(q):
    segs = q["traces"][PANEL]
    segs = ast.literal_eval(segs) if isinstance(segs, str) else segs
    D = np.array([[s["dist"].get(k, 0.0) for k in q["keys"]] for s in segs], float) + 1e-6
    D /= D.sum(1, keepdims=True)
    w = np.array([s["share"] for s in segs], float)
    return D, w / w.sum()


def feats(q):
    D, w = personas(q)
    mix = w @ D
    pl = np.asarray(q["preds"]["plain (retr6_rev2)"])
    return np.array([1.0, M.Hn(mix), mix.max(), pl.max(), float(np.argmax(pl) == np.argmax(mix)),
                     0.0 if math.isnan(q["nbr_h"]) else q["nbr_h"], math.log(len(q["keys"])),
                     float(np.mean([M.tvd(x, mix) for x in D]))])


def pred(q, th):
    D, w = personas(q)
    t = math.exp(float(np.clip(feats(q) @ th, -2, 2)))
    Dt = np.power(D, t)
    Dt /= Dt.sum(1, keepdims=True)
    return w @ Dt


_, dev = C.scoreboard("dev", [PANEL])
X = np.array([feats(q) for q in dev])
mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0) + 1e-9
norm = lambda x: np.r_[x[0], (x[1:] - mu) / sd]  # noqa: E731
_feats = feats
feats = lambda q: norm(_feats(q))  # noqa: E731
loss = lambda th: -np.mean([M.components(q, pred(q, th))["S"] for q in dev]) + 0.05 * np.sum(th[1:] ** 2)  # noqa: E731
best = None
for meth in ("Powell", "Nelder-Mead", "Powell"):
    r = minimize(loss, np.zeros(X.shape[1]) if best is None else best.x, method=meth, options={"maxiter": 4000})
    best = r if best is None or r.fun < best.fun else best
th = best.x
print("fitted per-question sharpening coefficients:", np.round(th, 3))
C.scoreboard("eval", [PANEL], extra={"v1: demographic panel, per-persona sharpening": lambda q: pred(q, th)})
