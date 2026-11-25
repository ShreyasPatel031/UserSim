# Audit ledger

Every experiment and every decision, for Shreyas to audit (asked Nov 25). Schema and checker: `simharness/ledger.py`.

- `experiments.jsonl`: one row per experiment. Written BEFORE it runs (question, design, scoring fixed before results,
  budget), completed after (what actually ran, every deviation from the design with who decided it and why, results,
  measured cost, decision, how it was reported).
- `decisions.jsonl`: one row per decision (deploy, revert, close, budget, model choice), with its basis and who decided.
- Append-only. A correction is a new row with `"corrects": "<id>"`; old rows are never edited.
- `verification` says how far a number was checked: re-derived from the output file, read from code, log only, or
  mismatch (the outputs disagree with what was reported).
- No usernames, client data or credentials; point to the private bucket path instead.
- Backfill of Nov 1-25 from the research log, code and output files: part_a (Nov 1-12) and part_b (Nov 12-25), merged
  into the two files.
