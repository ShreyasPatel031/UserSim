"""Routed method v2 (no model calls): better router, sharp side = sharpened ensemble gated by the factor-analysis tool,
shallow side = weighted ensemble with the clustering tool. Everything fitted on dev, scored once on eval.

Sharp = top substantive answer >= 70%. Router features: question metadata + retr6 demos (as before) plus the existing
predictions' spread and whether retr6_rev2 / retr6 / D3 / the two tools agree on the top answer (all pre-answer).
Ablations: no component gate, no clustering tool, old router."""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_structure_sharp import CACHE
from human_sim.simbench_structure_sharpdef import sub_shares

H = M.HAIKU
ARMS = {"plain": "retr6_rev2", "retr6": "retr6", "D3": "D3_same_group_same_topic", "KC2": "KC2_rev2"}
NUM = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]
SHARP_MEMBERS = ("plain", "retr6", "D3", "KC2")
SHALLOW_MEMBERS = ("plain", "retr6", "D3", "KC2", "cl")
T_SHARP = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5)
GATE = (0.0, 0.25, 0.5)
T_SHALLOW = (0.8, 0.9, 1.0, 1.1, 1.25)
CUTS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7)


def ci(d):
    d = np.asarray(d, float)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def temper(p, t):
    r = np.power(np.clip(p, 1e-9, None), t)
    return r / r.sum()


def simplex(n, step=0.25):
    k = int(round(1 / step))
    return [np.array(c, float) / k for c in itertools.product(range(k + 1), repeat=n) if sum(c) == k]


def load(which, tools):
    M.EVAL_ARMS = M.DEV_ARMS = {k: (v, H) for k, v in ARMS.items()}
    out = []
    for q in M.load(which):
        if q["dataset"] not in A.D_DATASETS or "plain" not in q["preds"] or "retr6" not in q["preds"]:
            continue
        mem = {k: np.asarray(q["preds"][k]) for k in ARMS if k in q["preds"]}
        for name, cfg in (("cl", ("dmm", 10, 3)), ("fa", ("fa", 10, 3))):
            x = tools[cfg].get(q["qid"])
            if x is not None:
                mem[name] = np.asarray(x)
        q["mem"] = mem
        q["top_share"] = sub_shares(q["keys"], q["roles"], q["h"])[0]
        out.append(q)
    return out


def pred_features(q):
    m = q["mem"]
    p = m["plain"]
    f = {"h_plain": M.Hn(p), "max_plain": p.max(), "h_retr6": M.Hn(m["retr6"]), "tvd_plain_retr6": M.tvd(p, m["retr6"]),
         "agree_retr6": float(np.argmax(p) == np.argmax(m["retr6"]))}
    for k in ("D3", "KC2", "cl", "fa"):
        has = k in m
        f[f"has_{k}"] = float(has)
        f[f"h_{k}"] = M.Hn(m[k]) if has else M.Hn(p)
        f[f"agree_{k}"] = float(np.argmax(p) == np.argmax(m[k])) if has else 1.0
        f[f"tvd_{k}"] = M.tvd(p, m[k]) if has else 0.0
    ens = np.mean([m[k] for k in ("plain", "retr6", "D3") if k in m], axis=0)
    f["h_ens"], f["max_ens"] = M.Hn(ens), ens.max()
    return f


def mix(q, members, w):
    use = [(wi, q["mem"][k]) for k, wi in zip(members, w) if wi > 0 and k in q["mem"]]
    if not use:
        return q["mem"]["plain"]
    tot = sum(wi for wi, _ in use)
    return sum(wi * v for wi, v in use) / tot


def sharp_pred(q, w, t, g):
    e = mix(q, SHARP_MEMBERS, w)
    agree = "fa" in q["mem"] and np.argmax(q["mem"]["fa"]) == np.argmax(e)
    return temper(e, t + (g if agree else 0.0))


def shallow_pred(q, w, t):
    return temper(mix(q, SHALLOW_MEMBERS, w), t)


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def main():
    tools = pd.read_pickle(CACHE)
    dev, ev = load("dev", tools), load("eval", tools)
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    ds = sorted(l1.dataset.unique())
    means = l1[NUM].mean()

    def X(qs, with_preds=True):
        rows = []
        for q in qs:
            r = l1.loc[q["qid"]]
            base = [r[c] if pd.notna(r[c]) else means[c] for c in NUM] + [float(r.dataset == k) for k in ds] + [float(r.topic == k) for k in range(20)]
            rows.append(base + (list(pred_features(q).values()) if with_preds else []))
        return np.array(rows, float)

    y_dev = np.array([q["top_share"] >= 0.7 for q in dev], int)
    y_ev = np.array([q["top_share"] >= 0.7 for q in ev], int)

    def router(with_preds):
        Xd, Xe = X(dev, with_preds), X(ev, with_preds)
        sc = StandardScaler().fit(Xd)
        clf = LogisticRegression(C=0.3, max_iter=5000).fit(sc.transform(Xd), y_dev)
        cross = np.zeros(len(dev))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(Xd, y_dev):
            s2 = StandardScaler().fit(Xd[tr])
            cross[te] = LogisticRegression(C=0.3, max_iter=5000).fit(s2.transform(Xd[tr]), y_dev[tr]).predict_proba(s2.transform(Xd[te]))[:, 1]
        return cross, clf.predict_proba(sc.transform(Xe))[:, 1]

    routers = {"new router (+ prediction features)": router(True), "old router (metadata + demos only)": router(False)}
    for nm, (cd, pe) in routers.items():
        print(f"{nm}: eval AUC for sharp (>=70%) {roc_auc_score(y_ev, pe):.3f}; dev cross-fitted AUC {roc_auc_score(y_dev, cd):.3f}")

    sharp_cfgs = [(w, t, g) for w in simplex(len(SHARP_MEMBERS)) for t in T_SHARP for g in GATE]
    shallow_cfgs = [(w, t) for w in simplex(len(SHALLOW_MEMBERS)) for t in T_SHALLOW]

    def score_matrix(qs):
        A_ = np.array([[S(q, sharp_pred(q, *c)) for c in sharp_cfgs] for q in qs])
        B_ = np.array([[S(q, shallow_pred(q, *c)) for c in shallow_cfgs] for q in qs])
        return A_, B_

    Ad, Bd = score_matrix(dev)
    Ae, Be = score_matrix(ev)

    def fit(p_dev, sharp_mask=None, shallow_mask=None):
        """Jointly pick the router cut and each side's config on dev (cross-fitted router probabilities)."""
        sm = np.ones(len(sharp_cfgs), bool) if sharp_mask is None else sharp_mask
        hm = np.ones(len(shallow_cfgs), bool) if shallow_mask is None else shallow_mask
        best = None
        for cut in CUTS:
            sh = p_dev >= cut
            a = Ad[sh].sum(0) if sh.any() else np.zeros(len(sharp_cfgs))
            b = Bd[~sh].sum(0) if (~sh).any() else np.zeros(len(shallow_cfgs))
            ia = int(np.argmax(np.where(sm, a, -np.inf)))
            ib = int(np.argmax(np.where(hm, b, -np.inf)))
            tot = a[ia] + b[ib]
            if best is None or tot > best[0]:
                best = (tot, cut, ia, ib)
        return best[1:]

    def apply(p_ev, cut, ia, ib):
        sh = p_ev >= cut
        return np.where(sh, Ae[:, ia], Be[:, ib]), sh

    no_gate = np.array([c[2] == 0.0 for c in sharp_cfgs])
    no_cl = np.array([c[0][SHALLOW_MEMBERS.index("cl")] == 0 for c in shallow_cfgs])
    variants = {"v2 (new router, gated sharp side, clustering in shallow side)": ("new router (+ prediction features)", None, None),
                "ablation: no component gate on sharp side": ("new router (+ prediction features)", no_gate, None),
                "ablation: no clustering tool in shallow side": ("new router (+ prediction features)", None, no_cl),
                "ablation: old router": ("old router (metadata + demos only)", None, None)}
    plain_ev = np.array([S(q, q["mem"]["plain"]) for q in ev])
    res = {}
    preds_out = {}
    for nm, (rk, sm, hm) in variants.items():
        cd, pe = routers[rk]
        cut, ia, ib = fit(cd, sm, hm)
        s, sh = apply(pe, cut, ia, ib)
        d = s - plain_ev
        wa, ta, ga = sharp_cfgs[ia]
        wb, tb = shallow_cfgs[ib]
        cfg = {"cut": cut, "sharp_weights": dict(zip(SHARP_MEMBERS, wa.round(2))), "sharp_exponent": ta, "component_gate_boost": ga,
               "shallow_weights": dict(zip(SHALLOW_MEMBERS, wb.round(2))), "shallow_exponent": tb}
        acc_sharp = float(sh[y_ev == 1].mean())
        acc_shallow = float((~sh)[y_ev == 0].mean())
        res[nm] = {"config": cfg, "eval_S": float(s.mean()), "vs_plain": float(d.mean()), "ci": ci(d),
                   "routing_truly_sharp_to_sharp": acc_sharp, "routing_truly_shallow_to_shallow": acc_shallow}
        print(f"\n== {nm}\n   config: {cfg}\n   eval N {len(ev)}: plain {plain_ev.mean():.1f} -> {s.mean():.1f} ({d.mean():+.1f} {ci(d)}); "
              f"routing: truly sharp -> sharp {acc_sharp:.0%}, truly shallow -> shallow {acc_shallow:.0%}")
        if nm.startswith("v2"):
            for q, (i, flag) in zip(ev, enumerate(sh)):
                preds_out[q["qid"]] = sharp_pred(q, wa, ta, ga) if flag else shallow_pred(q, wb, tb)
    pd.to_pickle(preds_out, M.OUT / "structure_v2_eval_preds.pkl")
    (M.OUT / "structure_v2_report.json").write_text(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
