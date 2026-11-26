"""Walk-forward Residual Ranker & Objective Leaderboard Scorer.

Combines any domain's frozen structural baseline S_d(x) with `usersim_core` signals:
  1. Frontier Comparative Cohort Simulation (within-day z-scored endorsement/utility/substance/friction)
  2. Sanitized Live Product / CUA Execution Signals (interactive demo, OSS/CLI, free tier, waitlist/enterprise friction)
  3. UniversalUserPool Discerning-Cohort Fit (selective & critic voter match vs generic broad match)
  4. Walk-Forward (< D) Category Residual Prior & Same-Day Category Crowding

Key ML Safeguards (fixing E5's 4 bugs):
  - Never discards S_d(x): fits an L2-regularized residual shift Delta_hat(x) added to S_d(x),
    with maximum magnitude bounded by `max_shift` so outlier prompts cannot blow up top-1/top-2 locks.
  - Zero-shift fallback: if URL/surface/CUA hit a harness access failure (no_url, dead_host, captcha, block),
    product-surface features are 0-centered so missingness contributes 0 penalty (never median-imputed!).
  - Strict walk-forward / pre-test lock: hyperparameters (L2 alpha, blend scale, max_shift) are chosen
    strictly on Validation (Sep 2026) trained on Apr-Aug 2026, then frozen before touching Oct-Nov 2026.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.preprocessing import StandardScaler


# Feature groups for transparent ablation (Pool -> +Surface/CUA -> +Frontier Cohort Sim -> Full Stack)
POOL_FEATURES = [
    "pool_sim_discerning_z",
    "pool_sim_critic_z",
    "pool_selective_voters_z",
    "pool_specialist_z",
    "cat_prior_shrunk_resid",
    "same_day_cat_rivals",
]

SURFACE_CUA_FEATURES = [
    "surf_instant_demo_clean",
    "surf_open_source_clean",
    "surf_free_tier_clean",
    "surf_visible_pricing_clean",
    "surf_docs_clean",
    "surf_waitlist_clean",
    "surf_enterprise_gated_clean",
    "surf_platform_only_clean",
    "cua_reached_value_clean",
    "cua_friction_clean",
]

COHORT_LLM_FEATURES = [
    "llm_p_endorse_z",
    "llm_would_use_z",
    "llm_clarity_z",
    "llm_differentiation_z",
    "llm_substance_z",
    "llm_friction_z",
    "llm_net_conviction_z",
    "llm_pro_120b_agree_z",
]

ALL_RESIDUAL_FEATURES = POOL_FEATURES + SURFACE_CUA_FEATURES + COHORT_LLM_FEATURES


def within_day_zscore(df: pd.DataFrame, col: str, mask_col: str | None = None) -> np.ndarray:
    """Compute leak-free within-day z-score; rows failing `mask_col` receive exact 0.0 (neutral)."""
    df_r = df.reset_index(drop=True)
    out = np.zeros(len(df_r), dtype=np.float64)
    vals = df_r[col].to_numpy(dtype=np.float64)
    valid_global = np.isfinite(vals)
    if mask_col is not None:
        valid_global &= df_r[mask_col].to_numpy(dtype=bool)

    for _, idx in df_r.groupby("day").groups.items():
        pos = np.asarray(list(idx), dtype=np.int64)
        ok = valid_global[pos]
        if ok.sum() >= 2:
            v = vals[pos[ok]]
            sd = float(np.std(v))
            mu = float(np.mean(v))
            if sd > 1e-8:
                out[pos[ok]] = np.clip((v - mu) / sd, -3.0, 3.0)
    return out


@dataclass
class WalkForwardResidualModel:
    feature_cols: list[str]
    ridge_alpha: float = 250.0
    pairwise_C: float = 0.04
    target_std: float = 0.060
    max_shift: float = 0.150
    min_train_abs_rho: float = 0.030
    orthogonalize_arm3: bool = True

    def __post_init__(self) -> None:
        self.scaler = StandardScaler()
        self.ridge = Ridge(alpha=self.ridge_alpha, random_state=42)
        self.pair_clf = LogisticRegression(C=self.pairwise_C, fit_intercept=False, max_iter=500, random_state=42)
        self.active_cols: list[str] = list(self.feature_cols)
        self.ortho_betas: dict[str, float] = {}
        self.train_raw_std: float = 1.0
        self._fitted = False

    def _ortho_col(self, df: pd.DataFrame, col: str, z_arm3: np.ndarray) -> np.ndarray:
        raw = np.nan_to_num(df[col].to_numpy(dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0) if col in df.columns else np.zeros(len(df), dtype=np.float64)
        if not self.orthogonalize_arm3:
            return raw
        beta = self.ortho_betas.get(col, 0.0)
        return raw - beta * z_arm3

    def _matrix(self, df: pd.DataFrame, cols: list[str] | None = None) -> np.ndarray:
        use_cols = cols if cols is not None else self.active_cols
        if not use_cols:
            return np.zeros((len(df), 1), dtype=np.float64)
        z_arm3 = within_day_zscore(df, "structural_score") if self.orthogonalize_arm3 else np.zeros(len(df), dtype=np.float64)
        X = np.column_stack([self._ortho_col(df, c, z_arm3) for c in use_cols])
        return np.ascontiguousarray(X, dtype=np.float64)

    def fit(self, train_df: pd.DataFrame) -> "WalkForwardResidualModel":
        y_res = np.clip(train_df["true_log_residual"].to_numpy(dtype=np.float64), -1.2, 1.2)
        z_arm3_tr = within_day_zscore(train_df, "structural_score")
        var_a3 = max(float(np.var(z_arm3_tr)), 1e-6)

        self.ortho_betas = {}
        kept = []
        best_col, best_abs = None, -1.0
        for c in self.feature_cols:
            if c not in train_df.columns:
                continue
            v_raw = np.nan_to_num(train_df[c].to_numpy(dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
            if float(np.std(v_raw)) < 1e-6:
                continue
            beta = float(np.cov(v_raw, z_arm3_tr)[0, 1] / var_a3) if self.orthogonalize_arm3 else 0.0
            self.ortho_betas[c] = beta
            v = v_raw - beta * z_arm3_tr
            r, _ = spearmanr(v, y_res)
            ar = abs(float(r)) if np.isfinite(r) else 0.0
            if ar > best_abs:
                best_abs, best_col = ar, c
            if ar >= self.min_train_abs_rho:
                kept.append(c)
        if not kept and best_col is not None:
            kept = [best_col]
        self.active_cols = kept

        X = self._matrix(train_df, self.active_cols)
        with np.errstate(all="ignore"):
            Xs = np.nan_to_num(self.scaler.fit_transform(X), nan=0.0, posinf=0.0, neginf=0.0)
            srank = train_df["structural_rank"].to_numpy(dtype=np.float64)
            w_row = np.where(srank <= 15, 1.25, 0.85)
            self.ridge.fit(Xs, y_res, sample_weight=w_row)

            dX_list, dy_list, dw_list = [], [], []
            for _, dg in train_df.groupby("day"):
                if len(dg) < 4:
                    continue
                idx = dg.index.to_numpy()
                pos = train_df.index.get_indexer(idx)
                s_arr = dg["structural_score"].to_numpy(dtype=np.float64)
                v_arr = dg["real_votes"].to_numpy(dtype=np.float64)
                for i in range(len(pos)):
                    for j in range(i + 1, len(pos)):
                        if abs(s_arr[i] - s_arr[j]) <= 0.45 and abs(np.log1p(v_arr[i]) - np.log1p(v_arr[j])) >= 0.18:
                            diff = Xs[pos[i]] - Xs[pos[j]]
                            yi = 1 if v_arr[i] > v_arr[j] else 0
                            w = float(abs(np.log1p(v_arr[i]) - np.log1p(v_arr[j])))
                            dX_list.append(diff); dy_list.append(yi); dw_list.append(w)
                            dX_list.append(-diff); dy_list.append(1 - yi); dw_list.append(w)

            if len(dX_list) >= 40:
                self.pair_clf.fit(np.asarray(dX_list, dtype=np.float64), np.asarray(dy_list), sample_weight=np.asarray(dw_list))
                self._has_pair = True
            else:
                self._has_pair = False

            raw_tr = self._raw_linear(Xs)
            self.train_raw_std = max(float(np.std(raw_tr)), 1e-6)
        self._fitted = True
        return self

    def _raw_linear(self, Xs: np.ndarray) -> np.ndarray:
        r_pred = np.nan_to_num(self.ridge.predict(Xs), nan=0.0)
        if self._has_pair:
            p_raw = np.nan_to_num(Xs @ self.pair_clf.coef_[0], nan=0.0)
            p_std = max(float(np.std(p_raw)), 1e-6)
            r_std = max(float(np.std(r_pred)), 0.08)
            return 0.55 * r_pred + 0.45 * (p_raw / p_std * r_std)
        return r_pred

    def predict_shift(self, df: pd.DataFrame) -> np.ndarray:
        if not self._fitted or len(df) == 0 or not self.active_cols:
            return np.zeros(len(df), dtype=np.float64)
        with np.errstate(all="ignore"):
            Xs = np.nan_to_num(self.scaler.transform(self._matrix(df, self.active_cols)), nan=0.0, posinf=0.0, neginf=0.0)
            raw = self._raw_linear(Xs)
        scaled = (raw / self.train_raw_std) * self.target_std
        return np.clip(scaled, -self.max_shift, self.max_shift)

    def score_df(self, df: pd.DataFrame) -> np.ndarray:
        return df["structural_score"].to_numpy(dtype=np.float64) + self.predict_shift(df)


def evaluate_boards_and_ties(
    full_day_launches: dict[str, list[dict]],
    truth_by_day: dict[str, dict[str, dict]],
    shortlist_scores: pd.DataFrame,
    score_col: str = "final_score",
    n_boot: int = 5000,
    seed: int = 42,
) -> dict:
    """Compute exact 00:05 PT Daily Top-3/5/10, paired diffs vs frozen arm3, residual Spearman, and tie accuracy.

    Replaces shortlist items' structural_score with `score_col` (items outside Top-20 keep structural_score),
    sorts descending, and compares against `truth_by_day` (`final_rank` <= 3, 5, 10) with day-clustered bootstrap!
    """
    override = {}
    if len(shortlist_scores):
        for r in shortlist_scores[["day", "item_id", score_col]].itertuples(index=False):
            override[(str(r[0]), str(r[1]))] = float(r[2])

    days = sorted(d for d in shortlist_scores["day"].unique() if d in full_day_launches and d in truth_by_day)
    arm3_3, arm3_5, arm3_10 = [], [], []
    mod_3, mod_5, mod_10 = [], [], []
    rhos = []
    tie_arm3_ok, tie_mod_ok, tie_n = 0, 0, 0
    tie_by_day: list[tuple[int, int, int]] = []

    for d in days:
        launches = full_day_launches[d]
        truth = truth_by_day[d]
        ranked_truth = {str(k): int(v["final_rank"]) for k, v in truth.items() if v.get("final_rank") is not None}
        top3_real = {k for k, r in ranked_truth.items() if r <= 3}
        top5_real = {k for k, r in ranked_truth.items() if r <= 5}
        top10_real = {k for k, r in ranked_truth.items() if r <= 10}

        base_sorted = sorted(launches, key=lambda x: (-float(x["structural_score"]), int(x["structural_rank"])))
        mod_sorted = sorted(
            launches,
            key=lambda x: (-override.get((d, str(x["id"])), float(x["structural_score"])), int(x["structural_rank"])),
        )

        arm3_3.append(len({str(x["id"]) for x in base_sorted[:3]} & top3_real) / 3.0)
        arm3_5.append(len({str(x["id"]) for x in base_sorted[:5]} & top5_real) / 5.0)
        arm3_10.append(len({str(x["id"]) for x in base_sorted[:10]} & top10_real) / 10.0)

        mod_3.append(len({str(x["id"]) for x in mod_sorted[:3]} & top3_real) / 3.0)
        mod_5.append(len({str(x["id"]) for x in mod_sorted[:5]} & top5_real) / 5.0)
        mod_10.append(len({str(x["id"]) for x in mod_sorted[:10]} & top10_real) / 10.0)

        dg = shortlist_scores[shortlist_scores["day"] == d]
        if len(dg) >= 5:
            sh = dg[score_col].to_numpy(dtype=np.float64) - dg["structural_score"].to_numpy(dtype=np.float64)
            tr = dg["true_log_residual"].to_numpy(dtype=np.float64)
            if np.std(sh) > 1e-9 and np.std(tr) > 1e-9:
                r, _ = spearmanr(sh, tr)
                if np.isfinite(r):
                    rhos.append(float(r))

        # Objective Reach-Matched Pairwise Ties within shortlist: |arm3_i - arm3_j| <= 0.15 and vote ratio >= 1.5x
        s_arr = dg["structural_score"].to_numpy(dtype=np.float64)
        m_arr = dg[score_col].to_numpy(dtype=np.float64)
        v_arr = dg["real_votes"].to_numpy(dtype=np.float64)
        d_a3, d_md, d_tot = 0, 0, 0
        for i in range(len(dg)):
            for j in range(i + 1, len(dg)):
                if abs(s_arr[i] - s_arr[j]) <= 0.15 and max(v_arr[i], v_arr[j]) >= 1.5 * max(1.0, min(v_arr[i], v_arr[j])):
                    d_tot += 1
                    if (s_arr[i] - s_arr[j]) * (v_arr[i] - v_arr[j]) > 0:
                        d_a3 += 1
                    if (m_arr[i] - m_arr[j]) * (v_arr[i] - v_arr[j]) > 0:
                        d_md += 1
        tie_arm3_ok += d_a3
        tie_mod_ok += d_md
        tie_n += d_tot
        tie_by_day.append((d_a3, d_md, d_tot))

    a3 = np.array(arm3_3) * 100.0; a5 = np.array(arm3_5) * 100.0; a10 = np.array(arm3_10) * 100.0
    m3 = np.array(mod_3) * 100.0; m5 = np.array(mod_5) * 100.0; m10 = np.array(mod_10) * 100.0
    d3, d5, d10 = m3 - a3, m5 - a5, m10 - a10

    rng = np.random.default_rng(seed)
    n_days = len(days)
    idx_boot = rng.integers(0, n_days, size=(n_boot, n_days))
    b_d3 = d3[idx_boot].mean(axis=1)
    b_d5 = d5[idx_boot].mean(axis=1)
    b_d10 = d10[idx_boot].mean(axis=1)
    b_comb = (b_d3 + b_d5 + b_d10) / 3.0

    tie_arr = np.array(tie_by_day, dtype=np.float64)
    if tie_n > 0:
        bt = tie_arr[idx_boot].sum(axis=1)
        valid_bt = bt[:, 2] > 0
        tie_mod_ci = np.percentile(bt[valid_bt, 1] / bt[valid_bt, 2] * 100.0, [2.5, 97.5]).tolist()
        tie_diff_ci = np.percentile((bt[valid_bt, 1] - bt[valid_bt, 0]) / bt[valid_bt, 2] * 100.0, [2.5, 97.5]).tolist()
    else:
        tie_mod_ci = [50.0, 50.0]
        tie_diff_ci = [0.0, 0.0]

    return {
        "n_days": n_days,
        "arm3": {
            "top3": round(float(a3.mean()), 2),
            "top5": round(float(a5.mean()), 2),
            "top10": round(float(a10.mean()), 2),
            "mean_3_5_10": round(float((a3.mean() + a5.mean() + a10.mean()) / 3.0), 2),
        },
        "model": {
            "top3": round(float(m3.mean()), 2),
            "top5": round(float(m5.mean()), 2),
            "top10": round(float(m10.mean()), 2),
            "mean_3_5_10": round(float((m3.mean() + m5.mean() + m10.mean()) / 3.0), 2),
        },
        "paired_lift_pts": {
            "top3": {"diff": round(float(d3.mean()), 2), "ci95": [round(float(x), 2) for x in np.percentile(b_d3, [2.5, 97.5])]},
            "top5": {"diff": round(float(d5.mean()), 2), "ci95": [round(float(x), 2) for x in np.percentile(b_d5, [2.5, 97.5])]},
            "top10": {"diff": round(float(d10.mean()), 2), "ci95": [round(float(x), 2) for x in np.percentile(b_d10, [2.5, 97.5])]},
            "mean_3_5_10": {"diff": round(float((d3.mean() + d5.mean() + d10.mean()) / 3.0), 2),
                            "ci95": [round(float(x), 2) for x in np.percentile(b_comb, [2.5, 97.5])]},
        },
        "residual_spearman_mean": round(float(np.mean(rhos)) if rhos else 0.0, 4),
        "reach_matched_ties": {
            "n_pairs": int(tie_n),
            "arm3_acc_pct": round(100.0 * tie_arm3_ok / max(1, tie_n), 2),
            "model_acc_pct": round(100.0 * tie_mod_ok / max(1, tie_n), 2),
            "model_ci95": [round(float(x), 2) for x in tie_mod_ci],
            "paired_lift_pts": round(100.0 * (tie_mod_ok - tie_arm3_ok) / max(1, tie_n), 2),
            "lift_ci95": [round(float(x), 2) for x in tie_diff_ci],
        },
    }
