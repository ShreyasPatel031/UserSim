"""Interpretability layer for every question (no model calls). One explanation record per eval question.

  anchored, shared surveys : two-way decomposition - country level from named disjoint groups (their answers), group gap
                             from named other countries
  anchored, other datasets : the other countries that answered the identical question, and their answers
  no anchor, shared surveys: the evidence D3dyn shows (the group's own answers on same-topic questions) + a structural
                             profile: (dimension-reduction view) the group's gap from its own country's disjoint groups on
                             those related questions; (clustering view) the most similar groups in other countries by
                             answers on related questions
  no anchor, other datasets: the similar questions shown to the model and their real answers
Writes results/simbench_ablate/explanations_eval.json and docs/experiments/explanation_examples.md (one per case)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_xnat as XN

OTH = ["TISP", "MoralMachine", "MoralMachineClassic", "OSPsychBig5", "OSPsychMACH", "OSPsychMGKT", "ConspiracyCorr", "GlobalOpinionQA"]


def country(vm):
    v = next(iter(vm.values())) if vm else ""
    return re.sub(r"\s*\(.*\)\s*", "", str(v)).strip().lower()


def demo_view(d):
    ha = d.get("human_answer") or {}
    tot = sum(ha.values()) or 1.0
    q = A._stem(d.get("input_template", "")) if d.get("input_template") else d.get("stem", "")
    return {"question": q[:110], "answer": {k: int(round(100 * v / tot)) for k, v in ha.items()}}


def pop_profile(svp, t, K=19):
    """Country-level target: (dimension-reduction view) the country's answers on related questions vs the other
    countries' average; (clustering view) the countries whose answers on related questions are closest."""
    s = svp.get(t["q"]["dataset"])
    if s is None:
        return None
    C = t["country"]
    cell = next((c for c in s["cells"] if c[1] == C and not c[2]), None)
    if cell is None:
        return None
    nb = L.neighbours(s, t["text"], t["stem"], K)
    gaps, dist = [], defaultdict(list)
    for st, _ in nb:
        own = s["obs"].get((cell, st))
        if own is None:
            continue
        others = {c[1]: s["obs"][(c, st)] for c in s["cells"] if c[1] != C and not c[2] and (c, st) in s["obs"]}
        if not others:
            continue
        m = np.mean(list(others.values()), axis=0)
        k = int(np.argmax(m))
        gaps.append({"question": st[:90], "option": s["keys"][st][k], "country_minus_others_pts": int(round(100 * (own[k] - m[k])))})
        for c2, v in others.items():
            dist[c2].append(0.5 * np.abs(own - v).sum())
    near = sorted(((np.mean(v), c) for c, v in dist.items() if len(v) >= 2))[:3]
    return {"dimension_reduction_view": {"country_vs_other_countries_on_related_questions": gaps[:6],
                                         "mean_gap_pts": int(round(np.mean([g["country_minus_others_pts"] for g in gaps]))) if gaps else None},
            "clustering_view": {"most_similar_countries": [{"country": c, "avg_answer_distance": round(float(d), 3)} for d, c in near]}}


def pct(v, keys):
    return {k: int(round(100 * float(x))) for k, x in zip(keys, v)}


def dd_explain(sv, t):
    """Country level + group gap, with the named inputs (mirrors simbench_structure_twoway.predict)."""
    st, (ds, C, attrs) = t["stem"], t["cell"]
    if t["split"] == "Pop" or st not in sv["keys"] or len(attrs) != 1:
        return None
    (a, v), = attrs
    keys = sv["keys"][st]
    by_c = defaultdict(dict)
    for c in sv["cells"]:
        if len(c[2]) == 1 and c[2][0][0] == a and (c, st) in sv["obs"]:
            by_c[c[1]][c[2][0][1]] = sv["obs"][(c, st)]
    sib = [val for val in by_c.get(C, {}) if not XN.values_overlap(val, v)]
    if not sib:
        return None
    gaps = []
    for C2, vals in by_c.items():
        own = [x for x in vals if XN.values_overlap(x, v)]
        s2 = [x for x in sib if x in vals]
        if C2 != C and len(own) == 1 and s2:
            gaps.append({"country": C2, "group_answer": pct(vals[own[0]], keys), "siblings_answer": pct(np.mean([vals[x] for x in s2], axis=0), keys)})
    return {"type": "two-way decomposition", "attribute": a, "target_value": v,
            "country_level_from": [{"group": f"{a}={x}", "answer": pct(by_c[C][x], keys)} for x in sib],
            "group_gap_from_other_countries": gaps[:6], "n_gap_countries": len(gaps)}


def profile(sv, t, demos):
    """Structural profile of a group with no same-question data, from its answers on related questions."""
    if t["split"] == "Pop" or len(t["cell"][2]) != 1:
        return None
    C, ((a, v),) = t["cell"][1], t["cell"][2]
    gaps = []
    for d in demos:
        st = d["stem"]
        if st not in sv["keys"]:
            continue
        sib = [c for c in sv["cells"] if c[1] == C and len(c[2]) == 1 and c[2][0][0] == a and not XN.values_overlap(c[2][0][1], v) and (c, st) in sv["obs"]]
        own = sv["obs"].get((t["cell"], st))
        if own is None or not sib:
            continue
        m = np.mean([sv["obs"][(c, st)] for c in sib], axis=0)
        k = int(np.argmax(m))
        gaps.append({"question": st[:90], "option": sv["keys"][st][k], "group_minus_country_pts": int(round(100 * (own[k] - m[k])))})
    near = []
    nb = L.neighbours(sv, t["text"], t["stem"], 19)
    X, rows, cols = L.local_matrix(sv, [s for s, _ in nb])
    if t["cell"] in rows:
        ti = rows.index(t["cell"])
        dist = []
        for i, c in enumerate(rows):
            if c[1] == C:
                continue
            ds_ = [0.5 * np.abs(X[ti, s_] - X[i, s_]).sum() for s_ in cols.values() if not np.isnan(X[ti, s_.start]) and not np.isnan(X[i, s_.start])]
            if len(ds_) >= 2:
                dist.append((float(np.mean(ds_)), sv["label"].get(c, str(c))))
        near = [{"group": g, "avg_answer_distance": round(d, 3)} for d, g in sorted(dist)[:3]]
    return {"dimension_reduction_view": {"group_vs_own_country_on_related_questions": gaps,
                                         "mean_gap_pts": int(round(np.mean([g["group_minus_country_pts"] for g in gaps]))) if gaps else None},
            "clustering_view": {"most_similar_groups_in_other_countries": near}}


def main():
    sample, _, ctx = A.build_env(25, 100, 7, "eval")
    ctx["dpool"] = A._build_dpool(A.load_split("Pop"), A.load_split("Grouped"), 25, 100, 7)
    ctx["_target_stems"] = [(r["dataset_name"], A._stem(r["input_template"])) for _, r in sample.iterrows()]
    topics = A._topics(ctx)
    sv = L.build_surveys(L.held_rows())
    svp = L.build_surveys(L.held_rows(), split="Pop")
    pop = A.load_split("Pop")
    idx = defaultdict(list)
    for _, r in pop[pop.dataset_name.isin(OTH)].iterrows():
        tot = sum(r.human_answer.values()) or 1.0
        idx[(r.dataset_name, r.input_template)].append((country(r.group_prompt_variable_map), {k: round(100 * x / tot) for k, x in r.human_answer.items()}))
    tmap = {t["q"]["qid"]: t for t in L.targets("eval")}
    M.EVAL_ARMS = M.DEV_ARMS = {}
    out = {}
    for q in M.load("eval"):
        r = sample.loc[q["i"]]
        rec = {"dataset": q["dataset"], "split": q["split"], "question": q["question"][:200]}
        if q["dataset"] in A.D_DATASETS:
            t = tmap.get(q["qid"])
            ex = dd_explain(sv[q["dataset"]], t) if t else None
            if ex:
                rec.update(case="anchored: two-way decomposition", explanation=ex)
            else:
                pool = A._dpool(r, ctx)
                tt = topics.get((r["dataset_name"], A._stem(r["input_template"])))
                cell = A._cell_key(r)
                sg = [d for d in pool if d["cell"] == cell]
                demos = A._cap_per_stem(A._shuffled([d for d in sg if topics.get((r["dataset_name"], d["stem"])) == tt], r), 12)
                if len(demos) < 3:
                    demos += A._cap_per_stem([d for d in A._shuffled(sg, r) if d not in demos], 3 - len(demos))
                rec.update(case="no anchor: same-group evidence + structural profile",
                           explanation={"evidence_shown_to_model": [demo_view(d) for d in demos],
                                        "structural_profile": (pop_profile(svp, t) if q["split"] == "Pop" else profile(sv[q["dataset"]], t, demos)) if t else None})
        else:
            c = country(r.group_prompt_variable_map)
            others = [(cc, a) for cc, a in idx.get((q["dataset"], r.input_template), []) if cc != c]
            if others:
                rec.update(case="anchored: other countries, identical question", explanation={"other_countries": [{"country": cc, "answer": a} for cc, a in others[:8]], "n": len(others)})
            else:
                demos = A._rank_by_similarity(r, A._demo_pool(r, ctx), ctx)[:6]
                rec.update(case="no anchor: similar questions shown to the model",
                           explanation={"similar_questions": [demo_view(d) for d in demos]})
        out[q["qid"]] = rec
    (M.OUT / "explanations_eval.json").write_text(json.dumps(out, indent=1, default=str))
    cases = pd.Series([v["case"] for v in out.values()]).value_counts()
    print(cases.to_string())
    noa = [v for v in out.values() if v["case"].startswith("no anchor: same-group")]
    print("no-anchor shared with a structural profile:", sum(bool(v["explanation"].get("structural_profile")) for v in noa), "of", len(noa))
    print("no-anchor with non-empty evidence:", sum(any(e["answer"] for e in (v["explanation"].get("evidence_shown_to_model") or v["explanation"].get("similar_questions") or [])) for v in out.values() if v["case"].startswith("no anchor")))
    md = ["# Explanation examples (one per case)", "", "Every eval question gets one of these records (`results/simbench_ablate/explanations_eval.json`). No model calls.", ""]
    for case in cases.index:
        cand = [(k, v) for k, v in out.items() if v["case"] == case and v.get("explanation")]
        k, v = next(((k, v) for k, v in cand if v["explanation"].get("structural_profile")), cand[0])
        md += [f"## {case}", "", f"**{v['dataset']} / {v['split']}** — {v['question']}", "", "```json", json.dumps(v["explanation"], indent=1, default=str)[:3000], "```", ""]
    Path("docs/experiments/explanation_examples.md").write_text("\n".join(md))


if __name__ == "__main__":
    main()
