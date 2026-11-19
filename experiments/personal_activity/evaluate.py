"""Run every model on every task and collect metrics + per-point losses."""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from typing import Any

from .llm_sim import LLMSimulator, llm_next_rank
from .metrics import auc, brier, log_err, mean, paired_bootstrap, topk_hits, tv_distance
from .models import (
    CallModel,
    DayBaselines,
    DayPred,
    DayRollout,
    PersonalSimulator,
    SwitchBaselines,
    SwitchStats,
    rank,
)
from .tasks import Dataset, SwitchPoint

# metric -> (task, lower_is_better, description)
KEY_METRICS: dict[str, tuple[str, str]] = {
    "next_top1": ("next context", "top-1 accuracy of the next app/domain"),
    "next_top3": ("next context", "top-3 accuracy of the next app/domain"),
    "dwell_log_mae": ("time to next switch", "mean |log10 predicted - log10 actual| dwell"),
    "idle_brier": ("goes idle soon", "Brier score of P(idle within horizon)"),
    "first_active_mae": ("daily shape", "first-active time error, minutes"),
    "active_mae": ("daily shape", "total active time error, minutes"),
    "share_tv": ("daily shape", "total-variation distance of time shares (0..1)"),
    "call_brier": ("calls", "Brier score of P(call) per slot"),
}
HIGHER_IS_BETTER = {"next_top1", "next_top3"}


def _loss(metric: str, v: float) -> float:
    """Per-point value -> loss (lower is better) for bootstrap comparisons."""
    return 1.0 - v if metric in HIGHER_IS_BETTER else v


class Collector:
    def __init__(self) -> None:
        # model -> metric -> list of (group/day, value)
        self.pp: dict[str, dict[str, list[tuple[str, float]]]] = defaultdict(lambda: defaultdict(list))
        self.extra: dict[str, dict[str, Any]] = defaultdict(dict)

    def add(self, model: str, metric: str, day: str, v: float) -> None:
        self.pp[model][metric].append((day, v))

    def summary(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for m, mets in self.pp.items():
            out[m] = {k: mean([v for _, v in xs]) for k, xs in mets.items()}
            out[m].update(self.extra.get(m, {}))
        return out


def eval_switch(ds: Dataset, pts: list[SwitchPoint], models: dict[str, Any], col: Collector) -> None:
    for name, (nr, dw, pi) in models.items():
        scores, ys = [], []
        for p in pts:
            if p.next is not None and nr is not None:
                r = nr(p)
                col.add(name, "next_top1", p.day, topk_hits(r, p.next, 1))
                col.add(name, "next_top3", p.day, topk_hits(r, p.next, 3))
            if dw is not None:
                d = dw(p)
                col.add(name, "dwell_mae_s", p.day, abs(d - p.dur))
                col.add(name, "dwell_log_mae", p.day, log_err(d, p.dur))
            if pi is not None:
                q = pi(p)
                if q is None:
                    continue
                col.add(name, "idle_brier", p.day, brier(q, p.idle_soon))
                scores.append(q)
                ys.append(int(p.idle_soon))
        if scores:
            col.extra[name]["idle_auc"] = auc(scores, ys)


def eval_days(ds: Dataset, preds: dict[str, dict[str, DayPred]], col: Collector) -> None:
    for name, by_day in preds.items():
        allp, ally = [], []
        cover_f = cover_a = 0
        for day, pr in by_day.items():
            a = ds.days[day]
            col.add(name, "first_active_mae", day, abs(pr.first_min - a.first_min))
            col.add(name, "active_mae", day, abs(pr.active_min - a.active_min))
            col.add(name, "share_tv", day, tv_distance(pr.shares, a.shares))
            col.add(name, "calls_per_day_err", day, abs(sum(pr.call_p) - len(a.call_slots)))
            for s, p in enumerate(pr.call_p):
                y = int(s in a.call_slots)
                col.add(name, "call_brier", day, brier(p, y))
                allp.append(p)
                ally.append(y)
            if pr.first_iv:
                cover_f += pr.first_iv[0] <= a.first_min <= pr.first_iv[1]
                cover_a += pr.active_iv[0] <= a.active_min <= pr.active_iv[1]
        if allp:
            col.extra[name]["call_auc"] = auc(allp, ally)
        if by_day and any(p.first_iv for p in by_day.values()):
            col.extra[name]["first_active_80pct_coverage"] = cover_f / len(by_day)
            col.extra[name]["active_80pct_coverage"] = cover_a / len(by_day)


def compare(col: Collector, challenger: str, baselines: list[str], restrict: set[str] | None = None) -> dict:
    """For each key metric: best baseline on this test set vs the challenger,
    with a day-clustered paired bootstrap CI on the loss difference."""
    out = {}
    for metric in KEY_METRICS:
        ch = col.pp.get(challenger, {}).get(metric)
        if not ch:
            continue
        best, best_v = None, math.inf
        for b in baselines:
            xs = col.pp.get(b, {}).get(metric)
            if not xs or len(xs) != len(ch):
                continue
            v = mean([_loss(metric, x) for _, x in xs])
            if v < best_v:
                best, best_v = b, v
        if best is None:
            continue
        bx = col.pp[best][metric]
        bs = paired_bootstrap(
            [_loss(metric, v) for _, v in ch], [_loss(metric, v) for _, v in bx], [d for d, _ in ch]
        )
        ch_v = mean([v for _, v in ch])
        b_v = mean([v for _, v in bx])
        sig = bs["hi"] < 0
        out[metric] = {
            "challenger": ch_v,
            "best_baseline": best,
            "baseline": b_v,
            "loss_diff": bs["diff"],
            "ci90": [bs["lo"], bs["hi"]],
            "verdict": "better (CI excludes 0)" if sig else ("better" if bs["diff"] < 0 else "not better"),
        }
    return out


def run_all(ds: Dataset, *, rollouts: int = 100, llm: LLMSimulator | None = None, seed: int = 0) -> dict:
    train_pts = ds.pts(ds.train_days)
    test_pts = ds.pts(ds.test_days)
    bl = SwitchBaselines(ds, train_pts)
    sim = PersonalSimulator(ds).fit(train_pts, ds.val_days)

    switch_models: dict[str, tuple] = {
        n: (lambda p, n=n: bl.next_rank(n, p), lambda p, n=n: bl.dwell(n, p), lambda p, n=n: bl.p_idle(n, p))
        for n in SwitchBaselines.NAMES
    }
    switch_models["simulator"] = (sim.next_rank, sim.dwell, sim.p_idle)

    col = Collector()
    eval_switch(ds, test_pts, switch_models, col)

    # ---------------- day-level, day-ahead
    order = sorted(ds.days)
    train_days = [ds.days[d] for d in order if d in set(ds.train_days)]
    dbl = DayBaselines(ds.n_slots)
    calls = CallModel(ds.n_slots).fit(train_days)
    day_preds: dict[str, dict[str, DayPred]] = defaultdict(dict)
    day_jobs = []
    for d in ds.test_days:
        hist = [ds.days[x] for x in order if x < d]
        wd = ds.days[d].weekday
        for n in DayBaselines.NAMES:
            day_preds[n][d] = dbl.predict(n, hist, wd)
        sim_d = PersonalSimulator(ds)
        sim_d.lam = sim.lam
        before = [p for p in ds.points if p.day < d]
        same_type = [p for p in before if p.weekend == (wd >= 5)]
        # Simulate a weekend from weekend behaviour once there is enough of it.
        sim_d.st = SwitchStats.fit(same_type if len(same_type) >= 200 else before)
        roll = DayRollout(sim_d, n=rollouts, seed=seed)
        day_preds["simulator"][d] = roll.predict(hist, wd, ds.timeline.day_origin(d), calls.predict(hist, wd))
        day_jobs.append((d, hist, wd))
    eval_days(ds, day_preds, col)

    results: dict[str, Any] = {
        "switch_models": list(switch_models),
        "day_models": list(day_preds),
        "n_test_switch_points": len(test_pts),
        "n_test_next_points": sum(1 for p in test_pts if p.next),
        "simulator_mixture_weights": sim.lam,
        "simulator_dwell_coef": sim.dwell_w,
    }

    # ---------------- LLM
    if llm is not None and llm.mode != "off":
        fill = bl.fill
        lres = asyncio.run(
            llm.run(bl.st, test_pts, day_jobs, lambda d: day_preds["time_of_day"][d])
        )
        results["llm"] = {
            "mode": lres.mode,
            "estimated_cost_usd": round(lres.est_cost_usd, 4),
            "spent_usd": round(lres.budget.spent_usd, 4),
            "calls": lres.budget.calls,
            "skipped_for_budget": lres.budget.skipped,
            "errors": [x for x in lres.budget.log if "error" in x][:5],
            "sampled_points": len(lres.sample_ids),
            "answered_points": len(lres.switch),
            "answered_days": sum(lres.days_ok.values()),
        }
        if lres.switch:
            ids = set(lres.switch)
            sub = [p for p in test_pts if p.id in ids]
            g = rank({}, fill)
            base_dwell = bl.st.med_dwell
            sub_models = dict(switch_models)
            sub_models["llm"] = (
                lambda p: llm_next_rank(lres.switch.get(p.id), g, p.cur),
                lambda p: lres.switch.get(p.id, {}).get("dwell_s") or base_dwell,
                lambda p: (lres.switch.get(p.id, {}).get("p_idle")
                           if lres.switch.get(p.id, {}).get("p_idle") is not None else bl.st.base_idle),
            )
            sub_col = Collector()
            eval_switch(ds, sub, sub_models, sub_col)
            results["llm_subset"] = {
                "n_points": len(sub),
                "metrics": sub_col.summary(),
                "vs_baselines": compare(sub_col, "llm", list(SwitchBaselines.NAMES)),
                "simulator_vs_baselines": compare(sub_col, "simulator", list(SwitchBaselines.NAMES)),
            }
        if lres.days:
            day_preds["llm"] = dict(lres.days)
            # Days the LLM did not answer fall back to the time-of-day baseline.
            for d in ds.test_days:
                day_preds["llm"].setdefault(d, day_preds["time_of_day"][d])
            eval_days(ds, {"llm": day_preds["llm"]}, col)

    results["metrics"] = col.summary()
    results["simulator_vs_baselines"] = compare(col, "simulator", list(SwitchBaselines.NAMES))
    if "llm" in col.pp:
        results["llm_days_vs_baselines"] = compare(col, "llm", list(DayBaselines.NAMES))
    return results
