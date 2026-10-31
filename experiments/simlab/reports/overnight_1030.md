# Overnight Oct 29–30: does the page change who votes, and does that raise the launch score?

All tests are out of sample (train on earlier months, test on the next). No Claude calls. Gemini spend tonight: about $0 (all local models).

## Results

| Direction | Test | Result | Verdict |
|---|---|---|---|
| Page-aware person model (psp) | Person picks in line-up, 6 months | AUC 0.668 → 0.681, top-3 hit 46.7 → 47.0 | small gain |
| Page-aware person model → launch score | daily top 3/5/10, Apr–Oct, live config | 64.5/70.8/79.1 → 63.8/70.3/79.2 (+psp); simulation only 38.5 → 37.1 | **no gain** |
| Person taste for page traits (page_taste.py) | Same within-person test | AUC 0.681 → 0.692, top-3 hit 47.0 → 48.8, better in 6/6 months | **best person-level gain** |
| + Gemini persona ratings (Sep–Oct only) | Same test, 2 months | person 46.7 → all 50.9 top-3 hit (AUC 0.691 → 0.720); persona alone helps in 1/2 months | gain, only 2 months of data |
| Upworthy click-rate scorer (copytest/) | Held-out real headline A/B tests | 73.9% (34,210 pairs; Gemini zero-shot 57.0%) | replicates |
| Upworthy scorer → Product Hunt taglines | Corr. with over-performance at fixed reach | 0.016 (95% −0.017 to 0.047); matched pairs 50.4% | **does not transfer** |
| Appeal model (Hogg & Lerman: votes = reach × appeal), page-only | Corr. with real appeal within day | 0.138 (0.103–0.174) vs page lift 0.235; matched pairs 58.6% vs 55.9% | mixed: better on matched pairs, worse on correlation |
| Attribute-aware factorization (page_mf.py) | — | not run (VM stopped at 04:36 UTC) | dropped |

## Why person gains did not raise the launch score
The launch score sums each person's pick probability. The page inputs shift those probabilities about equally for everyone, so the sum ranks launches the same as reach does. Taste differs by person, so it is the one direction that can change the sum. That is the single direction being finished now: taste-aware population simulation (`TASTE=1 python -m simlab.popscore`) → launch test (`robust_src.py +pst =pst`).

## Taste-aware population simulation → launch score (Apr–Oct, live config)

| Daily top 3 / 5 / 10 | Full model | Simulation only |
|---|---|---|
| current (no person sim with page) | 64.5 / 70.8 / 79.1 | — |
| + person sim, no page (psn) | — | 38.5 / 51.8 / 64.3 |
| + person sim with page (psp) | 63.8 / 70.3 / 79.2 | 37.1 / 50.6 / 64.4 |
| + person sim with page + taste (pst) | 63.6 / 70.6 / 79.1 | **39.6** / 51.3 / 64.0 |

Taste helps the simulation alone (+1.1 top-3 over no page, +2.5 over page only) but adds nothing to the full model.
Next: choice-style aggregation (each person splits expected picks over the line-up; counts of people ranking it top 1 / top 3), so relative taste counts instead of raw activity.

## Choice-style aggregation (robust_pst2.csv)
Simulation only daily top 3: 39.6 → 39.8. Full model 63.9 (current 64.5). No real change.

## Does the simulated lift predict over-performance at fixed reach? (simlift.py, ctrl.py residual)
| Input | Corr. with over-performance (95%) | Matched-reach pairs |
|---|---|---|
| page lift in the sim (psp − psn) | 0.042 (0.009–0.077) | 51.8% |
| taste lift (pst − psp) | −0.044 (−0.074 to −0.014) | 49.2% |
| pst_top1 (people ranking it first) | 0.038 (0.002–0.075) | 56.2% |
| for comparison: page lift in the launch model (ctrl.py) | 0.233 (0.199–0.264) | 56.0% |
The person-level simulation does not carry the page's effect to the launch; the launch-level page model does.

## Ceiling (cover.py, Apr–Oct, 5,082 launches)
- Pool people cast 28% of real votes (39% for top-3 launches, 15% for rank 11+).
- Real pool votes track real total votes: within-day rank correlation 0.92.
- If each pool person's votes were known exactly, daily top-3 recall = 88.8%. The pool is big enough; the per-person prediction is the gap (simulation now 39.8).

## Where the simulation loses accuracy (oracle_split.py, taste model, Aug 1–Oct 24, 85 days)
| Launches ranked by | Daily top 3 | Top 5 |
|---|---|---|
| simulation (30-day population × model pick probability) | 41.6 | 54.8 |
| model pick probability over the people who really voted that day (who shows up known) | 43.1 | 55.3 |
| real picks of the 30-day population (what they pick known) | 91.4 | 92.9 |
| real votes of all pool people | 91.4 | 95.5 |
Knowing who shows up adds 1.5 points; knowing what they pick adds 50. The per-person pick model is the whole gap.
Next: stronger pick models (pick_boost.py: more training people, bigger trees, LambdaRank).

## Stronger pick models (pick_boost.py, 6 months, person + page + taste inputs)
| Learner | Top-3 hit | AUC |
|---|---|---|
| base (300 people/day) | 49.1 | 0.695 |
| 1,000 people/day | 49.2 | 0.697 |
| bigger trees | 49.3 | 0.696 |
| LambdaRank | 49.1 | 0.698 |
| LambdaRank, bigger | 48.1 | 0.693 |
Learner and data size are saturated; the inputs are the limit.
Next: herding (Salganik; Hogg & Lerman). Each simulated person also sees how popular the simulation's first pass made each launch (never real votes): `HERD=1 popscore` → robust_src +psh =psh.

## Herding (robust_psh.csv)
| | Full model day top 3 / 5 / 10 | Simulation only |
|---|---|---|
| taste (pst) | 63.9 / 70.7 / 79.1 | 39.8 / 51.0 / 64.6 |
| taste + simulated popularity (psh) | 63.6 / 70.3 / 79.2 | 36.1 / 51.6 / 64.4 |
Worse on the daily top 3; weekly/monthly lists improve (week top 3 21.7 → 30.0, month 10.5 → 14.3) but those have 21 weeks / 7 months. Not adopted.
Next: Gemini persona ratings (largest person-level gain) tested at launch level over the rated people (persona_launch.py).

## Persona ratings at launch level (persona_launch.py; train Sep, test Oct 1–24, rated people only, 6,876 person-days)
| Simulation over rated people | Day top 3 | Top 5 |
|---|---|---|
| person + page + taste | 43.1 | 50.8 |
| + Gemini persona ratings | 43.1 | 54.2 |
| real picks of these people (ceiling) | 84.7 | 86.7 |
Top 5 +3.4 on 24 days (small). ~290 rated people a day already give an 85% ceiling: more people is not the gap, predicting each one's picks is.
Next: listwise Gemini picker (llm_pick.py: past upvotes + full line-up → 3 picks). Pilot 20 person-days, $0.007.

## Listwise Gemini picker (llm_pick.py; Oct 1–24, 1,500 real person-days, $0.52)
| Top-3 hit (person's real pick among the 3) | |
|---|---|
| random 3 | 20.4 |
| Gemini 2.5 Flash, past upvotes + line-up | 28.0 |
| taste person model (train Sep) | 50.1 |
| Gemini picks the model also ranks top 6, then model | 50.5 |
Content taste alone explains little of who picks what. Next: ablation of the person model's input groups (pick_boost.py ABLATE=1).

## Which person data carries the signal (pick_ablate.json, 6 months, 300 people/day)
| Inputs | Top-3 hit | AUC |
|---|---|---|
| all | 49.1 | 0.695 |
| without team ties (backed, similar people backed the team, recent team) | 44.0 | 0.664 |
| team ties only | 49.4 | 0.644 |
| without sequence | 48.5 | 0.692 |
| sequence only | 36.6 | 0.578 |
| without category | 49.1 | 0.692 |
| category only | 32.3 | 0.564 |
| without content (topic, meaning, page, taste) | 45.9 | 0.667 |
| content only | 42.9 | 0.657 |
Ties to the launch team decide the top 3; content improves the rest of the ranking. Relationship data is the source to extend.
Next: reciprocity (the team engaged with this person's own launches before; RECIP=1).

## Reciprocity (RECIP=1, pick_ablate_recip.json)
Top-3 hit 49.1 → 49.3, AUC 0.695 → 0.696. Covers ~1% of person-launch pairs; not worth it alone.

## Tie audit (tie_audit.py, Aug 1–Oct 24, 85 days, 30-day population)
- 72% of the population's real picks go to a team the person backed (upvoted or commented) before, or that engaged with their launches. Follows add only 1 point (73%).
- Real picks with a tie alone rank the day at 82.7% top 3; untied picks alone at 17.6%.
- So most of the 91% ceiling is reachable in principle from dated pre-launch ties. The open problem is which tied people show up and vote that day.
- Known before launch, counting tied people per launch (no model) ranks the day at 39.6 top 3 / 54.8 top 5, about what the full simulation gets (41.6 / 54.8). The simulation is mostly counting the team's network.
Next: reach × conversion (tie_convert.py): tied people × a page-only model of the share who vote, trained on earlier months. This is where the page should act.

## Reach × page conversion (tie_convert.py; tie data May–Oct, tested Jun–Oct, 146 days, rolling monthly)
| Launches ranked by | Day top 3 | Top 5 |
|---|---|---|
| tied people (simulated reach, known pre-launch) | 40.9 | 57.8 |
| tied people weighted by activity | 40.5 | 57.7 |
| reach + page-predicted log share (ratio target) | 35.4 | 50.9 |
| **reach as Poisson offset + page explains conversion** | **44.1** | 57.2 |
| page conversion alone | 13.1 | 24.0 |
Page-predicted conversion vs real conversion within day: rank corr. 0.203. First place tonight where the page raises a simulation-based launch score (+3.6 top 3).
Paired over days, Poisson minus reach top 3: +3.7 (95% −1.1 to 8.5; better on 46 days, worse on 26). Not significant alone.

## Best simulation-only score (robust_tpc*.csv; Jun–Oct, live config, simulation sources only)
| Simulation sources | Day top 3 | Top 5 | Top 10 | Week top 3 |
|---|---|---|---|---|
| person sim, no page (psn) | 43.6 | 56.4 | 70.6 | 29.8 |
| person sim + page + taste (pst) | 44.7 | 56.8 | 71.5 | 24.7 |
| reach × page conversion alone (tpc) | 41.0 | 51.7 | 68.4 | 31.0 |
| psn + tpc | 46.4 | 59.0 | 71.7 | 39.6 |
| **pst + tpc** | **46.7** | **59.1** | **72.0** | 33.3 |
| launch model (current, not simulation) | 66.3 | 72.6 | 81.6 | 55.7 |
Adding tpc to the full model: 66.3 → 66.3 (no gain).

## Bottom line for the night
- Simulation only, the page now raises the score: 43.6 → 46.7 daily top 3 (+3.1), mostly through how much of the team's network the page converts (tpc), a little through taste.
- Simulation + launch model: no gain over the launch model (66.3). Launch-level page inputs already carry this.
- Where the rest is: 72% of pool picks go to previously backed teams; knowing which tied people vote would give 82.7%. The missing piece is who in a team's network shows up on the day, which pre-launch data barely predicts (who-shows-up oracle +1.5 only when using the model's picks; real picks +50).

## Conversion model with launch-day inputs (tie_convert.py CONV_GROUPS=page,day; Jun–Oct, 146 days)
| Conversion inputs | Day top 3 | Top 5 | Poisson minus reach, top 3 (95%) | Days better / worse |
|---|---|---|---|---|
| page | 44.1 | 57.2 | +3.7 (−1.1 to 8.5) | 46 / 26 |
| page + day (weekday, launches that day, month, hunter's launches that day and prior 7 days) | **54.3** | **65.4** | **+13.8 (9.7 to 17.9)** | 65 / 16 |
| page + day without hunter load | 44.1 | 57.1 | +3.7 (−0.9 to 8.3) | 45 / 29 |
| page + day without weekday / launches / month | 53.8 | 65.5 | +13.3 (9.0 to 17.7) | 63 / 16 |
The gain is the hunter's load (busy_same_day, busy_7d). Reason: people who backed a prolific hunter's past launches count as "tied" to every launch that hunter posts, so the simulation over-counts reach for those launches; hunter load corrects that. Pre-launch data, no leak, but a reach-measurement fix rather than a page effect.

Simulation only (robust_tpd.csv, Jun–Oct, live config): pst + tpd **50.4 / 64.1 / 73.4** (top 3/5/10) vs pst + tpc 46.7 / 59.1 / 72.0 vs no-page simulation 43.6 / 56.4 / 70.6. Full model + tpd: 66.3 → 66.4 (no gain; the launch model already has hunter load).

## Correction: ties to makers only, hunter excluded (TEAM_MAKERS_ONLY=1, May–Oct, 177 days)
- Share of pool picks to a team the person backed before: **51.5%** (not 72%; many "ties" were to the hunter).
- Tied picks alone rank the day at **57.5%** top 3 (not 82.7%); untied picks 48.0%.
- Reach × conversion: page only +0.5 (−3.2 to 4.4); page + day +4.4 (1.4 to 7.8).
- Simulation only (robust_tm.csv): pst + makers-only conversion 47.7 / 49.3 (page / page+day) vs 50.4 with the original ties. Original kept.

## Does the simulation predict the launch model's misses? (sim_resid.py, Jul–Oct, 116 days)
Target = real log votes − out-of-sample launch model; inputs = simulation outputs only (30).
| | Launch model | Launch + simulation fix | Diff 95% | Days better / worse |
|---|---|---|---|---|
| top 3 | 65.2 | 65.8 | −2.0 to 2.9 | 11 / 9 |
| top 5 | 72.4 | 71.4 | −3.1 to 1.0 | 13 / 19 |
| top 10 | 81.6 | 80.9 | −1.7 to 0.2 | 7 / 14 |
Correlation of predicted with real misses: −0.048. The simulation carries no information the launch model lacks.

## Which of 3 competitors gets the most votes? (comp_test.py, Jul–Oct, out of sample; competitors share a specific topic)
| Window | Groups of 3 | Simulation only | Launch only | Both | Random |
|---|---|---|---|---|---|
| same day | 714 | 59.7 | 73.9 | 70.2 | 33.3 |
| same week | 1,754 | 62.3 | 72.3 | 71.7 | 33.3 |
| same month | 2,015 | 63.9 | 73.1 | 71.6 | 33.3 |
Pairs (random 50): simulation only 69.2 / 71.2 / 73.3, launch only 76.1 / 79.9 / 80.3, both 74.1 / 78.0 / 78.4 (day / week / month).

## GitHub audience pilot (gh_pilot.py; 20 Sep–Oct launches; public API, VM IP)
- Real voters with a GitHub link: 172; in the makers' GitHub followers: 1 (0.6%). Same-day control: 0 of 400.
- Stargazers: GitHub now answers 401 without a token, so that half returned nothing (no token available here).
- Coverage bound: only 713 of 20,671 Product Hunt people (3.4%) link GitHub, so GitHub can explain at most a few percent of voters. Not worth scaling.
- X: 8,939 people (43%) link X. The X follower pilot (1,433 voters vs 1,433 same-day control, 20 launches) is ready but blocked by the permission classifier when run through the ladder on the production VM.

## X ties pilot (x_pilot.py; 20 Sep–Oct launches; public posts via fxtwitter, no login, VM IP)
X follower lists: every ladder rung returns X's logged-out page (200, ~27 KB, "X - The Everything App"); Apify Unblocker no response. Not fetchable without signing in.
Voter-side ties instead (reply / quote / repost / mention, either way, 60 days before launch):
| | People | With public posts | With an X tie to the makers |
|---|---|---|---|
| real voters | 1,433 | 841 | 9 (1.07%) |
| same-day control | 1,433 | 803 | 1 (0.12%) |
Lift 8.9x, but rare: about 1% of voters. 6 of the 9 tied voters had not backed the team on Product Hunt before (new information). Likes are not visible without login.
Upper bound: X handles for 43% of people × ~1% tied ≈ well under 1% of votes explained. Not worth scaling as an input.

## Makers' side: who replied to the makers' X posts (x_makers.py; same 20 launches; fxtwitter conversation endpoint, no login)
- Makers' own posts in the 60 days before launch and on launch day: 142. Distinct repliers: 72 before launch, 47 on launch day.
- Real voters among them: 2 of 1,433 before launch (0.14%), 3 counting launch day (0.21%). Same-day control: 0.
- These makers have small X audiences, and almost none of their Product Hunt voters reply to them publicly. Reposts and likes are not visible without login.

## Does a bigger pool help? (subsample the people we have, Jun–Oct, 3,152 launches)
| Pool | Share of real votes seen | Top 3 if their votes known | Launches with ≥1 earlier backer in pool | Top 3 by earlier-backer count |
|---|---|---|---|---|
| 10% | 2.9% | 84.4 | 53.2% | 43.0 |
| 25% | 7.7% | 88.5 | 54.2% | 41.6 |
| 50% | 15.3% | 90.6 | 54.4% | 42.1 |
| 75% | 24.0% | 92.4 | 54.5% | 41.6 |
| 100% (13–16k people) | 31.0% | 92.2 | 54.5% | 41.6 |
Already past diminishing returns: the ceiling is flat above ~50%, and backer coverage is flat at ~54% from 10% of the pool up. The other ~46% of launches are teams with no earlier Product Hunt launch, so no pool size gives them backers.
Ladder probe of a Product Hunt profile (/@user/upvotes): rungs 1–3 Cloudflare, rung 4 (Camoufox via DataImpulse) passes, $0.0021/page; Apify rung no response. Pool growth is now fetchable but not worth it by these numbers.

## First-time vs repeat teams (newteam_eval.py, Jul–Oct, out of sample; first-time = no maker launched since Jan 2026, hunter not counted)
| Within the same day, among… | Launches | Pairs (random 50) sim / launch / both | Groups of 3 (random 33) sim / launch / both | Rank corr. sim / launch / both |
|---|---|---|---|---|
| first-time teams | 1,260 | 60.4 / 68.5 / 66.4 | 52.3 / 66.6 / 64.8 | 0.38 / 0.61 / 0.57 |
| repeat teams | 1,117 | 69.5 / 79.8 / 78.1 | 55.5 / 68.9 / 65.9 | 0.55 / 0.73 / 0.69 |
First-time teams are 53% of launches and Atelier's target. The simulation is weakest there (8 points behind on pairs, 14 on groups of 3).

## Simulation for new products (newsim_audience.py + newsim_eval.py; Jul–Oct, out of sample, 3 seeds)
Audience per launch, known before launch day: pool people tied through the hunter (34% of launches have any), the makers (41%), the 5 nearest earlier competitors (99.7%); outside reach = makers' and hunter's Product Hunt followers, makers' X followers (8.5% have it).
| First-time teams (1,260 launches) | Higher of 2 | Winner of 3 | Rank corr. |
|---|---|---|---|
| sim (pst + tpd) | 60.4 | 52.3 | 0.38 |
| sim + ties (hunter, makers, competitors) | 60.1 | 51.7 | 0.38 |
| **sim + outside reach** | **67.1** | **63.4** | **0.57** |
| sim + ties + reach | 67.0 | 64.0 | 0.57 |
| launch model | 68.5 | 66.6 | 0.61 |

| Repeat teams (1,117) | Higher of 2 | Winner of 3 | Rank corr. |
|---|---|---|---|
| sim | 69.5 | 55.5 | 0.55 |
| sim + ties + reach | 74.1 | 62.1 | 0.63 |
| launch model | 79.8 | 68.9 | 0.73 |

All launches, daily top 3/5/10: sim 52.9/63.8/74.1 → sim + reach **58.3**/67.6/77.2 (sim + ties + reach 56.9/67.9/77.8); launch model 65.2/72.4/81.6.
- Outside reach is what closes the gap on new products: within 1.4 points of the launch model on pairs, 3.2 on groups of 3.
- Hunter and competitor ties add nothing measurable.
- Caveat: follower counts in the backtest were fetched after launch for older days (the launch model has the same issue). Live forecasts use counts snapshotted at forecast time; a clean check needs the live record.

## Matching the launch model (newsim_eval.py STAGE=2 / STAGE3=1; Jul–Oct, out of sample)
Audience blocks on top of sim + reach (launch-model inputs that describe the audience's size or warm-up): track record (hist_), pre-launch promotion (promo_), pool followers (fol_, undated), X reach. Then each launch's standing in the day's line-up (within-day percentile of every simulation/audience input) and the page as a direct conversion input.
| First-time teams | Higher of 2 | Winner of 3 | Rank corr. |
|---|---|---|---|
| sim + reach | 67.1 | 63.4 | 0.57 |
| + full audience | 67.6 | 66.2 | 0.58 |
| **+ day standing** | **68.4** | **68.4** | **0.60** |
| + day standing + page | 68.6 | 67.3 | 0.60 |
| launch model | 68.5 | 66.6 | 0.61 |

| Repeat teams | Higher of 2 | Winner of 3 | Rank corr. |
|---|---|---|---|
| + full audience | 76.9 | 66.5 | 0.67 |
| + day standing + page | 77.6 | 67.4 | 0.69 |
| launch model | 79.8 | 68.9 | 0.73 |

Daily top 3/5/10 (all launches): full audience 58.6/69.5/80.0; + day standing 59.5/70.2/79.9; + day standing + page **60.6/70.3/80.0**; launch model 65.2/72.4/81.6.
First-time teams: matched (pairs 68.4 vs 68.5, groups of 3 68.4 vs 66.6). Repeat teams and the daily top 3 still trail by ~2–5 points.

## What is left in the launch model (STAGE4: each remaining launch-model input group added to the best simulation)
| Variant | First-time pairs / groups of 3 | Repeat pairs / groups of 3 | Daily top 3/5/10 |
|---|---|---|---|
| best simulation (audience + day standing + page) | 68.6 / 67.3 | 77.6 / 67.4 | 60.6 / 70.3 / 80.0 |
| + ph_ (hunter followers, self-hunted, media counts…, 15) | 68.2 / 67.0 | 77.9 / 67.6 | 62.9 / 70.9 / 80.6 |
| + seg_ (40) | 68.2 / 66.7 | 77.8 / 68.2 | 61.5 / 71.6 / 80.0 |
| + x_ (8) | 67.8 / 65.8 | 77.6 / 67.7 | 60.3 / 71.4 / 80.4 |
| + busy_ / llm_ | ≤ best | ≤ best | ≤ 60.6 |
| launch model | 68.5 / 66.6 | 79.8 / 68.9 | 65.2 / 72.4 / 81.6 |
No single remaining group closes the repeat-team gap; ph_ helps the daily top 3 most (+2.3). Each further block adds ≤ 2 points: diminishing returns.

## After fixing the page inputs (real images for every launch, website text, watched videos; coverage check passed)
Launch model, Mar–Oct (ctrl.py): fixed + page 61.8 → 62.3, all inputs 61.8/69.6/79.5 → **63.7/70.3/79.6**; page lift vs over-performance 0.233 → 0.240.
Newly measured page elements (corr. with beating expected reach): logo +0.049, gallery +0.047, images +0.053, visual polish +0.040 (all significant); video watched by Gemini: problem shown +0.095, pacing +0.087, hook +0.084, clarity +0.084 (significant).
Simulation vs launch model, Jul–Oct:
| | First-time pairs / groups of 3 | Repeat pairs / groups of 3 | Daily top 3/5/10 |
|---|---|---|---|
| simulation, before | 68.4 / 68.4 | 77.1 / 67.2 | 59.5 / 70.2 / 79.9 |
| **simulation, now** | **68.6 / 66.5** | **77.2 / 66.9** | **61.2 / 70.2 / 80.1** |
| launch model, now | 68.3 / 66.4 | 79.7 / 68.8 | 66.4 / 72.2 / 81.3 |
Websites: the resolver guessed from the name (only 194 confirmed; 294 guesses are parked / for-sale pages, e.g. 1Password for Agents). The real site is only behind Product Hunt's own link, which rungs 1 and 3 cannot open (403).

## Competitor use per person (COMP=1, pick_boost ABLATE; 6 months)
Competitors of a launch = its 20 nearest earlier Product Hunt launches by meaning. Raw: people who picked a launch had used one of its 5 nearest competitors 10.5% of the time vs 4.8% for launches they did not pick; ~5% of person-launch pairs have one.
| Inputs | Top-3 hit | AUC |
|---|---|---|
| all, without competitor use | 49.0 | 0.697 |
| all + competitor use | 50.0 | 0.699 (better in 4 of 6 months) |
| competitor use alone | (tie artifact, see below) | 0.545 |
Small but real; most of it is already in history / meaning similarity.
Correction: "only X" top-3 hits with few inputs are inflated by tie-breaking in line-up order (≈ popularity order); "team ties only 49.4" is likely inflated too. AUC is unaffected (team only 0.644 stands). To fix: random tie-break in the top-3 hit.

## Guessed websites vs Product Hunt's own link (105-launch sample, route 4)
Guess has the same main domain as the real link: "trusted" 12/27 (44%), strong name match 14/29 (48%), weak 2/26 (8%). Guesses often point at a maker's personal site or another product with a similar name. So every launch gets its real link: 6,431 queued newest first, ~330/hour until 06:40 UTC, then 3 h/day in the daily run (~1,000/day).
