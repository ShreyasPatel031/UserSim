# Benchmark v0, Task V, round 1 (Nov 24 2026)

Question: once a person's activity is controlled for, does anything beat the per-person logistic (recency-weighted
upvotes + topic match) at saying who upvotes THIS launch, and does a language model add anything on top?

Answer: barely. With activity matched, every model sits between 0.50 and 0.58 AUC. taste-v1 (a learned model on
history features) is ahead of the logistic with the interval clear, but by 0.01 on all rows, and it does not work as a
full-pool ranker. No language model and no stack with a language model is clear of the logistic or of taste-v1.

Aggregates only in this folder (`results.json`, `table.md`). Rows, predictions and model outputs are private, under
`gs://.../usersim_sim/simharness/bench_v0/round1/` (`wip/data/` for per-row predictions and the call cache).

## Evaluation sets

| Set | What | Size |
|---|---|---|
| HARD | every held voter of every test launch (Nov 11-22) + one non-voter of that launch from the same day pool, matched on the nearest rw30 (recency-weighted upvotes in the 30 days before the day, 7-day half-life) | 50,100 rows, 394 launches, 12 days |
| HARD-LLM | fixed subsample of HARD that every prompt model scores: 40 launches over all 12 days x (12 voters + 12 matches) | 960 rows |
| VAL-HARD / VAL-HARD-LLM | the same construction on Nov 1-10 (choosing learners, fitting stack weights) | 48,864 / 480 rows |
| EASY | the v0 smoke sample: 20 test launches x (15 voters + 15 random pool non-voters) | 600 rows |
| FULL | full-pool ranking on every test launch | 1.8M pairs |

The matching works: most-active falls from 0.897 (EASY) to 0.499 (HARD), the logistic from 0.923 to 0.518.
Residual: matching is on rw30 only. Mean rw30 is 43.9 for voters and 37.9 for matches (the heaviest voters have no
equally heavy non-voter), and finer recency (upvotes in the last 7 days at equal rw30) still carries some signal.

## Results (95% intervals; bootstrap over launches, FULL over days)

| Model | HARD AUC (50,100 rows) | HARD-LLM AUC (960 rows) | vs logistic on HARD-LLM (paired) | EASY AUC | FULL recall@N | FULL AUC | $ / 1k | s / call |
|---|---|---|---|---|---|---|---|---|
| most-active | 0.499 [0.494, 0.502] | 0.461 [0.424, 0.492] | -0.047 [-0.070, -0.027] | 0.897 [0.871, 0.923] | 32.0 [30.4, 33.9] | 0.918 | 0 | |
| logistic (rw + topic) | 0.518 [0.515, 0.520] | 0.507 [0.482, 0.533] | | 0.923 [0.895, 0.948] | 38.5 [36.6, 40.5] | 0.938 | 0 | |
| taste-v1 | 0.529 [0.521, 0.537] | 0.579 [0.538, 0.620] | +0.072 [+0.013, +0.132] | 0.604 [0.523, 0.679] | 15.9 [14.5, 17.3] | 0.615 | 0 | |
| gemini-2.5-flash | | 0.528 [0.511, 0.549] | +0.021 [-0.007, +0.050] | | | | 0.52 | 0.98 |
| gpt-oss-120b | | 0.517 [0.488, 0.549] | +0.010 [-0.019, +0.040] | | | | 0.27 | 0.72 |
| llama-4-maverick | | 0.522 [0.505, 0.541] | +0.015 [-0.009, +0.042] | | | | 0.49 | 0.72 |
| claude-haiku-4-5 * | | 0.517 [0.497, 0.537] | not available | | | | 1.64 | 1.00 |
| claude-sonnet-4-6 * | | 0.530 [0.515, 0.543] | not available | | | | 4.91 | 1.83 |
| gemini-2.5-flash-lite tuned (yes/no, 4,000 train rows) * | | 0.517 [0.494, 0.543] | not available | | | | 0.14 | 0.80 |

\* Scored before a container restart that lost the per-row scores; the rebuilt rows are the same (identical input-token
counts), so the AUC stands (day-bootstrap interval), but there is no paired difference and no stack for these three.
The three models scored twice moved by 0.003 to 0.013 between runs (temperature 0.2).

On all HARD rows taste-v1 minus logistic is +0.011 [+0.003, +0.020] pooled and +0.018 [+0.010, +0.026] as the mean
per-launch AUC. Against taste-v1 on HARD-LLM the prompt models are behind: Gemini -0.051 [-0.098, -0.003],
Llama -0.057 [-0.104, -0.011], gpt-oss -0.062 [-0.121, +0.000].

| Stack (weights fit on validation only) | HARD AUC | HARD-LLM AUC | vs logistic (paired) | vs its non-LLM member |
|---|---|---|---|---|
| logistic + taste-v1 | 0.526 [0.519, 0.534] | 0.576 [0.537, 0.616] | +0.009 [+0.001, +0.018] (HARD) | |
| logistic + gemini-2.5-flash | | 0.516 [0.495, 0.536] | +0.009 [-0.035, +0.054] | +0.009 [-0.035, +0.054] |
| logistic + gpt-oss-120b | | 0.520 [0.488, 0.553] | +0.013 [-0.025, +0.050] | +0.013 [-0.025, +0.050] |
| taste-v1 + gemini-2.5-flash | | 0.578 [0.539, 0.618] | +0.071 [+0.013, +0.129] | -0.001 [-0.004, +0.002] |
| taste-v1 + gpt-oss-120b | | 0.587 [0.553, 0.620] | +0.079 [+0.030, +0.128] | +0.008 [-0.016, +0.033] |
| logistic + taste-v1, full pool | | | recall@N 36.8 [35.6, 38.2] vs 38.5: -1.7 [-2.7, -0.6] | |

Reading:
- A language model's score adds nothing measurable to either non-LLM model (the last column is never clear of zero).
- taste-v1 is not a replacement for the logistic: it was chosen on validation (VAL-HARD 0.565, validation full-pool
  AUC 0.88) but its full-pool ranking fell apart on test (recall@N 15.9 vs 38.5), where the pool is smaller and made of
  recently re-read heavy voters. Its trees lean on absolute activity (76% of gain on rw and 7-day count) and that
  mapping did not carry over. The logistic stays the full-pool model.
- Where taste-v1's edge on HARD comes from (LightGBM on feature groups, all HARD rows, mean per-launch AUC): the
  logistic 0.523; finer activity only 0.537; activity + text embeddings 0.546; all features 0.541. So about two
  thirds of the edge is finer recency of activity, and what the person backed before (topics, embeddings) adds
  +0.008 [+0.004, +0.012] pooled AUC over activity alone: real, and very small.

## taste-v1
LightGBM on 13 history features (`simharness/features.py`): activity (rw, counts over 7 / 30 / 60 days and all time),
topic shares, cosine between a local bge-small embedding of the launch (name + tagline) and the person's
recency-weighted mean / last-30 backed launches, comment count and rate. Trained on train days only (517,376 rows
<= Oct 31: up to 60 voters per launch, their activity matches, 20 random pool non-voters), frozen, applied to
validation and test unchanged. Three weightings were tried on validation; the rule (written before the run) picked
"pool-weighted, hard negatives 10% of the negative mass". Makers and descriptions are not used (missing for launches
after Oct 25 in the item table).

## Leak checks (all passed; `results.json` -> `leak_checks`)
- Item table has no vote, rank or outcome column; embeddings use name + tagline only.
- taste-v1 training rows end 2026-10-31; the logistic asserts every training day is before the scored day (and now
  refits when asked for an earlier day; a reused model instance would otherwise have seen that day's labels).
- Person state at day D recomputed independently from history rows with item day < D: max difference 4e-13.
- 240 prompts checked: 0 history events on or after the day, 0 timed after the day's start, the launch itself never
  in a history, newest history item at least 1 day old; 0 @handles (they are replaced in comments and launch text).
- HARD: 0 negatives that voted for their launch, 0 rows outside the day's pool.
- Known and unchanged from v0: upvotes are undated and attributed to the launch day, so a late upvote on an older
  launch can enter a history; the logistic's labels for day D-1 are read after D (offline convention).

## Spend (USD; cap 20)

| Model | Spend |
|---|---|
| claude-sonnet-4-6 (test + validation) | 6.93 |
| gemini-2.5-flash-lite supervised tuning (1 job, 4.22M training tokens) | 6.33 |
| claude-haiku-4-5 (test + validation) | 2.31 |
| gemini-2.5-flash (test twice, validation twice) | 1.47 |
| llama-4-maverick (test twice, validation once) | 1.16 |
| gpt-oss-120b (test twice, validation twice) | 0.78, plus at most 0.53 in two runs killed on a hung connection |
| tuned flash-lite scoring, probes | 0.14 |
| **Total** | **19.13 to 19.66** |

$1.60 of this is the second scoring of the three cheapest models after the restart (to get per-row scores back for the
paired differences and stacks). Every call is now cached in append-only files copied to the bucket as it runs.

## Fine-tune: prices and plan (price only from here; the pipeline lives in `simharness/finetune/`)
- **Gemini on Vertex, supervised tuning.** Billing catalog prices per 1M training tokens: 2.5 Flash-Lite $1.50,
  2.5 Flash $5.00, 2.5 Pro $25.00; a tuned model serves at the base model's token price. Task V rows are about 1,055
  tokens each (activity-aware prompt, yes/no answer), so 4,000 rows x 1 epoch = 4.22M tokens = $6.33 on Flash-Lite
  ($21 on Flash); 40,000 rows x 1 epoch = $63; x 3 epochs = $190. No new API or terms needed.
  One such job (Flash-Lite, 4,000 balanced HARD train rows, 1 epoch, 13 minutes) had already run before the
  price-only instruction: HARD-LLM 0.517 [0.494, 0.543], no better than untuned models. No other job was started.
  Its endpoint still exists (billed per token only).
- **Open model with LoRA on one GPU.** Quota is there (us-central1: L4 32, T4 16, A100 16, none needs enabling).
  Not measured here, estimated: a 7-8B model with QLoRA on one L4 (about $0.85 an hour) at 1.5-2.5k training tokens
  a second does 4,000 rows x 3 epochs (12.7M tokens) in 1.5-2.5 hours, about $2; 40,000 rows x 1 epoch in 5-8
  hours, about $5-7. Train on `hard_train_sample.parquet` (403,456 rows saved for this), score P(yes) from the first
  token on `llm_sub_test.parquet` (960 rows, comparable with every line above) and then on all of `hard_test.parquet`.
- Expectation from this round: a tuned model has to beat 0.53 pooled / 0.58 on HARD-LLM to matter, and the histories
  as rendered may not contain that much signal. Tie features (who made the launch, who follows whom) are the untested
  input, and they should go into the prompt before more tuning money is spent.

## Reproduce
`python -m simharness.run_round1 {sets,leak,taste,ablate,nonllm,llm,agg}` (see the module docstring).
