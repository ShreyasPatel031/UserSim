"""v3-lite and the full benchmark (no model calls).

v3-lite = v3 restricted to members that exist on the full benchmark without new model calls: retr6_rev2 ("plain"), the
factor-analysis and clustering tools on similar questions, cross-national factor completion ("xn") and cross-national
opinion segments ("xs"). Specialised as v3: sharp side = factor tools only, shallow side = clustering tools only,
soft routing by a dev-trained P(sharp >= 70%). Everything fitted on dev.

  python -m human_sim.simbench_structure_v3full eval   # fit on dev, score on eval (writes structure_v3lite_eval_preds.pkl)
  python -m human_sim.simbench_structure_v3full full   # compute members for all full-benchmark shared-survey questions, score

On the full benchmark the statistical tools use every Grouped training row (as the earlier full run did); the target
question's column never contains the target's own country (xn/xs) and the similar-question tools never contain the
target question at all. Questions outside the 5 shared surveys keep the retr6_rev2 answer."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_v2method as V2
from human_sim import simbench_structure_v3method as V3
from human_sim import simbench_structure_xnat as XN
from human_sim.simbench_structure_sharp import CACHE, ci
from human_sim.simbench_structure_sharpdef import sub_shares

LITE = ("plain", "D3", "cl", "fa", "xn", "xs") if "--d3" in sys.argv else ("plain", "cl", "fa", "xn", "xs")
TAG = "v3d3" if "--d3" in sys.argv else "v3lite"
if "--c5b" in sys.argv:  # demographic persona panel (observable segments) as a shallow-side member
    LITE, TAG = LITE + ("c5b",), TAG + "c5b"
TOOLS = {"cl": ("dmm", 10, 3), "fa": ("fa", 10, 3)}
FULL_CACHE = M.OUT / "structure_v3full_members.pkl"
NUM = V2.NUM


def lite_feats(m):
    p = m["plain"]
    f = [M.Hn(p), p.max()]
    for k in [x for x in LITE if x != "plain"]:
        has = k in m
        f += [float(has), M.Hn(m[k]) if has else M.Hn(p), m[k].max() if has else p.max(),
              float(np.argmax(p) == np.argmax(m[k])) if has else 1.0, M.tvd(p, m[k]) if has else 0.0]
    return f


def design(meta, ds, means):
    """meta rows: dict with NUM, dataset, topic."""
    return [[meta[c] if pd.notna(meta[c]) else means[c] for c in NUM] + [float(meta["dataset"] == k) for k in ds]
            + [float(meta["topic"] == k) for k in range(20)]]


def fit_on_dev():
    tools = pd.read_pickle(CACHE)
    xall = pd.read_pickle(XN.OUT)
    dev, ev = V2.load("dev", tools), V2.load("eval", tools)
    if "c5b" in LITE:
        M.EVAL_ARMS = M.DEV_ARMS = {"c5b": ("C5b_demo_mix", M.HAIKU)}
        c5 = {q["qid"]: q["preds"]["c5b"] for w in ("dev", "eval") for q in M.load(w) if "c5b" in q["preds"]}
        for q in dev + ev:
            if q["qid"] in c5:
                q["mem"]["c5b"] = np.asarray(c5[q["qid"]])
    for q in dev + ev:
        for k, cfg in (("xn", V3.XN_CFG), ("xs", V3.XS_CFG)):
            if xall[cfg].get(q["qid"]) is not None:
                q["mem"][k] = np.asarray(xall[cfg][q["qid"]])
        q["mem"] = {k: v for k, v in q["mem"].items() if k in LITE}
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    ds = sorted(l1.dataset.unique())
    means = l1[NUM].mean()
    X = lambda qs: np.array([design(l1.loc[q["qid"]], ds, means)[0] + lite_feats(q["mem"]) for q in qs], float)  # noqa: E731
    Xd, Xe = X(dev), X(ev)
    yd = np.array([q["top_share"] >= 0.7 for q in dev], int)
    ye = np.array([q["top_share"] >= 0.7 for q in ev], int)
    sc = StandardScaler().fit(Xd)
    clf = LogisticRegression(C=0.3, max_iter=5000).fit(sc.transform(Xd), yd)
    cv = np.zeros(len(dev))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(Xd, yd):
        s2 = StandardScaler().fit(Xd[tr])
        cv[te] = LogisticRegression(C=0.3, max_iter=5000).fit(s2.transform(Xd[tr]), yd[tr]).predict_proba(s2.transform(Xd[te]))[:, 1]
    pe = clf.predict_proba(sc.transform(Xe))[:, 1]
    print(f"v3-lite router AUC: dev cross-fitted {roc_auc_score(yd, cv):.3f}, eval {roc_auc_score(ye, pe):.3f}")
    sa = np.array([m not in ("cl", "xs", "c5b") for m in LITE], float)
    ha = np.array([m not in ("fa", "xn") for m in LITE], float)
    mod = V3.Model(len(LITE), use_conc=False, soft=True, sharp_allow=sa, shallow_allow=ha)
    Dd = V3.Data(dev, LITE)
    th, cut = V3.fit_model(mod, Dd, np.full(len(dev), 0.5), cv)
    return {"mod": mod, "th": th, "cut": cut, "sc": sc, "clf": clf, "ds": ds, "means": means, "ev": ev, "pe": pe, "ye": ye}


def eval_main():
    F = fit_on_dev()
    ev, mod, th = F["ev"], F["mod"], F["th"]
    De = V3.Data(ev, LITE)
    p = mod.predict(De, th, np.full(len(ev), 0.5), F["pe"], F["cut"])
    s = V3.scores(De, p)
    plain = np.array([V2.S(q, q["mem"]["plain"]) for q in ev])
    d = s - plain
    ls, _, _, lh, lt, a, b = mod.unpack(th)
    wsh = np.exp(ls - ls.max()) * mod.sa; wsh /= wsh.sum()
    whl = np.exp(lh - lh.max()) * mod.ha; whl /= whl.sum()
    cfg = {"sharp_weights": dict(zip(LITE, wsh.round(2).tolist())), "shallow_weights": dict(zip(LITE, whl.round(2).tolist())),
           "sharpen_exp": round(float(np.exp(np.clip(th[len(LITE)], -1.5, 1.5))), 3), "shallow_tau": round(float(np.exp(np.clip(lt, -1, 1))), 3),
           "route_a": round(float(a), 3), "route_b": round(float(b), 3)}
    ts = F["ye"] == 1
    print(f"v3-lite config: {cfg}\neval N {len(ev)}: plain {plain.mean():.1f} -> {s.mean():.1f} ({d.mean():+.1f} {ci(d)}); "
          f"truly sharp {s[ts].mean():.1f}, truly shallow {s[~ts].mean():.1f}")
    pd.to_pickle({q["qid"]: pi[:len(q["h"])] for q, pi in zip(ev, p)}, M.OUT / f"structure_{TAG}_eval_preds.pkl")
    (M.OUT / f"structure_{TAG}_report.json").write_text(json.dumps({"config": cfg, "eval_S": float(s.mean()), "vs_plain": float(d.mean()),
                                                                    "ci": ci(d)}, indent=2))


def compute_full_members(targets):
    cache = pd.read_pickle(FULL_CACHE) if FULL_CACHE.exists() else {}
    todo = [t for t in targets if t["q"]["qid"] not in cache]
    if not todo:
        return cache
    sv = L.build_surveys(set())
    Fi = L.Fitter(sv)
    for i, t in enumerate(todo):
        m = {}
        for k, cfg in TOOLS.items():
            x = L.predict(Fi, t, *cfg)
            if x is not None:
                m[k] = np.asarray(x)
        for k, cfg in (("xn", V3.XN_CFG), ("xs", V3.XS_CFG)):
            x, _ = XN.complete(sv[t["q"]["dataset"]], t, *cfg)
            if x is not None:
                m[k] = x
        cache[t["q"]["qid"]] = m
        if len(Fi.cache) > 300:
            Fi.cache.clear()
        if i % 250 == 0:
            pd.to_pickle(cache, FULL_CACHE)
            print(f"   members {i}/{len(todo)}", flush=True)
    pd.to_pickle(cache, FULL_CACHE)
    return cache


def full_main():
    from human_sim.simbench_structure_full import features, topic_model
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
    sample, _, ctx = A.build_env(25, 100, 7, "full")
    qs = [q for q in M.load("full") if "plain" in q["preds"]]
    targets = [t for t in L.targets("full") if "plain" in t["q"]["preds"]]
    print(f"full: {len(qs)} questions with retr6_rev2; shared-survey targets {len(targets)}", flush=True)
    mem = compute_full_members(targets)
    F = fit_on_dev()
    shared = {t["q"]["qid"] for t in targets}
    sq = [q for q in qs if q["qid"] in shared]
    feat = features(sq, sample, ctx, topic_model()).set_index("qid")
    for q in sq:
        q["mem"] = {"plain": np.asarray(q["preds"]["plain"]), **mem.get(q["qid"], {})}
    Xf = np.array([design(feat.loc[q["qid"]], F["ds"], F["means"])[0] + lite_feats(q["mem"]) for q in sq], float)
    pf = F["clf"].predict_proba(F["sc"].transform(Xf))[:, 1]
    Df = V3.Data(sq, LITE)
    pred = F["mod"].predict(Df, F["th"], np.full(len(sq), 0.5), pf, F["cut"])
    newp = {q["qid"]: p[:len(q["h"])] for q, p in zip(sq, pred)}
    dev_sample, _, _ = A.build_env(25, 100, 7, "dev")
    ev_sample, _, _ = A.build_env(25, 100, 7, "eval")
    key = lambda r: (r.dataset_name, A._filled_persona(r), r.input_template)  # noqa: E731
    dev_keys = {key(r) for _, r in dev_sample.iterrows()}
    ev_keys = {key(r) for _, r in ev_sample.iterrows()}
    v1 = json.loads((M.OUT / "structure_full_report.json").read_text())
    recs = []
    for q in qs:
        p0 = np.asarray(q["preds"]["plain"])
        p1 = newp.get(q["qid"], p0)
        r = sample.loc[q["i"]]
        recs.append({"dataset": q["dataset"], "group3": q["group3"], "split": q["split"], "S_model": L.S(q, p0), "S_method": L.S(q, p1),
                     "true_sharp": sub_shares(q["keys"], q["roles"], q["h"])[0] >= 0.7, "Hn": q["Hn"],
                     "in_dev": key(r) in dev_keys, "in_eval": key(r) in ev_keys, "shared": q["qid"] in shared})
    df = pd.DataFrame(recs)
    d = (df.S_method - df.S_model).values
    out = {"N": len(df), "S_retr6_rev2": float(df.S_model.mean()), "S_v3lite": float(df.S_method.mean()), "diff": float(d.mean()),
           "ci": ci(d), "S_v1_routed_previous": v1["S_method"], "slices": {}}
    for name, m in [("excluding dev rows (dev was used for fitting)", ~df.in_dev), ("shared surveys", df.shared),
                    ("shared surveys, excluding dev rows", df.shared & ~df.in_dev), ("true sharp (>= 70%)", df.true_sharp),
                    ("true shallow (< 70%)", ~df.true_sharp), ("entropy consensus (< 0.65)", df.Hn < 0.65), ("entropy divided (>= 0.84)", df.Hn >= 0.84),
                    ("shared surveys, true sharp", df.shared & df.true_sharp), ("shared surveys, divided", df.shared & (df.Hn >= 0.84)),
                    ("shared, Grouped", df.shared & (df.split == "Grouped")), ("shared, Pop", df.shared & (df.split == "Pop"))]:
        m = m.values
        out["slices"][name] = {"N": int(m.sum()), "S_retr6_rev2": float(df.S_model[m].mean()), "S_v3lite": float(df.S_method[m].mean()),
                               "diff": float(d[m].mean()), "ci": ci(d[m])}
    out["by_dataset"] = {k: {"N": int(len(g)), "S_retr6_rev2": float(g.S_model.mean()), "S_v3lite": float(g.S_method.mean())} for k, g in df.groupby("dataset")}
    print(f"\n== FULL BENCHMARK: {out['N']} questions")
    print(f"   retr6_rev2 {out['S_retr6_rev2']:.2f} | previous routed v1 {out['S_v1_routed_previous']:.2f} | v3-lite {out['S_v3lite']:.2f} "
          f"({out['diff']:+.2f} {out['ci']} vs retr6_rev2)")
    for k, v in out["slices"].items():
        print(f"   {k:48s} N {v['N']:5d}  {v['S_retr6_rev2']:.1f} -> {v['S_v3lite']:.1f}  {v['diff']:+.2f} {v['ci']}")
    for k, v in out["by_dataset"].items():
        print(f"   {k:20s} N {v['N']:5d}  {v['S_retr6_rev2']:.1f} -> {v['S_v3lite']:.1f}")
    (M.OUT / "structure_v3full_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    {"eval": eval_main, "full": full_main}[sys.argv[1]]()
