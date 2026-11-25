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

## 1b. North-star metrics, restated (Shreyas, Nov 25: keep the structural predictions; focus on the residual, on how
users behave on the actual product and its competitors, and on extracting meaning from that)

| Layer | Question | Metric (forward days only for language models; paired by day, day-bootstrap 95% intervals) | Today |
|---|---|---|---|
| 0. Structural (frozen) | Where does the launch land from its mechanics (hunter, network, followers, timing, competition)? | daily / weekly / monthly top 3 / 5 / 10 | top 3 about 60 |
| 1. Residual (primary for the simulation) | What does the structural model get wrong that the simulation gets right? | (a) capture of the real top 3 / 5 / 10 when the simulation re-orders the structural top 15, minus the structural order; (b) within-day rank correlation of the simulation score with the structural miss (real rank minus structural rank) | 0: every test so far is within noise (held-voter count, X buzz, persona appeal); room is 60 -> 95-99 on the top 3 |
| 2. Product reaction | When simulated users actually use the product and its two nearest competitors, do their reactions match what real users said and did? | recall and precision of real complaints, praise and competitor comparisons in the day's comments; preference vs competitor against real "switching from / compared to" comments | one test (Nov 17, 23781c29): 25% complaint recall vs 38% for a plain homepage prompt, because findings were test artefacts (signup walls, captchas) |
| 3. Meaning | For each launch, why it landed where it did | a per-launch card: structural expected rank with its top drivers, the residual, and the simulated findings that explain it, each finding carrying its measured predictive value from layers 1-2 | not built |

WHO / WHAT / HOW stay as the calibration gates under layers 1-2 (docs/NORTH_STAR_CALIBRATION.md).

Experiments in order:
1. PRODUCT-USE-1 (E5, on the seed VMs, Camoufox): nightly, before results, for the structural top 15: simulated users
   drawn from the launch's likely cohort use the product and its two nearest competitors on a first-use task; they report
   would-use, preference vs each competitor and the top problems. Access artefacts (signup walls, captchas, blocks) are
   tagged as such and kept out of the product findings. Scored forward on layers 1 and 2 against the text-only Stage B
   agents and the plain homepage prompt. First read at 7 scored days.
   Amended Nov 25 (Shreyas: "go into product use, as deep as possible", compare reliably within Product Hunt categories):
   competitors are PH's own Similar Products sharing the launch's PH category; every product in a category is judged on
   the same category-defined core task (completion, time and steps to first value, errors, would-use, preference order);
   competitor reactions are also calibrated against PH reviews posted after the model's cutoff; scorecards per category
   (20+ launches). Taxonomy: simharness/taxonomy/ (91 pasted categories with descriptions; 248 held via Similar Products
   on 6,668 launches). Fleet asked for the full category directory (by Nov 28) and nightly Similar Products (01:00 PT).
1b. CATEGORY-1 (orchestrator's subagent, by Nov 25 12:00Z): launch-to-category table with a validated fallback
   classifier, competitor sets per launch, and the structural miss per category (the residual baseline).
   CATEGORY-1 result (Nov 25, $0; simharness/bench_v0/category1/): all 7,430 launches labelled (2,407 own PH label,
   4,236 Similar-Products majority, 787 classifier; classifier top-1 41.5% [39.1, 44.0], top-3 64.6% on Sep 1-Nov 1).
   Competitor sets for 5,150 launches (4.1 of 5 from same-category Similar Products). Category explains 3.8% of the
   structural miss variance vs 1.9% shuffled (p < 0.002): worse than predicted No-Code AI Agent Builder +6.2 [+2.8, +10.0],
   AI Workflow Automation +3.2, SEO / lead generation / marketing automation about +3; better than predicted Games -6.0,
   Screenshots and recording -4.1, Chrome Extensions -2.6, Note and writing apps -2.2. Same-day category rivals +0.36
   places each [+0.09, +0.62] on one labelling only. Leak note: old-day Similar Products contain up to 7.8% later products.
2. RESID-EXPLAIN (orchestrator): which kinds of findings move with the structural miss (onboarding friction, clear
   difference from competitors, missing basics), so that layer 3 cites only findings with measured value.
3. Stage B (running): history-built agents reading the launch page only; the text-only control for 1.

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
| persona panel (Gemini, live) | | | 63.5 (Nov 21), 66.2 (Nov 22), 71.5 [61.8, 81.7] (Nov 23; plain prompt 60.3) | | 3 | |
| persona panel + 15 person-built Flash comments (deployed Nov 24) | | | recall 68.7, precision 54.3, complaints 36.4 vs panel 66.3 / 45.8 / 27.7 (precision +8.5 [+0.3, +16.5]) | | 3 | about $0.35 a day |
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

### Benchmark v0 round 1 and the ties probe: who votes, with activity taken out (subagent, Nov 24; $19.4)
HARD rows = every held voter on a test launch (Nov 11-22) plus one non-voter of the same recent activity: 50,100 rows.
The language models scored a 960-row subsample of the same rows. Score = AUC, where 0.50 is a coin flip.

| Model | HARD (all rows) | HARD (960-row subsample) | Full pool recall@N |
|---|---|---|---|
| most-active | 0.499 | 0.461 | 32.0 |
| logistic (recent upvotes + topic match) | 0.518 [0.515, 0.520] | 0.507 | 38.5 [36.6, 40.5] |
| learned taste model (taste-v1) | 0.529 [0.521, 0.537] | 0.579 | 15.9 |
| Gemini 2.5 Flash / Llama 4 Maverick / gpt-oss-120b | | 0.528 / 0.522 / 0.517 | |
| Claude Sonnet 4.6 / Claude Haiku 4.5 / tuned Flash-Lite | | 0.530 / 0.517 / 0.517 | |
| dated ties to the launch's team (TIES-1) | 0.539 [0.528, 0.549] | | |
| dated ties + logistic features | 0.547 [0.536, 0.557] | | 39.2 (+0.7 [+0.2, +1.1]) |
| dated ties + undated follows + logistic (upper bound, can leak) | 0.556 [0.543, 0.568] | | |
| diagnostic, not known at 00:05 PT: upvoted another launch that day | 0.651 | | |

- With activity matched, no model separates voters from non-voters well: the logistic that leads the full pool is at
  0.518, a learned taste model at 0.53, and six language models (three families, one tuned) at 0.52-0.53. No language
  model is clear of the logistic and no stack with one beats its non-language member.
- Ties to the team are a real but small signal (+0.022 [+0.008, +0.034] over the logistic; +0.7 recall@N on the full
  pool). Strong ties (on the team, or backed by it before) cover under 2% of voters; the common tie (backed an earlier
  launch by the same team) is nearly as frequent among non-voters.
- The larger gap is presence: 81% of voters against 58% of matched non-voters upvoted something else that day. Voting
  is mostly "was this person on Product Hunt today", then "which launches did they pick".
- Decision: Task V is split into presence (does the person upvote anything on day D, from what is known at 00:05 PT)
  and choice (given they are present, which launches). Next: PRESENCE-CHOICE-1 (subagent). The dated-tie features go to
  E5 as a candidate addition to the live backer model at its next slot.
- Leak checks passed: dated features unchanged after deleting everything on or after the day; teams taken from the
  00:05 PT capture; integer keys only. Gaps: 35 of 396 test launches were not on the 00:05 list (no ties); validation
  teams exist for 197 of 316 launches.

### Presence and choice (PRESENCE-CHOICE-1, subagent, Nov 24; $0.79): the limit on "who votes" is how fresh our reads are
Test days Nov 11-22, day-clustered intervals.

**Presence** (does the person upvote anything today; 56,878 person-days, 16% do):

| History used | Best model | AUC | Share of the day's voters in the top N people |
|---|---|---|---|
| complete through the day before (as later read) | logistic or LightGBM | 0.90 | 65.4 (recency count alone: 61.0) |
| what the store actually held at 00:05 PT | recency count | 0.56 | 38.3 |

Only 59% of these people had any history in the store at 00:05 PT, and their newest read was 8 to 21 days old; nobody
had been read within the 7 days before. With current histories presence is very predictable; with ours it is close
to a coin flip. This, not the model, is what holds live backer prediction down.

**Choice** (given the person is present, which of about 32 launches; 9,016 person-days), top-3 hit:
random 23.8, topic match 22.6, taste-v1 31.5, dated ties 44.6, structural order 60.9 [52.7, 70.2], best combination
61.5 (not clear of the structural order: +0.5 [-8.3, +7.5]). Choice is mostly popularity.

**Language models choosing from the whole line-up** (300 person-days, the design E5's Stage B v2 uses forward):
Gemini Flash 32.7, gpt-oss-120b 32.7, Llama 4 Maverick 27.7, against the structural order's 60.3 on the same rows
(-27.7 [-37.3, -19.0] for Flash). Strong position bias (Llama's first pick is in the first fifth of the list 79% of
the time). Ordering launches by how many simulated members picked them gets 28-33%. From line-up text and a person's
history, language models do not know which launches will be popular.

**Together** (full pool, 394 launches): presence x choice recall@N 39.3 vs the logistic's 38.5 (+0.8 [+0.4, +1.3]),
equal to logistic + ties (39.2). Perfect presence with this choice model would reach 44.1.

Decisions:
- Model work on Task V stops here: with complete histories every approach lands at 38-39, and the ceiling with
  perfect presence is about 44. The lever is freshness: held people's upvotes read through the day before.
- The fleet's refresh (due Nov 25) is the experiment that matters; E5 measures live recall by how stale each
  person's read was, once fresh reads exist.
- Stage B (language-model agents re-ranking the shortlist) keeps running forward as pre-registered at about $1 a
  day, with the expectation set by this backtest: no lift.

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

### What the model should be shown about a person (Task C context ablation, Nov 24; Gemini 2.5 Flash, $3.37)
Same model and rows, different history in the prompt. Every validation row (1,003; 912 with a second commenter) and
test row (413; 328). Person match; differences are paired against the first row, day-clustered 95% intervals.

| History shown | Validation | vs base | Test | vs base |
|---|---|---|---|---|
| 30 upvoted launches + 10 latest comments (base) | 57.9 [56.6, 59.6] | | 58.8 | |
| 30 upvoted launches + 30 latest comments | 58.8 | +0.9 [-0.6, +2.6] | 60.1 | +1.2 [-1.3, +3.1] |
| 10 latest comments only | 60.1 | +2.2 [-0.7, +5.1] | 59.5 | +0.6 [-2.4, +4.5] |
| 30 upvoted launches only | 50.2 | -7.8 [-9.6, -5.8] | 48.2 | -10.7 [-15.3, -4.9] |
| 30 upvoted launches + 10 past comments most similar to the launch | 54.4 | -3.6 [-6.1, -1.2] | 55.8 | -3.0 [-6.7, -0.2] |
| the person's own latest earlier comment (reference) | 64.3 [61.0, 67.7] | | 68.0 | |

- A person's voice comes only from their past comments: the upvote list alone is at chance, and removing it costs
  nothing. More comments (30) do not help; choosing comments by similarity to the launch is worse than the latest ones.
- So neither more training rows nor a different history closes the gap to the person's own last comment (64-68):
  prompt-only models sit at 58-60 and the tuned 7B model at 60-65.
- Decision: the fine-tune and the prompts keep the latest comments and may drop the upvote list for Task C (shorter,
  cheaper prompts). Person match is now well mapped; the next question is whether person-built comments are better on
  the launch-level measure the product is judged on (themes and complaints against all real comments on a launch).

### Person-built comments on the launch-level measure (WHAT-PANEL-1, Nov 24; E5 scoring bfbed0a3; about $2)
Nov 23, 11 launches, E5's frozen consensus themes, 22 comments per launch for every arm (the persona panel's size).
The person-built arms use 30 real held people per launch (closest upvote history to the launch's topics, at least 3
past comments), history before the day and the 00:05 line-up fields only.

| Who writes the comments | Theme recall | Precision | Complaint recall | Sentiment distance (lower is better) |
|---|---|---|---|---|
| persona panel (published) | 71.5 | 38.8 | 24.6 | 0.312 |
| plain prompt | 60.3 | 29.7 | 10.3 | |
| Gemini 2.5 Flash from real people's histories | 58.8 | 70.7 | 29.7 | 0.389 |
| Qwen2.5-7B fine-tuned, from real people's histories | 62.5 | 37.4 | 15.8 | 0.251 |
| Qwen2.5-7B untuned, from real people's histories | 53.6 | 58.4 | 11.3 | 0.543 |
| base sentiment mix (published line) | | | | 0.193 |

- Person-built Flash vs the persona panel, paired: recall -12.6 [-22.0, -3.2], precision +31.9 [+15.7, +49.8],
  complaint recall +5.1 [-5.1, +16.1]. Against the plain prompt: precision +41.0, complaint recall +19.4 [+9.1, +30.7].
- The fine-tuned model is not better than the persona panel or the plain prompt on any measure and loses precision to
  Flash (-33.3 [-49.5, -15.5]); its tone is the closest of the simulated arms (0.251) but still behind the base mix.
  Decision: the tuned model is closed for launch-level WHAT; it stays as the person-voice result.
- The threshold is recall >= 70 with precision >= 50. The persona panel misses on precision, the person-built Flash
  arm on recall. Next (WHAT-PANEL-2, E5, due 20:00Z): mixes of the two at equal size on Nov 21, 22 and 23; a mix that
  meets both becomes the candidate for the published panel.
- Small n: one day, 11 launches.

**Mixes at equal size (WHAT-PANEL-2, E5 05ebba70, Nov 24; $3.37).** 24 launches on Nov 21-23, 22 comments each, 5
subsample seeds x 3 judge runs. Recall / precision / complaint recall, then paired vs the persona panel:

| Arm | Recall | Precision | Complaint recall | Recall vs panel | Precision vs panel |
|---|---|---|---|---|---|
| persona panel | 68.4 [62.0, 74.7] | 46.8 [38.3, 55.6] | 28.5 | | |
| person-built Flash | 56.7 | 68.4 | 26.5 | -11.7 [-19.5, -4.1] | +21.7 [+14.0, +29.8] |
| mix 11 + 11 | 63.3 | 56.5 | 30.9 | -5.1 [-10.0, -0.1] | +9.7 [+4.9, +14.8] |
| mix 15 persona + 7 person-built | 65.4 [60.2, 70.7] | 53.4 [45.8, 61.5] | 31.8 | -3.0 [-7.3, +1.3] | +6.7 [+2.1, +10.9] |
| mix 7 + 15 | 62.0 | 59.0 | 30.5 | -6.4 [-11.9, -0.1] | +12.2 [+6.6, +17.8] |

No arm meets recall >= 70 with precision >= 50 (these three days are harder: the panel was at 75.4 recall on Nov
15-20). By the fixed rule nothing is deployed from the equal-size test. The per-comment result holds on three days:
person-built comments are far more precise. Next (WHAT-PANEL-3, E5, due 17:30Z): add 8 / 11 / 15 person-built
comments to the full persona panel instead of swapping; recall cannot fall and precision should rise.

**Adding instead of swapping (WHAT-PANEL-3, E5 62e61a88, Nov 24; $2.27): DEPLOYED as the scored panel.** Same 24
launches, the full persona panel plus a seeded draw of person-built Flash comments, 3 seeds x 3 judge runs.

| Arm | Recall | Precision | Complaint recall | Precision vs panel | Complaint recall vs panel |
|---|---|---|---|---|---|
| full persona panel (about 23 comments) | 66.3 [59.9, 72.6] | 45.8 [36.9, 55.3] | 27.7 | | |
| panel + 8 person-built | 68.7 | 49.5 | 34.3 | +3.7 [-1.3, +8.4] | +6.5 [+0.5, +12.8] |
| panel + 11 | 65.0 | 50.8 | 35.4 | +5.0 [-0.3, +10.6] | +7.7 [+0.4, +15.3] |
| **panel + 15** | **68.7 [62.4, 74.6]** | **54.3 [44.2, 64.9]** | **36.4** | **+8.5 [+0.3, +16.5]** | **+8.7 [+2.9, +14.7]** |

- Panel + 15 is the only arm that meets the rule fixed before scoring (precision clearly above the panel, recall not
  below: +2.3 [-1.9, +6.6], both closer to the thresholds). It does not yet meet recall >= 70 (68.7) at the point.
- Decision (model-choice rule, no wait for live days): the nightly adds 15 person-built comments per launch; the scorer
  reads persona + person-built merged as the main WHAT line, persona-only stays as the shadow. Revert after 7 scored
  live days if merged precision is not above the shadow or recall is clearly below it.
- Privacy guard: person-built comments are written from one real person's history, so they go under a separate key
  that the public page does not show, with no person key, a "no own name, employer or products" instruction and a
  filter for self-references. Showing them publicly is Shreyas's decision.
- Caveats: three harder days, the precision interval only just clears zero, Nov 21 alone shows almost no precision
  gain. Repeat on Nov 15-20 on Nov 25.
- Product implication, next coding item: the quick run's "what they'll say" should be written from the matched real
  people's histories (their past comments), not only from segment personas.

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

### Person voice, tuned vs Gemini (PERSON-VOICE-1, subagent, Nov 25; about $1.4)
On 1,450 out-of-sample Task C rows (Nov 11-24, 478 people, 256 launches), person match: tuned Qwen 61.4 [59.0, 64.1],
Flash + history 60.9, untuned Qwen 55.2, own last comment 66.1. Tuned - Flash +0.4 [-1.2, +2.5]: not clear. Tuned -
untuned +6.1 [+4.1, +8.4]. Content match: tuned 25.9 vs Flash 40.7 (tuned writes shorter comments). Decision: the tuned
line is closed for person voice; Flash + history stays. Files: simharness/bench_v0/person_voice_1/.

### Panel + 15 repeat check (WHAT-PANEL-4, subagent, Nov 25; $2.27)
85 launches on Nov 15-20, generated as the deployed job does, paired by launch (panel + 15 minus panel): recall -1.2
[-4.1, +1.2], precision +11.3 [+6.8, +14.7], complaint recall -1.3 [-5.4, +3.4]. Pooled Nov 15-23 (109 launches, 9 days):
precision +12.2 [+8.5, +15.3], recall -0.9, complaint recall 0.0 [-3.8, +4.4]. The precision gain holds; WHAT-PANEL-3's
complaint-recall gain did not replicate. No revert alarm: the deployed panel stays, judged by the 7-day live rule.
Judge levels drift between runs; compare only paired differences. Files: simharness/bench_v0/what_panel4/.

### Review truth for product use (REVIEW-TRUTH-1, subagent, Nov 25; about $2.30)
537 products with 5+ Product Hunt reviews dated 2025 or later (after the models' cutoffs), from 15,312 such reviews:
complaints (341 products, 1.9 each), likes (535, 5.0 each), mean rating 4.84. Frozen: simharness/taxonomy/review_truth.parquet
(sha256 0d81ad09...). The bar for layer 2: a model shown only the homepage reaches complaint recall 17.8 [14.1, 21.6] and
like recall 54.6 [50.9, 58.2] (precision 10.0 / 33.9). Coverage: about half of shortlist launches have 2 competitors with
truth. Files: simharness/bench_v0/review_truth1/.

### What a person actually says (CONTENT-LABELS-1, subagent, Nov 25; $2.20)
New Task C content metric "same point" (Claude Opus judge, frozen prompt same-point-v1, 3 runs, majority; agrees with blind
hand labels on 59 of 60, kappa 0.93). On 150 rows: another real commenter on the same launch 20.0 [14.0, 26.7], Flash +
history 12.0, tuned Qwen 8.0, the person's own last comment 3.3. Flash - other person -8.0 [-16.0, -0.7]. The embedding
measure ranked Flash first (restating the product); same point ranks it below a random real commenter. Person-built
comments sound like the person but rarely make the point the person made: the gap to close is about 8 points. Code:
simharness/content_judge.py; task_c.py score(..., content_judge=...). Files: simharness/bench_v0/content_labels1/.

### Product use against reviews (PRODUCT-USE-0, E5, Nov 25; $8.51): failed
70 products, 208 sessions, only 31% free of access problems (12 completed the task). Against post-2025 review truth,
simulated product use lost to a homepage-only prompt: complaint recall 3.1 vs 21.6 (-18.5 [-27.6, -9.9]), like recall
9.0 vs 53.4. 16% of simulated complaints were about access. Reading: first-use sessions surface first-ten-minutes friction,
not what reviewers report after weeks; and access still dominates. Closed. PU-1 continues forward with launch-day comments
as layer-2 truth (first impressions) and a target of 60%+ clean sessions (seed accounts, no-account paths). An artefact
rerun after the 11a fixes gave 25% clean (no gain).

### First residual read (RESID-READ-0, subagent, Nov 25; $0)
Only the persona panel and the say block were frozen on time (about 01:30 PT) on Nov 15-23 (9 days, 164 launches). Within-day
Spearman with the structural miss: panel interest -0.13 [-0.28, +0.01], sentiment +0.06 / +0.00; re-ordering never helps
(k = 0 on 8 of 9 days; top-3 capture change -3.7 [-11.1, 0.0]). Stage B and the person-built panel had no scorable day
(Nov 24 Stage B frozen 05:28 PT; Nov 15-23 person panels generated after results). Layer 1 is still 0; 9 days can only see
effects of about 10 points. Forward lines must freeze before 03:30 PT every night from Nov 25.

## 5. Open items (keep at least three beyond those running)
1. (done Nov 23) Ceiling of the structural shortlist: see the table above.
1b. Late-featured launches (added after 00:05 PT) cap the live shortlist; test a later line-up re-read for the re-rank.
2. Re-rank with BACKER-v2 expected voters (done Nov 24: no lift), then with history-built LLM agents (E5, SIM-RERANK-1
   stage B, running nightly, forward only; first read at 7 scored days). Nov 24: the first night froze late (session
   restarts; excluded) and v1 agents saturate (yes on 89-100% of launches unless the page read was thin). Stage B v2
   approved to run beside v1: each agent sees the whole shortlist from line-up fields only and picks its own usual
   number of launches.
3. Benchmark v0 builder, adapters and the first zero-shot leaderboard across model families (orchestrator).
4. Fine-tune an open model on Task V + Task C training rows; compare with zero-shot frontier models (orchestrator).
4b. Task C person match: first fine-tune done Nov 24 (65.2 vs 54.6 untuned, 59.3 Gemini Flash, 68.0 the person's own
    last comment); learning curve done Nov 24 (flat from 4,000 to 12,000 rows); context ablation done Nov 24 (voice
    comes from past comments only). Running: person-built comments on the launch-level WHAT scorer (WHAT-PANEL-1).
4c. (done Nov 25: CONTENT-LABELS-1, same-point judge) Task C content measure: embeddings do not work for content (projecting out the launch text measured style; tried
    Nov 24). Needs judged "same point as the real comment" labels; also a style distance (length, question vs praise).
4d. Joint fine-tune: vote + comment in one adapter. On hold: round 1 shows vote yes/no from history is near chance
    once activity is matched, so the vote half waits for the presence / choice split.
4f. Presence and choice: done Nov 24 (see the section above). Follow-up for E5 once fresh reads exist: live backer
    recall@N by staleness of each person's last upvote read (0-1, 2-3, 4-7, 8+ days), and the presence logistic
    added to BACKER-v2.
4i. Quick-run reactions from matched real people's histories (orchestrator, next coding item): in mvp/ph_site/try_sim.py
    write "what they'll say" from the matched people's past comments; check on calibration days before switching.
4h. Same-day person-linked comment rows: DONE Nov 24 (FORWARD-C-1; simharness/domains/ph_live_comments.py,
    run_forward_day.py, run_refresh.py; simharness/bench_v0/forward/README.md). Task C rows on test + forward days went
    from 413 to 1,572 (1,450 with a second commenter); the new rows score like the old ones (history minus item-only
    +8.3 [+4.5, +13.4] on content match, person match 61.6). From Nov 17 the profile reads brought 5-23 rows a day; the
    stream gives 100-200. A nightly refresh rebuilds the tables from the current store and the stream, with stable
    keys and a pointer that moves only after its checks pass; E5's nightly session runs it before the panel step.
4j. Person voice on the larger row set (orchestrator, Nov 25): tuned Qwen 7B vs Gemini Flash with history vs untuned
    on all 1,450 rows with a second commenter, to settle the tuned-vs-Flash difference that 327 rows could not.
4g. Dated ties in the live backer model (E5, next slot): add "backed an earlier launch of this team" features to
    BACKER-v2's walk-forward test; deploy if recall@N is clear of noise on its truth set.
4e. A serving path for a tuned open model (GPU endpoint started on demand) so a winner can replace the prompt model.
5. HOW axis: trace realism against human traces (plugin agent; unchanged).
6. Truth data: broad post-close re-reads and full comment threads (fleet; asked hourly).
7. Second domain to prove "plugs into any use case" (choose once Task R shows lift on Product Hunt).

## 6. Budget
$50 a day for experiments (model calls and GPU), logged daily. Working split: orchestrator $30, E5 $15, PH agent $5.
