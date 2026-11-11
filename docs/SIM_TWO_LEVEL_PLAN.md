# User simulation plan (corrected Nov 11)

**What we are building (Shreyas, Nov 11):** a user simulation. Given any product's information, predict how each
real person responds to it. Product Hunt votes are the ground truth for validating the simulation.

- We are NOT building a launch predictor.
- The launch model is a reference line only. It is not improved further.
- Product understanding lives inside the person model: P(person wants product | product information, person history).
- Inputs come in two labelled blocks:
  - **product-only**: available for any product (description, audience, pricing, category, media, site, competitors);
  - **PH context**: hunter and maker audience, team ties.
  Every result is reported with PH context off and on.
- Primary metrics are person-level: per-person Hit@1 and Hit@3 over the day's line-up, voter R-precision per
  product, calibration.
- The daily/weekly/monthly top 3/5/10, from summing people, is the population-level validation.

The original Nov 10 text follows. Where it differs from the above, the above wins.

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

## Where the evidence stands (Nov 11, 09:45 UTC)
- **Launch-day upvote, per person:** predicted by launch popularity × the person's activity. Product taste adds no
  measurable person-level gain on top of the launch-model score (E5: Hit@1 +0.019 [−0.008, 0.049], AUC −0.001).
  Team ties add about 5% of the within-day choice. Votes are 68% cast before the hour-4 reveal; top-3 launches are
  34% one-vote-that-day accounts.
- **Launch ranking (north star):** best from the launch model alone. Two-term simulation (taste + LM popularity):
  59.6 / 67.4 / 70.0, above the deployed sim (49.1 / 65.3 / 70.0) and it8 full (+15.8 top 3 [7.0, 26.3]), below
  the honest backtest LM (70.2 / 68.4 / 74.7). Not run on live LM forecasts yet. Live votes reach about 90% at ~6 h.
- **"Uses or wants" (stacks, reviews, collections), per person:** a learned taste scorer gives AUC 0.74–0.75 against
  popularity-, format- and length-matched negatives; personal part +0.11–0.12 over a shuffled profile. Fuller text
  adds +0.007; persona cards and the LLM judge add nothing.
- **Upvote taste and use taste transfer weakly** (zero-shot personal part +0.03). Keep them as two response channels.
- **Audience segments × product attributes:** real and stable at pooled level (0.25 vs control 0.05; cold-start 0.19
  vs 0.01). Not a per-launch or per-person predictor.
- **Ruled out on held data:** follower-list pull, audience-size scaling, on-PH team-audience term, cascade sim,
  LLM-as-the-user, blind LLM appeal (0.05–0.16 vs votes, full page included).
- **Bug fixed in simlab, not in the deployed pipeline:** `[REDACTED]` / id "0" maker placeholder in tie and
  maker-history features. LM fix is accuracy-neutral.

## Decision (orchestrator, Nov 11 13:45 UTC): ship the early-day forecast
Shreyas: stop asking, take the call, move the metric. Call taken:
- The PH operating north-star metric is now reported at two times: the 00:05 PT forecast (launch model, the
  pre-launch line), and the early-day forecast at the vote reveal (~04:00 PT) and +1 h / +2 h / +4 h, using only
  data up to that minute.
- Reason: pre-launch ranking is at its ceiling with held data (about 60–70 / 68 / 75 in honest backtest; every
  candidate since Nov 2 failed). Live votes reach 56 / 73 / 83 at the reveal and 89 / 93 / 90 two hours later
  (3 days). 68% of votes are cast before the reveal.
- PH agent: replay on all captured days, go live by hand from Nov 11, weekly and monthly lists from cumulative votes.
- The user simulation continues on the "uses or wants" channel (learned taste scorer) as a separate deliverable.
- Hacker News stays stopped.

## Experiment queue (orchestrator keeps this current; agents take the next open item when they finish)
Rule (Shreyas, Nov 11): no agent sits idle. Every hourly check confirms each agent is running the highest-priority
item it can, and assigns the next one if not. Waiting for forward days or a data reply is never a reason to stop.
Each item is a backtest on held data unless marked otherwise. Results go to docs/RESEARCH_LOG.md.

Status at 21:50 UTC Nov 11:
1. **Live vs backtest parity of the 00:05 forecast**: done. The gap was mostly a small, different day set. Same 14 live days: published 52.4/65.7/77.9 (corrected: duplicate forecast rows removed); current code on 00:05 inputs 57.1/64.3/77.9; backtest condition 59.5/67.1/77.9; no difference excludes zero; no new leak. Placeholder maker ids cost about 2 top-3 points (shadow fix, scored forward).
2. **Early-day vote forecast on months**: done. 93/95/93 at 08:00–12:00 PT on 29 days; 85/93/92 in the first hour after the reveal on 9 days; raw votes beat any learned projection.
3. **Dated domain popularity before launch**: done, no gain. In the top-1M list for 13% of launches; correlates with votes (+0.14) but not with what the launch model misses (−0.015); top 3/5/10 −0.2 / −0.3 / 0.0, all intervals span zero.
4. **User simulation at population level, "uses or wants" channel**: done. Weak but real: for new products, summed taste picks adopted products at about 1.5× random (top-decile 15.5 vs 9.8); for known products popularity dominates (taste adds +2.6 top-decile).
5. **Pre-reveal blend** (PH's pre-reveal API rank + comment forecast + launch model): scored forward daily from Nov 12; refit when 7 days exist. PH agent.
6. **Weekly and monthly calls from dated votes**: scored forward; daily re-read live from Nov 11 (raw/ph_at_launch/monthly_reread/); PH agent adds the monthly shadow line.
7. **Existing-fame prior at 00:05**: done, null (302 of 305 launches unknown to the model; brand flag vs residual +0.017 [−0.11, +0.15]).
8. **PH pre-reveal rank from Wayback**: not available (dailyRank null on all 1,822 pre-reveal rows; page order is randomised, Spearman −0.006 with final rank). The API rank stays a forward-only line.
9. **Resolve placeholder makers to real identities from held data (store 'made' tabs, thread dumps, people_ts) and recompute maker history**: PH agent, running. 48% of actual top-3 launches have a placeholder maker; they are missed 44.7% vs 30.1%; ceiling about +7 top 3.
10. **Second-stage correction of false favourites (brand sub-launches, versioned names, placeholder share, margin) + calibration / confidence flag**: E5, running.
11. Open: refit the pre-reveal blend when 7 scored days exist; brand sub-launch penalty for favourites ('X by Brand' names are false picks 52% of the time, 27/52; versioned names 50%); report the launch model's own margin as a confidence flag (top 3 is 73.7% on days with a large #3/#4 gap vs ~59%); maker-fix shadow (scored forward).
Standing conclusion (Nov 11): nothing knowable before launch explains the launch model's misses (all pre-launch attributes |rho| <= 0.05 with the error; closed today: domain popularity, fame prior, GitHub momentum, repeat-maker mobilisation, pre-midnight comments, early-commenter identity, comment text). The lever is the first hours after launch.

Done Nov 11: comment forecast before the reveal (+5.0 top 3, +3.9 top 5 at 4 h, 207 days, live-compatible); early-engager
identity (no gain); comment text / commenter / maker-reply / arrival-shape blocks (no gain); weekly call (57.5/71.5/77.8
without dated votes; 100/80/90 with day-end votes on 1 week); monthly call (42/50/52 from daily rank; 75/75/80 with dated reads, 4 months).

## Website (Shreyas, Nov 11 22:15 UTC): put the Product Hunt predictor on the site
Website agent: session_01WkCrUQw5HWVGM17CVJnoPr, branch `claude/ph-website`. Two pages: (1) live predictor (00:05, pre-reveal and
vote-based forecasts with a scored track record); (2) try a product URL → simulated reactions, likely users with names
redacted, and where it would land on Product Hunt with default hunter/maker values. PH agent and E5 supply entry points.
Shreyas has taken this agent over (Nov 11 22:35 UTC) and directs it himself; the orchestrator, PH agent and E5 support it on request.

**Standing rule (Shreyas, Nov 11):** every subagent or new session the orchestrator creates uses the Opus model.

Closed Nov 11 (late): repeat makers' past low-activity voters as a mobilisation feature (no gain, +0.0 top 3); reveal-time projection from voter lists (dropped: voter lists are not held and cannot be captured).

Near-ties (orchestrator, Nov 12): only 9–11% of top-3 misses are true coin-flips (place 3 vs 4 within 5–10% of votes); counting them as hits gives 66–67%. About 5–9 of the 27 points to 90 are irreducible before launch; realistic pre-launch gains total +3–6 points. 90% top 3 is not reachable before launch with held data.
