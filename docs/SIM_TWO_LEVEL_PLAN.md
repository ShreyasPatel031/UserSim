# Two-level simulation plan: person accuracy and launch accuracy together (Nov 10)

Goal (Shreyas, Nov 10): the simulation must predict both
1. **who** votes for each launch (person level), and
2. **how many** votes each launch gets, so the daily/weekly/monthly top 3/5/10 is right (population level, the north star).

Population votes are the sum of person votes. If the person model gets more accurate on a sample that
represents the voter population, the launch ranking has to improve. Both levels are measured on the same days,
every change is kept only if both move the right way, and both are reported together.

## Why the last two tests lost
- The person model was trained on warehouse people: mostly page-1 voters of top launches, with no true negatives.
- Store people were added without telling the model they are a different, complete sample.
- Store upvotes had no vote time, so they were dated to the launch day.
- The complete set over-represents maker-connected people, and nothing reweighted it.

## Design
**Population sample.** All complete people (39,774 now, growing). They are the only people whose non-votes are
known, so they are the only honest training and test set for the person model.

**Representativeness weights.** Each complete person gets a weight so the sample's vote volume matches the real
voter base. The real base is the voters seen on launches, by activity tier, team ties and tenure. The
seen-but-incomplete and unseen voters are covered by these weights; they are not dropped.

**Person model.** Predict P(person p upvotes launch L on day d). Rules:
- Train only on complete people, using only events dated before d.
- Negatives are the day's launches the person did not upvote. They are real, because the person's history is complete.
- Features: taste (meaning/topic match, category rate), relationships (backed team before, follows maker or hunter,
  co-maker, comment threads), activity (votes per day, recency, tenure), and launch traits known at 00:05 PT.
- Vote time: use the earliest dating available. Where a vote only has the launch day, carry a flag, and test with
  and without those rows.
- Model: LightGBM, ranking or binary.

**Population model.** A launch's expected votes = Σ_p w_p · P(p votes L). Rank the day's launches by it.

## Metrics, reported together for every change
**Person level, on held-out days, complete people active that day:**
- AUC and log-loss.
- Hit@3: is a real pick among the person's top 3 launches?
- Recall of each launch's real voters among its top-N predicted voters.

**Population level:**
- Daily top 3/5/10 vs final ranks, weekly and monthly where days allow.
- Spearman correlation of predicted vs real votes.
- Paired comparison against the deployed simulation and the launch model, with 95% intervals.

**Window:** Oct 20–Nov 9, with honest monthly retraining (September model for October days, October model for
November days), extended as days accrue.

**Ship rule:** deploy when population top 3 and top 5 beat the deployed simulation on the paired days, top 10
does not lose beyond its interval, and the person metrics improve.

## Owners
- PH agent: builds and runs it.
- E5: reviews the leakage and the weighting.
- Population agent: keeps the complete set and its activity-tier stats current.
- Orchestrator: reports both levels to Shreyas daily.

## Standing finding: where the PH error is (read before starting any PH test)
- **Nov 2 (E0, `simlab/e0_shock.py`, `shock_model.py`):** 90.5% of the simulation error is one shared per-launch
  shock. Daily top 3/5/10 with the simulation + TRUE shock: 86/93/90. Pre-launch inputs predicted the shock at
  within-day Spearman 0.49, mostly from audience counts. A 10% sample of real voters already gave 83/86/82, so
  coverage was not the limit.
- **Nov 11 (it8 launch-multiplier diagnostic):** the same result on complete people. One scalar per launch lifts
  0.555 → 0.881 and top 3/5/10 to 87/90/88. From held 00:05 features, 0.24 of it is predictable.
- **Tried against the shock, with no gain:** surge history, coming-soon (feature removed by PH), competitor
  grounding (4 tests), X audience (too few on-time reads), late-fetched page inputs (leaky), dated follows, team
  and hunter history, 5 LM candidates, the cascade sim, and more complete people.
- **Not tried until Nov 11:** product understanding from launch-day text inside the person model, a listwise
  ranking of the day's line-up, a gallery read, a persona panel.
- **Rule:** PH work targets the per-launch appeal term. People pulls do not address it.
