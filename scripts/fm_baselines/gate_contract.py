#!/usr/bin/env python3
"""Shared helpers for gate-aware FM baseline eval scripts.

Eval scripts (local or Colab) must:
- refuse subsetting unless ALLOW_PARTIAL=1
- write SUMMARY.json only when coverage is complete
- write PARTIAL.<reason>.json otherwise
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

# Fallback when gates.yaml is not on the VM (must match docs/plans/gates.yaml).
BEHAVIORBENCH_FULL_TASKS: list[str] = [
    "acrossdim_pers_score",
    "acrossgame_behavior_bomb",
    "acrossgame_behavior_dictator",
    "acrossgame_behavior_guessing",
    "acrossgame_behavior_public_goods",
    "acrossgame_behavior_push_pull",
    "acrossgame_behavior_trust_banker",
    "acrossgame_behavior_trust_investor",
    "acrossgame_behavior_ultimatum_proposer",
    "acrossgame_behavior_ultimatum_responder",
    "demo_pred_age",
    "game_behavior_bomb",
    "game_behavior_dictator",
    "game_behavior_guessing",
    "game_behavior_public_goods",
    "game_behavior_push_pull",
    "game_behavior_trust_banker",
    "game_behavior_trust_investor",
    "game_behavior_ultimatum_proposer",
    "game_behavior_ultimatum_responder",
    "ieo_economics",
    "missing_surv_resp",
    "multiround_behavior_bomb",
    "multiround_behavior_dictator",
    "multiround_behavior_guessing",
    "multiround_behavior_public_goods",
    "multiround_behavior_push_pull",
    "multiround_behavior_trust_banker_inv100",
    "multiround_behavior_trust_banker_inv50",
    "multiround_behavior_trust_investor",
    "pers_score_pred",
    "seq_surv_resp",
    "strategic_gameplay_guessing",
    "surv_resp_pred",
    "workflow_idea_generation",
    "workflow_impact_prediction",
    "workflow_method_recommendation",
    "workflow_outcome_prediction",
    "workflow_title_prediction",
]

SOCSCl210_EXPECTED_STUDIES = 40
PSYCH101_EXPECTED_ITEMS = 6561


def allow_partial() -> bool:
    return os.environ.get("ALLOW_PARTIAL", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def require_full_or_allow(kind: str, detail: str) -> None:
    """Refuse to start a subset run unless ALLOW_PARTIAL=1."""
    if allow_partial():
        print(f"ALLOW_PARTIAL=1 — running PARTIAL {kind}: {detail}", flush=True)
        return
    raise SystemExit(
        f"Refusing subset ({kind}: {detail}). "
        f"Set ALLOW_PARTIAL=1 for a labeled partial run, or remove the subset flag for a full Gate 0 run."
    )


def find_gates_yaml() -> Path | None:
    env = os.environ.get("GATES_CONTRACT", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            Path("/content/fm_baselines/gates.yaml"),
            Path(__file__).resolve().parents[2] / "docs" / "plans" / "gates.yaml",
            Path.cwd() / "docs" / "plans" / "gates.yaml",
            Path.cwd() / "gates.yaml",
        ]
    )
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_contract() -> dict[str, Any] | None:
    path = find_gates_yaml()
    if path is None:
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        # Minimal YAML subset not available — fall back to embedded constants.
        return None
    return yaml.safe_load(path.read_text())


def contract_sha() -> str | None:
    path = find_gates_yaml()
    if path is None:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def git_sha() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("GIT_SHA")


def behaviorbench_expected_tasks() -> list[str]:
    """Prefer live DEFAULT_DATA_PATHS, then contract, then embedded fallback."""
    try:
        import sys

        root = Path(__file__).resolve().parents[2]
        bb = root / "third_party" / "behaviorbench_eval" / "src"
        if bb.is_dir() and str(bb) not in sys.path:
            sys.path.insert(0, str(bb))
        from behaviorbench.eval.main import DEFAULT_DATA_PATHS  # type: ignore

        return sorted(DEFAULT_DATA_PATHS.keys())
    except Exception:
        pass
    contract = load_contract()
    if contract:
        tasks = (
            contract.get("benchmarks", {})
            .get("behaviorbench", {})
            .get("expected_tasks")
        )
        if tasks:
            return list(tasks)
    return list(BEHAVIORBENCH_FULL_TASKS)


def coverage_block(
    *,
    actual: int | float,
    expected: int | float,
    unit: str,
    complete: bool,
    failed: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failed = list(failed or [])
    if failed:
        complete = False
    block: dict[str, Any] = {
        "actual": actual,
        "expected": expected,
        "unit": unit,
        "complete": bool(complete) and actual >= expected and not failed,
        "failed": failed,
        "contract_sha": contract_sha(),
        "git_sha": git_sha(),
        "partial_allowed": allow_partial(),
    }
    if extra:
        block.update(extra)
    return block


def write_summary_or_partial(
    results_dir: Path,
    summary: dict[str, Any],
    *,
    complete: bool,
    reason: str | None = None,
) -> Path:
    """Write SUMMARY.json only if complete; otherwise PARTIAL.<reason>.json."""
    results_dir.mkdir(parents=True, exist_ok=True)
    # Never leave a stale SUMMARY.json from a previous full run when this run is partial.
    summary_path = results_dir / "SUMMARY.json"
    if not complete:
        if summary_path.exists():
            # Do not delete a prior complete SUMMARY unless this run claims to replace it.
            # Partial runs use a different filename so the verifier cannot confuse them.
            pass
        safe = (reason or "incomplete").replace(" ", "_").replace("/", "_")[:64]
        path = results_dir / f"PARTIAL.{safe}.json"
        summary = dict(summary)
        summary["complete"] = False
        summary["partial_reason"] = reason or "incomplete"
        path.write_text(json.dumps(summary, indent=2))
        print(f"WROTE_PARTIAL {path}", flush=True)
        return path

    summary = dict(summary)
    summary["complete"] = True
    summary_path.write_text(json.dumps(summary, indent=2))
    # Remove legacy DONE.json that could confuse agents.
    done = results_dir / "DONE.json"
    if done.exists():
        done.unlink()
    print(f"WROTE_SUMMARY {summary_path}", flush=True)
    return summary_path
