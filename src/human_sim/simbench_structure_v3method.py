"""Routed method v3 (no model calls): factor-analysis concentration matching on the sharp side, soft routing.

Sharp = top substantive answer >= 70%. What changed vs v2:
  * Factor analysis gets a job it can do on sharp questions: it predicts HOW CONCENTRATED the answer is. A ridge model
    predicts the top-answer share from the factor-analysis profile of the neighbour questions (structure_fafeat: fitted
    top share for the target's group, share of neighbours with a >=70% top answer, between-group spread, variance on the
    first factor, ...) plus the model predictions' own spread. The sharp-side ensemble is then sharpened toward that
    predicted concentration: exponent = exp(b0 + b1 * (logit(predicted top share) - logit(ensemble top share))).
  * Soft routing: final = pi * sharp + (1 - pi) * shallow, pi = sigmoid(a * logit(P(sharp)) + b), so a misrouted sharp
    question is not fully flattened.
  * v4 persona offsets are an ensemble member (out-of-fold predictions on dev, so weights are not fitted on in-sample v4).
All parameters fitted on dev (router and concentration model cross-fitted), scored once on eval. Real answers of the
question being predicted are never used: dev answers are training labels only, eval answers only for scoring.
Ablations: no factor features in the concentration model, no concentration matching, no v4 member, hard routing."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim.simbench_structure_sharp import CACHE

FA_FEATS = ["fa_fit_top", "fa_obs_top", "fa_cons_frac", "fa_between", "fa_resid", "fa_ev1", "fa_ev3", "fa_own_rows", "fa_nb_sim"]
MEMBERS = ("plain", "retr6", "D3", "KC2", "cl", "fa", "v4", "xn")
XN_CFG = ("fa", 10, 2)
OMAX = 12


def ci(d):
    return V2.ci(d)


def logit(x):
    x = np.clip(x, 1e-4, 1 - 1e-4)
    return np.log(x / (1 - x))


class Data:
    def __init__(self, qs, members):
        n = len(qs)
        self.members = members
        self.P = np.zeros((n, len(members), OMAX))
        self.has = np.zeros((n, len(members)), bool)
        self.opt = np.zeros((n, OMAX), bool)
        self.h = np.zeros((n, OMAX))
        self.norm = np.array([q["norm"] for q in qs])
        for i, q in enumerate(qs):
            k = len(q["h"])
            self.opt[i, :k] = True
            self.h[i, :k] = q["h"]
            for j, m in enumerate(members):
                if m in q["mem"]:
                    v = np.clip(np.asarray(q["mem"][m], float), 1e-6, None)
                    self.P[i, j, :k] = v / v.sum()
                    self.has[i, j] = True


def softmax_mix(D, logits_):
    w = np.exp(logits_ - logits_.max())
    W = D.has * w[None, :]
    W = W / W.sum(1, keepdims=True)
    return np.einsum("qm,qmo->qo", W, D.P)


def temper(p, t, opt):
    r = np.where(opt, np.power(np.clip(p, 1e-9, None), t[:, None]), 0.0)
    return r / r.sum(1, keepdims=True)


def scores(D, p):
    return 100 * (1 - 0.5 * np.abs(p - D.h).sum(1) / D.norm)


class Model:
    """theta = [sharp logits (m), b0, b1, shallow logits (m), log tau, a, b]."""

    def __init__(self, m, use_conc=True, soft=True):
        self.m, self.use_conc, self.soft = m, use_conc, soft

    def unpack(self, th):
        m = self.m
        return th[:m], th[m], th[m + 1], th[m + 2:2 * m + 2], th[2 * m + 2], th[2 * m + 3], th[2 * m + 4]

    def sharp(self, D, th, chat):
        ls, b0, b1, *_ = self.unpack(th)
        e = softmax_mix(D, ls)
        z = b0 + (b1 * (logit(chat) - logit(e.max(1))) if self.use_conc else np.zeros(len(e)))
        return temper(e, np.exp(np.clip(z, -1.5, 1.5)), D.opt)

    def shallow(self, D, th):
        *_, lh, lt, _, _ = self.unpack(th)
        return temper(softmax_mix(D, lh), np.full(len(D.h), np.exp(np.clip(lt, -1, 1))), D.opt)

    def pi(self, th, psharp, cut):
        *_, a, b = self.unpack(th)
        if not self.soft:
            return (psharp >= cut).astype(float)
        return 1 / (1 + np.exp(-(a * logit(psharp) + b)))

    def predict(self, D, th, chat, psharp, cut=0.5):
        pi = self.pi(th, psharp, cut)[:, None]
        return pi * self.sharp(D, th, chat) + (1 - pi) * self.shallow(D, th)

    def init(self):
        th = np.zeros(2 * self.m + 5)
        th[self.m] = 0.2
        th[2 * self.m + 3] = 1.0
        return th


def fit_model(mod, D, chat, psharp):
    cuts = (0.3, 0.4, 0.5, 0.6) if not mod.soft else (0.5,)
    best = None
    for cut in cuts:
        def loss(th):
            return -scores(D, mod.predict(D, th, chat, psharp, cut)).mean() + 0.01 * float(np.sum(th ** 2))

        r = minimize(loss, mod.init(), method="Powell", options={"maxiter": 20000, "xtol": 1e-3, "ftol": 1e-4})
        r = minimize(loss, r.x, method="Powell", options={"maxiter": 20000, "xtol": 1e-3, "ftol": 1e-4})
        if best is None or r.fun < best[0]:
            best = (r.fun, r.x, cut)
    return best[1], best[2]


def main():
    tools = pd.read_pickle(CACHE)
    fa = pd.read_pickle(M.OUT / "structure_fafeat.pkl")
    v4 = pd.read_pickle(M.OUT / "v4_crossfit_preds.pkl")
    dev, ev = V2.load("dev", tools), V2.load("eval", tools)
    xn = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")[XN_CFG]
    for q in dev + ev:
        if q["qid"] in v4:
            q["mem"]["v4"] = np.asarray(v4[q["qid"]])
        if xn.get(q["qid"]) is not None:
            q["mem"]["xn"] = np.asarray(xn[q["qid"]])
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    ds = sorted(l1.dataset.unique())
    means = l1[V2.NUM].mean()
    fa_mean = pd.DataFrame([v for v in fa.values() if v]).mean()

    def feats(q, use_fa=True, use_pred=True):
        r = l1.loc[q["qid"]]
        x = [r[c] if pd.notna(r[c]) else means[c] for c in V2.NUM] + [float(r.dataset == k) for k in ds] + [float(r.topic == k) for k in range(20)]
        if use_pred:
            x += list(V2.pred_features(q).values()) + [float("v4" in q["mem"]), q["mem"]["v4"].max() if "v4" in q["mem"] else q["mem"]["plain"].max()]
        if use_fa:
            f = fa.get(q["qid"])
            x += [(f or {}).get(k, fa_mean[k]) for k in FA_FEATS] + [float(f is not None)]
            m = q["mem"]
            hx = "xn" in m
            x += [float(hx), m["xn"].max() if hx else m["plain"].max(), float(np.argmax(m["xn"]) == np.argmax(m["plain"])) if hx else 1.0,
                  M.tvd(m["xn"], m["plain"]) if hx else 0.0]
        return x

    y_sharp_dev = np.array([q["top_share"] >= 0.7 for q in dev], int)
    y_sharp_ev = np.array([q["top_share"] >= 0.7 for q in ev], int)
    top_dev = np.array([q["h"].max() for q in dev])
    top_ev = np.array([q["h"].max() for q in ev])

    def crossfit(make, Xd, Xe, y, strat=False):
        Xd, Xe = np.array(Xd, float), np.array(Xe, float)
        sc = StandardScaler().fit(Xd)
        full = make().fit(sc.transform(Xd), y)
        cv = np.zeros(len(Xd))
        split = StratifiedKFold(5, shuffle=True, random_state=0).split(Xd, y) if strat else KFold(5, shuffle=True, random_state=0).split(Xd)
        for tr, te in split:
            s2 = StandardScaler().fit(Xd[tr])
            mdl = make().fit(s2.transform(Xd[tr]), y[tr])
            cv[te] = mdl.predict_proba(s2.transform(Xd[te]))[:, 1] if strat else mdl.predict(s2.transform(Xd[te]))
        pe = full.predict_proba(sc.transform(Xe))[:, 1] if strat else full.predict(sc.transform(Xe))
        return cv, pe

    # router: same features as v2's new router + factor profile
    rd, re_ = crossfit(lambda: LogisticRegression(C=0.3, max_iter=5000), [feats(q) for q in dev], [feats(q) for q in ev], y_sharp_dev, strat=True)
    from sklearn.metrics import roc_auc_score
    print(f"router AUC (sharp >= 70%): dev cross-fitted {roc_auc_score(y_sharp_dev, rd):.3f}, eval {roc_auc_score(y_sharp_ev, re_):.3f}")

    # concentration model, with and without the factor-analysis profile
    conc = {}
    for nm, kw in (("with factor profile", {}), ("without factor profile", {"use_fa": False}), ("factor profile only", {"use_pred": False})):
        cd, ce = crossfit(lambda: Ridge(alpha=3.0), [feats(q, **kw) for q in dev], [feats(q, **kw) for q in ev], logit(top_dev))
        cd, ce = 1 / (1 + np.exp(-cd)), 1 / (1 + np.exp(-ce))
        conc[nm] = (cd, ce)
        sh = y_sharp_ev == 1
        print(f"concentration model {nm:24s}: eval MAE on top share {np.abs(ce - top_ev).mean():.3f} (sharp qs {np.abs(ce - top_ev)[sh].mean():.3f}); "
              f"corr {np.corrcoef(ce, top_ev)[0, 1]:.3f}")
    ens_ev = np.array([np.mean([q['mem'][k] for k in ('plain', 'retr6', 'D3') if k in q['mem']], axis=0).max() for q in ev])
    print(f"baseline (ensemble's own top share): eval MAE {np.abs(ens_ev - top_ev).mean():.3f}; corr {np.corrcoef(ens_ev, top_ev)[0, 1]:.3f}")

    base = tuple(m for m in MEMBERS if m != "v4")
    variants = {"v3 (cross-national factor completion + soft routing, no v4 inside)": (base, "with factor profile", False, True),
                "ablation: no cross-national factor completion member": (tuple(m for m in base if m != "xn"), "with factor profile", False, True),
                "ablation: no factor-analysis neighbour tool as member": (tuple(m for m in base if m != "fa"), "with factor profile", False, True),
                "ablation: no clustering tool as member": (tuple(m for m in base if m != "cl"), "with factor profile", False, True),
                "ablation: hard routing": (base, "with factor profile", False, False),
                "addition: + factor concentration matching": (base, "with factor profile", True, True),
                "addition: + v4 member": (MEMBERS, "with factor profile", False, True)}
    plain_ev = np.array([V2.S(q, q["mem"]["plain"]) for q in ev])
    res, preds_out = {}, {}
    for nm, (mem, cname, use_conc, soft) in variants.items():
        Dd, De = Data(dev, mem), Data(ev, mem)
        mod = Model(len(mem), use_conc, soft)
        th, cut = fit_model(mod, Dd, conc[cname][0], rd)
        pe = mod.predict(De, th, conc[cname][1], re_, cut)
        s = scores(De, pe)
        d = s - plain_ev
        ls, b0, b1, lh, lt, a, b = mod.unpack(th)
        wsh = np.exp(ls - ls.max()); wsh /= wsh.sum()
        whl = np.exp(lh - lh.max()); whl /= whl.sum()
        cfg = {"sharp_weights": dict(zip(mem, wsh.round(2))), "sharpen_b0": round(float(b0), 3), "conc_b1": round(float(b1), 3),
               "shallow_weights": dict(zip(mem, whl.round(2))), "shallow_tau": round(float(np.exp(np.clip(lt, -1, 1))), 3),
               "route_a": round(float(a), 3), "route_b": round(float(b), 3), "hard_cut": cut if not soft else None}
        ts = y_sharp_ev == 1
        res[nm] = {"config": cfg, "eval_S": float(s.mean()), "vs_plain": float(d.mean()), "ci": ci(d),
                   "truly_sharp_S": float(s[ts].mean()), "truly_shallow_S": float(s[~ts].mean())}
        print(f"\n== {nm}\n   config: {cfg}\n   eval N {len(ev)}: plain {plain_ev.mean():.1f} -> {s.mean():.1f} ({d.mean():+.1f} {ci(d)}); "
              f"truly sharp {s[ts].mean():.1f}, truly shallow {s[~ts].mean():.1f}", flush=True)
        if nm.startswith("v3"):
            for q, p in zip(ev, pe):
                preds_out[q["qid"]] = p[:len(q["h"])]
    pd.to_pickle(preds_out, M.OUT / "structure_v3_eval_preds.pkl")
    (M.OUT / "structure_v3_report.json").write_text(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
