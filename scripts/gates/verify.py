#!/usr/bin/env python3
"""Gate verifier — the only thing allowed to declare a gate met.

Usage:
  python scripts/gates/verify.py --gate 0
  python scripts/gates/verify.py --gate 0 --json

Exit 0 iff the gate passes. Exit 1 otherwise.
No GPU, no network. Pure artifact + contract reader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs" / "plans" / "gates.yaml"
OUT_DIR = ROOT / "results" / "gates"
FM_DIR = ROOT / "results" / "fm_baselines"


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        # Minimal fallback: use PyYAML from requirements if present; else fail clearly.
        sys.stderr.write(
            "ERROR: PyYAML required. pip install pyyaml\n"
        )
        raise SystemExit(2)
    return yaml.safe_load(path.read_text())


def git_sha() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def contract_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def behaviorbench_expected_tasks(contract: dict[str, Any]) -> list[str]:
    """Derive from live DEFAULT_DATA_PATHS when third_party is present."""
    try:
        bb_src = ROOT / "third_party" / "behaviorbench_eval" / "src"
        if bb_src.is_dir() and str(bb_src) not in sys.path:
            sys.path.insert(0, str(bb_src))
        from behaviorbench.eval.main import DEFAULT_DATA_PATHS  # type: ignore

        return sorted(DEFAULT_DATA_PATHS.keys())
    except Exception:
        return list(
            contract.get("benchmarks", {})
            .get("behaviorbench", {})
            .get("expected_tasks", [])
        )


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_parse_error": str(e)}


def relative_ok(actual: float, target: float, tol: float, higher_is_better: bool | None = None) -> bool:
    """Within tol relative of target. Direction-agnostic for reproduction (match published)."""
    if target == 0:
        return abs(actual) <= tol
    return abs(actual - target) / abs(target) <= tol


def check_psych101(contract: dict[str, Any], tol: float) -> dict[str, Any]:
    spec = contract["benchmarks"]["psych101_test"]
    path = ROOT / spec["artifact"]
    data = load_json(path)
    checks: list[dict[str, Any]] = []
    ok = True

    if data is None:
        return {
            "benchmark": "psych101_test",
            "pass": False,
            "checks": [{"name": "artifact_present", "pass": False, "detail": f"missing {path}"}],
        }
    if "_parse_error" in data:
        return {
            "benchmark": "psych101_test",
            "pass": False,
            "checks": [{"name": "artifact_parse", "pass": False, "detail": data["_parse_error"]}],
        }

    expected_n = int(spec["expected"]["n_items"])
    actual_n = int(data.get("n_items") or data.get("coverage", {}).get("actual") or 0)
    complete = bool(data.get("complete", False) or data.get("coverage", {}).get("complete", False))
    failed = list(data.get("failed") or data.get("coverage", {}).get("failed") or [])

    cov_ok = actual_n >= expected_n and complete and not failed
    checks.append(
        {
            "name": "coverage_n_items",
            "pass": cov_ok,
            "detail": f"n_items={actual_n}/{expected_n} complete={complete} failed={failed}",
        }
    )
    ok = ok and cov_ok

    target = spec.get("metric_target")
    if target is not None and data.get(spec["metric_key"]) is not None:
        actual = float(data[spec["metric_key"]])
        met = relative_ok(actual, float(target), tol)
        checks.append(
            {
                "name": "metric_tolerance",
                "pass": met,
                "detail": f"{spec['metric_key']}={actual} target={target} tol={tol}",
            }
        )
        ok = ok and met
    else:
        checks.append(
            {
                "name": "metric_tolerance",
                "pass": True,
                "detail": "metric_target unset in contract — coverage-only until aggregate published NLL is recorded",
                "skipped": True,
            }
        )

    return {"benchmark": "psych101_test", "pass": ok, "artifact": str(path), "checks": checks, "summary": data}


def check_socrates(contract: dict[str, Any], tol: float) -> dict[str, Any]:
    spec = contract["benchmarks"]["socsci210_unseen"]
    path = ROOT / spec["artifact"]
    data = load_json(path)
    checks: list[dict[str, Any]] = []
    ok = True

    # Detect smoke masquerading: PARTIAL / SUMMARY_smoke must not pass.
    smoke = ROOT / "results" / "fm_baselines" / "socrates" / "SUMMARY_smoke.json"
    if data is None:
        detail = f"missing {path}"
        if smoke.is_file():
            smoke_data = load_json(smoke) or {}
            detail += (
                f"; found SUMMARY_smoke.json with n_studies={smoke_data.get('n_studies')} "
                f"(smoke ≠ Gate 0)"
            )
        return {
            "benchmark": "socsci210_unseen",
            "pass": False,
            "checks": [{"name": "artifact_present", "pass": False, "detail": detail}],
        }

    expected_studies = int(spec["expected"]["n_studies"])
    actual_studies = int(data.get("n_studies") or data.get("coverage", {}).get("actual") or 0)
    complete = bool(data.get("complete", False) or data.get("coverage", {}).get("complete", False))
    # If complete flag absent, infer from coverage only when n_studies matches expected.
    if "complete" not in data and "coverage" not in data:
        complete = actual_studies >= expected_studies
    failed = list(data.get("failed") or data.get("coverage", {}).get("failed") or [])

    cov_ok = actual_studies >= expected_studies and complete and not failed
    checks.append(
        {
            "name": "coverage_n_studies",
            "pass": cov_ok,
            "detail": f"n_studies={actual_studies}/{expected_studies} complete={complete} failed={failed}",
        }
    )
    ok = ok and cov_ok

    target = float(spec["metric_target"])
    actual_w = data.get(spec["metric_key"])
    if actual_w is None:
        checks.append({"name": "metric_tolerance", "pass": False, "detail": "wasserstein_mean missing"})
        ok = False
    else:
        actual_w = float(actual_w)
        met = relative_ok(actual_w, target, tol)
        checks.append(
            {
                "name": "metric_tolerance",
                "pass": met,
                "detail": f"wasserstein_mean={actual_w} target={target} tol={tol} empirical_bound={spec.get('empirical_bound')}",
            }
        )
        ok = ok and met

    return {"benchmark": "socsci210_unseen", "pass": ok, "artifact": str(path), "checks": checks, "summary": {
        k: data.get(k) for k in ("n_studies", "n_preds", "wasserstein_mean", "model", "complete")
    }}


def check_befm(contract: dict[str, Any], tol: float) -> dict[str, Any]:
    spec = contract["benchmarks"]["behaviorbench"]
    path = ROOT / spec["artifact"]
    data = load_json(path)
    checks: list[dict[str, Any]] = []
    ok = True
    expected_tasks = behaviorbench_expected_tasks(contract)
    expected_n = len(expected_tasks)

    # Legacy DONE.json is never sufficient for Gate 0.
    legacy = ROOT / "results" / "fm_baselines" / "befm4b" / "DONE.json"
    legacy_data = load_json(legacy) if legacy.is_file() else None

    if data is None:
        detail = f"missing {path}"
        if legacy_data:
            ran = legacy_data.get("tasks") or []
            detail += f"; found legacy DONE.json with {len(ran)}/{expected_n} tasks (incomplete)"
            checks.append(
                {
                    "name": "legacy_done_coverage",
                    "pass": False,
                    "detail": f"tasks={sorted(ran)} missing={sorted(set(expected_tasks) - set(ran))}",
                }
            )
        return {
            "benchmark": "behaviorbench",
            "pass": False,
            "checks": [{"name": "artifact_present", "pass": False, "detail": detail}] + checks,
        }

    ran = list(data.get("tasks") or data.get("coverage", {}).get("tasks") or [])
    actual_n = int(data.get("coverage", {}).get("actual") or len(ran))
    complete = bool(data.get("complete", False) or data.get("coverage", {}).get("complete", False))
    failed = list(data.get("failed") or data.get("coverage", {}).get("failed") or [])
    missing = sorted(set(expected_tasks) - set(ran))

    cov_ok = actual_n >= expected_n and not missing and complete and not failed
    checks.append(
        {
            "name": "coverage_tasks",
            "pass": cov_ok,
            "detail": f"tasks={actual_n}/{expected_n} complete={complete} failed={failed} missing={missing[:10]}{'...' if len(missing)>10 else ''}",
        }
    )
    ok = ok and cov_ok

    targets = spec.get("metric_targets") or {}
    for key, target in targets.items():
        val = data.get(key) or (data.get("metrics") or {}).get(key)
        if val is None:
            checks.append(
                {
                    "name": f"metric_{key}",
                    "pass": False,
                    "detail": f"{key} missing (need board-level win rates for Gate 0)",
                }
            )
            ok = False
        else:
            met = relative_ok(float(val), float(target), tol)
            checks.append(
                {
                    "name": f"metric_{key}",
                    "pass": met,
                    "detail": f"{key}={val} target={target} tol={tol}",
                }
            )
            ok = ok and met

    return {"benchmark": "behaviorbench", "pass": ok, "artifact": str(path), "checks": checks}


def check_centaur_skip(contract: dict[str, Any]) -> dict[str, Any]:
    spec = contract["benchmarks"]["centaur_70b"]
    if spec.get("skipped"):
        return {
            "benchmark": "centaur_70b",
            "pass": True,
            "skipped": True,
            "checks": [{"name": "skipped_by_contract", "pass": True, "detail": spec.get("reason")}],
        }
    return {
        "benchmark": "centaur_70b",
        "pass": False,
        "checks": [{"name": "not_skipped_but_missing", "pass": False, "detail": "centaur_70b not skipped and no artifact"}],
    }


def verify_gate(gate_id: int, contract: dict[str, Any]) -> dict[str, Any]:
    gates = {int(g["id"]): g for g in contract["gates"]}
    if gate_id not in gates:
        return {
            "gate": gate_id,
            "pass": False,
            "error": f"unknown gate id {gate_id}",
            "checks": [],
        }
    gate = gates[gate_id]
    tol = float(
        contract.get("reproduction", {}).get("tolerance_relative")
        or contract.get("tolerance_relative_default")
        or 0.02
    )
    csha = contract_sha(CONTRACT_PATH)
    gsha = git_sha()

    if gate.get("status") == "pending_definition":
        return {
            "gate": gate_id,
            "name": gate.get("name"),
            "pass": False,
            "status": "pending_definition",
            "blocking": bool(gate.get("blocking", True)),
            "detail": "Gate is pending_definition — unknown must never silently pass.",
            "contract_sha": csha,
            "git_sha": gsha,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "benchmarks": [],
        }

    results: list[dict[str, Any]] = []
    for name in gate.get("required", []):
        if name == "psych101_test":
            results.append(check_psych101(contract, tol))
        elif name == "socsci210_unseen":
            results.append(check_socrates(contract, tol))
        elif name == "behaviorbench":
            results.append(check_befm(contract, tol))
        else:
            results.append(
                {
                    "benchmark": name,
                    "pass": False,
                    "checks": [{"name": "unknown_required", "pass": False, "detail": name}],
                }
            )

    for name in gate.get("optional_skipped", []):
        if name == "centaur_70b":
            results.append(check_centaur_skip(contract))

    passed = all(r.get("pass") for r in results)
    return {
        "gate": gate_id,
        "name": gate.get("name"),
        "pass": passed,
        "status": gate.get("status"),
        "blocking": bool(gate.get("blocking", True)),
        "tolerance_relative": tol,
        "contract_sha": csha,
        "git_sha": gsha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmarks": results,
    }


def write_summary_md(report: dict[str, Any]) -> Path:
    """Regenerate results/fm_baselines/SUMMARY.md from verifier output (Gate 0)."""
    FM_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# FM baselines — Gate 0 (generated)",
        "",
        f"Generated by `scripts/gates/verify.py`. Do not edit by hand.",
        f"",
        f"- gate_pass: **{report.get('pass')}**",
        f"- contract_sha: `{report.get('contract_sha')}`",
        f"- git_sha: `{report.get('git_sha')}`",
        f"- timestamp: {report.get('timestamp')}",
        "",
        "| Benchmark | Status | Detail |",
        "|---|---|---|",
    ]
    for b in report.get("benchmarks", []):
        status = "SKIP" if b.get("skipped") else ("PASS" if b.get("pass") else "FAIL")
        details = "; ".join(
            c.get("detail", "") for c in b.get("checks", []) if not c.get("pass") or b.get("skipped")
        )
        if not details:
            details = "; ".join(c.get("detail", "") for c in b.get("checks", []))
        lines.append(f"| {b.get('benchmark')} | {status} | {details} |")
    lines.append("")
    lines.append("## Checks")
    for b in report.get("benchmarks", []):
        lines.append(f"### {b.get('benchmark')}")
        for c in b.get("checks", []):
            mark = "OK" if c.get("pass") else "FAIL"
            skip = " (skipped)" if c.get("skipped") else ""
            lines.append(f"- [{mark}]{skip} `{c.get('name')}`: {c.get('detail')}")
        lines.append("")
    path = FM_DIR / "SUMMARY.md"
    path.write_text("\n".join(lines))
    # Mirror as STATUS.md so agents stop hand-writing it.
    (FM_DIR / "STATUS.md").write_text(
        "\n".join(
            [
                "# STATUS (generated — do not edit)",
                "",
                "This file is overwritten by `python scripts/gates/verify.py --gate 0`.",
                "A gate claim without that command exiting 0 is invalid.",
                "",
            ]
        )
        + path.read_text()
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", type=int, required=True)
    ap.add_argument("--json", action="store_true", help="print full report JSON to stdout")
    ap.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = ap.parse_args()

    if not args.contract.is_file():
        print(f"ERROR: contract missing: {args.contract}", file=sys.stderr)
        raise SystemExit(2)

    contract = load_yaml(args.contract)
    report = verify_gate(args.gate, contract)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"gate{args.gate}.json"
    # Strip bulky nested summary copies for the on-disk report
    slim = dict(report)
    slim_bench = []
    for b in report.get("benchmarks", []):
        bb = {k: v for k, v in b.items() if k != "summary"}
        slim_bench.append(bb)
    slim["benchmarks"] = slim_bench
    out_path.write_text(json.dumps(slim, indent=2))

    if args.gate == 0:
        write_summary_md(report)

    if args.json:
        print(json.dumps(slim, indent=2))
    else:
        print(f"gate={args.gate} pass={report.get('pass')} → {out_path}")
        for b in report.get("benchmarks", []):
            flag = "SKIP" if b.get("skipped") else ("PASS" if b.get("pass") else "FAIL")
            print(f"  [{flag}] {b.get('benchmark')}")
            for c in b.get("checks", []):
                mark = "ok" if c.get("pass") else "FAIL"
                print(f"      {mark}: {c.get('name')}: {c.get('detail')}")
        if report.get("status") == "pending_definition":
            print(f"  detail: {report.get('detail')}")

    raise SystemExit(0 if report.get("pass") else 1)


if __name__ == "__main__":
    main()
