"""Held-out evaluation of the population adapter on any ResponseTable; writes one evaluation card per dataset.

Task: a NEW item (question / product) arrives; the answers of a random anchor set of units are revealed (5%, 10%, 25%);
predict every other unit's answer distribution. Overlapping units never inform each other.
Methods: anchor_mean (baseline), axes (anchor regressed on axis scores), segment (anchor mean within the unit's segment),
attribute (anchor mean within the unit's best single attribute, e.g. income). Axes and segments are fitted on TRAINING
items only; rank, k and the attribute are chosen on validation items carved out of training; test items are untouched.
Interpretability tests: (1) predictive - axes / segments must beat anchor_mean and attribute on test items (paired
bootstrap CI); (2) stable - axes congruence and segment ARI across bootstrap refits; (3) faithful - dropping an axis must
hurt test accuracy. Ceiling (person level): test-retest agreement where the item was asked again."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim.popadapt import adapters as AD
from human_sim.popadapt import engine as E

OUT = Path(__file__).resolve().parents[3] / "results" / "popadapt"
MIN_UNITS_PER_ITEM = 20  # below this, axes / segments cannot be estimated and are reported as not supported


def ci(d, B=2000, seed=0):
    d = np.asarray(d, float)
    if len(d) < 5:
        return None
    rng = np.random.default_rng(seed)
    m = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(B)]
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def tvd(p, q):
    return 0.5 * np.abs(np.asarray(p) - np.asarray(q)).sum(-1)


class Setup:
    def __init__(self, t, rank, k, attr, train_items, seed=0):
        self.M = E.Matrix(t, train_items)
        self.mu, self.S, self.V, self.var = E.fit_axes(self.M.X, rank, seed=seed, w=self.M.w)
        self.seg, self.km = E.segments(self.S, k, seed) if rank else (np.zeros(len(self.M.units), int), None)
        self.attr = attr
        self.groups = t.units.loc[self.M.units, attr].to_numpy() if attr else None


def run_item(t, st, item, frac, rng, overlap, max_targets=800, drop_axis=None):
    """Predict one held-out item for non-anchor units. Returns per-target TVDs per method plus raw predictions."""
    full = E.Matrix(t, [item])
    obs = np.where(full.observed(item))[0]
    if len(obs) < 3:
        return None
    y = full.X[:, full.cols[item]]
    n_anchor = max(1, int(round(frac * len(obs))))
    anchor_idx = rng.choice(obs, n_anchor, replace=False)
    anchor = np.zeros(len(full.units), bool)
    anchor[anchor_idx] = True
    targets = np.array([i for i in obs if not anchor[i]])
    if len(targets) == 0:
        return None
    if len(targets) > max_targets:
        targets = rng.choice(targets, max_targets, replace=False)
    S = st.S.copy()
    if drop_axis is not None and S.shape[1]:
        S[:, drop_axis] = 0.0
    ok = (lambda i: np.ones(len(full.units), bool)) if overlap is None else (lambda i: ~overlap[i])
    seg = st.seg if st.km is not None else None
    pred = (E.predict_item_shared(y, anchor, targets, S, seg, st.groups) if overlap is None
            else E.predict_item(y, anchor, targets, S, seg, st.groups, ok))
    keep = [j for j, p in enumerate(pred["anchor_mean"]) if p is not None]
    if not keep:
        return None
    P = {m: np.array([pred[m][j] for j in keep]) for m in pred}
    Yt = y[targets[keep]]
    res = {m: tvd(P[m], Yt) for m in P}
    res["uniform"] = tvd(np.ones(y.shape[1]) / y.shape[1], Yt)
    return res, targets[keep], P, y


def evaluate(t, test_items, fracs=(0.05, 0.10, 0.25), reps=3, ranks=(0, 1, 2, 3, 5, 8, 12), ks=(2, 3, 4, 6, 8), seed=0, retest=None, example_item=None):
    rng = np.random.default_rng(seed)
    cov = t.coverage()
    card = {"dataset": t.name, "level": t.level, "coverage": cov, "test_items": len(test_items)}
    supported = cov["median_units_per_item"] >= MIN_UNITS_PER_ITEM and cov["units"] >= 50
    card["axes_segments_supported"] = bool(supported)
    if not supported:
        card["why_not"] = (f"median {cov['median_units_per_item']:.0f} units per item and {cov['units']} units: axes and segments need at "
                           f"least {MIN_UNITS_PER_ITEM} units answering each item. Only anchor_mean and attribute predictions are evaluated.")
    overlap = None
    if t.level == "group":
        us = list(t.units.index)
        overlap = np.array([[t.overlap(a, b) for b in us] for a in us])
    train = [i for i in t.items.index if i not in set(test_items)]
    val = list(rng.choice(train, max(5, len(train) // 5), replace=False)) if len(train) > 10 else []
    fit_items = [i for i in train if i not in set(val)]
    attrs = [c for c in t.units.columns if t.units[c].nunique() > 1]

    # ---- choose rank, k and attribute on validation items (training data only)
    def score(st, items, method, frac=0.10):
        v = []
        for it in items:
            r = run_item(t, st, it, frac, np.random.default_rng(seed + 1), overlap)
            if r:
                v.append(r[0][method].mean())
        return np.mean(v) if v else np.inf
    best_attr, best_rank, best_k = None, 0, 1
    if val:
        if attrs:
            base = Setup(t, 0, 1, None, fit_items)
            sc = {}
            for a in attrs:
                base.attr, base.groups = a, t.units.loc[base.M.units, a].to_numpy()
                sc[a] = score(base, val, "attribute")
            best_attr = min(sc, key=sc.get)
            card["attribute_choice"] = {a: round(float(v), 4) for a, v in sorted(sc.items(), key=lambda kv: kv[1])[:6]}
        if supported:
            rs = {r: score(Setup(t, r, 1, None, fit_items), val, "axes") for r in ranks}
            best_rank = min(rs, key=rs.get)
            card["rank_choice"] = {str(r): round(float(v), 4) for r, v in rs.items()}
            if best_rank:
                kk = {k: score(Setup(t, best_rank, k, None, fit_items), val, "segment") for k in ks}
                best_k = min(kk, key=kk.get)
                card["k_choice"] = {str(k): round(float(v), 4) for k, v in kk.items()}
    card["chosen"] = {"rank": int(best_rank), "segments": int(best_k), "attribute": best_attr}
    st = Setup(t, best_rank, best_k, best_attr, train)

    # ---- held-out test
    results = {}
    GROUP_ATTRS = [c for c in ("sex", "age", "income", "party", "education", "race", "region") if c in t.units.columns]
    for f in fracs:
        per = {m: [] for m in ("uniform", "anchor_mean", "axes", "segment", "attribute")}
        gshare = {m: [] for m in ("anchor_mean", "axes", "segment", "attribute")}
        ggap = {m: [] for m in ("anchor_mean", "axes", "segment", "attribute")}
        for rep in range(reps):
            r2 = np.random.default_rng(seed + 100 + rep)
            for it in test_items:
                r = run_item(t, st, it, f, r2, overlap, max_targets=100000)
                if r:
                    for m in per:
                        per[m].append(r[0][m].mean())
                    if t.level == "person" and GROUP_ATTRS:
                        _, tg, pr, y = r
                        U = t.units.loc[[st.M.units[i] for i in tg]]
                        real_all = y[tg].mean(0)
                        for m in gshare:
                            errs, rg, pg = [], [], []
                            for col in GROUP_ATTRS:
                                for v in U[col].unique():
                                    msk = (U[col] == v).to_numpy()
                                    if msk.sum() < 40:
                                        continue
                                    real = y[tg][msk].mean(0)
                                    pred = pr[m][msk].mean(0)
                                    errs.append(0.5 * np.abs(real - pred).sum())
                                    rg.append(real[0] - real_all[0]); pg.append(pred[0] - pr[m].mean(0)[0])
                            gshare[m].append(np.mean(errs))
                            ggap[m].append(np.corrcoef(rg, pg)[0, 1] if np.std(pg) > 1e-9 else 0.0)
        row = {m: round(float(np.mean(v)), 4) for m, v in per.items() if v}
        base = np.array(per["anchor_mean"])
        for m in ("axes", "segment", "attribute"):
            d = base - np.array(per[m])  # positive = method is better (lower TVD)
            row[f"{m}_gain_vs_anchor"] = round(float(d.mean()), 4)
            row[f"{m}_gain_ci"] = ci(d)
        row["n_item_reps"] = len(base)
        if any(gshare.values()):
            row["group_share_error"] = {m: round(float(np.mean(v)), 4) for m, v in gshare.items()}
            row["group_gap_correlation"] = {m: round(float(np.nanmean(v)), 3) for m, v in ggap.items()}
            b = np.array(gshare["anchor_mean"])
            row["group_share_gain_ci"] = {m: ci(b - np.array(gshare[m])) for m in ("axes", "segment", "attribute")}
        results[str(f)] = row
    card["test_tvd"] = results

    # ---- stability and faithfulness (only where axes exist)
    if best_rank:
        cong, aris = [], []
        from sklearn.metrics import adjusted_rand_score
        for b in range(3):
            idx = np.random.default_rng(seed + 200 + b).choice(len(st.M.units), len(st.M.units), replace=True)
            Xb = st.M.X[idx]
            _, Sb, Vb, _ = E.fit_axes(Xb, best_rank, seed=b, w=st.M.w)
            C = np.abs(np.corrcoef(st.V.T, Vb.T)[:best_rank, best_rank:])
            cong.append(float(np.mean(C.max(1))))
            # project all units onto bootstrap axes, recluster, compare with full-data segments
            Xf = (np.where(np.isnan(st.M.X), st.mu, st.M.X) - st.mu) * st.M.w ** 2
            lb, _ = E.segments(Xf @ Vb, best_k, b)
            aris.append(adjusted_rand_score(st.seg, lb))
        card["stability"] = {"axis_congruence_mean": round(float(np.mean(cong)), 3), "segment_ARI_mean": round(float(np.mean(aris)), 3)}
        faith = []
        for a in range(best_rank):
            d = []
            for it in test_items:
                r_full = run_item(t, st, it, 0.10, np.random.default_rng(seed + 300), overlap)
                r_drop = run_item(t, st, it, 0.10, np.random.default_rng(seed + 300), overlap, drop_axis=a)
                if r_full and r_drop:
                    d.append(r_drop[0]["axes"].mean() - r_full[0]["axes"].mean())
            faith.append({"axis": a + 1, "tvd_increase_when_dropped": round(float(np.mean(d)), 5), "ci": ci(d)})
        card["faithfulness"] = faith
        card["axes"] = E.describe_axes(t, st.M, st.V, st.var)
        card["segments"] = E.describe_segments(t, st.M, st.seg)

    # ---- ceiling and a "who would buy" example (person level)
    if retest is not None:
        acc = []
        for it in test_items:
            if it in retest.columns:
                a = t.resp[t.resp.item == it]
                w = retest[it].dropna()
                both = [(np.argmax(d), int(w[u]) - 1) for u, d in zip(a.unit, a.dist) if u in w.index]
                if both:
                    acc.append(np.mean([x == z for x, z in both]))
        if acc:
            card["retest_ceiling"] = {"items": len(acc), "same_answer_rate": round(float(np.mean(acc)), 4)}
    if example_item is not None:
        r = run_item(t, st, example_item, 0.10, np.random.default_rng(seed + 400), overlap, max_targets=5000)
        if r:
            _, tg, pr, y = r
            U = t.units.loc[[st.M.units[i] for i in tg]]
            rows = []
            for col in ("sex", "age", "income", "party", "education"):
                if col not in U.columns:
                    continue
                for v in sorted(U[col].unique()):
                    m = (U[col] == v).to_numpy()
                    if m.sum() < 40:
                        continue
                    rows.append({"group": f"{col}={v}", "n": int(m.sum()), "real_yes_%": round(100 * float(y[tg][m][:, 0].mean()), 1),
                                 **{f"{k}_%": round(100 * float(pr[k][m][:, 0].mean()), 1) for k in ("anchor_mean", "axes", "segment", "attribute")}})
            card["who_would_buy_example"] = {"item": example_item, "text": t.items.at[example_item, "text"], "anchor": "10% of people", "by_group": rows}
    return card


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cards = {}
    if which in ("all", "twin"):
        t = AD.twin2k()
        rng = np.random.default_rng(0)
        pricing = [i for i in t.items.index if "Pricing" in t.items.at[i, "block"]]
        other = [i for i in t.items.index if i not in pricing]
        groups = sorted({t.items.at[i, "group"] for i in other})
        held_groups = set(rng.choice(groups, max(1, len(groups) // 8), replace=False))  # whole questions held out
        other_test = [i for i in other if t.items.at[i, "group"] in held_groups]
        cards["twin_pricing"] = evaluate(t, pricing, retest=AD.twin2k_retest(), example_item=pricing[0])
        cards["twin_other_blocks"] = evaluate(t, other_test, retest=AD.twin2k_retest())
    if which in ("all", "simbench"):
        from human_sim import simbench_ablate as A
        dss = sorted(set(A.load_split("Pop").dataset_name) | set(A.load_split("Grouped").dataset_name))
        for d in dss:
            t = AD.simbench(d)
            multi = t.resp.groupby("item").unit.nunique()
            cand = list(multi[multi >= 3].index)  # items answered by >= 3 units can be tested at all
            if not cand:
                cards[f"simbench_{d}"] = {"dataset": t.name, "coverage": t.coverage(), "testable": False,
                                          "why_not": "no item answered by 3 or more units: only one population per item, nothing to predict across units"}
                continue
            rng = np.random.default_rng(0)
            test = list(rng.choice(cand, max(1, len(cand) // 4), replace=False))  # representative 25% of testable items
            cards[f"simbench_{d}"] = evaluate(t, test, fracs=(0.25, 0.5), reps=3)
    fn = OUT / f"cards_{which}.json"
    if which == "twin" and (OUT / "cards.json").exists():
        (OUT / "cards.json").unlink()  # superseded first run (unweighted, sibling rows in training)
    old = json.loads(fn.read_text()) if fn.exists() else {}
    old.update(cards)
    fn.write_text(json.dumps(old, indent=1, default=str))
    for k, c in cards.items():
        print(k, json.dumps({x: c.get(x) for x in ("coverage", "axes_segments_supported", "chosen", "test_tvd", "stability", "retest_ceiling", "why_not")}, default=str)[:1500])


if __name__ == "__main__":
    main()
