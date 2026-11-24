# Social simulation plan (Shreyas's direction, Nov 23 2026)

The product is a calibrated social simulation that plugs into any domain at the point where the domain's own structural
model plateaus, and improves on it quickly. Product Hunt is the first domain: the structural model (LightGBM launch model,
arm 3) sits at about 50 / 70 / 67 on the daily top 3 / 5 / 10 live.

## 1. Two models
| | Structural model | Social simulation model |
|---|---|---|
| What | the domain's mechanics: hunter, network, promotion, competition | simulated people built from real people's histories |
| Status | frozen (bug fixes and live/backtest parity only) | all research effort |
| Owner | PH agent (20% of time) | E5 + orchestrator (60%) |
| Output | a score per launch and the daily shortlist (top 20) | per-person vote probability, what they would say, re-ranked shortlist |
| Judged by | daily top 3 / 5 / 10 | lift over structural on the shortlist; WHO / WHAT / HOW scorecards |

Go-to-market and dogfooding (20%) belongs to Grok Bot.

## 2. The harness (code is open-source; data, traces and weights are private)
A domain plugs in four tables:
1. **items**: what people act on (launches: id, day, name, tagline, description, topics).
2. **people histories**: per person, dated events (upvotes, comments with text, follows, launches made). Salted ids only.
3. **outcomes**: who acted on which item, what they said, and the item's final result (votes, rank).
4. **structural scores**: the domain model's score per item per day (frozen before the day).

The harness provides:
- **Benchmark builder**: turns the four tables into time-split tasks (train on days before T, test on days after).
- **Model adapters**: one interface (`predict(person_history, item) -> p_vote, comment`) for baselines, Gemini, Claude,
  OpenAI and open models (zero-shot and fine-tuned).
- **Scorer and leaderboard**: every model on the same test days against the same baselines.
- **Daily loop**: frozen predictions before the day -> truth after the day -> scorecard -> new training rows -> retrain ->
  shadow -> promote when better with the interval clear (AGENTS.md, how models are chosen).

## 3. Benchmark v0 (Product Hunt)
- **Task V (vote)**: given a held person's history before day D and a launch on day D, did the person upvote it?
  - Candidates per launch: every held person with at least one upvote in the 60 days before D (the active pool).
  - Metrics: recall@N per launch (N = real held backers), AUC, calibration (ECE), all with day-bootstrap intervals.
  - Baselines to beat: most-active (20.9% recall@N), BACKER-v2 logistic (27.6%).
- **Task C (comment)**: given the same inputs for a person who did comment, what did they say?
  - Launch level: theme recall and precision against the launch's real comments (the WHAT scorer E5 already runs).
  - Person level (simharness/task_c.py, Nov 24): the simulated comment is compared with that person's real comment by
    sentence embeddings. Headline: **person match** = share of rows where the simulated comment is closer to this
    person's real comment than to another person's real comment on the same launch (50% = nothing person-specific).
    Second number: **content match** = similarity above a threshold that a real comment from a different launch
    reaches 5% of the time. Both are compared with an item-only prompt on the same rows, paired.
- **Task R (re-rank)**: the structural top 20 for a day, re-ranked with simulation outputs. Metric: capture of the real
  top 3 / 5 / 10 versus the structural order, paired by day; near-miss recovery (structural rank 4-6 that finished top 3).
  First number to establish: the ceiling (share of the real top 3 / 5 / 10 inside the structural top 10 / 15 / 20).
- **Splits**: train on launch days up to Oct 31 2026, validate Nov 1-10, test Nov 11 onward and forward. Language models are
  scored on Task R forward only (or on days after their training cutoff).
- **Leak rules**: only events on launches before D; follow edges as read before D; no final votes or ranks in inputs.

## 4. Leaderboard (updated as results land)
| Model | Task V recall@N | Task V AUC | Task C theme recall | Task R top 3 / 5 / 10 lift | Days | Cost per 1k predictions |
|---|---|---|---|---|---|---|
| most-active baseline | 20.9 [20.1, 21.6] | | | | 14 | 0 |
| BACKER-v2 logistic (E5, live) | 27.6 [26.2, 29.0] | | | | 14 | 0 |
| persona panel (Gemini, live) | | | 63.5 (Nov 21), 66.2 (Nov 22) | | 2 | |
| history-built prompt, Gemini 2.5 Flash (bench v0) | | | person match 59.3 vs 50.3 launch-only (+8.9 [+0.6, +15.4]) | | 12 | $0.5 |
| Qwen2.5-7B fine-tuned on 4,000 of our comment rows (FT-TASKC-v0) | | | person match 65.2 [60.9, 70.1] vs 54.6 untuned (+10.7 [+5.1, +16.9]) | | 12 | about $3 to train |
| structural order (arm 3) | | | | baseline: 50.0 / 70.0 / 66.7 | 6 | |
| re-rank by expected held voters (E5, SIM-RERANK-1 stage A) | | | | top 3: -0.6 [-1.9, +0.8] (shortlist 10), +0.2 [-0.4, +0.8] (15), -0.2 [-1.2, +0.8] (20): no lift | 171 backtest + 8 live | 0 |

### Benchmark v0, Task V, first results (simharness, Nov 23; private data in the bucket under simharness/bench_v0/)
Built from the store: train 244 days / 5,703 launches / 392,763 real votes; validation 10 days / 316 launches; test
Nov 11-22, 12 days / 394 launches / 25,050 votes. Task C: 53,631 real comment texts joined to launches (485 in test).
Upvotes are dated to their launch day; follow edges are undated and left out. These pools differ from E5's re-read truth
set, so the levels below are not comparable with E5's 20.9 / 27.6; the gaps are.

| Model | Test: recall@N (full pool) | Test: AUC | Small sample AUC (20 launches, 15 voters + 15 random non-voters each) | Cost |
|---|---|---|---|---|
| most-active | 32.0 [30.4, 33.9] | 0.918 | 0.897 | 0 |
| logistic: recency-weighted upvotes + topic match | 38.5 [36.6, 40.5] | 0.938 | 0.923 | 0 |
| Gemini 2.5 Flash-Lite, zero-shot from the person's history text | | | 0.646 | $0.07 |
| Gemini 2.5 Flash, zero-shot from the person's history text | | | 0.614 | $0.23 |

Reading: a prompt-only language model reading a person's history is far worse than a two-feature logistic at "will this
person vote" (same finding as the Gemini Decisions test, 0.60 vs 0.74). Caveat: the prompt did not state the person's
activity rate, and random non-voters are mostly low-activity people, which is the signal "most-active" uses. Round 1
adds activity-matched non-voters, activity stats in the prompt, more model families, stacking and a first fine-tune.

Callable today on our GCP project: Gemini (and tuned Gemini endpoints), Claude Haiku 4.5 / Sonnet 4.5 / Sonnet 4.6,
gpt-oss-120b, Llama 4 Maverick. Not enabled: Claude Opus, Qwen, DeepSeek. No OpenAI API key is stored.

### Benchmark v0, Task C at person level, first results (simharness/task_c.py, Nov 24; $0.68)
Rows: comments written on the launch's own day by held people who are not makers of it. Validation 400 rows (10 days,
183 people); test 413 rows (Nov 11-22, 12 days, 136 people, 327 with another commenter on the same launch). Intervals
are day-clustered. Language models have not seen these launches (after their training cutoffs).

| What writes the comment | Test: person match (50 = chance) | Test: content match (5 = chance) | Validation: person match | Validation: content match |
|---|---|---|---|---|
| a real comment from another launch (floor) | 49.1 | 1.9 | 46.2 | 3.2 |
| the person's own latest earlier comment | 68.0 [60.2, 72.5] | 10.9 | 66.7 [61.2, 72.9] | 16.9 |
| another person's real comment on the same launch | n/a | 17.4 | n/a | 23.2 |
| Gemini 2.5 Flash-Lite, launch only | 48.8 | 33.9 | 54.9 | 29.5 |
| Gemini 2.5 Flash-Lite, person's history + launch | 54.4 [51.3, 58.5] | 39.5 | 57.6 | 38.2 |
| Gemini 2.5 Flash, launch only | 50.3 | 37.0 | 51.4 | 31.2 |
| Gemini 2.5 Flash, person's history + launch | 59.3 [51.6, 65.6] | 41.4 | 59.3 | 38.2 |

History minus launch-only, paired on the same rows:
- Person match: Flash +8.9 [+0.6, +15.4] on test and +7.9 [+5.1, +11.3] on validation; Flash-Lite +5.5 [+1.9, +9.4] on
  test and +2.7 [-0.6, +6.1] on validation.
- Content match: Flash +4.4 [+0.8, +6.6] on test and +7.0 [+3.6, +9.9] on validation; Flash-Lite +5.6 [+3.9, +7.0] and
  +8.8 [+5.2, +12.7].

Reading:
- Building the simulated person from their history does make the comment closer to what that person really said, on
  both splits. This is the first place the history-built simulation beats a plain prompt with the interval clear.
- It is still far from the person's voice: repeating the person's last comment identifies them 68% of the time, the
  history-built prompt 54-59%. The gap from 59 to 68 and beyond is the target for fine-tuning on the 51,895 training
  comment rows.
- Content match is a weak measure: a language model's on-topic comment scores above a second real commenter on the
  same launch (37-41 vs 17), because embeddings reward restating the product. Person match is the number to optimise.
- Small n: 327-366 rows with a second commenter per split, 136-183 people; the test interval for Flash only just
  clears zero. More comment truth (the blocked comment threads) widens this.

### First fine-tune (FT-TASKC-v0, simharness/finetune/, Nov 24; about $3 of GPU)
Qwen2.5-7B-Instruct (open weights) with a LoRA adapter, trained for one epoch on the 4,000 most recent training comment
rows (Sep 9-Oct 31, 2,133 people, at most 15 per person): prompt = the person's history and the launch, answer = their
real comment. 35 minutes on one A100. Scored on the same Task C rows as every other model.

| What writes the comment | Test: person match | Validation: person match | Test: content match | Median length vs real |
|---|---|---|---|---|
| Qwen2.5-7B, untuned, history + launch | 54.6 [50.5, 58.4] | 52.2 | 33.7 | 1.9x |
| **Qwen2.5-7B, fine-tuned, history + launch** | **65.2 [60.9, 70.1]** | **60.1 [54.7, 65.8]** | 26.2 | 0.7x |
| Gemini 2.5 Flash, history + launch | 59.3 [51.6, 65.6] | 59.3 | 41.4 | 1.1x |
| the person's own latest earlier comment | 68.0 [60.2, 72.5] | 66.7 | 10.9 | 1.0x |

Paired on the same rows (day-clustered 95% intervals):
- Tuned minus untuned, person match: +10.7 [+5.1, +16.9] test, +7.9 [+3.2, +13.4] validation. Clear on both.
- Tuned minus Gemini Flash with history: +5.8 [-1.1, +14.8] test, +0.8 [-2.2, +3.9] validation. Not clear: a 7B open
  model tuned on our rows equals the best zero-shot model here.
- Tuned minus the person's own last comment: -3.1 [-8.5, +5.3] test, -6.0 [-10.8, -0.4] validation. The gap to the
  person's own voice has narrowed and is no longer clear on test.
- Content match fell (26 vs 34 untuned): tuned comments are shorter and restate the product less, which moves them
  toward where a second real commenter sits (17). This is the weakness of that measure, not a loss.
- Not copying: 0.5-0.8% of tuned comments are near-copies of the person's last comment (real people: 0-0.5%).
- Decision: recorded, not deployed (no interval clears Gemini Flash, and there is no serving path yet). Next: a learning
  curve (12,000 rows, checkpoints at 4,000 and 8,000) to see whether more of our data keeps raising person match, then
  a joint vote + comment fine-tune on round 1's activity-matched rows.

### Learning curve for the fine-tune (FT-TASKC-v1, Nov 24; about $6 of GPU): more comment rows do not help yet
Same model and settings, 12,000 training comment rows (Jul 5-Oct 31, 5,663 people, at most 30 per person), with the
adapter saved after 4,000 and 8,000 rows. 96 minutes on one A100.

| Training rows seen | Test: person match | Validation: person match |
|---|---|---|
| 0 (untuned) | 54.6 | 52.2 |
| 4,000 (first run, most recent rows only) | 65.2 [60.9, 70.1] | 60.1 |
| 4,000 (snapshot of this run) | 63.1 [56.3, 69.2] | 59.8 |
| 8,000 | 64.3 [60.6, 67.9] | 61.2 |
| 12,000 | 61.3 [54.5, 68.2] | 60.4 |
| Gemini 2.5 Flash with history (no training) | 59.3 | 59.3 |
| the person's own latest earlier comment | 68.0 | 66.7 |

- 12,000 minus 4,000 rows, paired: -1.8 [-6.8, +2.7] test, +0.5 [-5.5, +5.6] validation. Flat.
- Reading: fine-tuning gives one step (untuned 52-55 to tuned 60-65) that 4,000 rows already buy; three times the
  rows add nothing we can measure. The number of training comments is not what limits person match.
- The measurement is also a limit: with about 330-370 scored rows the intervals are about +-5 points, so a gain under
  about 6 points cannot be seen. More comment truth (fleet, due Nov 26) and scoring every validation row widen this.
- Decision: no more data-scaling runs on this task. Next lever is what the model is shown about the person (more past
  comments, comments chosen by similarity to the launch, profile text), tested first with a prompt-only model because
  it costs cents, then carried into the tuned model.

### Task R, first test: re-rank the shortlist by expected held voters (E5, SIM-RERANK-1 stage A, b7061305, Nov 24)
Question: does "how many of our held people are expected to back this launch" reorder the structural shortlist better?
Answer: no. Re-ranked minus structural, paired by day, day-bootstrap 95% intervals.

| Shortlist | Top 3 | Top 5 | Top 10 | Near misses recovered / pushed out |
|---|---|---|---|---|
| structural top 10 | -0.6 [-1.9, +0.8] | -0.6 [-1.5, +0.4] | 0.0 | 7 / 10 (of 148) |
| structural top 15 | +0.2 [-0.4, +0.8] | -0.2 | | 3 / 2 |
| structural top 20 | -0.2 [-1.2, +0.8] | -0.8 [-1.6, 0.0] | | 5 / 6 |

- Backtest: 171 days (Apr 15-Oct 31), structural capture 56.7 / 66.9 / 78.1. The feature is a walk-forward logistic on
  recency-weighted upvotes and topic match, summed over the active pool. Caveat: store membership was chosen later.
- Live: 8 days (Nov 15-22), five variants of the feature; every top-3 difference is between -4.2 and +4.2 and every
  interval spans zero.
- Reading: the count of held people expected to vote carries no ordering information beyond the structural score.
  Closed. Stage B (70 history-built language-model agents per shortlist, frozen nightly before 03:45 PT, about $0.45 a
  day) is scored forward only; first read at 7 scored days.

### Ceiling of the structural shortlist (PH agent, STRUCT-SHORTLIST, b9613465, Nov 23)
Share of the real top k that sits inside the structural top m (arm 3, backtest 2026, 183 days, month-forward):

| Real | in top 10 | in top 15 | in top 20 | structural order alone captures |
|---|---|---|---|---|
| top 3 | 95.4 [93.6, 97.1] | 98.5 | 99.5 | about 60 |
| top 5 | 91.8 | 97.5 | 99.3 | about 68 |
| top 10 | 77.6 [75.9, 79.3] | 92.1 | 97.2 [96.2, 98.0] | about 76 |

The room for the simulation is the ordering inside the shortlist: from about 60% to a 95-99% ceiling on the top 3. Live
(6-8 frozen days) the ceilings are lower (top 3 in top 20: 94.4; top 10 in top 20: 85.0) because launches featured after
00:05 PT are in no shortlist (7 each on Nov 21 and 22). Files: results/structural/backtest/<day>.json (191 days) and
results/structural/<day>/shortlist.json nightly at 02:21 PT.

## 5. Open items (keep at least three beyond those running)
1. (done Nov 23) Ceiling of the structural shortlist: see the table above.
1b. Late-featured launches (added after 00:05 PT) cap the live shortlist; test a later line-up re-read for the re-rank.
2. Re-rank with BACKER-v2 expected voters (done Nov 24: no lift), then with history-built LLM agents (E5, SIM-RERANK-1
   stage B, running nightly, forward only; first read at 7 scored days).
3. Benchmark v0 builder, adapters and the first zero-shot leaderboard across model families (orchestrator).
4. Fine-tune an open model on Task V + Task C training rows; compare with zero-shot frontier models (orchestrator).
4b. Task C person match: first fine-tune done Nov 24 (65.2 vs 54.6 untuned, 59.3 Gemini Flash, 68.0 the person's own
    last comment); learning curve done Nov 24 (flat from 4,000 to 12,000 rows). Running: what the model is shown about
    the person (context ablation with a prompt-only model). Then add Claude, gpt-oss and Llama to the table.
4c. Task C content measure: embeddings do not work for content (projecting out the launch text measured style; tried
    Nov 24). Needs judged "same point as the real comment" labels; also a style distance (length, question vs praise).
4d. Joint fine-tune: vote (round 1's activity-matched rows) + comment in one adapter; score Task V and Task C.
4e. A serving path for a tuned open model (GPU endpoint started on demand) so a winner can replace the prompt model.
5. HOW axis: trace realism against human traces (plugin agent; unchanged).
6. Truth data: broad post-close re-reads and full comment threads (fleet; asked hourly).
7. Second domain to prove "plugs into any use case" (choose once Task R shows lift on Product Hunt).

## 6. Budget
$50 a day for experiments (model calls and GPU), logged daily. Working split: orchestrator $30, E5 $15, PH agent $5.
