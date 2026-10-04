"""Final pick-one rule (no blends, no dev search over orders; one dev-fitted exponent per source).

  sharp question  : two-way decomposition (country level + group gap from other countries, dd3) if it exists,
                    else v4 refitted on the same data
  shallow question: two-way decomposition (dd2: gap from other countries, else from similar questions) if it exists,
                    else raw blend B
  routing         : P(top answer >= 70%) from the dev-trained router, hard cut at 0.5 (one source per question)
Reports each slice on the questions where v4 exists, split by which source was used, vs v4 refit and B."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_v2method as V2
from human_sim.simbench_routing_audit import ci
from human_sim.simbench_structure_routed2 import attach, router, temper
from human_sim.simbench_structure_seg import load

TEMPS = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75)


def main():
    x = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")
    dev, ev = load("dev", "D3dyn"), load("eval", "D3dyn")
    attach(dev, x)
    attach(ev, x)
    v4r = pd.read_pickle(M.OUT / "v4_refit_eval_preds.pkl")
    B = pd.read_pickle(M.OUT / "structure_decomp_eval_preds.pkl")["B  D3dyn + raw extracted data"]
    t3 = max(TEMPS, key=lambda t: np.mean([V2.S(q, temper(q["m"]["twoway3"], t)) for q in dev if q["top_share"] >= 0.7 and "twoway3" in q["m"]]))
    t2 = max(TEMPS, key=lambda t: np.mean([V2.S(q, temper(q["m"]["twoway2"], t)) for q in dev if q["top_share"] < 0.7 and "twoway2" in q["m"]]))
    print(f"dev-fitted exponents: sharp decomposition {t3}, shallow decomposition {t2}")
    pdv, pe = router(dev, ev)
    yd = np.array([q["top_share"] >= 0.7 for q in dev])
    # cut chosen on dev (cross-fitted probabilities): maximise balanced accuracy (Youden's J), no eval data involved
    cut = max(np.arange(0.1, 0.71, 0.05), key=lambda c: np.mean(pdv[yd] >= c) + np.mean(pdv[~yd] < c))
    ye = np.array([q["top_share"] >= 0.7 for q in ev])
    print(f"router cut (dev Youden): {cut:.2f}; eval: truly sharp routed sharp {np.mean(pe[ye] >= cut):.0%}, truly shallow routed shallow {np.mean(pe[~ye] < cut):.0%}")
    routed_sharp = {q["qid"]: p >= cut for q, p in zip(ev, pe)}

    def sharp_rule(q):
        return ("decomposition", temper(q["m"]["twoway3"], t3)) if "twoway3" in q["m"] else ("v4 refit", v4r[q["qid"]])

    def shallow_rule(q):
        return ("decomposition", temper(q["m"]["twoway2"], t2)) if "twoway2" in q["m"] else ("raw blend B", B[q["qid"]])

    def final(q):
        return sharp_rule(q) if routed_sharp[q["qid"]] else shallow_rule(q)

    rep = {"exponents": {"sharp": t3, "shallow": t2}}
    for sl, sel, rule, ref_nm, ref in (("SHARP (perfect routing)", lambda q: q["top_share"] >= 0.7, sharp_rule, "v4 refit", v4r),
                                       ("SHALLOW (perfect routing)", lambda q: q["top_share"] < 0.7, shallow_rule, "raw blend B", B),
                                       ("SHARP (real router)", lambda q: q["top_share"] >= 0.7, final, "v4 refit", v4r),
                                       ("SHALLOW (real router)", lambda q: q["top_share"] < 0.7, final, "raw blend B", B),
                                       ("ALL (real router) vs v4 refit", lambda q: True, final, "v4 refit", v4r),
                                       ("ALL (real router) vs B", lambda q: True, final, "raw blend B", B)):
        qs = [q for q in ev if sel(q) and q["qid"] in v4r]
        src = [rule(q)[0] for q in qs]
        s = np.array([V2.S(q, rule(q)[1]) for q in qs]); r = np.array([V2.S(q, ref[q["qid"]]) for q in qs])
        print(f"\n== {sl}: N {len(qs)}  ours {s.mean():.1f} vs {ref_nm} {r.mean():.1f}: {(s - r).mean():+.1f} {ci(s - r)}")
        rep[sl] = {"N": len(qs), "ours": float(s.mean()), "ref": float(r.mean()), "diff": float((s - r).mean()), "ci": ci(s - r), "by_source": {}}
        for k in sorted(set(src)):
            m = np.array([z == k for z in src])
            print(f"   source = {k:14s} N {m.sum():3d}  ours {s[m].mean():.1f} vs {ref_nm} {r[m].mean():.1f}: {(s[m] - r[m]).mean():+.1f} {ci(s[m] - r[m]) if m.sum() > 4 else ''}")
            rep[sl]["by_source"][k] = {"N": int(m.sum()), "ours": float(s[m].mean()), "ref": float(r[m].mean())}
    pd.to_pickle({q["qid"]: final(q)[1] for q in ev if q["qid"] in v4r}, M.OUT / "structure_rule_eval_preds.pkl")
    (M.OUT / "structure_rule_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
