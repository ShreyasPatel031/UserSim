# Parity known difference: post-launch topic edit, Nov 20 (orchestrator 09:30Z Nov 21)

E5's alert 5cef3659: on Nov 20, 17 of 53 launches showed the "Google Cloud Run" topic at 00:05, and Product Hunt removed it after launch, so the final read no longer has it. It changes nothing in the top 3 or 5 and one top-10 pick across all live columns. Decision: list it as a known post-launch topic edit and leave the live inputs unchanged.

Change to E5's `experiments/simlab/parity_rules.py` (branch claude/person-model-v2):
- New `KNOWN_TOPIC_EDITS = {"2026-11-20": ...}`.
- On a listed night, any differing column whose name contains "topic" is classed as "post-launch topic edit (known)".
- The ranking-effect cap is unchanged.

Test (`test_parity_rules.py`, run in a worktree of claude/person-model-v2 with these two files):
- the 16 measured nights still raise no alert;
- a Nov 20 `ph_n_topics` at share_equal 0.68 is now known;
- the same drop on any other night still alerts.

Apply: copy both files over `experiments/simlab/` on claude/person-model-v2. The nightly `parity_nightly.sh` copies `parity_rules.py` from there.
