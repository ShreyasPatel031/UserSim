# STACK-1b (Nov 26 2026): the frozen STACK-1 stack on the full test pool

STACK-1 combined BACKER-v2's features with P(yes) from the CHOICE-FT-1 tuned model (500k-row adapter) in one
logistic. That stack beat BACKER-v2 on a 15% sample of the test pool. This run checks it on the whole pool.

The pool is every held person-day of Nov 11-22, crossed with that day's 00:05 PT line-up: 57,080 person-days,
1,654,907 pairs, 24,270 held backers, 359 launches with a backer. The stack is STACK-1's fit, rebuilt from the
validation pairs and checked to give identical coefficients; it was not refit on test. Intervals are launch
bootstrap 95% with 2,000 draws, paired on the same launches.

**Result: the gain holds and is clearer on the full pool.** Recall@N is +1.4 [+1.0, +1.7] points over BACKER-v2
walk-forward (39.0 to 40.3), and per-launch AUC is +0.005 [+0.004, +0.006].

| Model (full pool) | recall@N pooled | AUC mean per launch |
|---|---|---|
| BACKER-v2 logistic, walk-forward | 39.0 [38.0, 39.9] | 0.939 [0.935, 0.942] |
| P(yes) of the tuned model alone | 37.6 [36.5, 38.7] | 0.940 [0.935, 0.944] |
| **Stack (BACKER-v2 features + logit P(yes), frozen)** | **40.3 [39.3, 41.2]** | **0.943 [0.939, 0.947]** |

| Paired difference | recall@N | AUC |
|---|---|---|
| stack - BACKER-v2 | **+1.4 [+1.0, +1.7]** | **+0.005 [+0.004, +0.006]** |
| P(yes) alone - BACKER-v2 | -1.3 [-2.1, -0.6] | +0.001 [-0.000, +0.003] |

On the 15% sample in STACK-1 the stack's gain was +1.0 [+0.2, +1.9]. On the full pool the gain is a bit larger and
its interval is much narrower.

## Serving: measured nightly time and cost
- **Time.** Scoring took 4.3 ms per pair on one A100 40GB: 6,048 s for 1,406,597 pairs, model loading included.
  A test night averages 137,909 pairs (pool x line-up), which is 9.9 minutes of scoring. Setup (driver, packages,
  model download) adds about 6 minutes, for about 16 VM-minutes a night.
- **Cost.** About $0.97 a night on a standard A100 ($3.673/h). On a spot A100 ($2.204/h) it is about $0.58, but a
  spot VM can be preempted, as one was in this run.
- **Prices.** Both prices come from the Cloud Billing catalog for us-central1.
- **Inputs.** The forecast also needs that day's line-up and histories as known at 00:05.

## Cost of this run: $5.64 of the $6 budget
| VM | Type | Runtime | What happened | Cost |
|---|---|---|---|---|
| 1st | standard A100 | 21.2 min | stopped by me once it was clear it would overrun its run-time cap and its budget | $1.30 |
| 2nd | spot A100 | 88.2 min | finished 3 of the 4 shards, then was preempted | $3.24 |
| 3rd | spot A100 | 28.7 min | finished the last shard | $1.05 |
| | disk | | | $0.05 |

There were no model API calls.

## Deviations
1. **Reused scores.** P(yes) for the 8,564 person-days of CHOICE-FT-1's 15% sample was reused from that run, with
   the same adapter and prompts. The other 48,516 person-days were scored here.
2. **GPU.** Scoring ran on spot A100s instead of a standard A100. A standard A100 could not score the whole pool
   inside the $6 budget at the measured speed of about 2.2 s per batch, so the first VM was stopped after 21 minutes.
3. **Shards.** The rest of the pool was split into 4 shards, each uploaded when done. The first spot VM was
   preempted after 3 shards, and a second spot VM (35-minute cap) scored the last one.

## Leak checks
- 0 @handles in prompts.
- The history rules are the same as in CHOICE-FT-1.
- The stack's fit uses validation days only. Its coefficients are asserted equal to STACK-1's.

## Recommendation
The frozen stack is better than BACKER-v2 on the leak-free full-pool backtest, with its interval clear of noise.
Under "how models are chosen" it qualifies for the BACKER-v2 slot, with BACKER-v2 kept as the forward shadow line.
Deploying is the orchestrator's and E5's call. The serving cost is about $1 a night. Nothing was deployed here.

Files: `results.json` (aggregates only); code `simharness/finetune/stack1b.py`. Private rows and scores are under
`gs://usersim-bakeoff-347838016394/usersim_sim/simharness/choice_ft1/` (`data/rest_*`, `runs/stack1b-*`).
