# Post-mortem: user-simulation modelling, Oct 25 – Nov 19 2026

Written 2026-11-19 by an independent Opus review of docs/RESEARCH_LOG.md (RL = that file, then the line number),
experiments/simlab and the plan files. Grok Bot's own account was requested at the same time
(to_grokbot/…_orchestrator_sim_training_postmortem.md) and will be appended when it arrives.

## What was tried and how it scored
- **Oct 26–27: person persona, CF and choice models.** Person top-3 hit went from 57.5 to 60.7.
  Added to the launch model, they changed the launch top 3/5/10 by 0.0 (61.7/70.7/79.6 with and without)
  [experiments/simlab/registry.jsonl; reports/overnight_summary.md].
- **Nov 1: simulation-only score.** 57.8 vs 71.2 for the launch model on winner-of-3 [RL 62].
- **Nov 10–11: two-level it1–it8, it9b and it10 arrivals.** None beat the launch model (57/69/81).
  it8 scored 43.9/63.2/69.5. Product-only Hit@1 was 0.200 vs 0.193 for random [RL 1470–1506].
- **Nov 11–15: E5 side lines.** None helped:
  - voter harness +0.0;
  - X mentions not significant;
  - persona appeal −0.9 on top 3;
  - forced-choice panel Spearman 0.03 vs 0.62;
  - complaint recall: the persona panel was 4.5 points below a plain prompt (13.5%).
- **What worked: launch features and Product Hunt's own data.**
  - arm 2: +4.6 [+2.0, +7.1];
  - arm 3: +1.5 top 5 and +1.0 top 10;
  - the 03:45 hidden-order line: 72/75/78;
  - HN ModernBERT: +2.9.
- **Backtest daily top 3/5/10, where each line came from:**
  - simulation only 33.2/44.0/56.0 vs launch only 60.4/66.4/72.7: PH agent, Nov 19 Thursday report;
  - it8 forward 33.3 vs published 52.4 top 3: PH agent shadow table, Nov 19.

## Root causes, ranked by cost
1. **The core hypothesis was refuted on day 2** (simulation added 0 on Oct 27). We kept changing the target instead of stopping:
   person top-3 hit → population top 3 → R-precision → AUC → backer recall.
2. **Leaks were found late.**
   - Maker-record redaction inflated the baseline from about 55 to 61.7 top 3. It was found Nov 12, after ~2.5 weeks of comparisons [RL 1679].
   - Later data bugs: a [REDACTED] maker tie affecting 77% of people, and arm 2's live LLM inputs 100% null on Nov 15.
3. **Person data was incomplete and undated while models were retrained on each snapshot.**
   - Complete people went from 6.7k to 93.4k during the period.
   - Follows are undated, and only 9 of 2,856 newcomer launches have a hunter file dated before launch.
4. **Too few test days.** Forward checks had 7–19 days, giving top-3 intervals of about ±10–15 points, against real differences of 1–2 points.
5. **Most of the effort went to data infrastructure.** About 1,055 of 2,071 log entries are fleet, capture, Cloudflare or mailbox items; 613 are model metrics.
6. **No pre-registration until about Nov 11–14, and too many parallel lines.** HN, the X gate, /try, the cards and the website all ran beside the core question.
7. **No external benchmark.** Everything was scored against our own moving baseline.
8. **The ceiling of pre-launch public data is real but secondary.** It is about 70–75% for people; the late surge after the reveal explains 28 of 62 misses at 03:45.

## Spend (approximate)
- GCP was about $700 month to date by Nov 15.
- Vertex peaked near $40/day (mostly E5 Gemini harness runs). Fleet VMs were about $30/day.
- Training itself was cheap: ModernBERT about $2–3, the Gemini judge $13.54, and the two-level runs on CPU.
- [inferred] About 70% of dollars went to pulls, VMs and capture, under 15% to training and eval. The largest cost was agent time and tokens.

## Smallest test of a publishable result (about 1 day, no new pulls)
1. Freeze arm 3.
2. Score its 183-day backtest, paired by day, against three public baselines:
   - hunter track record;
   - Product Hunt's displayed order at 00:05;
   - an LLM-only forecast.
3. Go or stop:
   - If it does not beat all three by at least 5 top-3 points with intervals clear of zero, there is no story.
   - If it does, start a hashed, pre-registered public forecast record (one model, one metric, no target changes, 90+ days).
4. Reopen simulation only if a simulation line adds an interval clear of zero over arm 3 on that same paired set.
