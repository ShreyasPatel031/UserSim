"""Section 4.3 failure modes (diagnostic, uses truth): is the right information in the retrieved demos, and does the
model carry it into the answer? 2x2 per bucket: demo average close/far x prediction close/far (TVD 0.10)."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l2 as L2
from human_sim import simbench_structure_l2_d3 as D3

THR = 0.10


def demo_sets(which, arms):
    """arm -> qid -> list of aligned demo vectors the arm showed (same option count as the target)."""
    rule = pd.read_pickle(M.OUT / "structure_l2_retr_rule.pkl")
    rows = {r["qid"]: r for r in L2.build(which)}
    for r in rows.values():
        r["sig"] = L2.signals(r, rule["scale"])
    out = {a: {} for a in arms}
    k_of = {"retr6_rev2": lambda r: 6, "retrk3_rev2": lambda r: 3, "retrk12_rev2": lambda r: 12,
            "retrdyn_rev2": lambda r: L2.pick_k(r["sig"], rule["rule"])}
    for a in arms:
        if a in k_of:
            for qid, r in rows.items():
                k = k_of[a](r)
                out[a][qid] = [r["vecs"][i] for i in r["aligned"] if i < k]
    if any(a.startswith("D3") for a in arms):
        pool, topics = D3.pool_and_topics()
        sample, _, ctx = A.build_env(25, 100, 7, which)
        for q in M.load(which):
            if q["split"] != "Grouped" or q["dataset"] not in A.D_DATASETS:
                continue
            demos, _ = D3.candidates(sample.loc[q["i"]], q, pool, topics, ctx, "same+cell", "none", 0, "any")
            nk = len(q["keys"])
            vecs = [np.array(list(d["human_answer"].values()), float) / sum(d["human_answer"].values()) for d in demos[:6] if len(d["human_answer"]) == nk]
            for a in arms:
                if a.startswith("D3"):
                    out[a][q["qid"]] = vecs
    return out


def table(which, arms):
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl").set_index("qid")
    M.EVAL_ARMS = M.DEV_ARMS = {a: (a, M.HAIKU) for a in arms}
    qs = {q["qid"]: q for q in M.load(which)}
    sets = demo_sets(which, arms)
    res = {}
    for a in arms:
        recs = []
        for qid, q in qs.items():
            if a not in q["preds"]:
                continue
            vecs = sets[a].get(qid, [])
            p = np.asarray(q["preds"][a])
            s = 100 * (1 - M.tvd(p, q["h"]) / q["norm"])
            rec = {"bucket": l1.loc[qid, "label"], "band": l1.loc[qid, "band"], "S": s, "pred_close": M.tvd(p, q["h"]) <= THR}
            if vecs:
                avg = np.mean(vecs, axis=0)
                rec.update(covered=True, demo_close=M.tvd(avg, q["h"]) <= THR, any_demo_close=any(M.tvd(v, q["h"]) <= THR for v in vecs))
            else:
                rec.update(covered=False, demo_close=False, any_demo_close=False)
            recs.append(rec)
        df = pd.DataFrame(recs)
        res[a] = {}
        for grp, sel in [("all", df.index == df.index)] + [(f"band={b}", df.band == b) for b in ("consensus", "mixed", "divided")] + \
                [(f"bucket={b}", df.bucket == b) for b in ("unimodal-narrow", "unimodal-wide", "multimodal", "binary/3-option", "categorical")]:
            d = df[sel]
            if not len(d):
                continue
            cov = d[d.covered]
            short = (100 - d.S).clip(lower=0).sum() or 1.0
            cells = {}
            for dc in (True, False):
                for pc in (True, False):
                    c = cov[(cov.demo_close == dc) & (cov.pred_close == pc)]
                    key = f"demos {'close' if dc else 'far'} / pred {'close' if pc else 'far'}"
                    cells[key] = {"N": int(len(c)), "mean_S": float(c.S.mean()) if len(c) else None,
                                  "share_of_S_lost": float((100 - c.S).clip(lower=0).sum() / short)}
            cells["no aligned demo"] = {"N": int((~d.covered).sum()), "share_of_S_lost": float((100 - d[~d.covered].S).clip(lower=0).sum() / short)}
            res[a][grp] = {"N": int(len(d)), "S": float(d.S.mean()), "any_single_demo_close": float(cov.any_demo_close.mean()) if len(cov) else None,
                           "cells": cells}
    return res


def show(res):
    for a, groups in res.items():
        print(f"\n== {a}")
        for grp, g in groups.items():
            c = g["cells"]
            print(f"  {grp:26s} N {g['N']:4d} S {g['S']:5.1f} | " + " | ".join(
                f"{k.replace('demos ', 'D:').replace(' / pred ', ' P:')} {v['N']} ({100 * v['share_of_S_lost']:.0f}% lost)" for k, v in c.items()))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    arms = sys.argv[2:] or ["retr6_rev2", "D3_same_group_same_topic"]
    res = table(which, arms)
    show(res)
    path = M.OUT / "structure_failure_modes.json"
    allres = json.loads(path.read_text()) if path.exists() else {}
    allres[which] = {**allres.get(which, {}), **res}
    path.write_text(json.dumps(allres, indent=2, default=float))


if __name__ == "__main__":
    main()
