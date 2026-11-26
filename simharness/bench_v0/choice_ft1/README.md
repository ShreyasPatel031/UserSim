# CHOICE-FT-1 (Nov 26 2026): a 7B model fine-tuned on real yes/no backing choices

Question: does an open model fine-tuned on real (person, launch) backing choices name a launch's held backers in
advance better than BACKER-v2 / most-active, and does more training data keep helping?

**Answer: no, it does not beat BACKER-v2.** With 500,000 training rows the tuned Qwen2.5-7B ranks pairs as well as
the logistic (AUC +0.003 [+0.000, +0.005]), but it still names fewer real backers in each launch's top N
(recall@N -1.9 [-3.2, -0.6] points). It is clearly better than most-active (+4.4 [+3.0, +6.0]). More data helped a
lot up to 200k rows (50k: 26.9, 200k: 35.9). After that the curve is nearly flat: 350k gave 35.6, and 500k gave
37.0, a gain that coincides with the end of the learning-rate decay.

Files: `results.json` and `table.md` hold aggregates only. Code: `simharness/finetune/choice_ft1.py` (export,
baselines, agg), `simharness/finetune/choice_lora.py` (packed LoRA trainer and scorer, standalone) and
`simharness/finetune/gcp/startup_choice.sh` (self-deleting GPU job). Rows, prompts, scores and adapters are private,
under `gs://usersim-bakeoff-347838016394/usersim_sim/simharness/choice_ft1/` (`data/` and `runs/choice-ft1-b/`).

## Design (fixed before results; ledger row CHOICE-FT-1, status running, 08:20Z)
- **Data.** Benchmark v0 build 20261125T102222Z. A row is a (pool person, launch) pair. The pool is complete held
  people who were active in the 60 days before D and were read after D closed. The label is whether they upvoted
  the launch.
- **Prompt.** A person-day prefix plus one launch:
  - the prefix holds activity counts (yesterday / 7 / 30 / 60 days / all), active days, days since the last upvote,
    top 5 topics, the 12 latest upvoted launches and the 2 latest comments;
  - history includes only endorsements of launches dated before D and comments written before D starts;
  - the launch is described by its name, tagline and up to 4 topics.
- **Model.** Qwen2.5-7B-Instruct with LoRA r=16 (alpha 32, all projections), lr 2e-4 cosine with 5% warm-up, one
  epoch: the FT-TASKC recipe. The score is P(Yes) = sigmoid(logit "Yes" - logit "No") at the single answer
  position; the loss is cross-entropy on the real answer token.
- **Packing.** Each person-day is one sequence: the prefix once, then each launch attending only to the prefix and
  to itself (a 4-D mask, with positions restarted). This is checked equal to one prompt per pair (max logit
  difference 2e-7 on a test model).
- **Train.** Days Mar 2 to Oct 31 only. Person-days are drawn at random from the day pools: half with an upvote on
  the day's launches, half without. Each keeps all its positives plus 10 negatives drawn uniformly from the day's
  other launches. This gives 47,786 person-days, 500,000 rows and 44,314 positives (about 1:10.3), seed 0. The 50k,
  200k and 350k points are adapters saved during the same 500k run, scored when saved.
- **Test.** Nov 11-22 (the frozen test split). The candidates are each day's 00:05 PT line-up (361 launches)
  crossed with a fixed 15% random sample of each day's pool: 8,564 person-days, 248,310 pairs and 3,463 held
  backers on 356 launches that have one. It was scored once per adapter, with no tuning on test.
- **Baselines, on the same pairs.**
  - most-active: the 60-day count.
  - BACKER-v2-style logistic: ln recency-weighted upvotes, topic match and their interaction, walk-forward with a
    1-day gap. This is the primary comparison.
  - The same two models frozen on days up to Oct 31.
- **Metrics.** Per-launch recall@N (N = the launch's held backers in the scored pool; pooled and per-launch mean)
  and per-launch AUC. Intervals are launch-bootstrap 95% (2,000 draws); differences are paired on the same
  launches.

## Results (test, 15% pool sample x 00:05 line-up)

| Model | Training rows | recall@N pooled | recall@N mean | AUC mean | recall@N vs BACKER-v2 | AUC vs BACKER-v2 |
|---|---|---|---|---|---|---|
| BACKER-v2 logistic (walk-forward) | | 39.0 [37.4, 40.5] | 37.8 [35.5, 40.0] | 0.941 [0.935, 0.947] | | |
| BACKER-v2 logistic (frozen, Oct 31) | | 38.9 [37.4, 40.4] | 37.6 [35.4, 39.7] | 0.941 [0.935, 0.947] | -0.1 [-0.2, +0.1] | -0.000 |
| most-active | | 32.6 [31.1, 34.1] | 29.7 [27.8, 31.8] | 0.921 [0.914, 0.929] | -6.3 [-7.4, -5.3] | -0.020 [-0.023, -0.017] |
| Qwen2.5-7B, untuned | 0 | 12.8 [10.6, 14.9] | 5.7 [4.7, 6.7] | 0.741 [0.729, 0.753] | -26.1 [-28.5, -24.0] | -0.200 [-0.214, -0.188] |
| Qwen2.5-7B + LoRA | 50,000 | 26.9 [24.7, 28.9] | 18.7 [17.1, 20.5] | 0.926 [0.919, 0.932] | -12.1 [-14.2, -10.1] | -0.016 [-0.020, -0.012] |
| Qwen2.5-7B + LoRA | 200,000 | 35.9 [34.4, 37.4] | 33.6 [31.5, 35.8] | 0.942 [0.936, 0.948] | -3.0 [-4.3, -1.8] | +0.001 [-0.002, +0.004] |
| Qwen2.5-7B + LoRA | 350,000 | 35.6 [34.0, 37.0] | 32.6 [30.6, 34.8] | 0.942 [0.936, 0.948] | -3.4 [-4.7, -2.0] | +0.001 [-0.002, +0.003] |
| **Qwen2.5-7B + LoRA** | **500,000** | **37.0 [35.5, 38.4]** | **34.8 [32.8, 36.8]** | **0.944 [0.938, 0.950]** | **-1.9 [-3.2, -0.6]** | **+0.003 [+0.000, +0.005]** |

- **500k vs most-active:** recall@N +4.4 [+3.0, +6.0], AUC +0.023 [+0.018, +0.027].
- **Learning curve, paired:**

  | Comparison | recall@N | AUC |
  |---|---|---|
  | 500k - 50k | +10.2 [+8.2, +12.3] | +0.018 [+0.015, +0.022] |
  | 350k - 200k | -0.3 [-1.6, +0.9] | |
  | 500k - 350k | +1.5 [+0.7, +2.2] | +0.002 [+0.001, +0.003] |
  | 500k - 200k | +1.1 [-0.1, +2.4] | |

  The 50k, 200k and 350k adapters were saved mid-schedule, at a still-high learning rate. The 500k adapter is the
  only one at the end of the decay, so part of its last step is likely the decay and not the data.
- **Full pool, for reference** (baselines only; the GPU cost of the tuned model on the full pool was not spent):
  BACKER-v2 39.0 [38.0, 39.9], most-active 32.4. These match the 15% sample (39.0 / 32.6), so the sample does not
  move the baselines. Round 1 had 38.5 on all launches.
- **Reading.**
  - The tuned model learns the activity and presence signal that most-active and BACKER-v2 use. It is close to the
    logistic on pairwise ranking (AUC level, a hair above at 500k).
  - It is weaker at the very top of each launch's list, which is what recall@N measures.
  - Text-level taste from launch names, taglines and recent upvotes does not add backers beyond activity and topic
    match. This is the same finding as round 1 and PRESENCE-CHOICE-1, now with 500k real choices behind it.

## Leak checks (export_info.json in the bucket)
- 0 history endorsements on or after D. 0 comments written on or after D's start. 0 target launches in the
  history. All candidate launches are dated on the row's day. Checked on 6,000 train and test rows.
- History counts are equal to the benchmark's own `HistoryBatch.events` on 400 rows.
- 0 @handles remain in any prompt.
- Launch fields are name, tagline and topics only. Descriptions are left out because they can be edited later.
- Overlap: test and train share no launches (different days). 3,333 of the 4,898 test people (68%) also appear in
  training person-days, on earlier days.

## Cost
VM runtime times list price, a2-highgpu-1g standard at $3.673/h:
- run b: 4.17 h, $15.30;
- one failed start: 1.6 min, $0.10 (it could not install the pinned transformers on the image's Python 3.10);
- disk: $0.09.

The total is **$15.49 of $25**. There were no model API calls.

## Deviations from the registered design
1. **Test window.** Nov 11-22 instead of Nov 11-24: the build has no labelled pool for Nov 23-24, because almost no
   held person was read after those days closed. Decided before the run (running row).
2. **Training line-ups.** These are all launches of the day in the benchmark: there is no 00:05 capture before
   Nov 1. The test uses the 00:05 line-up as designed.
3. **Test candidates.** A fixed 15% pool sample instead of every pool person, for GPU cost. It was fixed in the
   running row before results, and the baselines on the full pool match the sample.
4. **Learning curve.** 50k / 200k / 350k / 500k from one run, instead of 50k / 200k / 1M. The running row planned
   50k / 100k / 200k. Before launch the run was extended to 500k with snapshots at 50k / 200k / 350k, because the
   measured token count (59 per row) made 500k fit the budget. 1M did not fit (an estimated 9 h of A100, about
   $33). Decided by the subagent before any result.
5. **Batching.** One optimizer step per micro-batch of about 6,000 tokens (about 107 rows, 5,227 steps), instead of
   FT-TASKC's 16 rows per step. Rows here are single-token answers.
6. **Library versions.** transformers 5.20.2 and peft 0.21.3 on the VM: 5.24.0 needs Python 3.11, and the packing
   was re-checked locally on 5.20.2. The first VM failed on this.
7. **Extra arm.** The untuned base model was scored as a 0-row point (not in the design).
8. **Metric.** AUC pooled across launches was dropped from the paired tests to keep the bootstrap tractable.
   Per-launch AUC, the registered metric, is reported.

## Recommendation
- Do not deploy it, and do not spend more on scaling yes/no fine-tunes of this kind. At 500k rows the model does
  not beat BACKER-v2 on recall@N, and the curve flattened after 200k.
- If the vote-choice tune is kept, the next test is a stack (logit of P(Yes) plus the BACKER-v2 features, fit on
  validation days). The tuned model's AUC is level with the logistic but its errors may differ. It should be scored
  forward on launches after the model's cutoff.
- The larger lever remains fresh upvote reads (presence), as PRESENCE-CHOICE-1 found.
