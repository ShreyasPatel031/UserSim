"""Free ideas for questions WITHOUT same-question data (eval/dev predictions already exist, no model calls).

1. Answer-label prior: the average real distribution over OTHER questions (training rows, eval/dev rows excluded) of the
   same dataset with the same answer labels (label text normalised); fallback same dataset + option count by position.
   Prediction = (1 - w) * model + w * prior, w fitted on dev (per group: shared surveys / other datasets).
2. D3dyn + v4 persona offsets (shared surveys), equal average.
3. Per-dataset exponent fitted on dev.
All scored on eval no-anchor questions, paired against plain."""

from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_divided_anatomy import parse_options
from human_sim.simbench_structure_sharp import ci

OTH = ["TISP", "MoralMachine", "MoralMachineClassic", "OSPsychBig5", "OSPsychMACH", "OSPsychMGKT", "ConspiracyCorr", "GlobalOpinionQA"]
WS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)


def country(vm):
    v = next(iter(vm.values())) if vm else ""
    return re.sub(r"\s*\(.*\)\s*", "", str(v)).strip().lower()


def build_priors(held):
    by_lab, by_pos = defaultdict(list), defaultdict(list)
    for split in ("Pop", "Grouped"):
        d = A.load_split(split)
        for _, r in d.iterrows():
            if (r.dataset_name, A._filled_persona(r), r.input_template) in held:
                continue
            keys = list(r.human_answer)
            tot = sum(r.human_answer.values()) or 1.0
            v = np.array([r.human_answer[k] / tot for k in keys])
            texts = parse_options(r.input_template)
            labs = tuple(L.norm_label(texts.get(k, "")) for k in keys)
            if all(labs):
                by_lab[(r.dataset_name, labs)].append(v)
            by_pos[(r.dataset_name, len(keys))].append(v)
    return ({k: (np.mean(v, axis=0), len(v)) for k, v in by_lab.items()}, {k: (np.mean(v, axis=0), len(v)) for k, v in by_pos.items()})


def prior_for(q, plab, ppos):
    labs = tuple(L.norm_label(q["texts"].get(k, "")) for k in q["keys"])
    if all(labs) and (q["dataset"], labs) in plab and plab[(q["dataset"], labs)][1] >= 5:
        return plab[(q["dataset"], labs)][0], "label"
    if (q["dataset"], len(q["keys"])) in ppos and ppos[(q["dataset"], len(q["keys"]))][1] >= 5:
        return ppos[(q["dataset"], len(q["keys"]))][0], "position"
    return None, None


def temper(p, t):
    r = np.power(np.clip(np.asarray(p, float), 1e-9, None), t)
    return r / r.sum()


def main():
    held = L.held_rows()
    plab, ppos = build_priors(held)
    pop = A.load_split("Pop")
    idx = defaultdict(set)
    for _, r in pop[pop.dataset_name.isin(OTH)].iterrows():
        idx[(r.dataset_name, r.input_template)].add(country(r.group_prompt_variable_map))
    dd2 = pd.read_pickle(M.OUT / "structure_xnat_preds.pkl")[("dd2", 1.0, 0)]
    import sys
    sys.argv = ["x"]
    from human_sim import simbench_panel_offsets as V
    v4 = {q["qid"]: V.predict(q, V.th, V.mu, V.sd) for q in V.dev + V.ev}
    S = lambda q, p: 100 * (1 - M.tvd(np.asarray(p), q["h"]) / q["norm"])  # noqa: E731
    sets = {}
    for w in ("dev", "eval"):
        M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU), "d3dyn": ("D3dyn", M.HAIKU)}
        sample, _, _ = A.build_env(25, 100, 7, w)
        keep = []
        for q in M.load(w):
            if "plain" not in q["preds"]:
                continue
            r = sample.loc[q["i"]]
            if q["dataset"] in A.D_DATASETS:
                anch = dd2.get(q["qid"]) is not None
            elif q["dataset"] in OTH:
                anch = bool(idx[(q["dataset"], r.input_template)] - {country(r.group_prompt_variable_map)})
            else:
                anch = False
            if anch:
                continue
            q["prior"], q["prior_kind"] = prior_for(q, plab, ppos)
            q["shared"] = q["dataset"] in A.D_DATASETS
            q["v4"] = v4.get(q["qid"])
            keep.append(q)
        sets[w] = keep
    dev, ev = sets["dev"], sets["eval"]
    print(f"no-anchor questions: dev {len(dev)}, eval {len(ev)}; eval with a label prior {sum(q['prior_kind'] == 'label' for q in ev)}, position prior {sum(q['prior_kind'] == 'position' for q in ev)}")

    def base(q, use_d3=True):
        return q["preds"]["d3dyn"] if (use_d3 and q["shared"] and "d3dyn" in q["preds"]) else q["preds"]["plain"]

    def mix(q, w, use_d3=True):
        b = np.asarray(base(q, use_d3))
        return (1 - w) * b + w * q["prior"] if q["prior"] is not None else b

    fits = {}
    for grp in (True, False):
        d = [q for q in dev if q["shared"] == grp]
        for use_d3 in (False, True):
            fits[(grp, use_d3)] = max(WS, key=lambda w: np.mean([S(q, mix(q, w, use_d3)) for q in d]))
    print("dev-fitted prior weights (shared?, D3dyn base?):", fits)
    tds = {}
    for ds in {q["dataset"] for q in dev}:
        d = [q for q in dev if q["dataset"] == ds]
        tds[ds] = max((0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5), key=lambda t: np.mean([S(q, temper(base(q), t)) for q in d]))
    methods = {
        "plain (retr6_rev2)": lambda q: q["preds"]["plain"],
        "best base (D3dyn in shared surveys, else plain)": lambda q: base(q),
        "plain + label prior": lambda q: mix(q, fits[(q["shared"], False)], False),
        "best base + label prior": lambda q: mix(q, fits[(q["shared"], True)], True),
        "best base, per-dataset exponent": lambda q: temper(base(q), tds.get(q["dataset"], 1.0)),
        "D3dyn + v4 average (shared, where v4 exists)": lambda q: 0.5 * np.asarray(base(q)) + 0.5 * np.asarray(q["v4"]) if (q["shared"] and q["v4"] is not None) else base(q),
        "label prior alone": lambda q: q["prior"] if q["prior"] is not None else q["preds"]["plain"],
    }
    out = {}
    for sl, sel in (("ALL no-anchor", lambda q: True), ("shared surveys", lambda q: q["shared"]), ("other datasets", lambda q: not q["shared"])):
        qs = [q for q in ev if sel(q)]
        p0 = np.array([S(q, q["preds"]["plain"]) for q in qs])
        print(f"\n== {sl}: eval N {len(qs)}")
        out[sl] = {}
        for k, f in methods.items():
            s = np.array([S(q, f(q)) for q in qs])
            print(f"   {k:48s} {s.mean():5.1f}   vs plain {(s - p0).mean():+5.1f} {ci(s - p0)}")
            out[sl][k] = {"S": float(s.mean()), "vs_plain": float((s - p0).mean()), "ci": ci(s - p0)}
    print("\nper dataset (other datasets), plain vs plain + label prior:")
    for ds in sorted({q["dataset"] for q in ev if not q["shared"]}):
        qs = [q for q in ev if q["dataset"] == ds]
        a = np.mean([S(q, q["preds"]["plain"]) for q in qs]); b = np.mean([S(q, mix(q, fits[(False, False)], False)) for q in qs])
        c = np.mean([S(q, q["prior"]) for q in qs if q["prior"] is not None]) if any(q["prior"] is not None for q in qs) else float("nan")
        print(f"   {ds:20s} N {len(qs):3d}  plain {a:5.1f}  + prior {b:5.1f}  prior alone {c:5.1f}")
    (M.OUT / "noanchor_ideas_report.json").write_text(json.dumps({"fits": {str(k): v for k, v in fits.items()}, "results": out}, indent=2, default=float))


if __name__ == "__main__":
    main()
