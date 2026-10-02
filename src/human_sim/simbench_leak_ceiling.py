"""Leak ceiling, no model: how well do other SimBench rows asking the SAME question predict each eval row?"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M

M.EVAL_ARMS = {"plain": ("retr6_rev2", M.HAIKU), "panel": ("P_groundall5", M.HAIKU)}
REL = ["same_group_other_wave", "country_total", "same_country_subgroups", "other_countries", "other_dataset"]


def _is_country(k):
    return "country" in k.lower() or "cntry" in k.lower()


def _country(vm):
    return next((str(v) for k, v in vm.items() if _is_country(k)), "")


def _attrs(vm):
    return tuple(sorted((k, str(v)) for k, v in vm.items()
                        if not _is_country(k) and k.lower() not in ("year", "wave", "survey_year")))


def index(full):
    idx = defaultdict(list)
    for j, r in full.iterrows():
        idx[r["input_template"]].append(j)
    return idx


def relation(t, s):
    """How source row s relates to target row t (both ask the identical question text)."""
    if s["dataset_name"] != t["dataset_name"]:
        return "other_dataset"
    vt, vs = t["group_prompt_variable_map"], s["group_prompt_variable_map"]
    if _country(vt) != _country(vs):
        return "other_countries"
    at, as_ = _attrs(vt), _attrs(vs)
    if at == as_:
        return "same_group_other_wave"
    if not as_:
        return "country_total"
    return "same_country_subgroups"


def vec(ans, keys):
    v = np.array([float(ans.get(k, 0.0)) for k in keys])
    return v / v.sum() if v.sum() > 0 else None


def main():
    sample, _, _ = A.build_env(25, 100, 7, "eval")
    full = pd.concat([A.load_split("Pop"), A.load_split("Grouped")]).reset_index(drop=True)
    full = full[full["human_answer"].map(len) > 1].reset_index(drop=True)
    idx = index(full)
    qs = {q["i"]: q for q in M.load("eval")}
    rows, cover = [], Counter()
    for i, t in sample.iterrows():
        q = qs[i]
        keys = q["keys"]
        same_keys = lambda s: set(s["human_answer"]) == set(keys)  # noqa: E731
        src = defaultdict(list)
        for j in idx[t["input_template"]]:
            s = full.loc[j]
            if A._filled_persona(s) == A._filled_persona(t) \
                    and s["split"] == t["split"]:
                continue  # the target row itself
            if not same_keys(s):
                continue
            v = vec(s["human_answer"], keys)
            if v is not None:
                src[relation(t, s)].append((v, float(s.get("group_size", 1.0) or 1.0)))
        S = lambda p: 100 * (1 - M.tvd(p, q["h"]) / q["norm"])  # noqa: E731
        rec = {"i": i, "dataset": q["dataset"], "split": q["split"], "group3": q["group3"],
               "S_plain": S(q["preds"]["plain"]), "S_panel": S(q["preds"]["panel"])}
        for r in REL:
            rec[f"n_{r}"] = len(src[r])
            if src[r]:
                V = np.array([v for v, _ in src[r]])
                w = np.array([w for _, w in src[r]])
                rec[f"S_{r}"] = S((w / w.sum()) @ V)
        # best available data-only estimate, in order of closeness
        for r in REL:
            if src[r]:
                rec["best_rel"] = r
                rec["S_best_data"] = rec[f"S_{r}"]
                break
        cover.update([rec.get("best_rel", "none")])
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_pickle(M.OUT / "leak_ceiling_rows.pkl")

    out = {"coverage_best_relation": dict(cover)}
    print("Closest same-question source available per eval row:", dict(cover))
    print(f"\n{'relation':26s}{'rows':>6s}{'S data':>8s}{'S plain':>9s}{'S panel':>9s}")
    for r in REL:
        d = df[df[f"n_{r}"] > 0]
        if len(d):
            out[r] = {"N": len(d), "S_data": d[f"S_{r}"].mean(), "S_plain": d.S_plain.mean(), "S_panel": d.S_panel.mean()}
            print(f"{r:26s}{len(d):6d}{d[f'S_{r}'].mean():8.1f}{d.S_plain.mean():9.1f}{d.S_panel.mean():9.1f}")
    best = df.S_best_data.fillna(df.S_plain)
    oracle = np.maximum(best, df.S_plain)
    out["overall"] = {"plain": df.S_plain.mean(), "data_where_available_else_plain": best.mean(),
                      "per_row_max(data,plain)": oracle.mean()}
    print("\nOverall eval (981): plain", round(df.S_plain.mean(), 1), "| closest data else plain", round(best.mean(), 1),
          "| per-row max(data, plain) [oracle pick]", round(oracle.mean(), 1))
    print("\nBy dataset (closest data relation; S data vs plain):")
    g = df.assign(best=best).groupby("dataset").agg(N=("i", "size"), covered=("best_rel", lambda x: x.notna().sum()),
                                                     rel=("best_rel", lambda x: Counter(x.dropna()).most_common(1)[0][0] if x.notna().any() else "-"),
                                                     S_best=("best", "mean"), S_plain=("S_plain", "mean"))
    print(g.round(1).to_string())
    out["by_dataset"] = g.reset_index().to_dict("records")
    (M.OUT / "leak_ceiling_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
