# STACK-1 (Nov 26 2026): BACKER-v2 features + the CHOICE-FT-1 tuned model's P(yes)

Question: does adding the tuned Qwen2.5-7B's P(yes) (CHOICE-FT-1, 500k-row adapter) as one feature of the BACKER-v2
logistic raise recall@N on held backers?

**Answer: yes, a little, and the interval clears zero.** On the Nov 11-22 test pairs, recall@N goes up by
**+1.0 [+0.2, +1.9] points** over BACKER-v2 (walk-forward), from 39.0 to 40.0. Per-launch AUC goes up by
**+0.006 [+0.004, +0.008]**.

## Design (ledger row STACK-1; specifics fixed in the running row before results)
- **Fitting data.** Validation days Nov 1-4 and Nov 8-10: the days with a line-up capture (Nov 1-3 same-day capture,
  the rest at 00:05; Nov 5-7 have none). Each day uses a fixed 15% sample of the pool, with the same rule as the
  CHOICE-FT-1 test. That gives 11,251 person-days, 309,399 pairs, 2,592 backers and 197 launches. The 500k adapter
  scored these days on one standard A100, on a VM that deleted itself.
- **Stack.** A logistic on standardised [ln_rw, topic match, interaction, logit P(yes)]. It is fit once on the
  validation pairs only and never refit on test.
- **Standardised coefficients.**

  | Feature | Coefficient |
  |---|---|
  | logit P(yes) | 1.30 |
  | ln_rw | 0.40 |
  | topic match | -0.05 |
  | interaction | 0.04 |

- **Test.** The CHOICE-FT-1 pairs (Nov 11-22, 361 line-up launches x 15% pool sample, 248,310 pairs; 356 launches
  scored). Intervals are a launch bootstrap, 95%, 2,000 draws, paired on the same launches.

## Results (test)

| Model | recall@N pooled | AUC mean per launch |
|---|---|---|
| BACKER-v2 logistic, walk-forward (CHOICE-FT-1 primary) | 39.0 [37.4, 40.5] | 0.941 [0.935, 0.947] |
| BACKER-v2 logistic, fit on the same validation pairs | 38.7 [37.2, 40.2] | 0.941 [0.935, 0.947] |
| P(yes) alone (tuned model) | 37.0 [35.5, 38.4] | 0.944 [0.938, 0.950] |
| **Stack: BACKER-v2 features + logit P(yes)** | **40.0 [38.4, 41.4]** | **0.947 [0.941, 0.953]** |

| Paired difference | recall@N | AUC |
|---|---|---|
| stack - BACKER-v2 walk-forward | **+1.0 [+0.2, +1.9]** | **+0.006 [+0.004, +0.008]** |
| stack - BACKER-v2 fit on the same validation pairs | +1.2 [+0.4, +2.1] | +0.006 [+0.004, +0.008] |
| BACKER-v2 validation fit - walk-forward | -0.2 [-0.5, -0.1] | -0.000 |

**Reading.**
- The tuned model and the logistic get different people wrong, so combining them adds about one point of recall@N.
  On its own the tuned model is below BACKER-v2 (CHOICE-FT-1).
- The gain is real but small, and it is measured on the 15% pool sample. BACKER-v2's full-pool score equals its
  score on the sample (CHOICE-FT-1).
- The test launches come after the model's training data (Oct 31), so the test is forward relative to the fine-tune.
  It is not forward relative to Qwen's pretraining, which predates November 2026.

**Leak checks.**
- No history endorsement on or after the day (checked on 3,000 validation person-days).
- No @handles in the prompts.
- Validation and test days do not overlap, and the stack never saw a test label.

## Cost
The A100 VM ran 23.9 min (05:36:01 to 05:59:55 PT) at $3.673/h, which is **$1.46**, plus about $0.01 of disk.
There were no model API calls. **Total: $1.47 of the $8 budget.**

## Deviations
1. Validation days are 7 of 10. Nov 5-7 have no line-up capture.
2. The line-ups for Nov 1-3 are same-day captures, not the 00:05 list.

## Recommendation
- The stack is better on this leak-free backtest, with its interval clear of zero. Under "how models are chosen" it
  is therefore a deployment candidate for the BACKER-v2 slot. The orchestrator makes that call and E5 owns the
  backer model.
- Serving cost: P(yes) for the full pool x the line-up every night is about 150k pairs, roughly 10 A100-minutes,
  about $0.6 a day.
- Before deploying, run the full pool on test. The gain may also shrink with fresh reads, because presence then
  carries more of the signal.

Files: `results.json` (aggregates only); code `simharness/finetune/stack1.py`. Score-only mode is in
`simharness/finetune/gcp/startup_choice.sh`. Private rows and scores are under
`gs://usersim-bakeoff-347838016394/usersim_sim/simharness/choice_ft1/` (`data/val_*`, `runs/stack1-val/`).
