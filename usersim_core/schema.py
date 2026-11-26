"""Unified 4-table flywheel schema for domain-agnostic social & CUA user simulation.

Extends `simharness.schema` (ITEMS, EVENTS, PEOPLE, OUTCOMES, STRUCTURAL) with the four
compounding assets required for cross-domain transfer and self-improvement:
1. UNIVERSAL_USERS         Cross-domain causal behavioral & taste embeddings z_u(D)
2. CUA_TRACES              Normalized, leak-scrubbed CUA / product-interaction trajectories
3. SIM_FEEDBACK_RESIDUALS  Simulated user votes/reactions paired with true structural residuals
4. CALIBRATION_LEDGER      Per-(category, archetype) calibration weights & error-bank memory
"""
from __future__ import annotations

import os
from dataclasses import dataclass
import pandas as pd

from simharness.schema import Column, TableSpec, ALL_TABLES as HARNESS_TABLES

ACCESS_CLEAN = "clean"
ACCESS_FAILURES = frozenset({"signup_wall", "captcha", "block", "js_only", "timeout", "engine", "dead_host", "no_url"})
PRODUCT_TRAITS = frozenset({"none", "instant_demo", "free_tier", "card_required", "onboarding_broken", "platform_only", "waitlist_only"})

UNIVERSAL_USERS = TableSpec(
    "universal_users",
    "Cross-domain causal user representation z_u computed strictly from events before as_of_day.",
    (
        Column("global_user_id", "string", "domain-prefixed salted id, e.g. ph:<hash> or hn:<hash>"),
        Column("domain", "string", "source domain (producthunt, hackernews, client_qa, crm)"),
        Column("domain_person_id", "string", "opaque salted person id within domain"),
        Column("as_of_day", "string", "ISO date cutoff; strictly uses events < as_of_day"),
        Column("complete", "bool", "whether history meets domain completeness gate"),
        Column("activity_rw7", "float64", "7-day half-life recency-weighted endorsements"),
        Column("activity_rw30", "float64", "30-day recency-weighted endorsements"),
        Column("n_endorse_all", "float64", "total prior dated endorsements"),
        Column("n_comments_all", "float64", "total prior dated comments"),
        Column("selectivity_entropy", "float64", "topic entropy of past endorsements (lower = specialist)"),
        Column("critique_rate", "float64", "empirical share of past comments raising substantive critique/questions"),
        Column("pricing_focus", "float64", "empirical rate of pricing/business-model commentary"),
        Column("tech_focus", "float64", "empirical rate of architecture/API/performance commentary"),
        Column("ux_focus", "float64", "empirical rate of onboarding/design/workflow commentary"),
        Column("archetype_id", "int64", "learned behavioral cluster index (0..K-1)"),
        Column("taste_vec", "object", "L2-normalized dense float32 taste vector z_u"),
        Column("voice_digest", "string", "scrubbed summary of recent verbatim comments (< as_of_day)", required=False),
    ),
)

CUA_TRACES = TableSpec(
    "cua_traces",
    "Normalized browser/mobile CUA trajectories and leak-scrubbed live product inspections.",
    (
        Column("trace_id", "string", "unique trace identifier"),
        Column("domain", "string", "target domain"),
        Column("item_id", "string", "target launch/post/build id"),
        Column("day", "string", "item competition day"),
        Column("global_user_id", "string", "simulated user or probe agent id"),
        Column("url", "string", "resolved product URL"),
        Column("driver_model", "string", "model driving CUA or inspection"),
        Column("leak_sanitized", "bool", "true when post-launch badges/dates/counters were stripped"),
        Column("badges_stripped_n", "int64", "count of social-proof / PH badge matches stripped before model read"),
        Column("access_status", "string", "clean or harness access failure (excluded from product penalization)"),
        Column("product_trait", "string", "product-intrinsic access/onboarding trait"),
        Column("http_status", "int64", "HTTP status or -1 on network error"),
        Column("load_ms", "float64", "time to initial usable document/render in ms"),
        Column("has_interactive_demo", "bool", "usable sandbox/demo/playground reachable without login"),
        Column("has_free_tier", "bool", "clear free plan or open-source try path visible"),
        Column("has_open_source", "bool", "public code/repo/CLI installable immediately"),
        Column("reached_value_moment", "bool", "agent reached core category value moment"),
        Column("steps_to_value", "float64", "step index of first value moment (null if unreached)", required=False),
        Column("n_steps", "int64", "total CUA steps executed"),
        Column("error_steps", "int64", "steps encountering UI/HTTP/action errors"),
        Column("sanitized_digest", "string", "leak-scrubbed structured digest of live product surface & trace"),
        Column("steps_json", "string", "JSON-serialized step trajectory", required=False),
        Column("frozen_at", "string", "ISO UTC timestamp"),
    ),
)

SIM_FEEDBACK_RESIDUALS = TableSpec(
    "sim_feedback_residuals",
    "Cohort-grounded simulated user reactions & votes linked to post-structural ground truth.",
    (
        Column("eval_id", "string", "unique row id"),
        Column("domain", "string", "domain"),
        Column("item_id", "string", "item id"),
        Column("day", "string", "competition day"),
        Column("global_user_id", "string", "matched pool user or cohort representative"),
        Column("pool_similarity", "float64", "cosine similarity of matched user in z_u space"),
        Column("evaluator_model", "string", "reasoning model used"),
        Column("trace_id", "string", "linked CUA/product trace id", required=False),
        Column("p_endorse", "float64", "predicted P(upvote | present, product trace, user history)"),
        Column("would_use", "float64", "predicted 0..1 adoption intent after product inspection"),
        Column("instant_clarity", "float64", "0..1 clarity of value proposition & immediate usability"),
        Column("differentiation", "float64", "0..1 concrete differentiation vs existing category tools"),
        Column("technical_substance", "float64", "0..1 depth of real product engineering vs thin wrapper"),
        Column("friction_severity", "float64", "0..1 product-intrinsic friction (paywall, waitlist, vague UX)"),
        Column("predicted_comment", "string", "simulated verbatim comment in user's voice", required=False),
        Column("predicted_critique", "string", "specific product risk/blocker identified", required=False),
        Column("structural_score", "float64", "frozen domain structural score S_d(item)"),
        Column("structural_rank", "float64", "within-day rank of S_d(item)"),
        Column("real_score", "float64", "observed final votes/points (never a model input)", required=False),
        Column("real_rank", "float64", "observed final daily rank (never a model input)", required=False),
        Column("true_log_residual", "float64", "log1p(real_score) - log1p(pred_structural_votes)", required=False),
    ),
)

CALIBRATION_LEDGER = TableSpec(
    "calibration_ledger",
    "Compounding calibration weights and category error-bank updated strictly walk-forward.",
    (
        Column("cal_id", "string", "unique calibration record id"),
        Column("domain", "string", "domain"),
        Column("through_day", "string", "fitted strictly on days <= through_day"),
        Column("category", "string", "product category or '*' for global"),
        Column("evaluator_model", "string", "model version"),
        Column("n_items", "int64", "number of scored items in window"),
        Column("residual_spearman", "float64", "within-day Spearman correlation with structural residual"),
        Column("pairwise_tie_acc", "float64", "accuracy on reach-matched pairs (|d_struct| < eps)"),
        Column("top10_lift_pts", "float64", "paired Top-10 capture lift over structural baseline"),
        Column("gold_trace_count", "int64", "traces passing calibration threshold for distillation"),
        Column("error_bank_json", "string", "JSON of verified category failure modes & calibration weights"),
    ),
)

FLYWHEEL_TABLES = {
    **HARNESS_TABLES,
    **{t.name: t for t in (UNIVERSAL_USERS, CUA_TRACES, SIM_FEEDBACK_RESIDUALS, CALIBRATION_LEDGER)},
}


@dataclass
class FlywheelStore:
    """Local + GCS-backed append/versioned store for usersim_core tables."""
    root_dir: str

    def __post_init__(self) -> None:
        os.makedirs(self.root_dir, exist_ok=True)

    def path(self, table_name: str) -> str:
        if table_name not in FLYWHEEL_TABLES:
            raise KeyError(f"Unknown flywheel table: {table_name}")
        return os.path.join(self.root_dir, f"{table_name}.parquet")

    def write(self, table_name: str, df: pd.DataFrame, append: bool = False, dedupe_key: str | None = None) -> str:
        spec = FLYWHEEL_TABLES[table_name]
        spec.validate(df)
        p = self.path(table_name)
        if append and os.path.exists(p):
            old = pd.read_parquet(p)
            df = pd.concat([old, df], ignore_index=True)
            if dedupe_key and dedupe_key in df.columns:
                df = df.drop_duplicates(subset=[dedupe_key], keep="last").reset_index(drop=True)
        df.to_parquet(p, index=False)
        return p

    def read(self, table_name: str) -> pd.DataFrame:
        p = self.path(table_name)
        if not os.path.exists(p):
            return FLYWHEEL_TABLES[table_name].empty()
        return pd.read_parquet(p)
