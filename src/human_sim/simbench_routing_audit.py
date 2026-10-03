"""Routing audit on eval (411 shared-survey questions covered by every method; no model calls).

Router = the principled one: sharpness classifier trained on dev with label 'top substantive answer >= 70%'; predicted
shallow (P(sharp) < 0.3 and a tool answer exists) -> 75% retr6_rev2 + 25% clustering tool, else retr6_rev2 unchanged.
For each slice, the routed method is compared with every other method on the same questions (paired bootstrap CI)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_mass_levers as M
from human_sim import simbench_panel_offsets as V  # fits v4 on dev at import
from human_sim.simbench_structure_sharp import CACHE
from human_sim.simbench_structure_sharpdef import sub_shares

NUM = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]
H = M.HAIKU


def ci(d):
    d = np.asarray(d, float)
    if len(d) < 5:
        return (None, None)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def main():
    S = lambda q, p: 100 * (1 - M.tvd(p, q["h"]) / q["norm"])  # noqa: E731
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl")
    ds = sorted(l1.dataset.unique())
    X = lambda d: np.c_[d[NUM].fillna(l1[NUM].mean()).values, np.array([[float(x == k) for k in ds] for x in d.dataset]),  # noqa: E731
                        np.array([[float(t == k) for k in range(20)] for t in d.topic])]
    M.EVAL_ARMS = M.DEV_ARMS = {}
    top = {q["qid"]: sub_shares(q["keys"], q["roles"], q["h"])[0] for w in ("dev", "eval") for q in M.load(w)}
    tr = l1[l1.set == "dev"]
    sc = StandardScaler().fit(X(tr))
    clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(X(tr)), np.array([top[q] >= 0.7 for q in tr.qid], int))
    ps = dict(zip(l1.qid, clf.predict_proba(sc.transform(X(l1)))[:, 1]))
    tool = pd.read_pickle(CACHE)[("dmm", 10, 3)]

    extra_arms = {"KC2 component retrieval": "KC2_rev2", "G1 group retrieval": "G1_contrast_rev2"}
    M.EVAL_ARMS = {k: (v, H) for k, v in extra_arms.items()}
    extra = {q["qid"]: q["preds"] for q in M.load("eval")}

    def routed_shallow(q):
        return ps[q["qid"]] < 0.3 and tool.get(q["qid"]) is not None

    def routed(q):
        p = np.asarray(q["preds"]["plain (retr6_rev2)"])
        return 0.25 * tool[q["qid"]] + 0.75 * p if routed_shallow(q) else p

    ev = V.ev
    methods = {"ROUTED (principled sharp/shallow)": routed,
               "plain (retr6_rev2)": lambda q: q["preds"]["plain (retr6_rev2)"], "retr6 (similar questions)": lambda q: q["preds"]["retr6"],
               "D3 (same group, same topic)": lambda q: q["preds"]["same-group data (D3)"],
               "invented personas": lambda q: q["preds"]["invented personas"], "adaptive personas": lambda q: q["preds"]["adaptive personas"],
               "segments": lambda q: q["preds"]["segments"], "agents": lambda q: q["preds"]["agents"],
               "50/50 plain+invented": lambda q: q["preds"]["50/50 plain+invented"],
               "demographic panel (C5b)": lambda q: q["preds"][V.PANEL],
               "v4 persona offsets": lambda q: V.predict(q, V.th, V.mu, V.sd)}
    for label, arm in extra_arms.items():
        methods[label] = (lambda a: lambda q: extra.get(q["qid"], {}).get(a))(label)
    scores = {m: np.array([np.nan if (p := f(q)) is None else S(q, np.asarray(p)) for q in ev]) for m, f in methods.items()}
    rs = np.array([routed_shallow(q) for q in ev])
    tsharp = np.array([top[q["qid"]] >= 0.7 for q in ev])
    hn = np.array([q["Hn"] for q in ev])
    slices = {"ROUTED TO SHALLOW (tool applied)": rs, "ROUTED TO SHARP (model answer only)": ~rs,
              "truly shallow (top answer < 70%)": ~tsharp, "truly sharp (top answer >= 70%)": tsharp,
              "truly sharp AND routed to sharp": tsharp & ~rs, "truly sharp BUT routed to shallow": tsharp & rs,
              "entropy consensus (< 0.65)": hn < 0.65, "entropy divided (>= 0.84)": hn >= 0.84}
    out = {"N": len(ev), "slices": {}}
    print(f"eval: {len(ev)} shared-survey questions; routed to shallow: {rs.sum()} ({rs.mean():.0%}); truly sharp (>=70%): {tsharp.sum()} ({tsharp.mean():.0%})")
    print(f"routing agreement: truly sharp routed to sharp {np.mean(~rs[tsharp]):.0%}; truly shallow routed to shallow {np.mean(rs[~tsharp]):.0%}")
    for name, m in slices.items():
        if m.sum() < 8:
            continue
        r = scores["ROUTED (principled sharp/shallow)"]
        rows = []
        for mn, s in scores.items():
            if mn.startswith("ROUTED"):
                continue
            ok = m & ~np.isnan(s)
            if ok.sum() < 8 or ok.sum() < 0.8 * m.sum():
                continue
            d = r[ok] - s[ok]
            lo, hi = ci(d)
            rows.append({"method": mn, "N": int(ok.sum()), "S": float(s[ok].mean()), "routed_S": float(r[ok].mean()), "routed_minus_method": float(d.mean()),
                         "ci": (lo, hi), "verdict": "routed better" if lo is not None and lo > 0 else ("routed worse" if hi is not None and hi < 0 else "tie")})
        rows.sort(key=lambda x: -x["S"])
        best = rows[0]
        out["slices"][name] = {"N": int(m.sum()), "routed_S": float(r[m].mean()), "best_other": best["method"], "best_other_S": best["S"],
                               "gap_to_best": float(best["S"] - np.mean(r[m & ~np.isnan(scores[best['method']])])), "rows": rows,
                               "counts": {v: sum(x["verdict"] == v for x in rows) for v in ("routed better", "tie", "routed worse")}}
        print(f"\n== {name}: N {m.sum()}, routed method S {r[m].mean():.1f}")
        c = out["slices"][name]["counts"]
        print(f"   vs {len(rows)} other methods: routed better than {c['routed better']}, tied with {c['tie']}, worse than {c['routed worse']}; "
              f"best other = {best['method']} ({best['S']:.1f}); routed is {best['S'] - r[m & ~np.isnan(scores[best['method']])].mean():+.1f} behind it")
        for x in rows:
            print(f"   {x['method']:34s} N {x['N']:3d}  {x['S']:5.1f}   routed - method {x['routed_minus_method']:+5.1f} {x['ci']}  {x['verdict']}")
    (M.OUT / "routing_audit_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
