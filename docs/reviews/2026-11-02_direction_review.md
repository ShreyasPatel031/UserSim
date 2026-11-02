# Direction review (Fable), Nov 2, 2026, 01:50 UTC

North stars: (1) show that competitor grounding increases the simulation's predictive value, then 90% on daily top
3/5/10; (2) HN: Caught per post at 1 h, 15 min and at posting, each to 80%. Scores now: PH launch model
65.5 / 73.9 / 81.2; best "simulation" 62.6 / 71.2 / 79.7 (page-aware, with audience-size inputs); pure simulation
with no audience inputs 52.9 / 63.8 / 74.1; HN 47.2 / 24.7 / 23.2.

## What the last 48 hours proved
1. **The simulated people are right about the people they see.** Tie strength: person-level top-3 hit 50.4 → 55.8
   (6/6 months); the pool's own votes +2.7 top 3; winner of 3 over a month +2.7 to +3.7 (CI excludes 0).
2. **None of it reaches the leaderboard.** With audience-size inputs present, every simulation variant's final
   predictions correlate 0.99+. The pool is 31% of votes. The other 69% (makers' and hunter's followers, X,
   promotion, homepage browsers) are represented only as counts in the launch model.
3. **Reweighting the pool cannot stand in for those audiences** (panel test: 47.7 / 59.9 / 69.3). The missing voters
   are not like anyone in the pool.
4. **Our decision metric cannot see most of our gains.** Daily top 3 over ~200 days has ±3.5 noise; almost every
   result in two days landed inside it. Pool-vote correlation, winner-of-3 and person-level hit all saw gains the
   headline could not.
5. **Competitor grounding has a validated source now.** PH Similar Products find real alternatives 45.8% / 68.7% vs
   28.6% / 43.1% for Gemini naming. Predictive value is not yet shown, because it has only been tested as extra
   features in a launch-level GBM, where everything washes out.
6. **HN is content-first, PH is connections-first.** A simulated user must learn the mix per community.

## Critique of the approach
- **Two models competing instead of one model of votes.** The "simulation" sums per-person pick probabilities over
  the pool, then a launch-level GBM re-learns from that sum plus reach counts. Reach dominates, so person-level
  gains are diluted at the sum and then overridden by the GBM. The number we have called "simulation-only" (62.6)
  includes audience-size inputs; the honest pure-simulation number is 52.9. We should stop calling the hybrid a
  simulation.
- **We simulate one audience out of five.** Votes on a launch day come from identifiable audiences: pool regulars,
  the makers' followers, the hunter's followers, people reached on X and by promotion, and homepage browsers who
  see the launch because of its position. We have person-level data only for the first. The other four enter as
  counts, never as populations with a conversion rate.
- **Feature tuning against a noisy headline.** Two days of ±2-point deltas. The headline stays daily top 3/5/10, but
  decisions must be made on metrics with power: within-day pairwise accuracy (thousands of pairs per month),
  competitor-pair accuracy on validated lists, pool-vote correlation, and log-likelihood of total votes.
- **Competitor grounding tested in the wrong place.** Gaps-as-GBM-features cannot show value when the GBM already has
  the page scores. The decision-level test (which of these real competitors wins) is where grounding pays.

## The three most promising directions
### A. One generative vote model with simulated audiences (the bridge from people to leaderboard)
Model each launch's votes as a sum over audiences:
`votes = pool_votes + maker_follower_votes + hunter_follower_votes + x_votes + browse_votes (+ promo)`,
where `pool_votes` is the person simulation (tie strength included), each follower segment is
`size × conversion_rate`, with the conversion rate learned per maker/hunter from their past launches (and from
similar makers for first-timers), `x_votes` likewise from X reach, and `browse_votes` from the launch's expected
early position (position effects, learned from the hourly snapshots). Fit as a Poisson/negative-binomial model on
total votes, components additive on the count scale, calibrated on earlier months. This replaces "sum + GBM" with a
single model in which every component is an audience and a rate. Person-level gains flow through the pool
component instead of competing with reach. As person data for a segment arrives (X engagement, follower lists), that
segment moves from a rate to simulated people, which is exactly how the product is meant to grow. This is the
PH agent's "simulated follower populations" idea in a fittable form.

### B. Launch-day dynamics as both a product and a training signal
Early votes (hours 0–2 PT) are the makers' mobilized audience made visible. Two uses. (1) The launch-day forecast
(hour 1/2/4 → final rank), expected 75–85 on top 3, labelled as made during the day. (2) Hour-2 votes as a clean
training target for the reach components in A: far less noisy than final rank, and available for every launch from
Nov 2 on. The hourly snapshots are the data; 7 days of them exist by Nov 9.

### C. Competitor grounding at the decision level
With PH Similar Products (launch-time-safe in backtests): the headline competitor metric becomes accuracy on real
competitor pairs and winner-of-N among real competitors, which has thousands of pairs and tight intervals. Three tests:
competitor-relative page gaps as inputs to a pairwise model; "used a competitor" as a person-level tie with the
validated lists; and the simulation's pick shares among competitors vs the real split. This is where the first north
star gets proven or not.

(Research track behind A: a trained person model on the event graph (person × team × time × category), scored on
person-level top-3 hit and pool-vote correlation, plugging into A's pool component. Hand features got 55.8; the
oracle on perfect pool picks is 91 on daily top 3, so the headroom is large. Start with a two-tower model on CPU.)

## Concrete plan
**Metric change, today:** every result reports daily top 3/5/10 as the headline and, for decisions, within-day
pairwise accuracy and competitor-pair accuracy with paired-by-day intervals. A frozen benchmark (fixed days, fixed
line-ups, baseline scores) in `experiments/simlab/bench/`.

**E1, PH agent, Nov 2:** the generative vote model (A), first version: components pool_sim (pnr), maker followers,
hunter followers, X followers, promotion, page quality, line-up size; Poisson GLM and a monotone additive GBM; train
earlier months, test Jul–Oct. Report vs the launch model and vs pure simulation on top 3/5/10, pairwise accuracy and
log-likelihood, paired. Then swap pnr for psn and pnx to show whether tie strength now reaches the launch level.

**E2, PH agent, Nov 2–3:** competitor grounding at decision level (C) on PH Similar Products: competitor-pair
accuracy with vs without competitor-relative gaps, and the person-level competitor tie. Report with intervals.

**E3, PH agent, Nov 3:** X follow checks land. Test "follows the maker on X" as a person-level tie and as a segment
size for the maker-follower component in E1.

**E4, PH agent, from Nov 9:** 7 days of clean snapshots: fit the reach components on hour-2 votes, and ship the
launch-day forecast (hour 1/2/4) as a separately scored product forecast.

**E5, new parallel session, Nov 2–4:** trained person model (two-tower on person history and launch team/page) vs the
GBM, on person-level top-3 hit and pool-vote correlation. CPU only, inside GCP $50/day.

**HN, HN agent, continuing:** page judge as an input (running); /newest early votes at 15 min / 1 h on the October
archive (now complete); recorder at ~2 req/min; live Caught from Nov 4. Add one intermediate target: predict rank at
15 min from at-posting inputs, then chain to 1 h. At posting the content judge plus "seen elsewhere first" are the
new information; everything else has been shown to be the same surface.

## What to stop
- Adding features to the launch-level GBM and reading ±2 on daily top 3.
- Calling sim-plus-audience-counts "the simulation".
- Reweighting the pool to stand in for audiences it does not contain.
