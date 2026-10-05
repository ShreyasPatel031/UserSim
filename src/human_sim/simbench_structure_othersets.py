"""Same-question anchors for the datasets outside the 5 shared surveys (full benchmark, no model calls, no fitting).

In TISP, MoralMachine, MoralMachineClassic, OSPsychBig5/MACH/MGKT, ConspiracyCorr and GlobalOpinionQA every population
is ONE country. For a question asked to country C: prediction = mean of the real answers that OTHER countries gave to
the identical question (same text and options). Same country under another label ("X (Non-national sample)") counts as
C and is excluded, so no answer from the target population is ever used. No other country asked it -> retr6_rev2.
Combined with the shared-survey rule (structure_fullrule) to give the new full-benchmark score."""

from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_structure_sharp import ci

DATASETS = ["TISP", "MoralMachine", "MoralMachineClassic", "OSPsychBig5", "OSPsychMACH", "OSPsychMGKT", "ConspiracyCorr", "GlobalOpinionQA"]


def country(vm):
    v = next(iter(vm.values())) if vm else ""
    return re.sub(r"\s*\(.*\)\s*", "", str(v)).strip().lower()


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def main():
    sample, _, _ = A.build_env(25, 100, 7, "full")
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
    qs = [q for q in M.load("full") if "plain" in q["preds"]]
    idx = defaultdict(list)  # (dataset, template) -> [(country, {key: share})]
    for _, r in sample.iterrows():
        if r.dataset_name in DATASETS:
            tot = sum(r.human_answer.values()) or 1.0
            idx[(r.dataset_name, r.input_template)].append((country(r.group_prompt_variable_map), {k: v / tot for k, v in r.human_answer.items()}))
    rule = pd.read_pickle(M.OUT / "structure_fullrule_preds_final.pkl") if (M.OUT / "structure_fullrule_preds_final.pkl").exists() else None
    recs = []
    for q in qs:
        r = sample.loc[q["i"]]
        p0 = np.asarray(q["preds"]["plain"])
        src, p = "plain", p0
        if q["dataset"] in DATASETS:
            c = country(r.group_prompt_variable_map)
            others = [a for cc, a in idx[(q["dataset"], r.input_template)] if cc != c]
            if others:
                p = np.mean([[a.get(k, 0.0) for k in q["keys"]] for a in others], axis=0)
                p = p / p.sum()
                src = f"other countries ({len(others)})"
        recs.append({"qid": q["qid"], "dataset": q["dataset"], "anchor": src != "plain", "n_other": len(others) if q["dataset"] in DATASETS and src != "plain" else 0,
                     "S_plain": S(q, p0), "S_anchor": S(q, p)})
    df = pd.DataFrame(recs)
    out = {"datasets": {}}
    print("per dataset (full benchmark):")
    for ds in DATASETS:
        g = df[df.dataset == ds]
        a = g[g.anchor]
        d = (a.S_anchor - a.S_plain).values
        out["datasets"][ds] = {"N": int(len(g)), "with_anchor": int(len(a)), "S_plain_all": float(g.S_plain.mean()), "S_new_all": float(g.S_anchor.mean()),
                               "S_plain_anchored": float(a.S_plain.mean()) if len(a) else None, "S_anchor_anchored": float(a.S_anchor.mean()) if len(a) else None,
                               "diff_anchored": float(d.mean()) if len(a) else None, "ci": ci(d) if len(a) > 4 else None}
        v = out["datasets"][ds]
        print(f"   {ds:20s} N {v['N']:4d}, anchored {v['with_anchor']:4d} | on anchored: plain {v['S_plain_anchored'] if v['S_plain_anchored'] is None else round(v['S_plain_anchored'], 1)} -> "
              f"other-country mean {v['S_anchor_anchored'] if v['S_anchor_anchored'] is None else round(v['S_anchor_anchored'], 1)} | whole dataset {v['S_plain_all']:.1f} -> {v['S_new_all']:.1f}")
    pd.to_pickle(df, M.OUT / "structure_othersets_full.pkl")
    (M.OUT / "structure_othersets_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
