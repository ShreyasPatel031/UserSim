import ast, math
import numpy as np
from scipy.optimize import minimize
from human_sim import simbench_panel_criteria as C, simbench_mass_levers as M

PANEL = "C5b_demo_mix"
BASES = ["retr6", "plain (retr6_rev2)", "same-group data (D3)", PANEL]


_CACHE = {}


def fastS(q, p):
    return 100 * (1 - 0.5 * float(np.abs(np.asarray(p) - q["h"]).sum()) / q["norm"])


def personas(q):
    if q["qid"] in _CACHE:
        return _CACHE[q["qid"]]
    segs = q["traces"][PANEL]
    segs = ast.literal_eval(segs) if isinstance(segs, str) else segs
    D = np.array([[s["dist"].get(k, 0.0) for k in q["keys"]] for s in segs], float) + 1e-6
    D /= D.sum(1, keepdims=True)
    w = np.array([s["share"] for s in segs], float)
    _CACHE[q["qid"]] = (D, w / w.sum(), [s["desc"] for s in segs])
    return _CACHE[q["qid"]]


def raw_feats(q):
    D, w, _ = personas(q)
    mix = w @ D
    P = [np.asarray(q["preds"][b] if b != PANEL else mix) for b in BASES]
    tops = {int(np.argmax(p)) for p in P}
    return np.array([M.Hn(mix), P[0].max(), float(len(tops) == 1), float(q["split"] == "Pop")])


def predict(q, th, mu, sd, detail=False):
    D, w, desc = personas(q)
    mix = w @ D
    if "_x" not in q:
        q["_x"] = np.r_[1.0, (raw_feats(q) - mu) / sd]
    x = q["_x"]
    k = len(x)
    logits = np.array([x @ th[i * k:(i + 1) * k] for i in range(len(BASES))])
    a = np.exp(logits - logits.max()); a /= a.sum()
    base = sum(ai * (np.asarray(q["preds"][b]) if b != PANEL else mix) for ai, b in zip(a, BASES))
    t = math.exp(float(np.clip(x @ th[len(BASES) * k:(len(BASES) + 1) * k], -2, 2)))
    base = np.power(base + 1e-9, t); base /= base.sum()
    Dp = np.clip(base + (D - mix), 1e-6, None)  # each persona = population level + its own demographic offset
    Dp /= Dp.sum(1, keepdims=True)
    p = w @ Dp
    if detail:
        return p, {"base_weights": dict(zip(BASES, np.round(a, 2))), "sharpen": round(t, 2),
                   "personas": [{"who": d, "share": round(float(wi), 2), "opinion": np.round(o, 3).tolist(),
                                 "offset_vs_population": np.round(o - p, 3).tolist()} for d, wi, o in zip(desc, w, Dp)]}
    return p


_, dev = C.scoreboard("dev", [PANEL])
X = np.array([raw_feats(q) for q in dev])
mu, sd = X.mean(0), X.std(0) + 1e-9
k = X.shape[1] + 1
n = (len(BASES) + 1) * k


def loss(th):
    reg = 0.05 * float(np.sum(th ** 2))
    return -np.mean([fastS(q, predict(q, th, mu, sd)) for q in dev]) + reg


best = None
for meth in ("Powell", "Powell"):
    r = minimize(loss, np.zeros(n) if best is None else best.x, method=meth, options={"maxiter": 3000})
    best = r if best is None or r.fun < best.fun else best
th = best.x
print("dev in-sample S:", round(-best.fun, 1))
res, ev = C.scoreboard("eval", [PANEL], extra={"v4: demographic offsets on dynamic population level": lambda q: predict(q, th, mu, sd)})
import json, pathlib
ex = [dict(dataset=q["dataset"], question=q["question"][:200], truth=np.round(q["h"], 3).tolist(), **{"pred": np.round(predict(q, th, mu, sd), 3).tolist()},
           **predict(q, th, mu, sd, detail=True)[1]) for q in ev[:3]]
pathlib.Path("results/simbench_ablate/panel_offsets_examples.json").write_text(json.dumps(ex, indent=1, default=float))
