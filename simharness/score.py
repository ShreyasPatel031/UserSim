"""Scorer and leaderboard for Task V.

Per item (launch) with N >= 1 held endorsers in the pool:
  recall@N  share of the N real endorsers among the model's top N of the pool
  AUC       ranking AUC of positives vs pool negatives (ties count half)
  ECE       expected calibration error over 10 equal-width probability bins (pooled over all scored pairs)

Aggregates: recall@N pooled (sum hits / sum N, as E5 reports it) and mean per item; AUC mean per item; ECE pooled.
Intervals: day-clustered bootstrap (resample days with replacement; all items of a day move together), 95%.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

NBINS = 10


def _auc(p: np.ndarray, y: np.ndarray) -> float:
    n1 = y.sum(); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return np.nan
    r = rankdata(p)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _bins(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    b = np.clip((p * NBINS).astype(int), 0, NBINS - 1)
    return np.stack([np.bincount(b, minlength=NBINS), np.bincount(b, weights=p, minlength=NBINS),
                     np.bincount(b, weights=y, minlength=NBINS)]).astype(float)


def _ece(B: np.ndarray) -> float:
    n = B[0].sum()
    if n == 0:
        return np.nan
    m = B[0] > 0
    return float(np.sum(np.abs(B[1][m] - B[2][m])) / n)


def score_item(p: np.ndarray, y: np.ndarray, rng: np.random.Generator | None = None) -> dict:
    """Metrics for one item. NaN scores (failed calls) rank last; random tie-break for recall@N."""
    p = np.where(np.isnan(p), -np.inf, p)
    N = int(y.sum())
    rng = rng or np.random.default_rng(0)
    order = np.lexsort((rng.random(len(p)), -p))
    hits = int(y[order[:N]].sum()) if N else 0
    pc = np.clip(np.where(np.isfinite(p), p, 0.0), 0, 1)
    return {"N": N, "hits": hits, "auc": _auc(p, y), "n": int(len(y)), "bins": _bins(pc, y)}


def evaluate_full(model, bench, days: list[str], item_subset: set | None = None, log=print) -> pd.DataFrame:
    """Full-pool ranking for every item on `days` (or only items in item_subset)."""
    rows = []
    for d in days:
        pool = bench.pool(d)
        its = [i for i in bench.items_on(d) if item_subset is None or i in item_subset]
        if not len(pool) or not its:
            continue
        model.prepare(bench, d)
        b = bench.batch(d, pool)
        t = time.time()
        for it in its:
            y = np.isin(pool, bench.positives(d, it)).astype(np.int8)
            if y.sum() == 0:
                continue
            r = score_item(model.score(b, bench.item(it)), y)
            rows.append({"day": d, "item_idx": int(it), **r})
        log(f"  {model.name} {d}: {len(its)} items, pool {len(pool)}, {time.time() - t:.1f}s")
    return pd.DataFrame(rows)


def evaluate_sample(model, bench, sample: pd.DataFrame) -> pd.DataFrame:
    """Score a fixed sample: columns day, item_idx, person_idx, y. One row per item in the result."""
    rows = []
    for (d, it), g in sample.groupby(["day", "item_idx"], sort=True):
        model.prepare(bench, d)
        b = bench.batch(d, g["person_idx"].to_numpy())
        p = model.score(b, bench.item(it))
        y = g["y"].to_numpy().astype(np.int8)
        rows.append({"day": d, "item_idx": int(it), "p": p, "y": y, **score_item(p, y)})
    return pd.DataFrame(rows)


def _agg(df: pd.DataFrame, pooled_auc: bool = False) -> dict:
    out = {"recall_at_N_pooled": df["hits"].sum() / max(df["N"].sum(), 1),
           "recall_at_N_mean": float((df["hits"] / df["N"]).mean()),
           "auc_mean": float(df["auc"].mean()),
           "ece": _ece(np.sum(np.stack(df["bins"].to_list()), axis=0))}
    if pooled_auc and "p" in df:
        p = np.concatenate(df["p"].to_list()); y = np.concatenate(df["y"].to_list())
        ok = ~np.isnan(p)
        out["auc_pooled"] = _auc(p[ok], y[ok])
    return out


def summarize(df: pd.DataFrame, n_boot: int = 2000, seed: int = 0, pooled_auc: bool = False) -> dict:
    point = _agg(df, pooled_auc)
    days = df["day"].unique()
    groups = {d: g for d, g in df.groupby("day")}
    rng = np.random.default_rng(seed)
    boots = {k: [] for k in point}
    for _ in range(n_boot):
        pick = rng.choice(days, len(days), replace=True)
        a = _agg(pd.concat([groups[d] for d in pick]), pooled_auc)
        for k in point:
            boots[k].append(a[k])
    res = {"days": int(len(days)), "items": int(len(df)), "positives": int(df["N"].sum()),
           "pairs": int(df["n"].sum())}
    for k, v in point.items():
        lo, hi = np.nanpercentile(boots[k], [2.5, 97.5])
        res[k] = {"value": round(float(v), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)]}
    return res


def paired_diff(a: pd.DataFrame, b: pd.DataFrame, metric: str = "recall_at_N_pooled", n_boot: int = 2000,
                seed: int = 0, pooled_auc: bool = False) -> dict:
    """a - b on the same items, day-clustered bootstrap."""
    keys = ["day", "item_idx"]
    m = a.merge(b, on=keys, suffixes=("_a", "_b"))
    A = m[keys + [c for c in m if c.endswith("_a")]].rename(columns=lambda c: c[:-2] if c.endswith("_a") else c)
    B = m[keys + [c for c in m if c.endswith("_b")]].rename(columns=lambda c: c[:-2] if c.endswith("_b") else c)
    point = _agg(A, pooled_auc)[metric] - _agg(B, pooled_auc)[metric]
    days = m["day"].unique()
    ga = {d: g for d, g in A.groupby("day")}; gb = {d: g for d, g in B.groupby("day")}
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(n_boot):
        pick = rng.choice(days, len(days), replace=True)
        bs.append(_agg(pd.concat([ga[d] for d in pick]), pooled_auc)[metric]
                  - _agg(pd.concat([gb[d] for d in pick]), pooled_auc)[metric])
    lo, hi = np.nanpercentile(bs, [2.5, 97.5])
    return {"metric": metric, "diff": round(float(point), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)]}


def write_leaderboard(entries: list[dict], path_json: str, path_md: str, title: str = "Task V leaderboard") -> None:
    """entries: {"model", "eval", "summary": summarize(...), "cost_usd", "notes"}"""
    with open(path_json, "w") as f:
        json.dump(entries, f, indent=1, default=float)

    def fmt(s, k, pct=True):
        if k not in s:
            return ""
        v, (lo, hi) = s[k]["value"], s[k]["ci95"]
        f = 100 if pct else 1
        d = 1 if pct else 3
        return f"{v * f:.{d}f} [{lo * f:.{d}f}, {hi * f:.{d}f}]"

    lines = [f"# {title}", "", "| Model | Eval | recall@N pooled | recall@N mean | AUC (mean per item) | AUC pooled | ECE "
             "| Days | Items | Positives | Cost USD |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in entries:
        s = e["summary"]
        lines.append(f"| {e['model']} | {e['eval']} | {fmt(s, 'recall_at_N_pooled')} | {fmt(s, 'recall_at_N_mean')} "
                     f"| {fmt(s, 'auc_mean', False)} | {fmt(s, 'auc_pooled', False)} | {fmt(s, 'ece', False)} "
                     f"| {s['days']} | {s['items']} | {s['positives']} | {e.get('cost_usd', 0):.2f} |")
    lines += ["", "Intervals: day-clustered bootstrap, 95%."]
    with open(path_md, "w") as f:
        f.write("\n".join(lines) + "\n")
