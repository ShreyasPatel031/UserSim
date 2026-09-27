# Making the G-FOCUS judge repeatable on gemini-2.5-flash (2026-09-27 PT)

Branch `grokbot/pairwise-judge`, module `mvp/pairwise.py`. Model: gemini-2.5-flash only (Vertex, thinking off, 429 backoff
across regions). No tuning. Dev = the 75 dev pairs (`dev_indices.txt`).

**Problem.** The baseline, G-FOCUS single judge (stream `gfocus`: v1 prompts, strict per-order chains, both orders,
temperature 1), is too noisy to show input effects. Its two independent runs gave the same per-pair CA outcome on only 53/75
pairs, and the same picks in both orders on only 42/75 (FLASH_INPUTS_REPORT.md).

## New flags (`PairFlags`, all default to the old behaviour; names and cache keys of old runs are unchanged)
- `argue_temperature` (already existed): the temperature of every G-FOCUS stage (goal, differences, both-side reasons, Evaluator).
  `run_bench.py --argue-temperature 0`.
- `samples_per_order` (new, default 1): N G-FOCUS judgments per judge and order, then a **majority vote of their First/Second
  picks per order**. `vote_judgment` keeps the votes and each sample's pick and reason. A tied vote (only possible after a failed
  parse or with even N) counts as a tie for that order.
- `sample_stage` (new, default "all"): where the samples branch.
  - `all`: the whole chain.
  - `argue`: one goal/difference extraction per order, then N x (both-side reasons + Evaluator).
  - `evaluator`: one chain up to the reasons, then N Evaluator calls.
- Sample 0 always uses the single-run call keys, and sample s > 0 appends `|s<s>`. So a cached single run can serve as sample 0,
  and samples never share a cache entry. Independent runs use separate ledgers (`--out` dirs), so they share no keys.
  `--seed-ledger` / `--seed-match` copy an earlier run's calls in at $0.
- Tests: `mvp/test_pairwise.py` checks keys, counts per stage, majority vote, ties, and that default names are unchanged
  (20/20 pass, including the existing short-pick test).

## Step 1: noise options (75 dev pairs, two independent runs each) -- `fullset/noise_agreement_dev.md`
| option | same CA outcome [95% CI] | same picks, both orders [95% CI] | per-order pick agreement | same OI winner | CA run 1 | CA run 2 | $/pair |
|---|---|---|---|---|---|---|---|
| baseline: temperature 1, 1 sample (existing runs) | 53/75 = 70.7 [60.0, 81.3] | 42/75 = 56.0 [45.3, 66.7] | 74.0 | 61.3 | 49.3 | 46.7 | 0.0114 |
| **a) temperature 0** | **74/75 = 98.7 [96.0, 100.0]** | **70/75 = 93.3 [86.7, 98.7]** | **96.0** | **94.7** | **53.3** | **52.0** | **0.0112** |
| b) temperature 1, 3 samples/order, majority vote (sample_stage=evaluator) | 50/75 = 66.7 [56.0, 77.3] | 40/75 = 53.3 [41.3, 64.0] | 70.7 | 58.7 | 53.3 | 46.7 | 0.0194 |

Accuracy of every run against the old baseline run: `fullset/noise_options_dev.md`. Every dCA CI includes 0.
T0 runs: CA 53.3 and 52.0, AA 68.0 and 66.7, OI 68.0 and 66.7. Old T1 runs: CA 49.3 and 46.7.

- **Temperature 0 makes the verdicts repeatable.** Across the two runs, one pair changed its CA outcome and 5/75 changed a
  per-order pick. Accuracy did not drop (CA 53.3 / 52.0 vs 49.3 / 46.7 at T1). It costs the same as the baseline.
  Vertex T0 is not byte-deterministic: only 77-88% of calls returned identical text per stage (goal 132/150, differences 126/150,
  reasons 117-123/150, Evaluator 115/150). Even so, the final picks are stable.
- **Voting 3 Evaluator samples does not help** (66.7% vs 70.7% at baseline). Most of the noise comes from the upstream T1 stages
  (goal, differences, reasons), and a vote over the last stage alone cannot remove it. It also adds $0.008 per pair.
- **Budget change to option b.** The full-chain vote the spec describes (`sample_stage=all`, 3 samples) would have cost about
  $0.034 per pair, about $3.4 for two runs even with the existing T1 runs reused as sample 0. Together with option a (~$1.7), that
  is over the $5 cap before step 2. So option b was run as `sample_stage=evaluator`. The `all` and `argue` stages are implemented
  and tested but were **not run**. 5 samples were not considered: 3 were not better.
- Run 1 of option b: an ordering mistake in my runs (a 2-pair smoke run created the ledger first, so the $0 seed did not apply)
  made 49 of its 75 pairs draw a fresh T1 sample 0 instead of reusing the cached baseline run
  (`results/noise_v3e_r1/sample0_source.json`). The samples are still independent T1 draws, so the option is still valid. It
  wasted about $0.55 (49 pairs x $0.0114).

**Chosen setup: G-FOCUS single judge, strict, both orders, `argue_temperature=0`, 1 sample.**

## Step 2: + difference list on the chosen setup (T0), 75 dev pairs -- `fullset/noise_difflist_dev_vs_r1.md`
The difference list is the same JSON diffs step as before (`gf_diff_list`). Its temperature-0 calls were copied from the earlier
diff_list ledger (`--seed-match '^goal\|'`). Every G-FOCUS stage ran fresh at T0.

| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p (n01/n10) | significant | AA | FA / SA | OI | $/pair |
|---|---|---|---|---|---|---|---|---|
| base, T0 run 1 | 53.3 [42.7, 64.0] | | | | 68.0 | 61.3 / 74.7 | 68.0 | 0.0112 |
| + diff_list, T0 | 45.3 [34.7, 56.0] | **-8.0 [-18.7, +2.7]** | 0.238 (6/12) | no | 62.7 | 53.3 / 72.0 | 62.7 | 0.0120 |
| (vs base, T0 run 2) | | -6.7 [-17.3, +5.3] | 0.359 (7/12) | no | | | | |

- At T0 the difference list does **not** help. It is -8 CA on dev (not significant), where the noisy T1 comparison showed +8.
  That sign flip is consistent with FLASH_INPUTS_REPORT.md: the T1 dev gain was noise, and it shrank to +1.7 on held-out.
- With T0, run-to-run noise is about 1 pair in 75. The remaining uncertainty is the sampling of pairs (CI about +/-11 CA at
  n=75), not judge noise.
- **Held-out (177 pairs) was not run.** Base T0 plus diff_list T0 would cost about $4.1, and only about $0.77 was left.

## Spend (new calls only, Vertex list price)
| run | $ |
|---|---|
| T0 run 1 / run 2 (75 dev each) | 0.844 / 0.837 |
| vote-3 (evaluator) run 1, including the 2-pair smoke and the unplanned fresh sample 0 / run 2 | 1.156 / 0.605 |
| T0 + diff_list (75 dev) | 0.793 |
| **total** | **4.235** (cap $5) |

## Recommendation
Use `argue_temperature=0` for the G-FOCUS judge in the product and in every future ablation. It is repeatable, costs the same
and is no less accurate. At T0, one run per arm is enough to compare arms. The error bars then come from the pair set, so
arms should be compared paired on the same pairs (arm_compare.py), and a confirmation on held-out pairs is still needed before
claiming an effect. Drop the difference list for now.

## Files
`results/noise_t0_r1`, `noise_t0_r2`, `noise_v3e_r1`, `noise_v3e_r2`, `noise_t0_diff_list` (on the box, not committed);
`fullset/noise_agreement_dev.{md,json}`, `fullset/noise_options_dev.{md,json}`,
`fullset/noise_difflist_dev_vs_r1.{md,json}`, `fullset/noise_difflist_dev_vs_r2.md`; `noise_agree.py`.

## Step 3: the other four inputs on the stable setup (T0), 75 dev pairs -- `fullset/noise_inputs_t0_dev_vs_r1.md`
Approved by Shreyas at 5:32 AM PT. Setup: G-FOCUS single judge, strict, both orders, `argue_temperature=0`, 1 sample.
Each input is added alone. The baseline is T0 run 1. The cross-check against T0 run 2 is `fullset/noise_inputs_t0_dev_vs_r2.md`.
All four arms ran at once (4 x 75 pairs in flight, `--concurrency 96` each, 429 spillover across regions).
The goal arm's stated-goal call (temperature 0) was copied from the earlier goal ledger. Everything else ran fresh.
The diff_list row is repeated from step 2.

| arm | CA [95% CI] | dCA vs base [95% CI] | McNemar p (improved/worse) | significant | OI | $/pair |
|---|---|---|---|---|---|---|
| base (T0 run 1) | 53.3 [42.7, 64.0] | | | | 68.0 | 0.0112 |
| + goal | 53.3 [42.7, 64.0] | +0.0 [-12.0, +12.0] | 1.000 (11/11) | no | 66.7 | 0.0110 |
| + audience | 50.7 [40.0, 61.3] | -2.7 [-13.3, +8.0] | 0.804 (7/9) | no | 65.3 | 0.0123 |
| + page_text (OCR) | 45.3 [34.7, 57.3] | -8.0 [-20.0, +4.0] | 0.307 (9/15) | no | 66.7 | 0.0121 |
| + crops | 38.7 [28.0, 49.3] | **-14.7 [-26.7, -4.0]** | **0.027 (5/16)** | **yes (hurts)** | 59.3 | 0.0127 |
| + diff_list (step 2) | 45.3 [34.7, 56.0] | -8.0 [-18.7, +2.7] | 0.238 (6/12) | no | 62.7 | 0.0120 |

Against T0 run 2 (CA 52.0), the changes are:

| arm | dCA [95% CI] | McNemar p (improved/worse) |
|---|---|---|
| goal | +1.3 [-10.7, +14.7] | 1.000 (12/11) |
| audience | -1.3 [-12.0, +9.3] | 1.000 (8/9) |
| page_text | -6.7 [-20.0, +6.7] | 0.424 (10/15) |
| crops | -13.3 [-25.3, -1.3] | 0.052 (6/16) |
| diff_list | -6.7 [-17.3, +5.3] | 0.359 (7/12) |

So crops are borderline against run 2 (p = 0.052 and the CI excludes 0), and nothing else is significant.

- **No input helps.** goal and audience are neutral, at about +/-3 CA.
- page_text and diff_list lean negative but are not significant. page_text again pushes toward the second version (FA 52.0 vs SA 81.3).
- **The pixel-diff crops hurt.** CA drops by 14.7 against run 1 (significant) and by 13.3 against run 2 (p = 0.052). FA falls to 50.7.
- Recommendation: keep the plain G-FOCUS judge at T0 with no extra inputs, and drop crops.
- Timing: launched at 05:33:34 PT.
  - The goal arm finished at 05:34:48 (74 s). The other three reached 70/75 pairs by about 05:35:15.
  - 5 pairs then stalled on hung Vertex calls with no new calls for about 3 min. `gemini_generate` has no per-request timeout.
  - I killed and resumed those runs from the cache. They finished at 05:38:22 (the resume took 15 s). Total wall time was 4 min 48 s.
- Spend for step 3: goal $0.823, audience $0.923, page_text $0.907, crops $0.956, **total $3.61** (cap $4).
  Steps 1-3 together: $7.84.
