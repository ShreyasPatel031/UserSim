# Handoff: Calibrated & Model-Invariant User Simulation (`tau2-bench`)

> Saved 2026-11-27 from a session on a separate GCP VM that ran out of subscription
> time. **The code is not in this repo.** It sits on a `tau2-bench` checkout
> (branch `feature/calibrated-user-simulator` @ `b6d064a`) and in a git bundle on GCS (see "Recovering the code").

**Branch (tau2-bench fork):** `feature/calibrated-user-simulator` @ `b6d064a` (34 files)
**GCS archive:** `gs://usersim-trace-store-347838016394/tau2_calibrated_user/`
**Git bundle:** `gs://usersim-trace-store-347838016394/tau2_calibrated_user/repo_handoff/tau2_calibrated_user.bundle` (86.2 MiB)
**Verification at handoff:** `UV_FROZEN=1 make check-all` (680 files clean) + `pytest tests/test_cli_output.py tests/test_user_fidelity.py` (12/12 passed)

## Recovering the code

The VM could not push: `origin` pointed at upstream `sierra-research/tau2-bench` and the VM had no GitHub credentials. Recover the code from the bundle on any machine with GCS access to the bucket:

```bash
gcloud auth login
gsutil cp gs://usersim-trace-store-347838016394/tau2_calibrated_user/repo_handoff/tau2_calibrated_user.bundle .
git clone -b feature/calibrated-user-simulator tau2_calibrated_user.bundle tau2-bench
cd tau2-bench
git remote set-url origin https://github.com/<YOUR_USER>/tau2-bench.git
git push -u origin feature/calibrated-user-simulator
```

Datasets, simulations and embedding caches are under the same GCS prefix.
`data/external_human/` is git-excluded on purpose. Restore it from GCS.

**Security:** an `HF_TOKEN` and an `OPENAI_API_KEY` were pasted into the earlier chat. Rotate or revoke both.

## Completed work

1. **`tau2 user-fidelity` library & CLI (`D1–D6` + `K=128` multi-embedding geometry)**
   - `src/tau2/metrics/user_fidelity.py`, `user_fidelity_reference.json`,
     `src/tau2/scripts/user_fidelity_cli.py`, `tests/test_user_fidelity.py`.
2. **External human datasets** (GCS + `data/external_human/`, git-excluded)
   - `ABCD v1.1` (10,042 chats), `RealUserSim` (600 test + 7,273 profiles),
     `cmu-lti/tau-usi` (495 Prolific runs, **eval-only**).
3. **Full paired empirical suite, no subsampling** ($115.20 total)
   - 6,000 context-matched counterfactual turns (1,000 contexts × (Human + 5 LLMs)),
     1,000 Option B rollouts, and 1,387 / 1,390 clean full 278-task `tau2-bench` runs across
     `gemini-2.5-flash`, `gemini-2.5-pro`, `claude-haiku-4-5`, `claude-sonnet-4-5`,
     `openai/gpt-oss-120b-maas`.
   - Zero-regex discovery with 7 embedders (OpenAI 3-large/small, Gemini 001/004, Snowflake
     Arctic, BGE, Qwen3-0.6B) + an exact 164-task bijective `TAU-USI` join.

## Key results

- **54.7%** (152/278) of `tau2-bench` tasks flip PASS/FAIL across the 5 user models
  (`σ_LLM(Pass^1) = 8.42 pp`).
- **65–69%** of the Human-vs-Sim embedding divergence depends on dialogue state (floor-granting,
  checklist hunting at the end of a conversation, hallucinated updates to a static card, role inversion on minimal prompts).
- Delexicalized turn embeddings alone predict within-task `Pass^1` on the 152 discordant tasks at
  **OOF AUROC 0.772** (r = 0.523, Gemini 004) / 0.763 (r = 0.516, OpenAI 3-small);
  `cos(w_human_to_sim, w_pass) = -0.099`.
- Unweighted `TAU-USI` `USI` correlates **positively** with `Pass^1` on `retail` (ρ = +0.90) and
  **inverts** on `telecom` (r = -0.20).
- Human participants rated **52.2%** of `TAU-USI` DB failures as "Yes - Task completed".

## Next steps (Days 2–4)

1. Implement `CalibratedUserSimulator` (Dialogue-State Controller + Scenario-Blind Realizer +
   Best-of-`k` Anchor Reranker). Run the Candidate A/B/C ablation and the `UserOnlyReviewer` check.
2. Register `calibrated_user_simulator` in `src/tau2/registry.py` and validate it on the full
   278-task `tau2-bench` matrix (target `σ_LLM(Pass^1) < 3.0 pp`).
3. Add `tests/test_calibrated_user.py` and `docs/user-fidelity.md`, remove `PROJECT_PLAN.md` from
   the repo root, and open the upstream PR.
