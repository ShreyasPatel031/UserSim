"""Audit ledger: one row per experiment and one row per decision, for Shreyas to audit.

    python -m simharness.ledger validate              # checks every row against the schema
    python -m simharness.ledger add experiments row.json
    python -m simharness.ledger add decisions row.json

Files: docs/ledger/experiments.jsonl, docs/ledger/decisions.jsonl (append-only; a correction is a new row with
"corrects": <id>, never an edit of the old one). No usernames, client data, credentials or private rows go here; point to
the bucket path instead.

Rule: an experiment row is written BEFORE it runs (design, stated budget, pre-set scoring) and completed after (what
actually ran, every deviation from the design with who decided it and why, results, cost measured, decision). A
deviation that is not recorded is an audit failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs" / "ledger"

SCHEMA = {
    "experiments": {
        "required": ["id", "title", "owner", "status", "requested_by", "registered_at", "question", "design",
                     "scoring_fixed_before_results", "budget_usd", "source_refs"],
        "optional": ["finished_at", "what_ran", "deviations", "results", "cost_usd", "cost_basis", "decision",
                     "decision_ids", "reported_as", "corrections", "caveats", "code", "outputs", "verification",
                     "corrects", "notes"],
        "status": {"planned", "running", "finished", "abandoned", "superseded"},
    },
    "decisions": {
        "required": ["id", "date", "decision", "decided_by", "basis", "source_refs"],
        "optional": ["experiment_ids", "alternatives_rejected", "rule_cited", "reversible", "revert_condition",
                     "later_outcome", "corrects", "verification", "notes"],
    },
}
# verification: "checked_against_outputs" | "checked_against_code" | "log_only" (the number is only in a log/report and
# was not re-derived) | "mismatch" (the outputs disagree with what was reported; details in notes)
VERIFICATION = {"checked_against_outputs", "checked_against_code", "log_only", "mismatch"}


def rows(kind: str) -> list[dict]:
    p = ROOT / f"{kind}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def check(kind: str, r: dict) -> list[str]:
    s = SCHEMA[kind]
    errs = [f"missing {k}" for k in s["required"] if k not in r]
    errs += [f"unknown field {k}" for k in r if k not in s["required"] + s["optional"]]
    if kind == "experiments" and r.get("status") not in s["status"]:
        errs.append(f"bad status {r.get('status')}")
    if r.get("verification") and r["verification"] not in VERIFICATION:
        errs.append(f"bad verification {r['verification']}")
    if kind == "experiments" and r.get("status") == "finished":
        errs += [f"finished without {k}" for k in ("what_ran", "results", "cost_usd", "decision", "deviations")
                 if k not in r]
    return errs


def validate() -> int:
    bad = 0
    for kind in SCHEMA:
        seen = set()
        for r in rows(kind):
            e = check(kind, r)
            if r.get("id") in seen and "corrects" not in r:
                e.append("duplicate id")
            seen.add(r.get("id"))
            if e:
                bad += 1
                print(kind, r.get("id"), "; ".join(e))
        print(kind, len(rows(kind)), "rows")
    return 1 if bad else 0


def add(kind: str, path: str) -> None:
    r = json.load(open(path))
    e = check(kind, r)
    if e:
        sys.exit("; ".join(e))
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / f"{kind}.jsonl", "a") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "validate":
        sys.exit(validate())
    add(sys.argv[2], sys.argv[3])
