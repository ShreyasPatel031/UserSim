"""`usersim_core`: Portable, domain-agnostic user simulation & calibration flywheel layer.

Modules:
  - schema:            UNIVERSAL_USERS, CUA_TRACES, SIM_FEEDBACK_RESIDUALS, CALIBRATION_LEDGER, FlywheelStore
  - sanitizer:         Strict PH-badge / post-launch date / social-proof leak stripper & HTML surface parser
  - pool:              UniversalUserPool (causal < D taste SVD + behavioral selectivity + K-Means archetypes)
  - cua_runner:        Sanitized HTTP/cached surface inspector + real Camoufox MCP CUA session driver
  - cohort_sim:        Comparative multi-model frontier cohort evaluator (`gpt-oss-120b` + `gemini-2.5-pro`)
  - calibration:       Walk-forward (< D) empirical-Bayes category calibration ledger & Gold-Trace selector
  - residual_learner:  Regularized Ridge + Bradley-Terry pairwise stacker & day-clustered bootstrap scorer
"""
from usersim_core.schema import (
    UNIVERSAL_USERS,
    CUA_TRACES,
    SIM_FEEDBACK_RESIDUALS,
    CALIBRATION_LEDGER,
    FLYWHEEL_TABLES,
    FlywheelStore,
)
from usersim_core.pool import UniversalUserPool
from usersim_core.sanitizer import SanitizedSurface, sanitize_text, parse_html_surface, surface_from_cached_scrape
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.residual_learner import WalkForwardResidualModel, evaluate_boards_and_ties

__all__ = [
    "UNIVERSAL_USERS",
    "CUA_TRACES",
    "SIM_FEEDBACK_RESIDUALS",
    "CALIBRATION_LEDGER",
    "FLYWHEEL_TABLES",
    "FlywheelStore",
    "UniversalUserPool",
    "SanitizedSurface",
    "sanitize_text",
    "parse_html_surface",
    "surface_from_cached_scrape",
    "WalkForwardCalibrator",
    "WalkForwardResidualModel",
    "evaluate_boards_and_ties",
]
