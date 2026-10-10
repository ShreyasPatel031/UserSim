"""Score HUMAINE predictions: every arm on the same cells, with ceilings, extras and in-dataset yardsticks kept separate.

Arms scored
  uniform                       no information (S = 0 by construction)
  gemini_plain / _meta / _arena Gemini 2.5 Flash with the given external context (humaine_predict.py)
  arena_direct                  no LLM: LMArena Elo win probability + external tie share (humaine_external.py)
  blend_plain_arena             fixed 50/50 average of gemini_plain and arena_direct (weights fixed a priori, not tuned
                                on HUMAINE); falls back to gemini_plain where a product has no arena rating
Yardsticks (USE HUMAINE ROWS - not allowed for our methods; shown only to size the gap)
  ref_bt_leave_pair_out         Bradley-Terry strengths fitted on all OTHER HUMAINE pairs, tie share of other pairs
  ref_tie_prior                 HUMAINE's own tie rate per dimension with a 50/50 split of the rest

Writes results/humaine/scores.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim import humaine_bench as HB
from human_sim import humaine_external as X

OUT = HB.OUT


def load_preds(arm, task):
    p = OUT / f"preds_{arm}_{task}.jsonl"
    if not p.exists():
        return None
    recs = {}
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["cell"]] = r
    return recs


def bt_leave_pair_out(f):
    """In-dataset yardstick: BT on decisive overall votes of all other pairs; tie share of all other pairs."""
    ow = f[f.metric == "overall_winner"]
    prods = sorted(set(ow.m1) | set(ow.m2))
    ix = {p: i for i, p in enumerate(prods)}
    g = ow.groupby(["m1", "m2"]).y.agg(w1=lambda s: (s == 0).sum(), w2=lambda s: (s == 1).sum(), t=lambda s: (s == 2).sum()).reset_index()
    W = np.zeros((len(prods), len(prods)))
    for r in g.itertuples():
        W[ix[r.m1], ix[r.m2]] += r.w1
        W[ix[r.m2], ix[r.m1]] += r.w2
    ties_all, n_all = g.t.sum(), (g.w1 + g.w2 + g.t).sum()
    out = {}
    for r in g.itertuples():
        i, j = ix[r.m1], ix[r.m2]
        Wm = W.copy()
        Wm[i, j] = Wm[j, i] = 0
        s = np.ones(len(prods))
        N = Wm + Wm.T
        wins = Wm.sum(1)
        for _ in range(200):  # MM updates
            denom = (N / (s[:, None] + s[None, :] + 1e-12)).sum(1)
            s = np.where(denom > 0, (wins + 0.1) / (denom + 1e-12), s)
            s /= np.exp(np.mean(np.log(s)))
        p = s[i] / (s[i] + s[j])
        t = (ties_all - r.t) / max(n_all - (r.w1 + r.w2 + r.t), 1)
        out[(r.m1, r.m2)] = [(1 - t) * p, (1 - t) * (1 - p), t]
    return out


def evaluate():
    f, c = HB.load()
    p4 = pd.read_pickle(OUT / "p4_cells.pkl")
    p3 = pd.read_pickle(OUT / "p3_cells.pkl")
    res = {"cells": {"p4": int(len(p4)), "p3": int(len(p3))}, "p4": {}, "p3": {}, "notes": []}

    # ---- assemble P4 predictions per arm (every arm on every cell)
    arms = {}
    for arm in ("plain", "meta", "arena"):
        pr = load_preds(arm, "p4")
        if pr and len(pr) >= 0.98 * len(p4):
            arms[f"gemini_{arm}"] = {cell: pr[cell]["pred"] for cell in p4.cell if cell in pr}
    direct = {}
    for r in p4.itertuples():
        d = X.arena_direct_p4(r.m1, r.m2)
        direct[r.cell] = {m: d if d is not None else [1 / 3] * 3 for m in HB.METRICS}
    arms["arena_direct"] = direct
    if "gemini_plain" in arms:
        bl = {}
        for r in p4.itertuples():
            d = X.arena_direct_p4(r.m1, r.m2)
            g = arms["gemini_plain"].get(r.cell)
            if g is None:
                continue
            bl[r.cell] = {m: (0.5 * np.asarray(g[m]) + 0.5 * np.asarray(d)).tolist() if d is not None else g[m] for m in HB.METRICS}
        arms["blend_plain_arena"] = bl
    bt = bt_leave_pair_out(f)
    tie = {m: float((f[f.metric == m].y == 2).mean()) for m in HB.METRICS}
    arms["ref_bt_leave_pair_out"] = {r.cell: {m: bt[(r.m1, r.m2)] if m == "overall_winner" else [(1 - tie[m]) / 2, (1 - tie[m]) / 2, tie[m]] for m in HB.METRICS} for r in p4.itertuples()}
    arms["ref_tie_prior"] = {r.cell: {m: [(1 - tie[m]) / 2, (1 - tie[m]) / 2, tie[m]] for m in HB.METRICS} for r in p4.itertuples()}
    arms["uniform"] = {r.cell: {m: [1 / 3] * 3 for m in HB.METRICS} for r in p4.itertuples()}

    common = set(p4.cell)
    for a in arms.values():
        common &= set(a)
    P = p4[p4.cell.isin(common)].reset_index(drop=True)
    res["p4_common_cells"] = int(len(P))
    ceil_cache = {}
    for arm, pr in arms.items():
        row = {}
        for m in HB.METRICS:
            reals = np.stack(P[f"real_{m}"].to_numpy())
            preds = np.stack([pr[c][m] for c in P.cell])
            s, ceil, norm = HB.score(preds, reals, P.n.to_numpy())
            ceil_cache[m] = ceil
            row[m] = {"S": round(float(s.mean()), 2), "ci": HB.bootstrap_ci(s), "ceiling": round(float(ceil.mean()), 2)}
            if m == "overall_winner":
                by = {}
                for k, g in P.groupby("seg_key").groups.items():
                    by[k] = round(float(s[list(g)].mean()), 2)
                row[m]["by_segment_type"] = by
        P["pred_overall_winner"] = [pr[c]["overall_winner"] for c in P.cell]
        row["extras"] = HB.p4_extras(P)
        res["p4"][arm] = row

    # ---- P3
    p3arms = {}
    for arm in ("plain", "meta", "arena"):
        pr = load_preds(arm, "p3")
        if pr and len(pr) >= 0.98 * len(p3):
            p3arms[f"gemini_{arm}"] = {cell: pr[cell]["pred"] for cell in p3.cell if cell in pr}
    p3arms["uniform"] = {cell: [0.2] * 5 for cell in p3.cell}
    allg = pd.to_numeric(c.goal_achievement_score, errors="coerce").dropna().astype(int)
    pooled = (np.bincount(allg.clip(1, 5) - 1, minlength=5) / len(allg)).tolist()
    p3arms["ref_pooled_humaine"] = {cell: pooled for cell in p3.cell}
    common3 = set(p3.cell)
    for a in p3arms.values():
        common3 &= set(a)
    Q = p3[p3.cell.isin(common3)].reset_index(drop=True)
    for arm, pr in p3arms.items():
        reals = np.stack(Q.real.to_numpy())
        preds = np.stack([pr[c] for c in Q.cell])
        s, ceil, _ = HB.score(preds, reals, Q.n.to_numpy())
        mean_pred = (preds * np.arange(1, 6)).sum(1)
        mean_real = (reals * np.arange(1, 6)).sum(1)
        res["p3"][arm] = {"S": round(float(s.mean()), 2), "ci": HB.bootstrap_ci(s), "ceiling": round(float(ceil.mean()), 2),
                          "corr_mean_score": round(float(np.corrcoef(mean_pred, mean_real)[0, 1]), 4) if np.std(mean_pred) > 1e-9 else 0.0}
    res["notes"].append("ref_* arms use HUMAINE rows and are yardsticks only; P3 goal-achievement provenance is not documented on the dataset card.")
    (OUT / "scores.json").write_text(json.dumps(res, indent=1))
    return res


def show(res):
    print(f"P4 cells scored: {res['p4_common_cells']}")
    print(f"{'arm':24s} {'overall S':>10s} {'ceiling':>8s} {'winner acc':>10s} {'spearman':>9s}  reasons S (task/fluid/style/trust)")
    for arm, r in res["p4"].items():
        o = r["overall_winner"]; e = r["extras"]
        dims = " / ".join(f"{r[m]['S']:.1f}" for m in HB.METRICS[1:])
        print(f"{arm:24s} {o['S']:10.1f} {o['ceiling']:8.1f} {e.get('winner_accuracy_clear_pairs', float('nan')):10.3f} {e['spearman_net_preference']:9.3f}  {dims}")
    print("segment gaps (corr):", {a: {k: v["corr"] for k, v in r["extras"]["segment_gap_correlation"].items()} for a, r in res["p4"].items() if a.startswith(("gemini", "arena", "blend"))})
    print("P3:", {a: (r["S"], r["ceiling"], r["corr_mean_score"]) for a, r in res["p3"].items()})


if __name__ == "__main__":
    show(evaluate())
