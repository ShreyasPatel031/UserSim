"""What should "sharp" mean? Sharp = one substantive answer clearly above the rest (DK / refused ignored).

Two candidate families: top share of substantive answers >= theta, or lead of the top answer over the runner-up >= delta.
(1) Best for the routed method: per definition, retrain the pre-answer sharpness classifier and refit routing
    (predicted sharp -> model; predicted shallow -> model + clustering tool) on dev; choose on dev; eval shown for all.
(2) General criteria (no method involved): natural break in the top-share distribution over all SimBench rows; where
    real demographic groups stop differing (subgroup cells); where the clustering tool's blend gain changes sign."""

from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_divided_anatomy import option_roles, parse_options
from human_sim.simbench_structure_sharp import CACHE, ci

THETAS = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)
DELTAS = (0.1, 0.2, 0.3, 0.4, 0.5)
WS = np.linspace(0, 0.6, 13)
PTHR = (0.3, 0.4, 0.5, 0.6, 0.7)


def sub_shares(keys, roles, h):
    subs = roles.get("subs") or keys
    v = np.array([h[keys.index(k)] for k in subs], float)
    v = v / v.sum() if v.sum() > 0 else v
    s = np.sort(v)[::-1]
    return float(s[0]), float(s[0] - (s[1] if len(s) > 1 else 0.0))


def defs():
    out = [(f"top share >= {t:.0%}", "top", t) for t in THETAS]
    out += [(f"lead over runner-up >= {d:.0%}", "lead", d) for d in DELTAS]
    return out


def is_sharp(top, lead, kind, thr):
    return (top >= thr) if kind == "top" else (lead >= thr)


def method_part():
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl")
    ds = sorted(l1.dataset.unique())
    num = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]
    X = lambda d: np.c_[d[num].fillna(l1[num].mean()).values, np.array([[float(x == k) for k in ds] for x in d.dataset]),  # noqa: E731
                        np.array([[float(t == k) for k in range(20)] for t in d.topic])]
    shares = {}
    M.EVAL_ARMS = M.DEV_ARMS = {}
    for w in ("dev", "eval"):
        for q in M.load(w):
            shares[q["qid"]] = sub_shares(q["keys"], q["roles"], q["h"])
    cache = pd.read_pickle(CACHE)
    cfgs = [c for c in cache if c[0] in L.CL_TOOLS]
    sets = {w: [t for t in L.targets(w) if "plain" in t["q"]["preds"]] for w in ("dev", "eval")}
    S = L.S

    def sc(t, c, w):
        p = np.asarray(t["q"]["preds"]["plain"])
        x = cache[c][t["q"]["qid"]] if c else None
        return S(t["q"], p if (x is None or w == 0) else w * x + (1 - w) * p)

    base_ev = np.array([S(t["q"], t["q"]["preds"]["plain"]) for t in sets["eval"]])
    rows = []
    for name, kind, thr in defs():
        lab = {qid: is_sharp(*shares[qid], kind, thr) for qid in shares}
        tr = l1[l1.set == "dev"]
        y = np.array([lab[q] for q in tr.qid], int)
        sc_ = StandardScaler().fit(X(tr))
        clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc_.transform(X(tr)), y)
        p = dict(zip(l1.qid, clf.predict_proba(sc_.transform(X(l1)))[:, 1]))
        best = None
        for pt in PTHR:
            sub = [t for t in sets["dev"] if p[t["q"]["qid"]] < pt]
            opt = max([(c, w) for c in cfgs for w in WS], key=lambda o: np.mean([sc(t, *o) for t in sub])) if sub else (None, 0)
            tot = sum(sc(t, *opt) for t in sub) + sum(S(t["q"], t["q"]["preds"]["plain"]) for t in sets["dev"] if p[t["q"]["qid"]] >= pt)
            if best is None or tot > best[0]:
                best = (tot, pt, opt)
        _, pt, opt = best
        dev_gain = best[0] / len(sets["dev"]) - np.mean([S(t["q"], t["q"]["preds"]["plain"]) for t in sets["dev"]])
        f = np.array([sc(t, *opt) if p[t["q"]["qid"]] < pt else S(t["q"], t["q"]["preds"]["plain"]) for t in sets["eval"]])
        d = f - base_ev
        ev_lab = np.array([lab[t["q"]["qid"]] for t in sets["eval"]])
        ev_p = np.array([p[t["q"]["qid"]] for t in sets["eval"]])
        rows.append({"definition": name, "kind": kind, "threshold": thr, "share_sharp_eval": float(ev_lab.mean()),
                     "classifier_auc_eval": float(roc_auc_score(ev_lab, ev_p)) if 0 < ev_lab.mean() < 1 else None,
                     "dev_gain": float(dev_gain), "eval_gain": float(d.mean()), "eval_ci": ci(d),
                     "eval_gain_true_sharp": float(d[ev_lab].mean()) if ev_lab.any() else None,
                     "eval_gain_true_shallow": float(d[~ev_lab].mean()) if (~ev_lab).any() else None,
                     "routing": {"prob_cutoff": pt, "shallow_tool": list(opt[0]) if opt[0] else None, "weight": float(opt[1])}})
    best = max(rows, key=lambda r: r["dev_gain"])
    print("== (1) which definition of sharp works best for the routed method (chosen on dev)")
    print(f"{'definition':28s}{'sharp share':>12s}{'AUC':>7s}{'dev gain':>10s}{'eval gain':>11s}{'eval CI':>15s}{'on true sharp':>15s}{'on true shallow':>17s}")
    for r in rows:
        mark = "  <- chosen on dev" if r is best else ""
        print(f"{r['definition']:28s}{r['share_sharp_eval']:>12.0%}{(r['classifier_auc_eval'] or 0):>7.2f}{r['dev_gain']:>+10.2f}{r['eval_gain']:>+11.2f}"
              f"{str(r['eval_ci']):>15s}{(r['eval_gain_true_sharp'] or 0):>+15.1f}{(r['eval_gain_true_shallow'] or 0):>+17.1f}{mark}")
    return rows, best["definition"], shares, sets, cache


def general_part(shares_eval, sets, cache):
    out = {}
    # (a) natural break: distribution of substantive top share over all SimBench rows
    full = pd.concat([A.load_split("Pop"), A.load_split("Grouped")])
    tops, leads = [], []
    for _, r in full.iterrows():
        keys = list(r.human_answer)
        roles = option_roles(keys, parse_options(r.input_template), r.dataset_name)
        tot = sum(r.human_answer.values()) or 1.0
        t, l = sub_shares(keys, roles, [r.human_answer[k] / tot for k in keys])
        tops.append(t)
        leads.append(l)
    tops = np.array(tops)
    hist, edges = np.histogram(tops, bins=np.linspace(0.2, 1.0, 17))
    out["top_share_histogram"] = {f"{edges[i]:.2f}-{edges[i + 1]:.2f}": int(hist[i]) for i in range(len(hist))}
    # Otsu threshold on the top-share distribution (the cut that best separates two groups of questions)
    best_t, best_v = None, -1
    for t in np.linspace(0.4, 0.95, 56):
        a, b = tops[tops < t], tops[tops >= t]
        if len(a) and len(b):
            v = len(a) * len(b) * (a.mean() - b.mean()) ** 2
            if v > best_v:
                best_t, best_v = float(t), v
    out["otsu_threshold_top_share"] = best_t
    out["N_rows"] = int(len(tops))
    print(f"\n== (2a) natural break: top-share distribution over {len(tops)} SimBench questions")
    print("   " + " ".join(f"{k}:{v}" for k, v in out["top_share_histogram"].items()))
    print(f"   best two-group split (Otsu) at top share {best_t:.2f}")

    # (b) where real demographic groups stop differing (subgroup cells, same question and country, one attribute)
    g = A.load_split("Grouped")
    grp = defaultdict(list)
    for _, r in g.iterrows():
        vm = r.group_prompt_variable_map
        other = [k for k in vm if k not in A._COUNTRY_KEYS]
        if len(other) != 1:
            continue
        keys = list(r.human_answer)
        tot = sum(r.human_answer.values()) or 1.0
        grp[(r.dataset_name, A._country_of(vm), other[0], r.input_template)].append(
            (float(r.group_size or 1), np.array([r.human_answer[k] / tot for k in keys]), keys))
    bins = [(0.3, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    acc = defaultdict(list)
    for (dsn, c, a, tmpl), cells in grp.items():
        if len(cells) < 2:
            continue
        keys = cells[0][2]
        roles = option_roles(keys, parse_options(tmpl), dsn)
        subs = [keys.index(k) for k in (roles.get("subs") or keys)]
        W = np.array([w for w, _, _ in cells])
        D = np.array([v[subs] / max(v[subs].sum(), 1e-9) for _, v, _ in cells])
        pooled = (W / W.sum()) @ D
        top = pooled.max()
        between = float((W / W.sum()) @ (np.abs(D - pooled).sum(1) / 2))
        agree = float(np.all(D.argmax(1) == pooled.argmax()))
        for lo, hi in bins:
            if lo <= top < hi:
                acc[(lo, hi)].append((between, agree))
    out["groups_by_top_share"] = {}
    print("\n== (2b) do real demographic groups agree? (same question + country, groups of one attribute)")
    print(f"   {'pooled top share':18s}{'N':>6s}{'between-group difference (TVD)':>32s}{'all groups same top answer':>29s}")
    for (lo, hi) in bins:
        v = acc[(lo, hi)]
        if v:
            b, ag = np.mean([x for x, _ in v]), np.mean([y for _, y in v])
            out["groups_by_top_share"][f"{lo:.1f}-{min(hi, 1):.1f}"] = {"N": len(v), "between_tvd": float(b), "all_agree": float(ag)}
            print(f"   {f'{lo:.0%}-{min(hi, 1):.0%}':18s}{len(v):>6d}{b:>32.3f}{ag:>29.0%}")

    # (c) where the clustering tool's blend gain changes sign (diagnostic, uses real answers to bin)
    c = ("dmm", 10, 3)
    w = 0.25
    if c in cache:
        allt = sets["dev"] + sets["eval"]
        gain = []
        for t in allt:
            x = cache[c][t["q"]["qid"]]
            if x is None:
                continue
            p = np.asarray(t["q"]["preds"]["plain"])
            gain.append((shares_eval[t["q"]["qid"]][0], L.S(t["q"], w * x + (1 - w) * p) - L.S(t["q"], p)))
        gain = np.array(gain)
        out["tool_gain_by_top_share"] = {}
        print("\n== (2c) where does blending in the clustering tool stop helping? (dev + eval, by real top share)")
        for lo, hi in bins:
            m = (gain[:, 0] >= lo) & (gain[:, 0] < hi)
            if m.sum() >= 5:
                out["tool_gain_by_top_share"][f"{lo:.1f}-{min(hi, 1):.1f}"] = {"N": int(m.sum()), "gain": float(gain[m, 1].mean()), "ci": ci(gain[m, 1])}
                print(f"   top share {lo:.0%}-{min(hi, 1):.0%}: N {m.sum():3d}  gain {gain[m, 1].mean():+5.1f} {ci(gain[m, 1])}")
    return out


def main():
    rows, chosen, shares, sets, cache = method_part()
    gen = general_part(shares, sets, cache)
    (M.OUT / "structure_sharpdef_report.json").write_text(json.dumps({"method": rows, "chosen_on_dev": chosen, "general": gen}, indent=2, default=float))


if __name__ == "__main__":
    main()
