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

## Step 4: few-shot Evaluator (T0), 75 dev pairs -- `fullset/noise_fewshot_dev_vs_r1.md`, `..._vs_r2.md`
Approved by Shreyas at 5:46 AM PT. Setup: the stable baseline (G-FOCUS single judge, strict, both orders, T0, no extra inputs)
plus K solved examples.

**How the examples are built and chosen.**
- Each example has its page context (company, industry, page type), both screenshots, and the real winner as
  "Better version: First/Second".
- The pool is the 75 dev pairs, leave-one-out: the pair being judged is never its own example. `pick_examples` prefers the same
  page type and industry, then the same page type, then the same industry, then random. Ties are broken by a shuffle seeded by
  (seed 0, pair).
  - K=3: of 225 example slots, 105 matched page type and industry, 114 page type only, 6 industry only.
  - K=5: of 375 slots, 138 / 202 / 32 matched, and 3 matched nothing.
- The winner's position is balanced within each pair's examples: k//2 winner-first, and the odd one out is a seeded coin flip.
  Overall, K=3 had 109 First / 116 Second, and K=5 had 184 First / 191 Second.

**Where the examples go.** They are added to the **Evaluator step only**. The earlier stages (goal, differences, both-side
reasons) are the T0 run 1 calls, copied in with `--seed-ledger noise_t0_r1 --seed-match ...`. So against run 1, the only
difference is the Evaluator prompt. Adding the examples to every stage was not cheap: it would re-run all 10 calls per pair with
2K more images each.

**Flags and code.**
- `PairFlags.few_shot_k` / `few_shot_seed`; `compare_pair(..., few_shot_pool=[FewShotExample], pair_id=...)`.
- `run_bench.py --few-shot-k K --few-shot-pool @dev_indices.txt`.
- Evaluator input grew from about 1.9k tokens to 3.7k (K=3) and 4.9k (K=5).
- Model calls now have a per-request timeout (`MVP_GEMINI_TIMEOUT_S`, default 90 s, via `HttpOptions`). A hung call raises and is
  retried with backoff instead of stalling. No call hung in this run.

| arm | CA [95% CI] | dCA vs T0 run 1 [95% CI] | McNemar p (improved/worse) | dCA vs T0 run 2 [95% CI] | McNemar p (improved/worse) | significant | OI | FA / SA | $/pair |
|---|---|---|---|---|---|---|---|---|---|
| base T0 run 1 | 53.3 [42.7, 64.0] | | | +1.3 | | | 68.0 | 61.3 / 74.7 | 0.0112 |
| base T0 run 2 | 52.0 [41.3, 62.7] | | | | | | 66.7 | 64.0 / 69.3 | 0.0112 |
| + few-shot K=3 | 50.7 [40.0, 61.3] | -2.7 [-8.0, +2.7] | 0.625 (1/3) | -1.3 [-5.3, +2.7] | 1.000 (1/2) | no | 64.7 | 58.7 / 70.7 | 0.0120 |
| + few-shot K=5 | 46.7 [36.0, 57.3] | -6.7 [-13.3, -1.3] | 0.062 (0/5) | -5.3 [-10.7, -1.3] | 0.125 (0/4) | no | 62.0 | 57.3 / 66.7 | 0.0127 |

FA = accuracy when the winner is shown first, SA = when it is shown second.
$/pair is the full per-pair cost, including the copied upstream calls. The new spend per pair is only the Evaluator: about
$0.0045 (K=3) and $0.0053 (K=5).

- **Few-shot does not help.** K=3 changes the CA outcome of only 4 pairs (1 better, 3 worse).
  K=5 changes 5 pairs, all for the worse. That is borderline (McNemar p = 0.062; the bootstrap CI excludes 0), and it also lowers
  OI and AA.
- Position bias is unchanged or slightly worse (FA 58.7 / 57.3 vs SA 70.7 / 66.7). So showing examples with balanced winner
  positions does not teach the Evaluator to ignore position.
- With only the winner label and no reasoning, the examples are mostly ignored. The Evaluator still follows its own reasons.
- Timing:
  - Both arms launched at 05:48:08 PT with all 75 pairs in flight.
  - K=3 finished at 05:48:43 (35 s).
  - The K=5 process ran out of memory at about 05:48:41: 150 requests with 12 full-size PNGs each at concurrency 96 reached 6.5 GB.
    It had recorded no calls.
  - Rerun at concurrency 32, it went from 05:48:57 to 05:49:31 (34 s).
  - Total wall time was 83 s.
- Spend recorded in the ledgers: K=3 $0.339 and K=5 $0.396, **total $0.735** (cap $3).
  The Evaluator calls that were in flight when the K=5 process was killed may also have been billed by Vertex without being
  recorded. The upper bound is about 150 x $0.0026 = $0.39. So the worst case is about $1.13.

## Step 5: the stable G-FOCUS setup on Gemini 3.1 Pro (preview), 75 dev pairs -- `fullset/pro31_vs_flash_t0_r1.md`, `..._r2.md`
Approved by Shreyas at 5:57 AM PT: one run. Model `gemini-3.1-pro-preview` on Vertex, called through the `global` endpoint, which
is the only one that serves the 3.x previews and routes across regions itself.
Setup: G-FOCUS single judge, strict, both orders, temperature 0, no extra inputs. The prompts are the same as the Flash runs.

**Model-specific changes** (in `gemini_generate`, only for `gemini-3*`):
- Gemini 3 cannot turn thinking off, so it runs at `thinking_level=low` (`MVP_GEMINI3_THINKING`).
- Thinking gets 8k tokens of headroom on top of each stage's max_tokens.
- Thinking tokens are counted as output, which is how they are billed.
- `arm_compare.py` now prices each call at its own model's list price ($2 / $12 per 1M in/out for 3.1 Pro).
- Selected with `MVP_PAIRWISE_MODEL=gemini-3.1-pro-preview`.

| arm | CA [95% CI] | dCA vs Flash T0 run 1 [95% CI] | McNemar p (improved/worse) | dCA vs Flash T0 run 2 [95% CI] | McNemar p (improved/worse) | significant | OI | FA / SA | $/pair |
|---|---|---|---|---|---|---|---|---|---|
| Flash T0 run 1 | 53.3 [42.7, 64.0] | | | | | | 68.0 | 61.3 / 74.7 | 0.0112 |
| Flash T0 run 2 | 52.0 [41.3, 62.7] | | | | | | 66.7 | 64.0 / 69.3 | 0.0112 |
| **3.1 Pro T0** | 50.7 [40.0, 61.3] | -2.7 [-17.3, +12.0] | 0.856 (14/16) | -1.3 [-16.0, +13.3] | 1.000 (15/16) | no | 69.3 | 56.0 / 82.7 | 0.0703 |

- **3.1 Pro is no better than Flash on this task.** CA is 50.7 vs 53.3 / 52.0, and OI 69.3 vs 68.0 / 66.7 is within noise. It
  costs 6.3x as much per pair.
- It disagrees with Flash on about 30 of 75 pairs (14 better, 16 worse against run 1), so it is a different judge but not a better one.
- Its position bias is stronger. It favours the second-shown version (FA 56.0 vs SA 82.7). That is why its CA falls below its AA
  (69.3).
- Per pair: 25.5k input tokens (Gemini 3 images are larger) and 1.6k output tokens, including low thinking. No errors, no format
  retries, 0 failed judgments.
- **Wall time: 58 s** for all 75 pairs (05:58:46 to 05:59:44 PT, 750 calls in flight together).
  Before that, a 1-pair smoke run took 18 s; it was the same run, resumed from its cache.
- **Spend: $5.27** (cap $15), including the $0.067 smoke pair.

## Step 6: one supervised tune of gemini-2.5-flash on the short-pick prompt -- `fullset/sft_split_dev*.md`
Approved by Shreyas at 5:57 AM PT: exactly one Vertex SFT job.

**Training data.** `sft_folds.py build-split` builds 354 rows: the 177 non-dev clean pairs x 2 orders
(`fullset/heldout177_indices.txt`).
- The prompt is the short-pick prompt, with both screenshots fit to 768 px.
- The target is "Better version: First/Second". In 215 rows it is followed by "Reason: ..." (a condensed Key Rationale from the
  baseline G-FOCUS Evaluator where that Evaluator was right). The other 139 rows are pick-only.
- The dataset's rationale is never used.
- The winner is shown first in 177 rows and second in 177.
- The rows and images are in the project GCS bucket and in `$WISERUI_BENCH/ft/sft/`. They are not committed.

**The job.**
- The token estimate before launch (`count --split`, 16 sampled rows) was 687 tokens/row, so 3 epochs came to 0.73M training
  tokens, about $3.65.
- Launched at 05:59:53 PT with `launch --split --epochs 3`, us-central1.
- Job `tuningJobs/8131719039589285888`, SUCCEEDED at 06:18:14 PT (18 min).
- Endpoint `endpoints/2462471189369454592`.
- Vertex reports 241,479 billable dataset tokens (354 examples). Billed tokens = 3 epochs x 241,479 = **724k tokens, about $3.62**
  at $5/1M.
- The five fold jobs from the earlier aborted run (05:13 PT) were already CANCELLED at 05:17-05:18 PT. They were not touched.

**Scoring.** On the 75 dev pairs, temperature 0, both orders, same prompt as the untuned run (`results/sft_untuned_shortpick`,
gemini-2.5-flash). Dev pair 255 has only one parsed order in the untuned run.

| arm | CA [95% CI] | dCA vs untuned [95% CI] | McNemar p (improved/worse) | significant | OI | FA / SA | $/pair |
|---|---|---|---|---|---|---|---|
| untuned 2.5 Flash, short pick | 34.7 [24.0, 45.3] | | | | 60.0 | 42.7 / 76.0 | 0.0006 |
| **tuned 2.5 Flash, short pick** | 34.7 [24.0, 45.3] | +0.0 [-10.7, +10.7] | 1.000 (9/9) | no | 57.3 | 69.3 / 45.3 | 0.0005 |
| G-FOCUS Flash T0 run 1 | 53.3 [42.7, 64.0] | +18.7 [+5.3, +32.0] | 0.013 (21/7) | yes | 68.0 | 61.3 / 74.7 | 0.0112 |
| G-FOCUS Flash T0 run 2 | 52.0 [41.3, 62.7] | +17.3 [+4.0, +29.3] | 0.019 (20/7) | yes | 66.7 | 64.0 / 69.3 | 0.0112 |

The tuned model against G-FOCUS T0:

| comparison | dCA [95% CI] | McNemar p (improved/worse) | significant |
|---|---|---|---|
| vs run 1 | -18.7 [-30.7, -6.7] | 0.009 (6/20) | yes |
| vs run 2 | -17.3 [-29.3, -5.3] | 0.015 (6/19) | yes |

- **Tuning did not help.** Tuned CA equals untuned CA (34.7). 9 pairs got better and 9 got worse.
- It mostly flipped the position bias. Untuned short-pick picks the second-shown version 99/148 times (FA 42.7 / SA 76.0).
  The tuned model picks the first-shown version 93/150 times (FA 69.3 / SA 45.3).
  With 177 train pairs, the model learned a position prior, not a UI judgement.
- Both short-pick models are far below the G-FOCUS judge: about -18 CA, significant against both T0 runs.
  One-call picking is about 20x cheaper per pair, but not usable at this accuracy.
- Scoring wall time was 96 s (06:21:28 to 06:23:05 PT, 150 calls; the tuned endpoint is slower than base Flash).
  Scoring cost $0.039 (billed at base Flash price).

## Spend for steps 5-6 (approved 5:57 AM PT)
| item | $ |
|---|---|
| 3.1 Pro G-FOCUS run (75 dev, including the smoke pair) | 5.27 (cap 15) |
| SFT job: 724k billed training tokens | about 3.62 (cap 5) |
| tuned endpoint scoring (75 dev) | 0.04 |
| token counting (`count_tokens`) | 0 |
| **total** | **about 8.93** |
