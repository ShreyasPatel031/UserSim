# Direction review, Nov 2, 2026 (Fable, at Shreyas's request)

Scope: the Product Hunt work against north star 1 (competitor grounding raises predictive value; then 90% daily top
3 / 5 / 10). Sources: `docs/HISTORY.md`, `experiments/simlab/reports/overnight_1030.md` (Nov 1 sections),
`path_to_90.md`. Every number below is from those logs.

## 1. What the measurements say, read together

| Fact | Number | Where |
|---|---|---|
| Launch model, pre-launch | 65.8 / 72.9 / 80.8 | HISTORY §3 |
| Best simulation, pre-launch (page-aware + tie strength) | 62.6 / 71.2 / 79.7; vs launch −3.2 (−7.5 to +0.9) | overnight Nov 1 |
| Simulation reproduces the launch model's skill | simcore alone gets 87% of the launch model's skill; combined +0.1 | path_to_90 §14 |
| Pool's *real* votes rank launches | ~91% daily top 3, from 16% of all votes | path_to_90 §11 |
| Pool's *simulated* votes rank launches | ~48% daily top 3; pool Spearman 0.48–0.49 | overnight Nov 1 (panel, pool_check) |
| Tie strength | person +1.8 (6/6 months); pool Spearman +0.03 (CI > 0); winner-of-3 by month +2.7 (+1.0 to +4.4); daily top 3 ±1 | overnight Nov 1 |
| Panel reweighting of the pool | 47.7 / 59.9 / 69.3; below the raw sum | overnight Nov 1 |
| Launch-day data, person level | +3.2 with 3 h of comments; 62.2 vs 56.0 with 12 h | path_to_90 §8–9 |
| Hacker News, same stack | per-post AUC 0.796 at posting, 0.956 at 1 h; 80.2% top-30 recall at 21:00 UTC | RESEARCH_LOG |
| Competitor gaps as launch-score inputs | no gain, twice (+1.2 noise; 62.3 → 62.2 ctrl) | HISTORY §5 |
| Competitor use per person | +1.0 person top-3 hit (meaning-based lists, 14% accurate) | overnight Oct 31 |
| PH Similar Products as alternatives | 45.8% of real alternatives in the top 5 vs 28.6 Gemini, 13.8 meaning | overnight Nov 2 |

The three results that matter most are: the pool's real votes rank launches at 91% while its simulated votes rank
them at 48%; a better person model (tie strength) improves the simulated pool votes but not the daily ranking; and
on both platforms launch-day data moves accuracy far more than any pre-launch input.

## 2. Critique of the approach

**1. The gap is a shared, launch-level shock, not person-level noise.** A person model with AUC 0.73 summed over
20,000 people should rank launches well if its errors were independent across people: independent errors average
out. They don't average out, so they are correlated within a launch. The thing all of a launch's would-be voters
share, and that no pre-launch input sees, is what the makers do on the day: DMs, email lists, Slack, and where the
launch sits on the page by hour 2. That is why tie strength (who is *disposed* to vote) improves the pool Spearman
and the month-level competitor test, and not the day's top 3; why reweighting pool people by traits cannot recover
totals; and why the simulation and the launch model top out at the same place (87% shared skill). Pre-launch, both
models are bounded by the same unobserved shock. This is a hypothesis with a cheap direct test (E0 below), and it
decides where effort goes.

**2. The evaluation loop cannot see the effects it is testing.** With 116 days, the paired interval on daily top 3 is
about ±2.6 points; every single-input change this week landed inside it. A change worth 2 points needs about 400
days to detect. Testing increments at the day level measures noise. Development metrics must be the ones with
power: person top-3 hit (70k person-days), pool Spearman (207 days, SE 0.01), winner-of-3 by month (3,300 groups).
Daily top-k is the north star and gets reported with its interval; it is not the signal to tune on.

**3. Competitor grounding has been tested where it cannot show.** Daily top-k is scored against the same-day
line-up, and the model already sees that line-up (day-standing inputs). Adding competitors to a model that already
knows every competitor on the page is redundant by construction. The two places competitor grounding can add
predictive value are (a) at the *person* level, where "this person used a competitor" is a real signal (+1.0 with
14%-accurate lists; PH's lists are 3× more accurate), and (b) forecasts made *before the line-up exists*: a week
ahead, scored on weekly rank or on votes relative to the week. Neither has been run with the good lists.

**4. What is working and should be kept.** Out-of-sample discipline, paired intervals, the coverage gate, the
honesty rules; the deployed daily simulation forecast as a live, separately scored benchmark; the data repairs
(fail-loud steps, upvotes restored, leaderboard cross-check); the HN stack as a second domain.

**5. Stop.** Panel reweighting by pool traits (negative, understood). Further tie-strength extensions (person +0,
pool +0.01). Competitor gaps as launch-score inputs (null twice). Any new input evaluated only on daily top 3.

## 3. The three directions, in order of expected return on the north star

**A. Launch-day forecast, with the simulation as the model of who has not voted yet.** The first hours reveal the
shared shock. On HN the same stack goes from AUC 0.80 to 0.96 in one hour. On PH the hour-7 ranking matched the
final top 3 on the one day observed. The simulation's role changes from "predict votes from nothing" to "given the
first 200 votes and which pool people have already shown up, predict the remaining votes per launch": tied
audience not yet converted, presence by hour (the comment-hour data that was useless pre-launch), position effects
by hour. This is the route to 90 for the launch-day claim, and it does not wait for Nov 16: comment timestamps
exist for every launch since March and are a proxy for the vote trajectory, so the backtest can run now and be
calibrated on real hourly votes as they accrue.

**B. Pre-launch: see the shock before the day.** If E0 confirms the shock is launch-level, the pre-launch route is
to measure the makers' capacity to produce it: X audience and engagement (the go/no-go sample lands Nov 3), newsletter
and community signals, pre-launch promotion (already in `promo_`), and the team's turnout history as a *launch-level*
input (how many of a maker's past backers come back, which this week's `team_turnout` computed per person). This is
where the pre-launch claim moves; it is data work first, modelling second.

**C. Competitor grounding where it can show.** Use PH Similar Products (launch-time-safe) in the person model and
the audience inputs, measured at person and pool level and on winner-of-3 by month; and define the T−7 forecast
test, with vs without competitor grounding, scored on weekly rank. The product claim ("who will care and why")
also lives here: the qualitative layer against reviews and comments, which is independent of the daily top-k.

## 4. Experiment plan

Each experiment names its question, method, cost and decision rule. All out of sample, paired intervals.

**E0. Where the error lives (today; exp-1, ~1 h; existing data).**
Question: is the pool's prediction error a shared per-launch shock or person-level noise?
Method: Jul–Oct person × launch rows with the `pnr` person model's p and the real pick y (`choice.rows(all_people)` +
`featurize`, as `score_day`). Residual r = y − p. (i) Variance decomposition of r: launch-within-day component vs
person component vs remainder. (ii) Oracle: add each launch's mean residual to every person's p (the shock known),
re-sum, score daily top 3/5/10. (iii) Oracle: real votes for tied people only / untied only, simulated for the rest.
Decision: if (ii) recovers most of 48 → 91, the shock dominates: A and B are the routes and more person modelling
is not. If (iii) tied-only recovers most of it, "which tie the person acts on" is still the problem and the person
model has headroom.

**E1. Launch-day forecast backtest from comment trajectories (Nov 2–4; exp-1, ~half a day).**
Question: at hour h of launch day, how well is the final daily top 3/5/10 known?
Method: for every launch Mar–Oct, comments by hour 0–24 PT (102k timed comments). Features at h ∈ {1, 2, 4, 8, 12}:
the launch's and the line-up's comment counts and ranks, the pre-launch forecast, and the simulation's remaining
audience (predicted pool voters not yet among the commenters). LightGBM on final log votes, rolling monthly, 3
seeds. Report daily top 3/5/10 by hour with intervals, and per-launch AUC for top-3 membership. From Nov 2, fit the
comments → votes calibration on the real hourly snapshots (dedupe Nov 1 on launch_id × at) and report both.
Decision: this sets the launch-day curve. If top 3 at h = 4 is already in the 80s, the plan to 90 is the remaining-
audience model; if it is in the 60s, the proxy is too weak and the test waits for 14 real days.

**E2. Competitor grounding with PH Similar Products (Nov 3–5; exp-1, ~half a day).**
Question: do 3×-more-accurate competitor lists make the simulation more predictive?
Method: build launch-time-safe lists (every listed product launched ≥ 2 days before the launch; the
launch_slug → product_slug table in `similar_products_all.jsonl`). Swap them into `comp_features`
(`comp_used5 / n20 / best`) and `nsa_comp_ties`. Measure: person top-3 hit and AUC (`pick_boost` ABLATE), pool
Spearman (`pool_check`), winner-of-3 by month (`comp_boot`, day-clustered), first-time teams higher-of-2; daily
top 3/5/10 reported. Baseline: the same with meaning-based lists.
Decision: a gain with intervals excluding 0 at person or pool level is the first positive answer to north star 1's
first clause. No gain with 46%-accurate lists means competitor *audience overlap* is not how competitors matter, and
the remaining competitor value is in the T−7 forecast and the qualitative layer.

**E3. T−7 forecast with vs without competitor grounding (design this week, run after E2).**
For launches with a scheduled date, forecast at T−7 with no line-up: team reach, page, and (with grounding) the
competitors' outcomes relative to their own reach and the overlap of audiences. Score on weekly rank top 5/10 and
on votes relative to the week's median. This is the test that can show competitor grounding's predictive value
without the line-up masking it.

**E4. X go/no-go (Nov 3, as planned).** Voter–maker vs non-voter–maker follow rate; scale only at ≥ 3× and ≥ 10%
coverage of untied voters. If go: makers' X audience as the first pre-launch proxy for the shock (direction B).

**Evaluation rule from here.** A change counts when its paired interval excludes 0 on a development metric
(person top-3 hit, pool Spearman, winner-of-3 by month) and daily top 3/5/10 did not get worse. Daily top-k is
reported every time with its interval; nothing is tuned on it.

## 5. What this does not change
The north stars stand. Pre-launch and launch-day stay separate claims and both are driven to 90. The live
pipeline keeps producing both forecasts daily; the first scored day is Nov 3.
