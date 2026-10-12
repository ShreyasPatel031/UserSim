"""Population/segment-level scoring of Mega-Study runs (no new model calls).

For every outcome and demographic segment (age, sex, education, race, party, ideology, income) with >= 20 people:
  segment mean error  |twin mean - human mean| / human SD of the outcome
  segment gap         (segment mean - overall mean) / SD, compared human vs twin: does the arm know how groups differ?
Paired bootstrap over outcomes for arm differences. Writes results/twin_mega/segments.json."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from human_sim import mega_pipeline as M
from human_sim import people_repo as PR

ARMS = ["A0_demographics", "A3_naive_rag", "A4_harness"]
COLLAPSE = {"EDUCATION": {"Less than high school": "HS or less", "High school graduate": "HS or less", "Some college, no degree": "Some college",
                          "Associate's degree": "Some college", "College graduate/some postgrad": "BA+", "Postgraduate": "BA+"},
            "PARTY": {"Something else": "Independent"},
            "IDEOLOGY": {"Very liberal": "Liberal", "Very conservative": "Conservative"},
            "INCOME": {"Less than $30,000": "<50k", "$30,000-$50,000": "<50k", "$50,000-$75,000": "50-100k", "$75,000-$100,000": "50-100k"}}
SEG_ATTRS = ["AGE", "SEX", "EDUCATION", "RACE", "PARTY", "IDEOLOGY", "INCOME"]


def segments_table():
    lab = pd.read_csv(M.TWIN / "wave1_3_response_label.csv", usecols=["pid"] + M.DEMO_QIDS).set_index("pid")
    rows = {}
    for pid, r in lab.iterrows():
        p = PR.twin_profile(r.to_dict())
        rows[str(pid)] = {a: COLLAPSE.get(a, {}).get(p.get(a), p.get(a)) for a in SEG_ATTRS}
    return pd.DataFrame.from_dict(rows, orient="index")


def load(arm):
    out = []
    for sd in sorted(M.OUT.iterdir()):
        f = sd / arm / "meta analysis individual level.csv"
        if sd.is_dir() and f.exists():
            d = pd.read_csv(f)
            d["study"] = sd.name
            out.append(d)
    return pd.concat(out)


def run(arms=None, tag=""):
    global ARMS
    if arms:
        ARMS = list(arms)
    seg = segments_table()
    per = {}
    for arm in ARMS:
        d = load(arm)
        d = d.dropna(subset=["TWIN_ID"]); d["TWIN_ID"] = d.TWIN_ID.astype(float).astype(int).astype(str)
        d["value"] = pd.to_numeric(d.value, errors="coerce")
        w = d.pivot_table(index=["study", "variable_name", "TWIN_ID"], columns="respondent_type", values="value", aggfunc="first").dropna()
        w = w.reset_index().merge(seg, left_on="TWIN_ID", right_index=True, how="left")
        per[arm] = w
    keys = set.intersection(*[set(map(tuple, per[a][["study", "variable_name"]].drop_duplicates().values)) for a in ARMS])
    recs = []
    for arm, w in per.items():
        for (st, var), g in w.groupby(["study", "variable_name"]):
            if (st, var) not in keys:
                continue
            sd = g.human.std()
            if not sd or np.isnan(sd):
                continue
            mh, mt = g.human.mean(), g.twin.mean()
            for a in SEG_ATTRS:
                for val, s in g.groupby(a):
                    if len(s) < 20 or val is None:
                        continue
                    recs.append({"arm": arm, "study": st, "var": var, "attr": a, "val": val, "n": len(s),
                                 "err": abs(s.twin.mean() - s.human.mean()) / sd,
                                 "gap_h": (s.human.mean() - mh) / sd, "gap_t": (s.twin.mean() - mt) / sd})
    R = pd.DataFrame(recs)
    summ = {}
    for arm, g in R.groupby("arm"):
        summ[arm] = {"segment_cells": int(len(g)), "segment_mean_error_sd": round(float(g.err.mean()), 4),
                     "segment_gap_corr": round(float(np.corrcoef(g.gap_h, g.gap_t)[0, 1]), 4),
                     "gap_slope": round(float(np.polyfit(g.gap_h, g.gap_t, 1)[0]), 3)}
    # paired bootstrap over outcomes
    rng = np.random.default_rng(0)
    outs = sorted(keys)
    def by_out(arm):
        g = R[R.arm == arm].set_index(["study", "var"])
        return {k: g.loc[[k]] for k in outs if k in g.index}
    B = {a: by_out(a) for a in ARMS}
    deltas = {}
    pairs = [(x, ARMS[0]) for x in ARMS[1:]] + [(x, ARMS[1]) for x in ARMS[2:]]
    for x, y in pairs:
        common = [k for k in outs if k in B[x] and k in B[y]]
        e = np.array([B[y][k].err.mean() - B[x][k].err.mean() for k in common])  # positive = x better
        bs_e, bs_c = [], []
        for _ in range(1000):
            idx = rng.integers(0, len(common), len(common))
            bs_e.append(e[idx].mean())
            gx = pd.concat([B[x][common[i]] for i in idx]); gy = pd.concat([B[y][common[i]] for i in idx])
            bs_c.append(np.corrcoef(gx.gap_h, gx.gap_t)[0, 1] - np.corrcoef(gy.gap_h, gy.gap_t)[0, 1])
        deltas[f"{x} vs {y}"] = {"segment_error_reduction_sd": [round(float(e.mean()), 4), round(float(np.percentile(bs_e, 2.5)), 4), round(float(np.percentile(bs_e, 97.5)), 4)],
                                 "gap_corr_gain": [round(float(np.mean(bs_c)), 4), round(float(np.percentile(bs_c, 2.5)), 4), round(float(np.percentile(bs_c, 97.5)), 4)]}
    by_attr = R.groupby(["attr", "arm"]).apply(lambda g: round(float(np.corrcoef(g.gap_h, g.gap_t)[0, 1]), 3)).unstack().to_dict("index")
    res = {"outcomes": len(keys), "summary": summ, "deltas": deltas, "gap_corr_by_attr": by_attr}
    (M.OUT / f"segments{tag}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1:], tag="_" + sys.argv[-1].split("@")[-1])
    else:
        run()
