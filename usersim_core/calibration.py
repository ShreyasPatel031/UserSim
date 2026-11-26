"""Walk-forward Calibration Ledger & Category Error-Bank Memory (< D strictly).

Maintains causal, expanding-window calibration statistics per 00:05-knowable category:
1. Empirical-Bayes shrunk structural residual prior per category (strictly from days < D),
   capturing systematic structural blind spots (e.g. generic AI agent wrappers underperforming
   maker reach vs concrete screenshot/extension/game tools outperforming maker reach).
2. Verified category failure/delight exemplars from days < D injected into cohort prompts so
   simulated users calibrate skepticism to real historical crowd outcomes rather than LLM hype.
3. Gold-trace selection weights for downstream open-model distillation (CUA + comment traces
   whose simulated residual direction and critique matched real post-structural outcomes).
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


class WalkForwardCalibrator:
    """Strictly causal (< D) category calibration memory & Gold-Trace selector."""

    def __init__(self, prior_strength: float = 18.0):
        self.prior_strength = prior_strength

    def category_prior_as_of(self, history_df: pd.DataFrame, day: str) -> dict[str, dict]:
        """Compute empirical-Bayes shrunk residual stats strictly from rows with `row.day < day`.

        history_df columns required:
          day, category_0005, true_log_residual, rank_miss (structural_rank - real_rank, positive = beat arm3),
          title, product_trait
        """
        past = history_df[history_df["day"] < day]
        if len(past) == 0:
            return {}

        global_mean = float(past["true_log_residual"].mean())
        out: dict[str, dict] = {}
        for cat, g in past.groupby("category_0005"):
            if not cat or cat == "unknown":
                continue
            n = len(g)
            raw_mean = float(g["true_log_residual"].mean())
            shrunk = (n * raw_mean + self.prior_strength * global_mean) / (n + self.prior_strength)
            win_rate = float((g["true_log_residual"] > 0).mean())

            # Concrete < D exemplars for prompt calibration (no post-D leak)
            g_sorted = g.sort_values("true_log_residual")
            flops = [str(t) for t in g_sorted.head(2)["title"].tolist()] if n >= 5 else []
            hits = [str(t) for t in g_sorted.tail(2)["title"].tolist()] if n >= 5 else []
            out[str(cat)] = {
                "n_past": int(n),
                "shrunk_log_resid": round(shrunk, 4),
                "raw_log_resid": round(raw_mean, 4),
                "beat_struct_rate": round(win_rate, 3),
                "past_underperformers": flops,
                "past_overperformers": hits,
            }
        return out

    def render_category_note(self, cat: str, priors: dict[str, dict]) -> str:
        """Render concise < D calibration note for category `cat` to ground frontier cohort evaluators."""
        info = priors.get(cat)
        if not info or info["n_past"] < 6:
            return f"Category `{cat or 'General'}`: limited prior calibration history (<6 launches); judge strictly on concrete product execution and immediate utility."
        delta = info["shrunk_log_resid"]
        direction = (
            "historically OVER-PREDICTED by structural hype (crowded wrapper fatigue; real users penalize vague pitches/waitlists)"
            if delta < -0.06
            else "historically UNDER-PREDICTED by structural reach (real users strongly reward instant utility/demos here)"
            if delta > 0.06
            else "historically neutral relative to structural baseline"
        )
        return (
            f"Category `{cat}` (n={info['n_past']} prior launches before today): {direction} "
            f"(beat-baseline rate={info['beat_struct_rate']*100:.0f}%, mean log-residual={delta:+.2f})."
        )

    def build_ledger_table(
        self,
        scored_df: pd.DataFrame,
        domain: str = "producthunt",
        through_day: str = "2026-09-30",
        evaluator_model: str = "ensemble:gpt-oss-120b+gemini-2.5-pro",
    ) -> pd.DataFrame:
        """Materialize CALIBRATION_LEDGER rows strictly up to `through_day`."""
        sub = scored_df[scored_df["day"] <= through_day].copy()
        if len(sub) == 0:
            return pd.DataFrame()

        rows = []
        groups = [("*", sub)] + [(str(c), g) for c, g in sub.groupby("category_0005") if len(g) >= 12]
        for cat_name, g in groups:
            rhos = []
            for _, dg in g.groupby("day"):
                if len(dg) >= 5 and dg["sim_pred_resid"].std() > 1e-8 and dg["true_log_residual"].std() > 1e-8:
                    r, _ = spearmanr(dg["sim_pred_resid"], dg["true_log_residual"])
                    if np.isfinite(r):
                        rhos.append(float(r))
            mean_rho = float(np.mean(rhos)) if rhos else 0.0

            # Reach-matched tie accuracy within group
            tie_correct, tie_total = 0, 0
            for _, dg in g.groupby("day"):
                arr_s = dg["structural_score"].to_numpy()
                arr_v = dg["real_votes"].to_numpy()
                arr_p = dg["final_score"].to_numpy()
                for i in range(len(dg)):
                    for j in range(i + 1, len(dg)):
                        if abs(arr_s[i] - arr_s[j]) <= 0.15 and max(arr_v[i], arr_v[j]) >= 1.5 * max(1.0, min(arr_v[i], arr_v[j])):
                            tie_total += 1
                            if (arr_p[i] - arr_p[j]) * (arr_v[i] - arr_v[j]) > 0:
                                tie_correct += 1
            tie_acc = (tie_correct / tie_total) if tie_total > 0 else 0.5

            # Gold traces: clean product inspection + residual sign matches reality with |true_log_residual| >= 0.15
            gold_n = int(
                (
                    (g["access_clean"] > 0.5)
                    & (g["sim_pred_resid"] * g["true_log_residual"] > 0)
                    & (g["true_log_residual"].abs() >= 0.15)
                ).sum()
            )
            eb = {
                "mean_true_resid": round(float(g["true_log_residual"].mean()), 4),
                "tie_pairs": tie_total,
                "clean_share": round(float(g["access_clean"].mean()), 3),
            }
            rows.append({
                "cal_id": f"{domain}:{through_day}:{cat_name}",
                "domain": domain,
                "through_day": through_day,
                "category": cat_name,
                "evaluator_model": evaluator_model,
                "n_items": int(len(g)),
                "residual_spearman": round(mean_rho, 4),
                "pairwise_tie_acc": round(float(tie_acc), 4),
                "top10_lift_pts": 0.0,
                "gold_trace_count": gold_n,
                "error_bank_json": json.dumps(eb),
            })
        return pd.DataFrame(rows)
