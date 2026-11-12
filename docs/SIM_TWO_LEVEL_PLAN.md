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
9. **Resolve placeholder makers to real identities**: done, no gain (16% of slots, 31% of launches resolved; top 3 +0.3 [−1.2, +1.8]). Resolved makers have almost no earlier launches; the gap is about new/company teams, not missing identities. Found: all placeholder makers were pooled as one maker in history features (offline too); treating them as missing is the shadow fix.
10. **Second-stage correction of false favourites**: done, null (top 3 −1.0 [−3.1, 1.1]). Calibration kept: the launch model's #1 / #2 / #3 picks finish top 3 90.3% / 57.0% / 41.1% of the time; sent to the website as a confidence flag.
11. **Validate the website's "what users will say"**: done, passes. 300 launches: the site's simulated comments cover 38.5% [36.0, 41.0] of the themes real users raised; 42.3% [39.4, 45.2] of simulated points appear in real comments; generic-topic and shuffled controls score about 5%. Persona conditioning adds nothing.
11b. **Raise it**: done. Flash at temperature 0.3 + themes retrieved from the 10 most similar earlier launches: recall 49.9%, precision 51.4%; +12.2 [9.6, 14.8] / +8.9 [5.7, 12.1] over the site's pipeline; confirmed with a second judge (+6.4 [3.3, 9.6]). 5 s, ~$0.003 per request. Handed to the website agent.
11c. **Similar-past-launch outcomes for the try-a-URL rank band**: done, null (top 3 −0.3 [−2.7, 2.1]); redundant with the product text. The existing band is calibrated: its 10–90% range covers 79.7% of true ranks (n = 5,351).
11d. **Simulated reactions vs real post-use reviews** (228 products, PH product reviews): done. With a post-use prompt: recall 52.3% [48.8, 55.7], precision 54.2%; generic 4.3%. Praise 65.5%, complaints 25.1%. The launch-framed prompt does much worse on reviews (36.4 / 32.7). Caveat: mostly established products the model may already know.
11e. **Complaint recall and memorisation control**: done. A critic pass adds +8 recall on established products but only +3.6 [1.6, 5.7] on 300 post-cutoff launches, at −6.1 precision. For new products about 1 in 5 real critical points are anticipated (18.2% [15.8, 20.7]). Keep the reactions prompt; a 'concerns worth checking' checklist is the most the page can claim.
11f. **Do the page's closest matches actually upvote more?**: done, no. 114 launches: matches 0.98% vs activity-matched 1.04% (ratio 0.95, −0.05 [−0.30, 0.20]); most active members 9.81%. Voting follows activity; tool similarity adds nothing. The page must say 'who it resonates with', not 'who will vote'.
11g. **Vote-specific match from upvote history**: done, closed. 17,764 complete people, 114 launches, base rate 1.3%: activity + recency alone picks voters at 15.9% (top 100); product taste adds +1.8 [1.4, 2.2]; maker/hunter ties add +5.1 [4.1, 6.2]. Not exported (small gain, unverified bundle, upvote lists can fingerprint a person). The page shows resonance, not voters.
User-simulation status (Nov 12): validated = what people say at launch (about half of real themes) and after use (about half; complaints 1 in 4, 1 in 5 for new products); rank band calibrated (8 in 10). Not supported = who will vote (activity decides), which new products get adopted beyond 1.5× random. 
12. **Votes on comments before the reveal** (dated in live comments_ts; forward-only) + train/serve rescale of the comment ridge + first live pre-reveal points on Nov 12: PH agent, running.
13. **What PH's weekly/monthly rank is made of**: done. It is votes frozen at the period end and nothing else (live Spearman 0.9993; the running rank lags recent launches). A learned score does not beat votes. The period-end read (23:50 PT daily) is the call; weekly and monthly reread points added.
13b. **Reveal-time gap**: done. Not a defect: votes reorder fast in the first hour. 4 days, raw votes: reveal 58/70/82; +15 min 75/80/88; +30 min 75/90/88; +60 min 83/90/88. New live points at +15 and +30 min. Follow-up running: blend reveal votes with the pre-reveal signals.
14. **Ranking objective / classifier / ensemble and same-day line-up competition at 00:05**: done, null (best: regression + LambdaRank rank-average +1.2 [−0.1, +2.6] top 3; line-up features +0.1; second stage +0.8 [−0.3, +1.9]). Pre-launch at 00:05 is exhausted with held data; the remaining 00:05 ideas need NEW signals (items 17–19).
15. **Bracket hidden votes before the reveal from the weekly rank**: done. It validates (estimate at 03:45 PT vs real votes at the reveal: Spearman 0.92–0.97, level within 6–15% once the week has enough launches; coarse on Tuesday). No new ordering (same as the API daily rank) and a velocity projection hurts. Kept as extra columns: vote magnitudes, gaps, an absolute level for the mid-day weekly call. Monthly rank asked of the Data Feeder for Mondays.
16. Open: refit the pre-reveal blend at 7 scored days; maker-fix shadow (scored forward); weekly and monthly shadow lines (scored Nov 16 and Dec 1).
Pre-launch status (Nov 12 01:30 UTC): exhausted with held data. Honest 00:05 level is about 60–63 / 68–69 / 75; no tested pre-launch input moved it.
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

### Queue restart (Nov 12 01:45 UTC). Shreyas: experiments never stop; "ideas exhausted" is not an outcome.
17. **More days for the hidden pre-reveal rank**: done. The pipeline's hourly recorder holds the API daily rank before the reveal on Nov 2 and 3 too → 6 days. API rank vs launch model, top 3/5/10: 01:00 PT 72.2/56.7/68.3 vs 38.9/60.0/76.7 (top 3 +33.3 [+6, +56]); 03:00 PT 72.2/76.7/81.7. It starts beating the launch model 35–65 min after launch; at 00:05 it is worse (40.7/48.9/58.9 on 9 days). No other held feed has it.
17b. **Hidden rank + launch model, depth kept**: done. Weighted mean of rank positions (leave-one-day-out picks the same weight every time), 6 days, replay: 01:00 PT 66.7/66.7/78.3; 02:00 72.2/76.7/80.0; 03:00–04:00 83.3/80.0/80.0 (launch model alone 38.9/60.0/76.7). Written as pred_rank_best in the pre-reveal files from Nov 12 and scored forward. Weak spot: small weekend line-ups (Nov 8), where late-morning votes overturn the early order.
18. **Maker/company X audience via handles on the product site**: done, closed. X handle found for 21% of launches (29% of top-3). Even the leaky version (followers read after launch, 720 launches) has no within-day relation to what the launch model misses (−0.02 [−0.13, 0.08]); followers correlate +0.17 with the launch model itself. No pilot read, no daily line.
18b. **Likely voters (internal use)**: done. Person level: AUC 0.875 from activity + recency, 0.912 with taste; top-100 lift 15–22×; top 2,000 hold 83% of a launch's pool voters; holds for cold makers; calibrated. Launch level: summed taste has no ranking signal (Spearman +2.1 [−3.6, 7.6]); summed ties 39.0, adds +11.9 top 3 to the product-only ridge and nothing to the full launch model. Coverage: 10% of the pool gives the same signals (about 2,000 people suffice).
18c. **Simulating a specific person's comment**: done, no. Only 88 people have enough comment history. Own history vs generic member: same specific point 22.1% vs 12.4% (+9.7 [3.3, 16.5]) but a judge picking the closest of four cannot tell them apart (28.9% vs 26.5%); tools and upvotes add nothing. The site voices member types, not real individuals.
18d. **Value of optional visitor inputs for the try-a-URL rank band**: done. 150 test days: product-only 30.0/41.1/61.9; + hunter history 47.6/62.4/75.3 (+17.6 [12.7, 22.7] top 3); + maker history 56.9/66.4/75.5 (+26.9 [21.6, 32.0]); full model 61.1/67.7/77.1. Band width shrinks from 33.5 to about 20 ranks. Two optional fields (hunter profile, maker profiles) recover about 85% of the gap; recommendation sent to the website agent.
18e. **Ranked top-3 concerns for new products**: done, clears the bar. 300 post-cutoff launches: ranked list precision@3 24.4% and at least one of the top three raised on 54.7% of launches; generic category list 11.1% / 29.4%; deployed order 19.1% / 45.6%. Ranked − generic +13.3 [9.9, 16.8]; ranked − deployed +5.3 [1.9, 8.8]. Recipe sent to the website agent.
18f. **Hunter/maker lookup bundle + predicted questions**: done. Bundle validated on 474 unseen launches (both fields: 56.9/65.9/74.7; privacy flag with Shreyas). Predicted questions: about 1 in 7 of the top three were actually asked (15.5%) vs 1 in 15 for a generic FAQ (6.8%); +8.7 [5.7, 11.8]; weaker than concerns.
18g. **Page-gap detector, discussion volume, mirror test**: done. Gap detector rejected (users ask about what the page mentions: platforms 59.5% when mentioned vs 15.5% when silent); "mentions it" as a positive vote adds nothing at item level (concerns −0.5, questions +0.1). Discussion volume: within-day correlation 0.28 product-only, 0.44 with hunter + makers; band covers 81–83%.
18h. **Noise ceiling and self-consistency**: done. Split-half bar (one half of real comments predicting the other, 158 launches): reactions recall 43.9 / precision 40.6, ours 55.9 / 56.8 (above the bar); concerns p@3 bar 27.2, ours 23.3 (86%); questions bar 15.8, ours 15.9 (at it). Self-consistency (−5.3) and gemini-2.5-pro (−6.3) both worse for concerns; ranked list unchanged.
18i. **Does the simulation know the audience: Hacker News vs Product Hunt reactions to the same products** (2×2 cross test): E5, running.
19. **Community size from the product site**: done, closed. Discord link on 5.5% of launches (10.5% of top-3); 506 public count reads, no blocks. Discord members vs the launch model's misses +0.06, and only +0.03 (n.s.) on recent launches, i.e. mostly growth after launch; top 3 −0.8 [−2.1, +0.5]. Dated npm downloads: no signal.
19b. **Scan of every captured pre-reveal field**: done. Nothing adds usefully beyond the hidden rank (best: self-hunted and prior reviews, +0.02 correlation before 02:00 PT, zero top-3 hits). Homepage order is random before the reveal; follower fields are empty on API days; content edits are capture artefacts. Two columns recorded forward.
19c. **Reading the launch model's misses, 87 text flags**: done, null. The differences are real (misses: indie Mac/local/free and open-source dev tools; false favourites: big-company feature drops, AI media models, update wording) but every residual correlation is <= 0.12 and no flag or set gains top 3 or top 5 month-forward (all 87: −1.0 [−3.1, +1.1]).
19e. **When the vote order can be trusted, by day type**: done (80 days). Top 5 reliable from about 05:00 PT everywhere; top 3 reaches 90 at 06–08 PT on weekends and small line-ups, 08–12 overall, 12–18 on weekdays with more than 20 launches (the slow case). A launch outside the top 5 at 05:00 finishes top 3 on about 1 day in 16. Confidence rule: votes of #3 ÷ #4 >= 1.2 after 05:00 → top 3 exactly right in 58 of 60 reads; >= 1.3 → 32 of 32; same for top 5 (96%). PH agent adds lock columns and 05:00 / 06:00 points.
19f. **"Call it when confident", out of sample**: done. CORRECTION of 19e: the 97% for "#3 leads #4 by 20%" was in-sample. Out of sample it is 67–81% exact before noon and about 93% from 12:00 PT; thresholds chosen on one half of the days swing between 1.1 and 1.3. Locking does not raise the hit rate over the plain vote order (±1 point); its value is the label. Robust: "2 locked, 1 open" (#2 leads #3 by 20%): both in the final top 3 in 141 of 141 reads, exact top 2 in 96%. Exact top-10 lock essentially never; "9 of 10" on the plain order from 12:00 PT is 98–100%. Thresholds sent to the PH agent.
19g. **Depth before the reveal**: done. Top 10 is near its ceiling: 5 of 12 misses at 03:00 PT are boundary coin-flips (88–92 if those count). Equal-weight mix for places 6+ is worth about +3 to +5 on top 10 (provisional, 3 swapped launches). The 6 top-5 misses are all late builders that nothing before the reveal catches. A top-15 watch-list from 02:00 PT contains 97% of the final top 10. Columns pred_rank_depth and watch15 added by the PH agent.
19h. **What the official daily rank follows**: done. It is exactly the order of votes at midnight PT (= launchDayScore): 100% of top 3/5/10 and full top-10 order on 54 Wayback days; cut-off scan best at 00:01 PT. Votes read later are not the truth (warehouse votes reproduce the official top 3 on 81% of days: launches keep gaining after midnight and PH removes votes later). No hidden score. Rank stable from 03:00 PT next day. WITHDRAWN: the "84% exact / 97.9% overlap ceiling" in 19e–19f; the real ceiling is about 100% apart from exact ties.
19i. **Is the launch model trained on a noisy target** (warehouse votes vs midnight votes / rank-consistent targets): PH agent, queued after the feature-set comparison.
19j. **Independent audit of every visitor-facing number on /ph and /try against primary data**: orchestrator (Opus subagent), running.
19d. **Training window of the launch model**: interim, null. Rolling windows (60/90/120 days) and time-decay weights cost 0.3–1.1; day-of-week input +0.7 [−0.3, +1.6] top 3. The deployed pipeline already retrains daily on an expanding window. Follow-up running (PH agent): the deployed feature set and params vs the honest backtest config on the same 00:05 inputs (honest model scores 66.7/68/72 on Nov 1–10 vs 57/64/78 for the deployed config).
20. Open: commenter follower counts and comment votes dated in the live feed, scored as days accrue; a "what the site itself says about launch day" read at 00:05 (launch banner, waitlist size, pricing change) as a live-only feature; error anatomy of each live forecast point from results/NORTH_STAR.md each morning; raise complaint recall for new products using objections from the same category's reviews at retrieval time; raise the product-only rank band (29/40/60) with site-derived audience proxies if 18/19 show signal.

### Queue state, 02:35 UTC Nov 12
Running: PH agent = launch-model training window / recency (19d), then Nov 11 scoring (7th day for the pre-reveal recipe); E5 = ranked top-3 concerns vs category base rates (18e); orchestrator = reading the launch model's misses, rule-based text flags (19c).
Done since the restart: pre-reveal recipe 83.3/80.0/80.0 at 03:00 PT (6 replay days), per-pick confidence (#1 pick 24/24 in the top 3), P0 at 00:45 PT, expected day-end votes (9.5% error at the reveal), weekly call with fitted factors 88.9/100/90 (3 days), optional-input ladder for the rank band (30 → 57 top 3 with hunter + makers), likely-voters validity, person-level comment simulation (no), X audience and community size (closed), field scan (closed).
Open, next to assign:
21. Refit the pre-reveal weights and the comment ridge each morning as scored days arrive (7th day Nov 11, 8th Nov 12); report the pooled table with intervals at 8 days.
22. Top-10 depth before the reveal (80.0 at every hour): what the misses in slots 6–10 are, and whether the comment forecast or expected final votes helps there even though it does not help the top 3.
23. Weekend / small line-up regime (Nov 8 failure): a separate weight or a later forecast time on days with fewer than 20 launches; test on all weekend days as they accrue and on Wayback post-reveal curves for how late weekend orders settle.
24. Try-a-URL with optional hunter/maker fields: build the lookup bundle (hunter and maker histories keyed by profile) so the website can use the ladder result; validate end to end on 50 recent launches.
25. Reveal-time forecast (75/80/88 at +15 min): blend with the pre-reveal recipe and expected final votes; LODO on the days held.
26. What users ask: predict the questions makers get in the first hours (question themes only) and score against real questions, as a separate website section.

### Queue state, 03:40 UTC Nov 12
Running: PH agent = deployed vs backtest inputs at 00:05 (feature sets turn out identical live; the gap is input values), then launch-model target noise (19i); E5 = audience conditioning, Hacker News vs Product Hunt (18i); orchestrator = audit of every visitor-facing number (19j).
Open, next to assign:
27. 00:05 input values: for each of the 41 live inputs, the value at 00:05 vs the re-read value, and which ones move the forecast (follow-on to the feature-set comparison); fix or impute the ones that are simply late.
28. Votes that Product Hunt removes later: which launches lose votes after midnight, whether it is visible on launch day (vote bursts, one-vote accounts in our pool), and whether it explains launch-model false favourites.
29. Tie and near-tie handling at the top-3 boundary in every forecast file (official tie-break is unidentified): report top 3 with ties counted both ways.
30. Pre-reveal recipe on the Nov 11 and Nov 12 live files once official ranks land (7th and 8th day): pooled table with intervals; refit weights LODO.
31. Try-a-URL end to end on 30 recent launches through the actual site code path (page fetch, not the PH description): reactions recall, concerns p@3, rank band, with the page-read inputs the site really uses.
32. Weekly call earlier in the week: probability that the current weekly top 3 survives, from how many launch days remain and the size of the leaders (calibration on 44 weeks).
