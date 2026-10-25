"""Choose sources and settings on validation months, report on later test months only.

Validation: June-July 2026. Test: August-October 2026 (never used for any choice). Each month is still predicted
by a model trained only on earlier months. Selection metric: mean of day@5 and week@10 recall.
  1. Greedy forward selection over source groups (add the group that helps most; stop when nothing helps).
  2. Small LightGBM settings grid on the chosen groups.
  3. Optional average with a per-day LambdaRank model.
Writes out/optimize.json.

    python experiments/ph_predict/optimize.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as E  # noqa: E402
import features as F  # noqa: E402

VAL, TEST = ["2026-06", "2026-07"], ["2026-08", "2026-09", "2026-10"]
GRID = [{}, dict(num_leaves=7, n_estimators=800), dict(num_leaves=31, min_child_samples=40),
        dict(colsample_bytree=0.4), dict(n_estimators=1000, learning_rate=0.015), dict(reg_lambda=10.0)]


def metric(r: dict) -> float:
    return float(np.mean([r[k]["recall"] for k in ("day@5", "week@10") if k in r]))


def rank_backtest(df, X, cols, months, params):
    s = pd.Series(np.nan, index=df.index)
    for m in months:
        tr, te = (df.month < m).to_numpy(), (df.month == m).to_numpy()
        d = df[tr].sort_values("day")
        rel = np.select([d.dailyRank <= 3, d.dailyRank <= 5, d.dailyRank <= 10, d.dailyRank <= 20], [4, 3, 2, 1], 0)
        model = lgb.LGBMRanker(**params).fit(X.loc[d.index, cols], rel, group=d.groupby("day", sort=True).size().to_numpy())
        s[te] = model.predict(X[cols][te])
    return s


def zscore_by_day(df, s):
    return (s - s.groupby(df.day).transform("mean")) / (s.groupby(df.day).transform("std") + 1e-9)


def main() -> None:
    df, X, groups = F.build()
    keep = df.complete.to_numpy()
    df, X = df[keep].reset_index(drop=True), X[keep].reset_index(drop=True)
    groups = {g: c for g, c in groups.items() if c and g != "followers"}
    val = lambda cols, params=None: metric(E.recall_lists(df, bt(cols, VAL, params)))  # noqa: E731

    def bt(cols, months, params=None):
        saved = E.PARAMS
        E.PARAMS = {**saved, **(params or {})}
        try:
            return E.backtest(df, X, cols, months)
        finally:
            E.PARAMS = saved

    chosen, best, log = [], 0.0, []
    while True:
        trials = {g: val([c for x in chosen + [g] for c in groups[x]]) for g in groups if g not in chosen}
        if not trials:
            break
        g, v = max(trials.items(), key=lambda kv: kv[1])
        log.append({"step": len(chosen) + 1, "trials": {k: round(x, 3) for k, x in trials.items()}, "picked": g})
        print("step", len(chosen) + 1, "best", g, round(v, 3), "vs", round(best, 3), flush=True)
        if v <= best + 0.003:
            break
        chosen.append(g)
        best = v
    cols = [c for x in chosen for c in groups[x]]
    grid = {json.dumps(p): val(cols, p) for p in GRID}
    params = json.loads(max(grid, key=grid.get))
    print("grid", {k: round(v, 3) for k, v in grid.items()}, flush=True)

    reg_val = bt(cols, VAL, params)
    rank_val = rank_backtest(df, X, cols, VAL, {**E.PARAMS, **params})
    blend_val = zscore_by_day(df, reg_val) + zscore_by_day(df, rank_val)
    use_blend = metric(E.recall_lists(df, blend_val)) > metric(E.recall_lists(df, reg_val)) + 0.003

    # Test months only, nothing chosen on them
    out = {"validation": VAL, "test": TEST, "selection_log": log, "chosen_groups": chosen, "params": params,
           "blend_with_lambdarank": use_blend, "test_results": {}}
    pre = [c for g in E.PRE for c in groups[g]]
    first4 = [c for g in E.CONFIGS[E.HEADLINE] if g in groups for c in groups[g]]
    for name, s in [("pre-launch (previous)", bt(pre, TEST)), ("first 4 hours (previous headline)", bt(first4, TEST)),
                    ("optimized", bt(cols, TEST, params))]:
        if name == "optimized" and use_blend:
            s = zscore_by_day(df, s) + zscore_by_day(df, rank_backtest(df, X, cols, TEST, {**E.PARAMS, **params}))
        r = E.recall_lists(df, s, complete_months=["2026-08", "2026-09"])
        out["test_results"][name] = {k: {"recall": v["recall"], "random": v["random"], "lists": v["lists"],
                                         "ci95": v["ci95"]} for k, v in r.items()}
        print(name, {k: v["recall"] for k, v in r.items()}, flush=True)
    (E.OUT / "optimize.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
