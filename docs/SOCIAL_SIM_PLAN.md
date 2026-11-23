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
- **Task C (comment)**: given the same inputs for a person who did comment, what did they say? Scored by theme recall and
  precision against the real comment (the WHAT scorer E5 already runs), versus a plain prompt.
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
| structural order (arm 3) | | | | baseline: 50.0 / 70.0 / 66.7 | 6 | |

## 5. Open items (keep at least three beyond those running)
1. Ceiling of the structural shortlist (PH agent, STRUCT-SHORTLIST).
2. Re-rank with BACKER-v2 expected voters, then with history-built LLM agents (E5, SIM-RERANK-1).
3. Benchmark v0 builder, adapters and the first zero-shot leaderboard across model families (orchestrator).
4. Fine-tune an open model on Task V + Task C training rows; compare with zero-shot frontier models (orchestrator).
5. HOW axis: trace realism against human traces (plugin agent; unchanged).
6. Truth data: broad post-close re-reads and full comment threads (fleet; asked hourly).
7. Second domain to prove "plugs into any use case" (choose once Task R shows lift on Product Hunt).

## 6. Budget
$50 a day for experiments (model calls and GPU), logged daily. Working split: orchestrator $30, E5 $15, PH agent $5.
