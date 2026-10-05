"""Which method is best on questions WITHOUT same-question data (eval, all 981 questions considered)?

Anchored = 5 shared surveys: the two-way decomposition (dd2) exists; other datasets: another country answered the
identical question. Everything else is "no anchor". For every method with eval predictions, score it on the no-anchor
questions, split by true shape (sharp = top substantive answer >= 70%), on the questions where it exists and paired
against the plain model on the same questions."""

from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_structure_sharp import ci
from human_sim.simbench_structure_sharpdef import sub_shares

ARMS = {"zero-shot": "base", "plain (retr6_rev2)": "retr6_rev2", "retr6": "retr6", "KC2 component retrieval": "KC2_rev2",
        "D3 same group/topic": "D3_same_group_same_topic", "D3dyn": "D3dyn", "G1 contrast groups": "G1_contrast_rev2",
        "persona panel C5b": "C5b_demo_mix", "D0 similar questions (pool)": "D0_retr6", "D1 same topic, any group": "D1_same_topic",
        "D2 same group, any topic": "D2_same_group", "D4n8 (8 same-group demos)": "D3n8"}
OTH = ["TISP", "MoralMachine", "MoralMachineClassic", "OSPsychBig5", "OSPsychMACH", "OSPsychMGKT", "ConspiracyCorr", "GlobalOpinionQA"]


def country(vm):
    v = next(iter(vm.values())) if vm else ""
    return re.sub(r"\s*\(.*\)\s*", "", str(v)).strip().lower()


def main():
    M.EVAL_ARMS = M.DEV_ARMS = {k: (v, M.HAIKU) for k, v in ARMS.items()}
    qs = M.load("eval")
    sample, _, _ = A.build_env(25, 100, 7, "eval")
    pop = A.load_split("Pop")
    idx = defaultdict(set)
    for _, r in pop[pop.dataset_name.isin(OTH)].iterrows():
        idx[(r.dataset_name, r.input_template)].add(country(r.group_prompt_variable_map))
    dd2 = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")[("dd2", 1.0, 0)]
    v4 = {}
    try:
        import sys
        sys.argv = ["x"]
        from human_sim import simbench_panel_offsets as V
        v4 = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.ev}
    except Exception as e:  # noqa: BLE001
        print("v4 unavailable:", e)
    S = lambda q, p: 100 * (1 - M.tvd(np.asarray(p), q["h"]) / q["norm"])  # noqa: E731
    rows = []
    for q in qs:
        r = sample.loc[q["i"]]
        if q["dataset"] in A.D_DATASETS:
            anchored = dd2.get(q["qid"]) is not None
        elif q["dataset"] in OTH:
            anchored = bool(idx[(q["dataset"], r.input_template)] - {country(r.group_prompt_variable_map)})
        else:
            anchored = False
        if anchored:
            continue
        top = sub_shares(q["keys"], q["roles"], q["h"])[0]
        rec = {"dataset": q["dataset"], "shared": q["dataset"] in A.D_DATASETS, "shape": "sharp" if top >= 0.7 else "shallow"}
        for k in ARMS:
            if k in q["preds"]:
                rec[k] = S(q, q["preds"][k])
        if q["qid"] in v4:
            rec["v4 persona offsets"] = S(q, v4[q["qid"]])
        rows.append(rec)
    df = pd.DataFrame(rows)
    meths = [c for c in df.columns if c not in ("dataset", "shared", "shape")]
    out = {"N": len(df), "slices": {}}
    print(f"eval questions WITHOUT same-question data: {len(df)} (shared surveys {int(df.shared.sum())}, other datasets {int((~df.shared).sum())})")
    for sl, m in (("ALL no-anchor", np.ones(len(df), bool)), ("sharp", (df["shape"] == "sharp").values), ("shallow", (df["shape"] == "shallow").values),
                  ("shared surveys", df.shared.values), ("other datasets", (~df.shared).values)):
        g = df[m]
        print(f"\n== {sl}: N {len(g)}")
        res = []
        for k in meths:
            ok = g[k].notna() & g["plain (retr6_rev2)"].notna()
            if ok.sum() < 10:
                continue
            d = (g.loc[ok, k] - g.loc[ok, "plain (retr6_rev2)"]).values
            res.append((k, int(ok.sum()), float(g.loc[ok, k].mean()), float(d.mean()), ci(d)))
        res.sort(key=lambda x: -x[3])
        for k, n, s, dm, c in res:
            print(f"   {k:26s} n {n:3d} ({n / len(g):4.0%} coverage)  S {s:5.1f}   vs plain on same {dm:+5.1f} {c}")
        out["slices"][sl] = res
    (M.OUT / "noanchor_sota_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
