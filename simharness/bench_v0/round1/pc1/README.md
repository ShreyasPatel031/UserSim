# PRESENCE-CHOICE-1 (Nov 24 2026): Task V split into "shows up" and "picks"

Test days Nov 11-22. Intervals: day-clustered bootstrap, 95%. Aggregates only here (`results.json`, `table.md`);
rows, predictions and model outputs are private under `gs://.../simharness/bench_v0/round1/choice/`.

**Read**
1. **Presence is predictable, if the person has been read.** With history complete through D-1, a model finds 65% of
   the day's voters in its top N (AUC 0.90), 4.4 points clear of the recency-weighted count. With the store as it was
   actually read at 00:05 PT, AUC is 0.56: no one in a test pool had been read in the 7 days before the day.
2. **Choice is popularity.** The structural order alone puts an upvoted launch in a person's top 3 on 60.9% of
   person-days. Personal signals alone are far behind (topic match equals a random order), and adding them to the
   structural score gives 61.5%. The old finding (57.5% vs 56%) holds on clean, dated data.
3. **Language models picking from the whole line-up do not find the popular launches.** Top-3 hit 28-33% against 60%
   for the structural order on the same person-days; 27-44% of their picks come from the first fifth of a shuffled
   list. Ordering launches by how many simulated members picked them also gets 28-33%.
4. **Together** P(present) x P(choose | present) reaches recall@N 39.3 on the full pool: +0.8 [+0.4, +1.3] over the
   logistic's 38.5 and level with logistic + ties (39.2). Even a perfect presence oracle only reaches 44.1 with this
   choice model, so the remaining gap is choice, not presence.

## A. Presence
Label: a person in the day's active pool upvoted at least one launch that day (base rate 16.0% on test, 56,878
person-days). Features known at 00:05 PT (`simharness/presence.py`): days since the last upvote; upvotes and active
days in the last 1 / 3 / 7 / 30 days; current streak; share of past active days on this weekday; comment recency;
history length. Walk-forward: refit every 2 scored days on the 45 benchmark days before the refit day.

| History used | Model | AUC (mean per day) | ECE | day's voters in top N | vs baseline |
|---|---|---|---|---|---|
| complete through D-1 (read later) | recency-weighted count (baseline) | 0.874 [0.858, 0.889] | 0.013 | 61.0 [60.3, 61.7] | |
| | logistic | 0.897 [0.882, 0.911] | 0.008 | 65.4 [63.8, 66.7] | +4.4 [+2.8, +5.9] |
| | LightGBM | 0.898 [0.883, 0.912] | 0.005 | 65.4 [63.9, 66.6] | +4.4 [+2.9, +5.7] |
| as known at 00:05 PT | recency-weighted count (baseline) | 0.562 [0.548, 0.576] | 0.132 | 38.3 [36.9, 39.7] | |
| | logistic | 0.565 [0.552, 0.579] | 0.146 | 37.8 [36.4, 39.2] | -0.5 [-1.1, -0.0] |
| | LightGBM | 0.534 [0.521, 0.547] | 0.146 | 27.7 [24.9, 30.0] | -10.6 [-12.7, -9.0] |

**How late reading is handled.** Every upvote in the store carries the time it was first read. "As known at 00:05"
rebuilds each person's features from upvotes first read before the day's 00:05 PT and scores them with the same
models. On test days 59% of pool person-days had any history in the store at 00:05, and their newest read was 8 to 21
days old (median 13). **No person-day had been read on D-1 or within 7 days before D, so the "people read through D-1"
line cannot be scored on this store** (0 person-days). The first block is therefore what daily reading would give,
the second what today's reading gives. A read that found nothing new leaves no trace, so read ages are upper bounds.

## B. CHOICE benchmark
One row per (person, day) where a pool member upvoted at least one launch of the day's 00:05 PT line-up; candidates =
that line-up; label = the launches they upvoted. Test: 9,016 person-days, 12 days, mean line-up 31.7 launches, mean
2.66 upvoted (median 1); 3.8% of these people's upvotes that day went to launches that were not on the 00:05 line-up
and are not candidates. Validation: 7,242 person-days on 7 days (Nov 5-7 have no capture; Nov 1-3 use a same-day
capture). Files: `choice_persondays.parquet`, `choice_labels.parquet`, `choice_lineup.parquet`, `SCHEMA.txt`.

Structural order = the published forecast frozen at 00:05 PT that day (`pred` in the day's forecast file: arm 2 to
Nov 16, arm 3 from Nov 17). The combination is a logistic on the structural score, topic and embedding match, dated
ties, the person's upvotes per active day and the line-up size, fit on the 5 validation days that have a frozen
forecast (logistic beat LightGBM leave-one-day-out) and scored once on test.

| Model | top-3 hit | MRR | AUC | top-3 vs structural |
|---|---|---|---|---|
| structural order | 60.9 [52.7, 70.2] | 0.459 [0.388, 0.532] | 0.774 [0.754, 0.795] | |
| topic match | 22.6 [17.7, 27.9] | 0.231 | 0.582 | -38.3 [-47.1, -29.5] |
| taste-v1 | 31.5 [25.5, 38.3] | 0.291 | 0.603 | -29.4 [-38.1, -21.8] |
| dated ties | 44.6 [37.6, 52.4] | 0.391 | 0.671 | -16.3 [-23.9, -7.2] |
| combination (fit on validation) | 61.5 [53.0, 69.7] | 0.498 [0.438, 0.567] | 0.788 [0.766, 0.807] | +0.5 [-8.3, +7.5] |
| random order | 23.8 [20.3, 28.3] | 0.235 | 0.499 | -37.1 [-43.6, -31.0] |

Combination minus structural: AUC +0.014 [+0.002, +0.027] (clear), MRR +0.040 [-0.017, +0.099], top-3 not clear.
Dated ties rank launches better than taste does because a known team is itself a popularity signal.

## C. Language models on CHOICE ($0.79 of the $4 cap)
300 test person-days (25 a day, fixed). One call per person-day: the person's history (activity rates, last upvoted
launches, comments) and the whole line-up, one line per launch from line-up fields only (name, tagline, up to 4
topics, description cut to 160 characters), shuffled per person-day with a recorded seed. The model returns a ranked
list of max(3, k) launches (k = the person's mean upvotes per active day; lists shorter than 3 would leave top-3
undefined). Unlisted launches are tied at the bottom, which lowers a model's AUC; top-3 hit is the fair comparison.

| Model | top-3 hit | MRR | vs structural (top-3) | vs combination (top-3) | $ / 1k | picks from the first fifth of the list |
|---|---|---|---|---|---|---|
| structural order, same person-days | 60.3 [51.7, 68.3] | 0.450 | | | | |
| combination, same person-days | 62.0 [55.3, 68.0] | 0.482 | | | | |
| random order, same person-days | 24.7 [19.0, 30.3] | 0.243 | | | | |
| gemini-2.5-flash | 32.7 [24.3, 41.3] | 0.310 | -27.7 [-37.3, -19.0] | -29.3 [-38.0, -20.0] | 0.99 | 26.9% |
| gpt-oss-120b | 32.7 [24.3, 41.0] | 0.304 | -27.7 [-37.7, -18.3] | -29.3 [-38.0, -20.7] | 0.58 | 37.5% |
| llama-4-maverick | 27.7 [20.3, 35.3] | 0.272 | -32.7 [-40.3, -25.3] | -34.3 [-41.7, -26.0] | 1.08 | 44.0% |

- Position: a fifth of the picks should come from each fifth of the list. The first pick is in the first fifth 48%
  (Gemini), 57% (gpt-oss) and 79% (Llama) of the time.
- About 22% of a model's first k picks were really upvoted.
- Launch order from pick counts (the day's 25 simulated members; scored on all 9,016 test person-days): top-3 hit
  32.5 (Gemini), 28.2 (gpt-oss), 30.8 (Llama) against 60.9 for the structural order (-28 to -33, all clear).
- For the forward re-rank this says: from line-up text and a person's history alone, picks do not carry which
  launches will be popular. The structural score (or rank) has to be in front of the model, the list has to be
  reshuffled per call, and 25 members a day is too few to order a line-up.

## D. Full pool: P(present) x P(choose | present) (394 test launches)

| Model | recall@N | vs logistic | vs logistic + ties |
|---|---|---|---|
| logistic (round 1) | 38.5 [36.6, 40.5] | | |
| logistic + dated ties (TIES-1) | 39.2 [37.5, 41.0] | | |
| P(present, logistic) x P(choose \| present) | 39.3 [37.6, 41.3] | +0.8 [+0.4, +1.3] | +0.1 [-0.4, +0.7] |
| P(present, LightGBM) x P(choose \| present) | 38.7 [37.2, 40.5] | +0.2 [-0.4, +0.9] | -0.5 [-1.2, +0.3] |
| P(present) alone | 25.1 [23.3, 27.1] | -13.4 | |
| P(choose \| present) alone | 26.7 [24.9, 28.2] | -11.8 | |
| oracle presence x P(choose \| present) (diagnostic) | 44.1 [42.0, 46.6] | +5.6 [+4.4, +6.9] | +4.9 [+3.8, +6.1] |

Both presence models are shown because presence was not scored on validation, so neither was chosen in advance.
Launches that were not on the 00:05 line-up (35) get a neutral structural score and no ties. History is the complete
(read later) one, as for the logistic.

## Leak checks (`results.json` -> `leak_checks`)
- Presence features recomputed independently from history rows before the day: max difference 2e-7. Every fit uses
  only days before the refit day.
- All 12 test line-ups come from the 00:05 PT capture (361 launches, all with a frozen structural score); only the
  launch id and description are read from a capture, never votes, comments or ranks.
- The combination is fit on Nov 3-10 only and scored once on test.
- 300 choice prompts checked: 0 @handles, 0 history events on or after the day.
- Known and unchanged: upvotes are undated and attributed to the launch day; training labels for a day are read
  after it. Histories in A (first block), B, C and D are the store as read later.

## Spend
This assignment: $0.79 (Gemini 0.30, gpt-oss 0.17, Llama 0.32). Round 1 was $19.13 to $19.66. Total $19.92 to $20.45.

## Next
1. Freshness before modelling: presence needs each active person's upvotes read daily (about 12,000 people in a
   day's pool). Without it the live presence signal is at 0.56.
2. Choice is where the full-pool gap is (39 now, 44 with perfect presence). Test what moves a person off the popular
   order: the launch's position on the page when they arrive, time of day, and whether people they follow have
   already upvoted it (needs dated follows and intra-day vote times).
3. For the language-model re-rank: put the structural rank in the prompt and score the picks as a re-rank of the top
   20, not as a ranking of the whole line-up; average over several shuffles per person.

## Reproduce
`python -m simharness.run_pc1 {presence,choice,llm,combine,leak,agg}` (see the module docstring).
