"""HUMAINE as a UserSim benchmark (P4 overall choice + reasons, P3 task outcome), with no in-dataset evidence.

Data: ProlificAI/humaine-evaluation-dataset (MIT), downloaded to data/humaine/ (feedback_dataset.csv,
conversations_metadata_dataset.csv). 51,456 comparisons of two AI chat products by US/UK adults, each judged on five
dimensions (A / B / tie).

Cells
  P4  (unordered product pair, segment) -> distribution over [first product wins, second wins, tie] for each of the five
      dimensions; 'overall_winner' is the primary target. Pair order is canonical (alphabetical), so answers are mapped
      from the A/B position shown to the participant. Segments: everyone, age band, country, political leaning,
      education, ethnicity. A cell needs >= MIN_N comparisons.
  P3  (product, task type) -> distribution of the 1-5 goal achievement score of conversations with that product on that
      task type (provenance of this score is not documented on the dataset card: treated as unverified).

Scoring (same convention as SimBench)
  S = 100 * (1 - TVD(pred, real) / mean TVD(uniform, real)) per task; 0 = uniform guess, 100 = exact.
  Ceiling: expected S of the TRUE distribution against a sample of the cell's size (multinomial resampling of the
  observed distribution), so 'share of ceiling' separates model error from sampling noise.
  P4 extras: winner accuracy on pairs with a statistically clear winner, Spearman of predicted vs real net preference,
  and segment-gap correlation (does it predict how young vs old, UK vs US, left vs right differ on the same pair).

Rule: predictors may use any EXTERNAL data (other benchmarks, public leaderboards, product metadata) but never other
HUMAINE rows. In-dataset references (e.g. a Bradley-Terry fit on other HUMAINE pairs) are reported separately and
labelled as such; they are a yardstick, not an allowed method."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "humaine"
OUT = ROOT / "results" / "humaine"
METRICS = ["overall_winner", "core_task_performance_and_reasoning", "interaction_fluidity_and_adaptiveness",
           "communication_style_and_presentation", "trust_ethics_and_safety"]
MIN_N = 25
LEFT = {"Labour", "Green Party", "Liberal Democrats", "Democrat"}
RIGHT = {"Conservative", "Reform UK", "Republican"}


def load():
    f = pd.read_csv(DATA / "feedback_dataset.csv")
    f = f[f.choice.isin(["A", "B", "tie"])].copy()
    first = f[["model_a", "model_b"]].min(axis=1)
    second = f[["model_a", "model_b"]].max(axis=1)
    swapped = f.model_a != first
    f["m1"], f["m2"] = first, second
    f["y"] = np.where(f.choice == "tie", 2, np.where((f.choice == "A") ^ swapped, 0, 1))  # 0 = m1 wins, 1 = m2 wins, 2 = tie
    age = pd.to_numeric(f.age, errors="coerce")
    f["age_band"] = pd.cut(age, [17, 34, 54, 120], labels=["18-34", "35-54", "55+"]).astype(str)
    pol = f.political_affiliation.fillna("")
    f["leaning"] = np.where(pol.isin(LEFT), "left", np.where(pol.isin(RIGHT), "right", np.where(pol == "Independent", "independent", "")))
    f["edu"] = f.education_level.fillna("")
    f["eth"] = f.ethnic_group.where(~f.ethnic_group.isin(["DATA_EXPIRED", "Prefer not to say"]), "")
    f["country"] = f.country_of_residence.fillna("")
    c = pd.read_csv(DATA / "conversations_metadata_dataset.csv")
    return f, c


SEGMENTS = [("all", None, "all participants (UK and US adults)")] + \
    [("age_band", v, f"participants aged {v}") for v in ("18-34", "35-54", "55+")] + \
    [("country", v, f"participants living in the {v}") for v in ("United Kingdom", "United States")] + \
    [("leaning", "left", "participants who support a left-of-centre party (Labour, Green, Liberal Democrats or Democrat)"),
     ("leaning", "right", "participants who support a right-of-centre party (Conservative, Reform UK or Republican)"),
     ("leaning", "independent", "participants who identify as political independents (US)")] + \
    [("edu", v, f"participants whose education level is {v.replace('_', '-')}") for v in ("pre_tertiary", "tertiary", "postgraduate")] + \
    [("eth", v, f"participants who identify as {v}") for v in ("White", "Black", "Asian", "Mixed", "Latino/Hispanic")]


def p4_cells(f, min_n=MIN_N):
    """One row per (pair, segment) with the five real distributions and n."""
    rows = []
    wide = f.pivot_table(index=["conversation_id", "m1", "m2", "age_band", "country", "leaning", "edu", "eth"], columns="metric", values="y", aggfunc="first").reset_index()
    for key, val, desc in SEGMENTS:
        g = wide if key == "all" else wide[wide[key] == val]
        for (m1, m2), d in g.groupby(["m1", "m2"]):
            if len(d) < min_n:
                continue
            dist = {m: np.bincount(d[m].dropna().astype(int), minlength=3) / max(d[m].notna().sum(), 1) for m in METRICS}
            rows.append({"cell": f"{m1}|{m2}|{key}={val}", "m1": m1, "m2": m2, "seg_key": key, "seg_val": val or "all", "seg_desc": desc,
                         "n": int(len(d)), **{f"real_{m}": dist[m].tolist() for m in METRICS}})
    return pd.DataFrame(rows)


def p3_cells(c, min_n=40, top_tasks=10):
    tasks = c.task_type.value_counts().index[:top_tasks]
    rows = []
    for (m, t), d in c[c.task_type.isin(tasks)].groupby(["model_name", "task_type"]):
        s = pd.to_numeric(d.goal_achievement_score, errors="coerce").dropna().astype(int)
        s = s[(s >= 1) & (s <= 5)]
        if len(s) < min_n:
            continue
        rows.append({"cell": f"{m}|{t}", "model": m, "task_type": t, "n": int(len(s)), "real": (np.bincount(s - 1, minlength=5) / len(s)).tolist()})
    return pd.DataFrame(rows)


def tvd(p, q):
    return 0.5 * np.abs(np.asarray(p, float) - np.asarray(q, float)).sum(-1)


def ceiling_tvd(real, n, reps=200, seed=0):
    """Expected TVD between the true distribution (taken as the observed one) and a fresh sample of size n."""
    rng = np.random.default_rng(seed)
    real = np.asarray(real, float)
    real = real / real.sum()
    draws = rng.multinomial(int(n), real, size=reps) / float(n)
    return float(np.mean(0.5 * np.abs(draws - real).sum(1)))


def score(preds, reals, ns):
    """S per cell, mean S and mean ceiling S (same normalizer: mean TVD of uniform)."""
    reals = np.asarray(reals, float)
    k = reals.shape[1]
    norm = float(np.mean(tvd(np.full(k, 1.0 / k), reals)))
    s = 100 * (1 - tvd(np.asarray(preds, float), reals) / norm)
    ceil = 100 * (1 - np.array([ceiling_tvd(r, n) for r, n in zip(reals, ns)]) / norm)
    return s, ceil, norm


def bootstrap_ci(x, B=2000, seed=0):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    m = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(B)]
    return [round(float(np.percentile(m, 2.5)), 2), round(float(np.percentile(m, 97.5)), 2)]


def p4_extras(cells, pred_col="pred_overall_winner"):
    """Winner accuracy on clear pairs, Spearman of net preference, segment-gap correlations (population cells / segments)."""
    from scipy.stats import binomtest, spearmanr
    out = {}
    allc = cells[cells.seg_key == "all"]
    real = np.stack(allc["real_overall_winner"].to_numpy())
    pred = np.stack(allc[pred_col].to_numpy())
    n = allc.n.to_numpy()
    w1 = np.round(real[:, 0] * n).astype(int)
    w2 = np.round(real[:, 1] * n).astype(int)
    clear = np.array([binomtest(a, a + b).pvalue < 0.05 if a + b > 0 else False for a, b in zip(w1, w2)])
    if clear.any():
        out["winner_accuracy_clear_pairs"] = round(float(np.mean(np.sign(pred[clear, 0] - pred[clear, 1]) == np.sign(real[clear, 0] - real[clear, 1]))), 4)
        out["n_clear_pairs"] = int(clear.sum())
    out["spearman_net_preference"] = round(float(spearmanr(pred[:, 0] - pred[:, 1], real[:, 0] - real[:, 1]).correlation), 4)
    out["n_pairs"] = int(len(allc))
    gaps = {}
    for key, a, b in (("age_band", "18-34", "55+"), ("country", "United Kingdom", "United States"), ("leaning", "left", "right")):
        A = cells[(cells.seg_key == key) & (cells.seg_val == a)].set_index(["m1", "m2"])
        Bc = cells[(cells.seg_key == key) & (cells.seg_val == b)].set_index(["m1", "m2"])
        common = A.index.intersection(Bc.index)
        if len(common) < 10:
            continue
        ra = np.stack(A.loc[common, "real_overall_winner"].to_numpy()); rb = np.stack(Bc.loc[common, "real_overall_winner"].to_numpy())
        pa = np.stack(A.loc[common, pred_col].to_numpy()); pb = np.stack(Bc.loc[common, pred_col].to_numpy())
        real_gap = (ra[:, 0] - ra[:, 1]) - (rb[:, 0] - rb[:, 1])
        pred_gap = (pa[:, 0] - pa[:, 1]) - (pb[:, 0] - pb[:, 1])
        r = float(np.corrcoef(real_gap, pred_gap)[0, 1]) if np.std(pred_gap) > 1e-9 else 0.0
        gaps[f"{key}:{a}_vs_{b}"] = {"pairs": int(len(common)), "corr": round(r, 4), "real_gap_sd": round(float(np.std(real_gap)), 4)}
    out["segment_gap_correlation"] = gaps
    return out


def build_cells():
    OUT.mkdir(parents=True, exist_ok=True)
    f, c = load()
    p4 = p4_cells(f)
    p3 = p3_cells(c)
    p4.to_pickle(OUT / "p4_cells.pkl")
    p3.to_pickle(OUT / "p3_cells.pkl")
    tie = {m: round(float((f[f.metric == m].y == 2).mean()), 3) for m in METRICS}
    info = {"comparisons": int(f.conversation_id.nunique()), "products": int(len(set(f.m1) | set(f.m2))), "p4_cells": int(len(p4)),
            "p4_cells_by_segment": p4.seg_key.value_counts().to_dict(), "p3_cells": int(len(p3)), "tie_rate_by_dimension": tie}
    (OUT / "cells_info.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))
    return p4, p3


if __name__ == "__main__":
    build_cells()
