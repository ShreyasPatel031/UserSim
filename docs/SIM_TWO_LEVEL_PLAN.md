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
18i. **Audience conditioning, Hacker News vs Product Hunt**: done. On 57 products launched on both sites, the matching-audience framing covers more of that community's themes (interaction +11.9 [4.8, 18.9] on recall, +11.4 on precision) but does not change which concerns are predicted (−1.8 [−10.3, 6.7]). On 180 Show HN posts: HN-framed recall 39.7, concerns p@3 27.0 vs generic HN list 15.9; the generic HN list beats us on questions (20.3 vs 11.5 recall). "Choose the audience" is defensible for overall reactions only.
18j. **E5 audit for the maker-redaction leak**: done. Masked honest backtest (239 days): 58.4/67.7/75.7, picks 70.6/57.1/47.1, exact winner 44%; minus first-comment fields 56.8/68.3/75.4; minus all page inputs 53.7/67.0/74.8. STANDS: ladder hunter rung +17.6 (unchanged); maker rung shrinks to +5.3 on top of hunter (was +9.3) and needs ONE main maker + maker count (bundle v2: 54.9/65.9/74.7 on 474 unseen launches); likely-voters ties are a HUNTER-ties effect (+14.4 [10.6, 18.7] over product-only; maker ties +0.1); discussion volume; product-only ridge and band. WITHDRAWN: 90/57/41 calibration. Needs re-basing: everything with target log votes − honest LM (early engagers, mobilisation, fame prior, false favourites).
18k. **Page inputs, masked-residual re-runs, clean calibration, truth quality**: done. Honest page gain about half of +3.1 (clean baseline 53.7–55); early-engager count +5.9 [3.5, 8.3] top 3 at +4 h on the clean model; fame and summed voters null; identity-free truth moves the simulated-comment numbers by under 1 point; calibration v2 on the website (71 / 55 / 44).
18l. **Rank-neutral maker identity**: done. The author of the earliest top-level comment (the maker's intro, posted before launch) is available for 88–96% of launches at every rank and carries the maker badge 86% of the time; saved people's "made" events are rank-biased and excluded. Maker history built only from those identities adds top 3 +2.3 [−0.2, 4.8] to the clean model (thread position alone +1.8), mostly by recovering the self-hunted signal the API under-reports for non-winners. Two features passed to the PH agent for the clean shadow.
18m. **One honest early-hours model**: done (238 days; clean model alone 56.3/65.8/76.1). Ridge on clean model + identity-free comment counts (+ pool count + thread maker features): top 3 58.2 at 00:05, 60.6 at +1 h, 63.1 at +2 h, 65.8 at +3 h, 64.9 at +4 h (gain +8.6 [5.2, 12.2] at +4 h); top 5 about 69–70; first pick in the top 3 82–84%. Comments carry it; the pool-engager count and thread-based maker features add nothing once comments are in. Caveat: our comment history is capped at 20 threads per launch; on days with at most one capped launch the gain is +5.6 to +6.9 at 3–4 h and not separable from zero before 2 h. Recipe JSON with the PH agent for the live points.
18n. **Try-a-URL end to end through the site's real code** (57 recent launches, 43 fetched and judged): done. Reactions from the site's page read: recall 47.8% [39.7, 55.6], precision 51.9%, vs 50.7 / 53.9 from the PH description on the same launches (−2.9, not significant). The page's "doubts" list as concerns: p@3 11.6% (the ranked recipe, not on the site, gets about 24). RANK BAND WEAKENS on page text: its correlation with final rank is 0.31 vs 0.68 from the PH description (−0.36 [−0.68, −0.11]); coverage 76.7%. About 1 URL in 6 fails to fetch (JS-only 9%, HTTP 403 7%). Latency about 9 s; cost about $0.004 per request.
18o. **Testing the try-a-URL fixes** (130 fetched page reads): done. Rewriting the page read in PH style does NOT recover the rank band (Spearman 0.345 vs 0.311 now; real PH description 0.591): the information is in the launch text, not its style. Ranked concerns work from the raw page excerpt (p@3 23.5 [16.7, 30.3]) and lose 10 points from the short summary. 27% of URLs failed to fetch; a root-domain retry recovers a quarter; the rest need a paste box (shipped by the website agent as /api/try/text).
18p. **Train the rank band on product-site text (the serving distribution)**: E5, running.
19. **Community size from the product site**: done, closed. Discord link on 5.5% of launches (10.5% of top-3); 506 public count reads, no blocks. Discord members vs the launch model's misses +0.06, and only +0.03 (n.s.) on recent launches, i.e. mostly growth after launch; top 3 −0.8 [−2.1, +0.5]. Dated npm downloads: no signal.
19b. **Scan of every captured pre-reveal field**: done. Nothing adds usefully beyond the hidden rank (best: self-hunted and prior reviews, +0.02 correlation before 02:00 PT, zero top-3 hits). Homepage order is random before the reveal; follower fields are empty on API days; content edits are capture artefacts. Two columns recorded forward.
19c. **Reading the launch model's misses, 87 text flags**: done, null. The differences are real (misses: indie Mac/local/free and open-source dev tools; false favourites: big-company feature drops, AI media models, update wording) but every residual correlation is <= 0.12 and no flag or set gains top 3 or top 5 month-forward (all 87: −1.0 [−3.1, +1.1]).
19e. **When the vote order can be trusted, by day type**: done (80 days). Top 5 reliable from about 05:00 PT everywhere; top 3 reaches 90 at 06–08 PT on weekends and small line-ups, 08–12 overall, 12–18 on weekdays with more than 20 launches (the slow case). A launch outside the top 5 at 05:00 finishes top 3 on about 1 day in 16. Confidence rule: votes of #3 ÷ #4 >= 1.2 after 05:00 → top 3 exactly right in 58 of 60 reads; >= 1.3 → 32 of 32; same for top 5 (96%). PH agent adds lock columns and 05:00 / 06:00 points.
19f. **"Call it when confident", out of sample**: done. CORRECTION of 19e: the 97% for "#3 leads #4 by 20%" was in-sample. Out of sample it is 67–81% exact before noon and about 93% from 12:00 PT; thresholds chosen on one half of the days swing between 1.1 and 1.3. Locking does not raise the hit rate over the plain vote order (±1 point); its value is the label. Robust: "2 locked, 1 open" (#2 leads #3 by 20%): both in the final top 3 in 141 of 141 reads, exact top 2 in 96%. Exact top-10 lock essentially never; "9 of 10" on the plain order from 12:00 PT is 98–100%. Thresholds sent to the PH agent.
19g. **Depth before the reveal**: done. Top 10 is near its ceiling: 5 of 12 misses at 03:00 PT are boundary coin-flips (88–92 if those count). Equal-weight mix for places 6+ is worth about +3 to +5 on top 10 (provisional, 3 swapped launches). The 6 top-5 misses are all late builders that nothing before the reveal catches. A top-15 watch-list from 02:00 PT contains 97% of the final top 10. Columns pred_rank_depth and watch15 added by the PH agent.
19h. **What the official daily rank follows**: done. It is exactly the order of votes at midnight PT (= launchDayScore): 100% of top 3/5/10 and full top-10 order on 54 Wayback days; cut-off scan best at 00:01 PT. Votes read later are not the truth (warehouse votes reproduce the official top 3 on 81% of days: launches keep gaining after midnight and PH removes votes later). No hidden score. Rank stable from 03:00 PT next day. WITHDRAWN: the "84% exact / 97.9% overlap ceiling" in 19e–19f; the real ceiling is about 100% apart from exact ties.
19i. **Launch-model target noise**: done, small. The current target's within-day order disagrees with the official rank for the top-3 set on 53 of 308 days, but retraining on midnight votes where held gives top 3 +0.8 [−0.1, +1.7]; rank-consistent +0.1; −log rank −1.2; percentile −2.0. Not the cause of anything large.
19j. **Audit of every visitor-facing number**: done. Arithmetic correct everywhere. Three problems: (1) the "live" 00:05 record of 14 days (52.4/65.7/77.9) includes 6 days written late (Oct 25–28 all on Oct 28, Nov 1 after the reveal, Oct 30 86 min late); honest live record is 8 days, 45.8/62.5/73.8; (2) confidence badges describe a different model than the picks shown (deployed model's live #1 pick in the top 3 on 7 of 14 days vs 90% in the backtest; pre-reveal badges measure pred_rank_best while the page orders by the comment ridge); (3) the day page declares "final" before the official rank exists and a day-boundary bug assigns 00:00 PT launches to the previous day. Sent to the PH agent and the website agent; day-boundary bug filed to the Data Feeder.
19k. **Why the live #1 pick fails half the time**: done, and it points at the BACKTEST. Published #1 pick in the final top 3 on 7 of 14 days; the replay on 00:05 inputs also 7 of 14 (exact winner 3/14 and 5/14); the honest backtest: 90% and 78%, with a #1–#2 margin of 0.44 log-votes vs 0.14. P(7 or fewer of 14 | 0.90) = 1.8e-4. Not noise, not the live llm/promo inputs, not input drift. Suspected leak: the llm / page source in the backtest (judgements from page and site text read after launch). If confirmed, the honest 00:05 level is about 46–57 top 3, not 63, and every comparison against 63/69/75 needs restating.
19l. **Leak in the backtest: CONFIRMED and localised to cached `ph_` values of the test rows.** Same model, same 14 live days: with cached (later-read) rows the #1 pick is in the top 3 on 12 of 14 days and top 3 is 64.3; with the real 00:05 rows 8 of 14 and 50.0. Swapping only the `ph_` columns moves the #1 rate 8 → 12 (and back 12 → 9). llm, promo, text, X and topic columns change nothing; dropping llm or promo from the long backtest changes nothing. Suspect columns: the hunter's same-day hunt count, within-day rank features computed on the final line-up, maker ages from makers resolved later. CONSEQUENCE: 63/69/75 and the 90/57/41 pick rates are inflated; the honest 00:05 level is about 50–57 top 3. The model is also trained on leaky values and served 00:05 values (train/serve skew), so a clean retrain may raise the live forecast.
19m. **Clean launch model** (name the leaky columns, drop or recompute them 00:05-consistently, score on live days with 00:05 rows, honest baseline v2, restate comparisons made against the old baseline): PH agent, running, top priority.
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
27. **00:05 inputs: the live LLM-judgement and promo sources.** Feature set and params are identical between deployed and backtest (53 columns; 41 when llm and promo are dropped). Replay without llm/promo scores 57.1/64.3/76.9 vs published 52.4/65.7/77.9 on 14 days (hint that the live LLM inputs hurt). PH agent: third 00:05 shadow line (no llm/promo) from Nov 13; per-source attribution and long-backtest ablation after the target experiment.
28. Votes that Product Hunt removes later: which launches lose votes after midnight, whether it is visible on launch day (vote bursts, one-vote accounts in our pool), and whether it explains launch-model false favourites.
29. Tie and near-tie handling at the top-3 boundary in every forecast file (official tie-break is unidentified): report top 3 with ties counted both ways.
30. Pre-reveal recipe on the Nov 11 and Nov 12 live files once official ranks land (7th and 8th day): pooled table with intervals; refit weights LODO.
31. Try-a-URL end to end on 30 recent launches through the actual site code path (page fetch, not the PH description): reactions recall, concerns p@3, rank band, with the page-read inputs the site really uses.
32. Weekly call earlier in the week: probability that the current weekly top 3 survives, from how many launch days remain and the size of the leaders (calibration on 44 weeks).

### ROOT CAUSE of the backtest leak (Nov 12, 06:20 UTC) — read before any 00:05 work
Product Hunt shows the makers of the day's #1 launch BY NAME only after the day ends. At 00:05 the eventual winner
has about one named maker and the rest are "[REDACTED]", like every other launch. Rows read after the day therefore
mark the winner: it is nearly the only launch with several named makers.
- Live days, 00:05 pull vs later read: winners' named makers 1.25 -> 3.00; ranks 2-3 1.04 -> 0.96; others 0.99 -> 0.94.
  Total maker count is unchanged; only naming changes.
- "Rank by number of named makers" finds the exact winner on 60-91% of days from the warehouse and 15% from the real
  00:05 read. The backtest's #1 pick is that launch on 74% of days (then right 99% of the time); on other days it is
  right 20% of the time, the live level.
- The period after Oct 25 is not harder (simple baselines hold or improve; no step change in the line-ups).
- Leaky inputs: everything derived from maker identity in rows read after the day (named-maker counts, maker ages,
  maker headline / X flags, maker history and ties, within-day ranks of those) and history tables built from them.
  Clean: total maker count, hunter identity and history, text, topics.
- WITHDRAWN: backtest 63/69/75; pick rates 90/57/41; "hunter + makers" ladder gains that rely on named makers; the
  miss-anatomy reading (hits 2.65 named makers vs 0.95); every pre-launch null was tested on top of a leaky model.
- Honest 00:05 record: 45.8/62.5/73.8 on the 8 live days written on time.
Running: PH agent = clean launch model (19m); orchestrator = independent leak-free baseline from the launches table
with makers masked to the 00:05 view (19n).

### Clean 00:05 baseline (Nov 12, 07:10 UTC)
19n. **Independent leak-free baseline**: done (orchestrator; scripts in gs://.../tmp/orchestrator/clean_baseline/). Launches table masked to the
00:05 view (total maker count; at most one named maker, always the last entry; hunter never hidden). 207 days month-forward:
53.8 [50.6, 57.2] / 66.6 / 74.1; pick #1 in top 3 64.7%; exact winner 31.9%. Hunter history carries the signal, maker count second,
text and topics add almost nothing. On the 8 on-time live days with real 00:05 pulls: 62.5 [50, 75] / 70.0 / 76.2 and pick #1 75%,
vs published 45.8 / 62.5 / 73.8 and 50% (better on 4 of 11 days, tied on 7, never worse; n small).
Honest 00:05 level: about 54 / 66 / 74. Top 10 was essentially right before; top 3 was inflated by about 9 points.
Running: PH agent = reproduce on the VM, shadow_clean line from Nov 13, clean prior inside the pre-reveal recipe;
orchestrator = re-test of the earlier nulls on the clean baseline (19o); E5 = audit of its results for the same leak (18j).

### Queue state, 04:35 UTC Nov 12
Running: PH agent = clean model reproduced on the VM, shadow_clean from Nov 13, clean prior in the pre-reveal recipe (19m); E5 = honesty of the page-input gain, re-runs on the masked residual, clean calibration (18k); orchestrator = re-test of earlier nulls and hunter-side refinements on the clean baseline (19o).
Open, next to assign:
33. Capture maker profiles BEFORE launch for every launch (dated), so maker identity becomes a legitimate input: what the official API exposes for scheduled posts' makers before 00:01 PT, and whether the 00:05 pull already names more makers than the one visible later (6 of 9 days had one non-winner fully named at 00:05).
34. Why does Product Hunt name exactly one maker at 00:05, and which one (always the last list entry): is that maker's history informative beyond the hunter's on the clean model?
35. Pre-reveal recipe with the clean 00:05 prior: replay on the 6–7 days and forward from Nov 13.
36. Comment forecast features on the clean residual: the blocks that were null over the leaked LM (comment text, commenter accounts, maker replies, arrival shape).
37. Weekly / monthly: nothing changes (they use votes), but check no weekly feature used maker identity.
38. Website: once shadow_clean has 7 days, replace the published 00:05 line on /ph if it wins (Shreyas's call on the deployed pipeline).
19o. **Earlier nulls re-tested on the clean baseline**: done. Tranco, 85 text flags, community links, line-up competition, seven hunter-history refinements, lambdarank and classifier objectives: all still null (no top-3 or top-5 interval above zero). One gain: rank-average of ridge and LightGBM → 55.6/67.1/74.6, pick #1 in top 3 71.0% (+6.3 [+1.0, +11.6]), exact winner 39.6% (+7.7 [+2.9, +12.6]); live 8 days 58.3/72.5/76.2, pick #1 87.5%. Added to shadow_clean as a second column.
19p. **Leak check of the comment forecast**: done. The script's team rule (makers named in our later API read) recognises team comments only for the #1 launch; this inflates EXACT WINNER by +5 to +11 (ridge) and +16 to +23 (LightGBM) but leaves top 3/5/10 gains unchanged. Honest comment forecast over the clean model (55.2/66.5/74.4), identity-free features, ridge: +1 h about 60 / 70 / 75; +2 h 62–63 / 71 / 76; +4 h 63–64 / 72 / 76.3; top-3 gain +5 at +1 h and +7 to +8 at +2 to +4 h (intervals exclude 0); exact winner 41–44%. Comments carry Product Hunt's own maker badge, and by it the team share is flat across ranks. Live +1 h sees only about half the comments (capture lag); +2 h is the first reliable live point.
19m. **Clean launch model on the live days**: done, and it wins. 14 live days, real 00:05 rows, same daily refit: deployed 57.1/64.3/76.4 (#1 pick in top 3 on 7 days); clean_v3 (maker-profile inputs dropped, total maker count kept) 61.9/67.1/76.4 (#1 on 11 days); +4.8 [0.0, +11.9] top 3, never worse. 8 on-time days: 58.3/67.5/75.0 with #1 on 7 of 8 vs deployed 50.0/60.0/73.8. Long backtest honest_preds_v2: 53.7/64.6/75.4 (matches the orchestrator's 53.8 and E5's 53.0–53.7). Live as the main 00:05 shadow line (rank_clean) from Nov 12 02:17 PT; also as the prior in the pre-reveal recipe (pred_rank_best_clean).

### CORRECTION (Shreyas, Nov 12 08:45 UTC): the website shows the full team on launch day
The "ROOT CAUSE" section above describes the behaviour of OUR SOURCE (the official API v2), not of Product Hunt's
website. Shreyas checked today's site: a launch page lists the hunter and every maker by name during launch day.
What is measured and stands: in our API reads, post.makers is mostly "[REDACTED]" at 00:05, and in reads after the day
the #1 launch's makers are named while others stay redacted; the backtest was inflated by that pattern; the clean
model beats the deployed one on live days.
What was wrong: saying Product Hunt "hides makers and reveals the winner's team after the day". The rule behind the
API's redaction is NOT known. Do not state it as fact.
Consequence to test: the full team is public at launch on the page, so maker identity is legitimate launch-time
information that the clean model discards only because the API hides it.
Asked for facts: Grok Bot and the Cursor agent (mailbox 20261112T0845Z_team_visibility.md), the PH agent (hourly
API rows), and an orchestrator read of the held API rows (19q).

### FACTS on maker visibility (Nov 12, 10:00 UTC) — replaces the "ROOT CAUSE" wording above
- WEBSITE (Grok Bot, box browser, signed in and logged out; and our page captures of Nov 3, 7, 8: 0 redacted of 905 team rows):
  the launch page lists every team member by name, at every rank, during launch day.
- OFFICIAL API v2 (our held rows, 2,937 detail rows + 00:05 pulls + warehouse): makers are redacted on EVERY read,
  launch day or weeks later. The hunter (post.user) is never redacted. Within a list of posts, the FIRST post of each
  returned page has its whole team named; every other post has exactly one named maker (the last listed; the hunter
  when the hunter is a maker). A list ordered by ranking puts the current leader first, so the leader shows its full
  team; when the lead changes the old leader reverts to one named maker; while votes are hidden a random launch is
  first. Final rank #21 (first of page 2) is fully named about as often as #1 (24/31); #2 and #3 are not (1/206, 1/196).
- So the backtest leak is an artefact of list position in our API reads. Nothing about Product Hunt revealing winners.
- Unknown: why first position and the last maker are exempt; what a single-post read returns. Grok Bot asked to confirm
  with two ordinary paginated reads.
- Legitimate rank-neutral maker identity we already have: the first top-level comment's author (88–96% at every rank).
- NOT done and not to be done without Shreyas: reading one post per page to get every team through the API.

## Queue state, Nov 12 ~08:35 UTC (real clock)
Confirmed since the block above: the API redaction is positional (Data Feeder, 4 ordinary calls); a single-post read returns the full team. Pilot on held data: full teams add nothing to the clean model (97 launches, −0.022 [−0.066, +0.025]) → the one-post-per-call read is not requested.
Headline numbers now: clean 00:05 backtest 56.1 / 67.5 / 74.4 on all 255 days (57.6 / 68.2 / 74.6 on the 207–214 day test sets). Stack (clean + thread features + link/media) top 3 62.3 vs 57.6, +4.7 [+1.9, +7.4] month-forward; no live gain shown yet (live re-score being redone with exact hunter ids). Weekly call from daily ranks only 59 / 70 / 76 (35 weeks); monthly 11/24, 24/40, 61/80 with official weekly ranks.
Closed today (do not re-run): full maker team; error anatomy corrections (segment offsets, text flags, interactions); hidden-rank momentum; first-hours shape terms at 03:00; comments as day-end-vote proxy for weekly/monthly; top-8 reranker; rank-band rewrite; retrieval for questions/concerns; voter-learned "who" (constant predictor); addressable-voters score; tone of reception.
Running:
- R1 (orchestrator subagent): text of the pre-launch intro comment as a 00:05 input; live re-score of the stack with exact hunter ids.
- R2 (PH agent): Nov 11 scoring at every point (7th pre-reveal day); shadow lines clean_stack, clean_thread with within-day standardisation, P0 at weight 0.25 and a 00:30 point, best_mix_th; weekly/monthly fallbacks.
- R3 (E5): stack as the prior of the early-hours model at +1/+2/+4 h; timestamped pool upvotes in the first 30–120 min; hidden rank × stack blend on the 7 live days.
Open (next to assign):
- O1: reviewsCount at 00:01 and product links as read at launch — needs the capture change (to_grokbot/20261112T0825Z_launch_fields, awaiting approval); score when 30 days exist; meanwhile mine products_ts for earlier reads.
- O2: 01:00–02:00 PT window: per-point weights refit each morning as live days accumulate (hidden rank × stack × comments), leave-one-day-out, published as shadow P columns.
- O3: first full live week (score Mon Nov 16): weekly call from day-end votes vs the daily-rank table; monthly early-month line from official weekly ranks.
- O4: /try rank band beyond 0.28–0.40 from a page read: page-read structured fields + nearest earlier launches' outcomes, tested against the best constant and the page-trained band on the 856-launch set.
- O5: who on /try stays descriptive; only reopen with a new information source (e.g. followers of the hunter, which a URL does not have).
Waiting on Shreyas: merge of the early_shock hidden-votes fix (before ~Nov 20); PR #147 merge and its Vercel key; RANKED concerns/questions build on /try; replacing the deployed 00:05 model with the clean one after ~7 scored shadow days.

## Queue state, Nov 12 14:35 UTC
Headlines: clean 00:05 backtest, conservative (no site judgement): 56.4 / 67.8 / 75.0 (214 days); + pre-launch commenter count 60.9 top 3 (+4.7 [+2.3, +7.2]), audited, live coefficient matches backtest, hit counts not yet separable. Live 15 days as-live: deployed 27/45 top 3, #1 in top 3 8/15; clean 27, 12; clean without site judgement 29, 14. Pre-reveal replay (7 days): 71.4 top 3 at 01:00 PT, 85.7 at 03:00. Official ranks = votes at the period close (daily midnight, Sunday midnight, month end); weekly running rank at Saturday end 5/6, 8/10, 18/20 (2 weeks). /try under the same-point standard: ranked concerns/questions from a pasted description beat the generic list and reach the real-vs-real ceiling; top-1 question holds from a URL (41% vs 21–23% generic); reactions are topic-level only; rank band from a page 0.28–0.40, percentile banding calibrated.
Closed today (do not re-run): full maker team; maker-count drift; llm_full leak (never an input); ensembles / rerankers / interactions / target variants on the stack; intro-comment text; richer pre-launch comment block; link/media bundle beyond +1 (not deployable until read at launch); hidden-rank momentum; first-hours shape at 03:00; comments as vote proxy for weekly/monthly; weekly growth factor; voter-learned "who" and addressable voters; tone of reception; consensus / temperature-0 reactions; four same-point reaction variants; drafted launch post; rank-band rewrite; band v2 with page facts (borderline, forward test running).
Running:
- R1 (PH agent): candidate deploy model clean_nosite_thread (backtest, as-live, nightly shadow, patch file); Nov 12 scoring 09:40Z Nov 13 — first forward day for the pre-reveal lines.
- R2 (E5): raising the top-1 question/concern from a URL; daily at-launch page-read job 02:13 PT (band v1 vs v2 forward).
- R3 (orchestrator): QA of each night's files before the outcome; next own analysis chosen at the next check from the scored Nov 12 day (error anatomy of the first forward day).
Open:
- O1: forward check of the thread coefficient (stop at se ≤ 0.07, ~13 days) and clean-vs-deployed block at 25 / 50 days.
- O2: fields that need the capture change (product links, review count at launch) — score when read at launch.
- O3: weekly running rank + expected entrants, first score Mon Nov 16; monthly at day 20 and month end.
- O4: top-1 concern from a URL (not established); "after using it" view under the same-point standard.
Waiting on Shreyas: deploy of the clean 00:05 model (recommended variant: without the site judgement; with the frozen-inputs hook and the VM cron for timed steps); Data Feeder capture changes (nightly monthly reread, day boundary, launch fields, website URLs, earlier comment reads with replies); DataImpulse account (407); early_shock fix before ~Nov 20; PR #147.

## Queue state (Nov 13, 10:40 UTC)
Headlines now:
- Deployed: the 00:05 PT run of Nov 13 published with the clean model (first clean day; Nov 12, last old-model day, scored 1/3, 1/5, 6/10).
- Clean 00:05 backtest: 56.4 / 67.8 / 75.0 (214 days; unaffected by the duplicate-id check).
- With pre-launch commenters (th_n_pre): 60.1 / 68.7 / 75.3 (214 days); gain top 3 +3.5 [+1.3, +5.9] after the thread-missingness check. Live rule: th_n_pre only from the night's first comment read if it lands by 00:30 PT, missing otherwise.
- 00:30 with total comments: top 3 61.2 -> 63.1 (+1.9 [+0.8, +3.0]), top 10 -0.4.
- Pre-reveal replay, 7 days (Nov 2, 3, 4, 8, 9, 10, 11): 00:30 hidden-rank blend top 10 71.4 -> 81.4 (top-10 only); 01:00 hr_clean 71.4 / 65.7 / 84.3; 03:00 hidden rank 76.2 / 71.4 / 81.4, top 10 85.7 with the clean prior; 03:45 hybrid 76.2 / 80.0 / 88.6.
- Reveal is 04:00 PT on every clean day. Plain vote order after it (9 days; early points 5): 04:00 66.7 / 72.0 / 84.0; 05:00 86.7 / 88.0 / 84.0; 06:00 86.7 / 88.0 / 90.0; 08:00 95.2 / 91.4 / 92.9; 12:00 95.2 / 91.4 / 95.7; 20:00 95.2 / 97.1 / 97.1. Top 3 crosses 90 at 08:00 PT, top 10 at 06:00 PT.
- Weekly at close from votes 82 [76, 88] / 88 / 90 (43 weeks; a later 2026 re-check gives 80 / 86 / 87 on 42 weeks); monthly at close 80 / 82 / 85. 2025 lists lower (weekly 62 / 75 / 80, monthly 57 / 64 / 70; cause unknown).
- /try simulator: b20 concerns replicate three times (pooled page p@3 +7.5 [+3.0, +12.0], PH description +12.4 [+7.9, +17.1]; confirmation half +6.5 / +9.3). Page-path questions did not replicate.
- /try rank band, corrected (month-forward): Spearman 0.353 [0.292, 0.412] on 856 launches, 0.417 on the 130 fresh; 80% band covers 75.5%. The 0.59 figure was in-sample and is withdrawn.
- Voter coverage on the merged store (provisional): Oct 29 - Nov 4 69.26% of votes, 94.60% on top-3 launches; unseeded Oct 1-24 48.37% / 80.30%. Caveat: the seeded week is inflated because merged people were drawn from those launches' voters; quote the unseeded figure alongside.
Closed tonight (null or not adopted):
- 00:05 held data: commenter identity (count is the signal); comment timing split; direct P(top 10)/P(top 5) models; six unscored day/comment fields; hunter account age; self-hunt adjustment; shrinkage of unstable inputs; day-regime variants (weekday, normalisation, lambdarank, top-10 weight, regime split); product history and version flags; new-hunter segment model (+0.4, not wired); team track record (coverage 5.9%); time-zone climbers; rank movement and comment counts before the reveal; vote velocity; 04:00-05:00 blends.
- Outside audience: X pre-launch mentions; X team handles; 00:05 API-only handles; hunter has X handle; domain popularity/age (Tranco, RDAP); site-cache signals (GitHub etc.); Wikipedia pageviews.
- Voter data: voter-expected votes at ~28% and at ~70% coverage (gain 0.0, weight 0 on all 10 days); follower-edge features; simulated hidden-window ceiling (not distinguishable from zero over hidden rank); accidental in-window pulls (noise); summed LLM person simulation; held follow edges beyond the hunter's followersCount; person-day choice test.
- Simulator: page -> description two-step; b20 page-path questions; verbatim retrieval; bigger bank; b20 for general reactions; k/points sweep; gap-based page questions; kNN-20 rank band; retrieval who-mix (card stays withdrawn); Vertex Gemini person/launch baselines; flash pairwise near-tie re-ordering (harmful).
Adopted as forward shadow lines tonight (frozen weights; registry results/web/forward_lines.json, 26 lines):
- 00:05: clean_nosite_tb (tie-break on clean ranks 2-6 with pre-launch commenters); clean_nosite_hf (hunter followersCount from the 00:05 read, top-10 candidate only); rank_clean_nosite_h25 and its pure-2026 twin.
- 00:30 (P030): pred_rank_mrep (hunter-only replies + total comments; publish pick); pred_rank_eh (hidden-rank blend, top 10 only); h25_th.
- 01:00 (P1): mrep with the 00:05-safe full team.
- 01:00 / 02:00 / 03:00: hr, hr_clean, best, best_cnosite (hr_clean is the 01:00 and 02:00 publish pick).
- 03:00 and 03:45 (P345): hybrid (top 5 from hidden order, slots 6-10 from the model; publish pick).
- Weekly/monthly running vote order (already live), scored Mon Nov 16; follow_shadow.py logged nightly; forward climber check in morning scoring.
- Note: P030/P1 are currently written at the 02:17 PT run, not at their clock time.
Running / waiting on data:
- 2025 history four-arm retrain (317 day files landed; corrected so far top 3 +0.9 ns, rho +0.016 [+0.005, +0.028]); full year, 5+ seeds.
- 2025 comments pilot (1 file; pre-launch commenter check on 2025 pilot days).
- X-buzz nightly (first freeze Nov 13, files written 00:19 PT) and backfill Nov 9-12 (Data Feeder holds no query rules; Grok Bot asked).
- Decisions API pilot: harness ready, sending stubbed; needs the AI Studio key.
- Hidden-window panel re-read (2,000 most active, 10 nights, expect 400-500 early votes a night): needs the Cursor agent.
- Nightly 00:07 comment-vote read (first night landed 00:15 PT; slot fixed for tomorrow).
- Forward simulator record: Nov 11 band coverage 84.6%, Spearman 0.29; Nov 12 91.9%, 0.52 (n 37); comment-judged launches still 2.
Open, not started:
- Hunter followersCount at 00:05 forward test: about 9 scored days to detect a partial of 0.2; 3 held (Nov 10-12), so 6 more (decide ~Nov 19).
- Pre-launch comment votes re-test after ~5 nights of the 00:07 feed (Nov 13-17); honest held reads exist on 4 days only.
- Day-of-week close correction (Sunday 0.82-0.83, Saturday 0.91-0.95, month's last day 0.72) as a weekly/monthly shadow line: +3 [1, 5] top 10 on the 2026 backtest; score Nov 16, Nov 23, Dec 1.
- Why 2025 frozen daily ranks disagree with today's vote order 9.3% vs 4.1% in 2026 (vote removals vs a rank-rule change), using repeat reads of 2025 day files.
- Late-climber study re-run at 15 days with a true ~04:00 PT read (5 now).
- Team following count, product followers, reviewsRating from a 00:03-00:07 PT read: re-test at 30 days.
- 2024 history once 2025 is done: check the learning-curve extrapolation (+1.6 to +2.9 top 3 at 700-1,000 days).
Waiting on Shreyas: AI Studio key for the Decisions API; website branch merge and the b20 concerns recipe; fleet size after the zero-gain voter result; a nudge to the Cursor agent (no reply since Nov 12 22:32 UTC); a model/version tag in the published forecast file (pipeline change; today the VM md5 is the only evidence of which model published).


## Queue state (Nov 14, 01:00 UTC)
Published (Shreyas, Nov 14): exactly two predictions. 00:05 PT = arm 2 (2025-trained; backtest 60.7 / 68.4 / 75.7 on 214 days; independent
audit +4.4 [+1.9, +6.9] top 3 over clean_nosite; Sep-Oct level ~56; live from Nov 14). 03:45 PT = hybrid (hidden top 5 + slot rule for 6-10;
replay 72.7 / 74.5 / 78.2 on 11 days). Live board on the site comes straight from the PH API. All other points are shadow lines.
Closed Nov 13-14 (null, leak, or not surviving out of sample): readable 10-input model as the forecast (kept as a labelled second
explanation); who-backs-it people model as the forecast (kept as explanation; names ~26% of backers); backer mix (relative-only card);
held-team count and "established member" (store selection; matched placebo); visible-maker count (API names the winner's makers later);
maker-comment content; first-time-hunter people features; top-10 re-ranker; brand split; arm-2 re-fit (capacity, weights, ranking loss,
blends, seeds); training on dailyRank; 2025 rows for the /try band; typed concerns; concerns merge; re-rank of positions 4-15 by activity;
velocity after reveal (fails leave-one-day-out); hidden rank + arm-2 prior blend (fails leave-one-day-out); momentum and tie-breaks at
03:45; monthly/weekly vote-growth model (votes at close are enough); launch images (tested Oct 29-31; no bytes held).
Adopted: arm 2 at 00:05; why-file drivers from the deployed model (SHAP groups, fidelity 45%); calibrated day confidence and per-launch
probabilities (shadow / optional card); /try band recalibrated to 80.5% coverage; simulator nightly forward record; track record file.
Open:
- More history: 2024 and 2023 day lists (expected ~+2 top 3 per the learning curve); with the Cursor fleet, prepared VM fallback.
- Days for the morning lines: pre-reveal blends need ~13-25 scored days, velocity ~30; recorder reads at 03:45 and 23:50 PT (bundle 12a).
- Commenter count read at 00:03 PT (+2 at 00:05, interval touching 0) and 00:27 PT (the 00:30 input).
- Forward shadows to read: held-team (no fleet capacity for it), visible makers at 00:05 (~60 days), hr_clean_arm2, slots 6-10 by prior only.
- Weekly / monthly: running vote order is the forecast; first live weekly score Mon Nov 16; calibrated stay-probabilities in progress.
- Ceiling: a 00:05 forecast tops out around 63-75 top 3; 90 first looks reachable 05:00-10:00 PT (plain votes 88 at 05:00, 92 at 10:00).
Infrastructure waiting on Shreyas: PH API token for the Cursor fleet; bundles 10 / 11 / 12 / 12a; website hosting steps (#149).
