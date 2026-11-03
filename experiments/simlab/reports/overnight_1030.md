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

## Competitor comparison (cmp_features.py: each page / video score minus the mean of the 5 nearest earlier competitors, launched ≥2 days before; competitors' votes)
Each gap vs beating expected reach (cmp_eff.py, Mar–Oct, within-day corr., 95%):
- video better than competitors: production +0.088, problem shown +0.081, hook +0.073, pacing +0.063, clarity +0.061, call to action +0.055, length fit +0.050, wow +0.048 (all significant)
- page better than competitors: audience breadth +0.055, website +0.044, Gemini top-5 chance +0.042, wow +0.039 (significant); other elements not
- competitors' own votes: no effect (−0.008)
Added to the simulation (Jul–Oct): all 78 inputs 60.9 → 60.6 daily top 3 (first-time groups of 3 65.4 → 64.8); fixed small groups chosen in advance: video gaps 61.2, summary 60.9, both 62.4 (first-time groups of 3 64.3). No consistent gain: the gaps are real but small and mostly overlap the page scores already in.
Launch model with competitor gaps as page inputs (ctrl.py CMP=1, Mar–Oct, 5 seeds): fixed + page 62.3/69.0/78.4 → 62.2/69.7/78.6; all 63.7/70.3/79.6 → 62.3/70.9/79.7; page lift corr. 0.240 → 0.236. No gain. Kept without (ctrl.json); with is results/ctrl_cmp.json.
Verdict: comparison with competitors has validity input by input (video gaps up to +0.088) and is useful to show a maker, but it does not add to either score; it overlaps the page scores already in. Competitor use per person (who already used a competitor) adds +1 point top-3 hit at person level.

## Raising the launch score: ranking objective (rank_launch.py, Mar–Oct, 239 days, 5 seeds, same inputs)
regression 63.7/70.3/79.6; LambdaRank within day 64.3/70.5/79.0; average 64.0/70.8/79.5. Within noise.
Where 90% would come from: knowing the pool's real picks gives 92% (pool-size curve), but pre-launch inputs explain only part of them; the rest follows the makers' private outreach (DMs, email, communities), which no public pre-launch source shows.

## Model-settings sweep (rank_launch.py GRID=1, Mar–Oct, 239 days, 5 seeds, real websites)
Daily top 3/5/10, regression / LambdaRank: base 62.3/70.7/79.2 / 63.3/70.1/78.6; deeper 63.2/70.3/79.2 / 63.7/70.1/78.5; shallow + more trees 62.2/70.2/79.7 / 63.2/70.6/78.4; fewer inputs per tree 63.6/70.5/79.5 / **64.4**/70.0/78.6; regularised 62.8/69.9/79.5 / 63.6/70.6/78.5. All within ~2 points: settings are not the limit.

## Presence and vector twins (Oct 31, plan_presence_experiment.md steps 1–3)
Inputs (`simlab/presence.py`, `PRESENCE=1 TWIN=1`):
- **Presence:** share of a person's comments in 00–02 / 00–06 / 18–24 PT, from 102,128 timed comments by 20,683
  people. 4,593 people have 5 or more comments; everyone else is unknown.
- **Twin:** recency-weighted (half-life 60 days) mean embedding of the person's past picks. Its cosine to the launch
  correlates 0.61 with the existing `meaning` input.
- Both use data before the day only. The coverage gate passed.

**Per person** (`pick_boost` ABLATE, Apr–Oct, 7 months):

| | Top-3 hit | AUC |
|---|---|---|
| Base with both | 48.6 | 0.694 |
| Without presence | 48.9 | 0.696 |
| Without twins | 49.7 | 0.698 |
| Before this experiment (no presence, no twins) | 49.0 | 0.697 |

"Only presence" shows 65.9 at AUC 0.50: the tie-break artifact. Presence is one number per person, so it cannot
reorder that person's line-up.

**Launch level** (`newsim_eval` STAGE=2 STAGE3=1, Jul–Oct, same VM, `SIM_SRC=pst` vs `psq`), daily top 3/5/10:

| | Current simulation (pst) | + presence + twins (psq) |
|---|---|---|
| sim + reach + audience | 60.3 / 69.1 / 80.7 | 60.3 / 70.0 / 80.1 |
| + day standing | 61.2 / 70.2 / 80.1 | 59.5 / 70.3 / 80.5 |
| + page | 60.1 / 70.2 / 80.7 | 62.4 / 70.2 / 80.5 |
| + day standing + page | 60.3 / 70.9 / 79.7 | 61.5 / 70.2 / 80.0 |
| Launch model | 65.8 / 72.9 / 80.8 | — |

Every change is within ±2.3 points, under the ±3.5 noise on daily top 3. First-time teams, winner of 3: 64.5 → 66.2
(sim + reach + audience), also noise.

**Verdict:** neither input adds signal on Product Hunt's pre-launch data. Presence can only matter when it is matched
against when a launch's votes arrive. That needs the hourly snapshots, and it is a launch-day forecast (step 4,
about Nov 14), not a pre-launch one. Twins repeat the existing taste inputs.

## Relationship vs taste split of the person model (`rel_split.py`, Jul–Oct, 72,554 active person-days, 126,674 picks)
| Pick label | Share of picks | Model has it in the person's top 3 |
|---|---|---|
| Tied (dated: backed the team before, or the team engaged with the person) | 63.4% | 44.1% |
| Follows a team member on PH (undated) | 6.7% | 18.0% |
| Untied | 29.9% | 9.9% |

- **Person-day top-3 hit:** 47.7. Ranking dated-tie launches first gives 47.8. Ranking every known relationship first
  gives 52.2.
- **Why ranking ties first doesn't help:** a line-up holds a median of 9 tied launches out of about 30 (80% of
  person-days have 4 or more). "Team" includes the hunter, and prolific hunters tie a person to many launches. The
  model knows the ties but not which one the person acts on that day.
- **By person-day:**

  | Person-day picks | Share of person-days | Top-3 hit |
  |---|---|---|
  | All tied/follow | 64% | 53.0 |
  | Mixed | 16% | 66.4 |
  | All untied | 20% | 16.5 |

- **"Acts on relationships" is a stable trait:** Jul–Aug vs Sep–Oct correlation 0.51 (1,038 people with 5+ picks in
  each half).
- **Trait vs later accuracy:** quartiles of the Jul–Aug trait sort Sep–Oct top-3 hit from 45.2 to 52.4, and the share
  of untied picks from 35% to 20%.

**Verdict:** the gap has two parts.
1. **Tie strength, about 35 points of the missing hit on tied picks:** which of about 9 ties the person acts on. This
   is solvable with data we already have.
2. **Untied picks, 30% of picks at 9.9%:** taste or outreach we can't see. This is where X data would add.

## Tie strength (Nov 1, `popscore.py` TIE=1)
- **Inputs:** the line-up already showed which launches a person is tied to (a median of 9 per day). These inputs say
  which tie is strong: ties to the makers and ties to the hunter counted separately, comments on the makers' launches,
  how many of the makers the person backed, days since the last engagement, share of the person's history, both-way
  ties, and the tie's standing in the person's line-up. On one day, the hunter tie alone had AUC 0.65 vs 0.59 for the
  maker tie.
- **Per person** (`pick_boost` ABLATE, TIE=1 RECIP=1): top-3 hit **54.2 vs 50.4 without tie strength** (AUC 0.718 vs
  0.701). It is better in all 6 months tested (+3.0 to +4.8). The previous best person model was 49.0 / 0.697. This is
  the first clear person-level gain.
- **Launch level** (Jul–Oct, `SIM_SRC=psr`): daily top 3/5/10 rose in all four setups. The best setup (+ day standing
  + page) went from 60.3 / 70.9 / 79.7 to **62.6 / 71.2 / 79.7**. Paired bootstrap over 116 days:

  | | Change | 95% CI |
  |---|---|---|
  | Top 3 | +2.3 | −0.3 to +4.9 |
  | Top 5 | +0.3 | −1.2 to +2.1 |
  | Top 10 | −0.1 | −1.0 to +0.8 |

  Borderline on top 3, none on top 5 or 10.
- **+ competitor gaps on top:** 61.5–62.4 top 3, so they add nothing beyond tie strength.
- **First-time teams, higher of 2 / winner of 3:** 68.8 / 66.4 (launch model 68.4 / 66.7).
- **New best simulation-only:** 62.6 / 71.2 / 79.7. The launch model is 65.8 / 72.9 / 80.8.

## PH ops agent, Nov 1 (session start, 18:20 UTC): blocked on GCP access
- This container has no GCP credentials (`gcloud auth list`: none), so the VMs, the bucket and the run check are out
  of reach. Reported to the orchestrator.
- **Nov 2 start, at risk:** DST ended Nov 1. `run_daily.sh` stops the recorder at 23:55 PST = **07:55 UTC**. If the
  instance schedule is still `usersim-daily-start` (07:05 UTC), the VM is still running at 07:05, the start does
  nothing, and Nov 2 is skipped. It is safe only if `usersim-daily-start-pt` (00:05 America/Los_Angeles = 08:05 UTC)
  is attached (`docs/handoff/grokbot_ph_pipeline.md` item 1). Asked the orchestrator to have Grok Bot check this.
- **Agenda 1 (tie strength into the daily forecast), plan:** the daily forecast (`ph_predict/forecast.py`) is the
  launch model only; the simulation is backtest-only. To add it:
  1. `simlab/popscore.py`: make `MONTHS` and the `<= 2026-10-24` cut-off follow the run date, and add a one-day
     mode. It trains the current month's person model on the previous month and scores today's line-up with
     `TASTE=1 TIE=1 RECIP=1`, giving today's `psr_` rows.
  2. The store, embeddings and `harness.baseline()` must include today's launches (an incremental rebuild).
  3. `ph_predict/sim_forecast.py`: the newsim "+day standing+page" model, trained on every finished day's `psr` rows
     and predicting today. Written to `forecasts` as model `simulation`; `s_score` then scores both models.
  4. New step `simforecast` in `pipeline/daily.py`, off by default at first (not in `STEPS`), so it cannot break the
     run until it has passed one dry run on the VM.
  Data (store, `ph_predict/data`) lives only on the VMs, so nothing can be built or tested from here.

### Nov 1 run check (18:35 UTC, after GCP sign-in)
- Run started 15:17 UTC: all 9 steps `ok`; no Traceback, 407 or 403. 19 launches, forecast 20 rows.
- Instance schedule: `usersim-daily-start-pt` (00:05 PT). Recorder stops at 07:55 UTC, so the VM is off before 08:05 UTC.
- **Two recorders are running**, from the 14:07 and 15:17 starts, so from 16:00 UTC each hourly snapshot is written
  twice (38 rows for 19 launches). Left alone: stopping the older one would let its `run_daily.sh` shut the VM down
  now. Anything that reads `vote_snapshots` for Nov 1 must dedupe on (`launch_id`, `at`). The first snapshot is
  14:07 UTC (hour 7), so Nov 1 has no hours 0–6: not a clean day for the launch-day model.
- No Grok Bot leaderboard read for Nov 1 in `raw/`, so `list_check` was skipped.

### Nov 1 evening (PH ops agent)
- **Upvote feed down since Oct 30.** Every `upvotes_page1` fetch has been 403 (170 / 98 / 66 pages on Oct 30 / 31 /
  Nov 1), while the `people` step reported `ok` with 0 items. Warehouse upvotes end on Oct 29; comments are still
  current. Test on 3 pages: VM IP 403, DataImpulse 403, Camoufox via DataImpulse 200 but a 30 KB shell with 0 upvotes
  parsed. Per the ladder rule, nothing further was tried. Grok Bot's signed-in browser sees the pages, so its fetch of the
  300 most active people is filed (`raw/requests/upvote_refresh_priority.txt`). Loader: `pipeline.load_signed_in`.
- **Fail-loud steps** (not yet deployed): `launches`, `comments`, `people` and `sites` now report `failed` when they
  fetch nothing or most pages are blocked.
- **Leaderboard cross-check:** every API launch is in Grok Bot's "all" reads (Nov 1 19/19, Oct 31 22/22). The "all" tab
  can't be cut by rank, because one non-featured launch is inside the top 19 / 22. Asked for the featured tab
  (mailbox `20261101T1855_ph-agent_leaderboard-featured-flag`).
- **Product Hunt "Similar Products" vs reviewers' alternatives** (`comp_validate_ph.py`):
  - Preview, recent 300 launches, 16 answer-key products: 31.0% of real alternatives in the top 5 (95% CI 12.9–50.7);
    at least one in the top 5 for 50.0% (25.0–75.0).
  - Reference: Gemini naming 28.6 / 43.1 (281 products); meaning similarity 13.8 / 22.8.
  - 52.5% of list entries are someone's reviewed alternative, so the answer key may be partly circular.
  - Full run when all 6,668 lists land.

## Tie extensions, person level (Nov 1, `popscore.py` TIE2=1, `pick_boost` ABLATE, May–Oct)
- **New inputs, all dated before the day.** Makers and hunter are computed separately; makers listed on more than 30
  launches are treated like hunters.
  - Return rate: of the team's launches after the person first engaged with it, the share they engaged with again.
  - Number of such chances.
  - Team turnout: the share of earlier backers who come back to each next launch.
  - Team backer count.
  - Engagement with the makers' launches, weighted by recency (60-day half-weight scale, `exp(-age/60)`).
- **Per person:** top-3 hit **55.8 vs 54.0** without the extensions (AUC 0.728 vs 0.716). Better in **6 of 6 months**:
  +0.6, +0.7, +3.6, +1.8, +2.5, +1.4. Mean +1.8, 95% interval over months +0.6 to +2.9.
  - With tie strength removed as well: 49.9.
  - Before tie strength: 50.4.
- Launch-level run (`SIM_SRC=psx` vs `psr`, paired bootstrap) is in progress.
- **list_check on the featured reads (Nov 1, 19:15 UTC):**
  - Oct 31 (final): API 22, featured page 22, no launch missing or repeated.
  - Nov 1 (read at 11:15 PT): API 19, featured page 17, none missing from the API.
  - The 2 extra in the API are Fluent 2 and Hamdori, ranks 18 and 19 on the "all" tab, both `featuredAt` 07:01 UTC.
    The featured read probably stopped before the bottom of the list, or the page was still updating. To check
    against tonight's final read.
- **Upvotes restored (top 300, Nov 1, 20:05 UTC).** Grok Bot's team fetched page 1 (the 20 newest upvotes) through route 4,
  with a `post_id` on every row: `raw/ph_upvotes_full/upvotes_page1_top300.jsonl`, 298 of 300 people (2 still 403).
  - Check: 98.9% of page-1 items from launches on or before the person's newest known upvote were already in
    `events` (2,729 items).
  - Loaded 3,241 new upvotes (`pipeline.load_signed_in upvotes_page1_top300 --full`). Upvotes per day now: Oct 30 584,
    Oct 31 562, Nov 1 418.
  - Limit: page 1 does not reach back to Oct 29 for 34 of 298 heavy upvoters (`has_more`). The full pool (20,947) is
    being fetched.
  - The signed-in file (product slugs) stays unloaded: it matched only 143 of 3,765 rows exactly.
- **Full pool loaded (21:15 UTC).** `upvotes_page1_full.jsonl`: page 1 for 20,934 of 20,947 people (13 failed), 227,105
  rows.
  - Check: 99.9% of page-1 items from launches on or before each person's newest known upvote were already known
    (121,055 items).
  - 4,193 new upvotes, on top of the top 300's 3,241.
  - 102,012 items are launches from before our launch table starts (Jan 1, 2026).
  - Upvotes per day now: Oct 28 1,055, Oct 29 1,260, Oct 30 1,263, Oct 31 936, Nov 1 678. The usual level was about
    1,500–1,800 per day; page 1 covers only the 20 newest upvotes per person.

## Tie strength in the live (no-page) simulation: launch-level deltas (Nov 1)
Setup:
- `newsim_eval.py NOPAGE=1 STAGE=2 STAGE3=1`, "+day standing": simulation + outside reach + audience blocks + day
  standing, no page or text inputs. This is the configuration deployed in the daily pipeline (`sim_forecast.py`).
- Rolling monthly, May–Oct, 3 seeds.
- Paired bootstrap over days (`paired_boot.py`, 10,000 resamples).
- Simulation sources, all without page inputs: `psn` (no tie strength), `pnr` (tie strength), `pnx` (tie strength +
  extensions).

| Simulation-only, daily top 3 / 5 / 10 | Top 3 / 5 / 10 |
|---|---|
| psn (no tie strength) | 59.8 / 71.2 / 79.3 |
| pnr (+ tie strength) | 59.2 / 70.8 / 79.8 |
| pnx (+ tie strength + extensions) | 59.8 / 70.6 / 79.3 |
| Launch model, same launches | 65.5 / 73.9 / 81.2 |

| Paired, B − A | Top 3 (95% CI) | Top 5 | Top 10 |
|---|---|---|---|
| pnr − psn | −0.6 (−2.7 to +1.5) | −0.4 (−1.8 to +1.1) | +0.4 (−0.2 to +1.2) |
| pnx − psn | −0.0 (−2.1 to +2.1) | −0.6 (−1.9 to +0.7) | −0.0 (−0.7 to +0.7) |
| pnx − pnr | +0.6 (−1.5 to +2.7) | −0.2 (−1.6 to +1.2) | −0.4 (−1.1 to +0.2) |

- **First-time teams** (higher of 2 / winner of 3): psn 67.1 / 66.6, pnr 67.5 / 65.9, pnx 67.1 / 65.4. Launch model
  68.5 / 67.2.
- **Why nothing moves.** The simulation inputs differ across sources (`ev` correlation 0.81–0.86 per month). Yet from
  June on, the final predictions correlate 0.99+, and in Sep and Oct the top 3 are identical. Without page inputs, the
  launch-level model takes almost everything from the audience and reach inputs, and the person simulation adds little
  on top.
- **Verdict:**
  - Per person, tie strength and the extensions help: +1.8, better in 6 of 6 months.
  - At launch level in the live configuration, none of it shows (all intervals span 0).
  - In the page-aware configuration the earlier gain was +2.3 (−0.3 to +4.9). That is still borderline; the `psx`
    re-run is in progress.
  - The daily simulation forecast is deployed as a separately scored, tracked forecast. No accuracy gain over `psn`
    is expected from it.

## Does the person-level gain reach the pool's own votes? (`simlab/pool_check.py`, Apr–Oct, 207 days)
Setup:
- Per launch: the simulation's expected pool picks (`ev` = sum of weight × p over people active in the 30 days before;
  `fans` = the same over the 100 most likely).
- Compared with the real number of pool people who upvoted or commented on launch day.
- Within-day Spearman correlation, and the top-3 hit of "most pool votes". Paired bootstrap over days.
- No page inputs. Each month is scored by a model trained on the previous month.

| | Spearman (ev / fans) | Pool top-3 hit (ev / fans) |
|---|---|---|
| psn (no tie strength; files from Oct 28) | 0.450 / 0.462 | 42.7 / 43.0 |
| pnr (+ tie strength) | 0.478 / 0.488 | 46.1 / 46.5 |
| pnx (+ extensions) | 0.488 / 0.495 | 45.2 / 46.9 |

| Paired | Spearman, ev (95% CI) | Top-3 hit, fans (95% CI) |
|---|---|---|
| pnr − psn | +0.028 (+0.009 to +0.047) | +3.5 (+0.5 to +6.8) |
| pnx − psn | +0.038 (+0.017 to +0.062) | +3.9 (+0.6 to +7.1) |
| pnx − pnr | +0.010 (−0.008 to +0.028) | +0.3 (−2.7 to +3.4) |

- **Reading:** tie strength makes the simulation better at the pool's own votes: about +3.5 points on the pool top 3,
  with intervals excluding 0. The extensions add nothing beyond tie strength at this level. The gain disappears at
  launch level, where the launch-level model leans on audience and reach (most votes come from outside the pool).
- **Caveat:** the psn files date from Oct 28 (older code). A clean psn rebuild with today's code and data
  (`TAG_SUFFIX=v2 PREFIX=psn2_`) is running; the psn rows will be replaced when it finishes.

### Winner of 3 competitors, no-page sources (`comp_test.py NOPAGE=1 SIM_SRC=…`, May–Oct, 4,149 launches)
"Simulation only" here is the simulation's own launch score: no audience or reach inputs, unlike the newsim "+day
standing" model above.

| Winner of 3 (pair) | Same day (1,404 groups) | Same week (2,945) | Same month (3,351) |
|---|---|---|---|
| psn (no tie strength) | 52.4 (62.7) | 55.9 (67.3) | 54.9 (64.9) |
| pnr (+ tie strength) | 58.8 (67.5) | 58.4 (68.7) | 58.6 (68.3) |
| pnx (+ extensions) | 57.8 (67.3) | 59.4 (69.3) | 59.6 (70.1) |
| Launch model | 71.2 (77.7) | 72.9 (79.3) | 71.3 (78.8) |
| Launch model + pnx | 68.9 | 71.8 | 69.7 |

- **Tie strength vs none:** +6.4 / +2.5 / +3.7. As a rough guide, the interval for a difference is ±3.7 (day),
  ±2.5 (week) and ±2.4 (month). That treats groups as independent; they overlap, so the real intervals are wider.
  A day-clustered paired bootstrap is still to do.
- **Extensions vs tie strength:** −1.0 / +1.0 / +1.0, noise.
- **Reading:** on its own, the simulation picks competitor winners better with tie strength. Once audience inputs are
  added (newsim), the gain disappears, which matches the pool-level result.

## Nov 1, 23:55 UTC: full set — clean baseline, day-clustered winner of 3, degradation, page-aware extensions, panel
All runs are out of sample, with paired bootstraps over days and 95% intervals. Winner of 3 is now resampled by day
(`comp_boot.py`; groups matched exactly across sources).

**Corrections to earlier entries today.** psn is now rebuilt with today's code and data as `psn2`; the old psn files
were from Oct 28. With the clean baseline:
- Pool check: tie strength vs none, pool top-3 hit (fans) +2.7 (−0.3 to +6.0); the earlier "+3.5, excludes 0" was
  against the old psn. Spearman is still clearly better: +0.030 (+0.012 to +0.048).
- Winner of 3, no page, simulation only: the earlier "+6.4 / +2.5 / +3.7" was against the old psn and used an unpaired
  rough interval. The clean, day-clustered numbers are in the table below.

### Launch level, daily top 3 / 5 / 10 (simulation only unless marked)
| Configuration | Top 3 / 5 / 10 |
|---|---|
| No page, psn2 (no tie strength) | 60.3 / 71.3 / 79.4 |
| No page, pnr (+ tie) | 59.2 / 70.8 / 79.8 (top 3 vs psn2 −1.1, −3.4 to +1.1) |
| No page, pnx (+ tie + extensions; deployed) | 59.8 / 70.6 / 79.3 (top 3 vs psn2 −0.6, −2.7 to +1.5) |
| Page, pst | 60.3 / 70.9 / 79.7 |
| Page, psr (+ tie) | 62.6 / 71.2 / 79.7 |
| Page, psx (+ tie + extensions) | 61.5 / 70.5 / 80.2 (top 3 vs psr −1.1, −3.2 to +0.9; vs pst +1.1, −1.4 to +4.0) |
| Page, psr with the last 3 / 7 / 14 days of upvotes hidden | 62.6 / 62.6 / 61.8 on top 3 (vs psr +0.0 / −0.0 / −0.9; all CIs within ±3) |
| Panel (pool reweighted, no model on top) | 47.7 / 59.9 / 69.3 (May–Oct) |
| Launch model (Jul–Oct / May–Oct) | 65.8 / 72.9 / 80.8 / 65.5 / 73.9 / 81.2 |

**Best simulation vs launch model, same launches (paired):**
- psr: top 3 −3.2 (−7.5 to +0.9); top 5 −1.7 (−4.3 to +0.9); top 10 −1.1 (−2.4 to +0.2).
- psx: top 3 −4.3 (−8.9 to −0.0).
- pnx (no page): top 3 −5.7 (−9.4 to −1.9).

### Winner of 3, day-clustered (day / week / month)
| B − A | Day | Week | Month |
|---|---|---|---|
| No page: pnr − psn2 | +2.5 (−0.3 to +5.7) | +0.5 (−1.6 to +2.5) | +2.7 (+1.0 to +4.4) |
| No page: pnx − psn2 | +1.6 (−2.7 to +5.8) | +1.5 (−0.4 to +3.4) | +3.7 (+1.7 to +5.6) |
| No page: pnx − pnr | −0.9 (−5.0 to +2.7) | +1.0 (−1.0 to +3.1) | +1.0 (−0.8 to +2.8) |
| Page: psr − pst | +0.6 (−4.7 to +5.3) | +1.5 (−0.5 to +3.5) | +2.1 (+0.5 to +3.8) |
| Page: psx − psr | +1.3 (−3.2 to +5.3) | +0.6 (−0.9 to +2.1) | +1.7 (+0.0 to +3.4) |
| psx simulation − launch model | −9.7 (−15.4 to −4.8) | −8.7 (−11.0 to −6.3) | −7.7 (−9.8 to −5.5) |
| psx launch model + simulation − launch model | −0.4 (−3.5 to +3.0) | +0.3 (−1.0 to +1.7) | −2.0 (−3.5 to −0.5) |

Levels: psx simulation 62.7 / 63.6 / 65.4. Launch model 72.4 / 72.2 / 73.1.

### Panel reweighting (`panel.py`, pnr + SEG=1, 54 trait cells, NNLS weights fitted on earlier months)
- **Panel:** 47.7 / 59.9 / 69.3. That is below the raw pool sum (48.5 / 61.5 / 71.3; top 10 −2.0, −3.1 to −0.9) and
  far below the launch model (top 3 −17.8, −21.8 to −13.8).
- **Blend with the launch model:** worse than the launch model alone (top 3 −6.5, −10.0 to −3.1).
- **Winner of 3:** panel 58.7 / 57.7 / 59.7; launch model 71.1 / 70.6 / 73.8.
- **Weights:** only 8–11 of 54 cells get weight. The largest is low-activity, untied, non-maker people with 100+
  followers.
- **Reading:** the pool's simulated picks, rescaled by trait alone, cannot reproduce launch totals. The audience the
  launch model sees (makers' and hunter's followers, X, promotion) is not represented by any pool cell. A pure-panel
  forecast needs those outside audiences in the panel itself, not only pool reweighting.

### Verdict
- **No simulation variant beats the launch model** on daily top 3/5/10 or winner of 3.
- **Closest:** page-aware psr, top 3 −3.2 (−7.5 to +0.9); top 10 −1.1 (−2.4 to +0.2).
- **Launch model + simulation:** ties the launch model on winner of 3 (day −0.4, week +0.3) and is −2.0 on month.
- **Tie strength:**
  - Helps the simulation itself: person level +1.8 (6/6 months); pool Spearman +0.03; winner of 3 by month +2.7 to
    +3.7, intervals excluding 0.
  - Does not move launch-level daily top-k.
- **Hidden upvotes:** hiding up to 14 days costs nothing measurable at launch level. So the Oct 30–Nov 1 upvote outage
  did not hurt the forecasts.

## Product Hunt "Similar Products" vs reviewers' alternatives, full file (Nov 2, `comp_validate_ph.py`)
`raw/ph_alternatives/similar_products_all.jsonl`: 6,668 launches, 5,846 product lists.
| Competitor source | Real alternatives in top 5 | At least one in top 5 | Products |
|---|---|---|---|
| **Product Hunt Similar Products** | **45.8** (95% CI 39.4–52.2) | **68.7** (61.2–76.2) | 147 |
| Gemini naming (`comp_gemini.py`) | 28.6 | 43.1 | 281 |
| Gemini rerank of nearest by meaning | 18.2 | 29.2 | 281 |
| Meaning similarity | 13.8 | 22.8 | 281 |

- **Coverage:** the answer key covers 147 products with a Product Hunt list. Only 115 of the 281 used for the Gemini
  numbers have one, so the sets overlap but are not the same. A same-product comparison needs Gemini's per-product
  results, which were not saved.
- **Circularity:** 54.7% of Product Hunt's list entries are someone's reviewed alternative. Product Hunt may build these
  lists from reviewers' alternatives, which would make this answer key partly circular. The with-vs-without simulation
  test (competitor step 1, launch-time-safe lists only) is the test that counts.
- **Verdict:** validates as the strongest competitor source by this measure, with the circularity caveat. Next is
  merged lists in `cmp_features.py`, held until the direction review lands.

## Competitor grounding with Product Hunt's Similar Products: with vs without (Nov 2, at Shreyas's request)
**Lists** (`ph_comp_lists.py`):
- PH Similar Products mapped to our launches.
- A list is launch-time-safe when no listed product first launches in our data on or after the launch: 3,609 of 6,475
  launches.
- Only 38% of listed products ever launched in our data (from Jan 1). The rest are established products, so a safe
  list averages 1.3 competitor launches with known votes (meaning-based lists: 5).

**Person level** (`pick_boost` ABLATE, TASTE=1 TIE=1 COMP=1, May–Oct): "used a competitor" (any earlier launch of a
listed product), with vs without.

| Lists | Top-3 hit with / without | Δ (95% over months) | AUC Δ (95%) |
|---|---|---|---|
| Meaning (20 nearest) | 54.2 / 54.1 | +0.12 (−0.30 to +0.53), 3/6 months | +0.0017 (+0.0003 to +0.0030) |
| PH Similar Products | 54.3 / 54.1 | +0.18 (−0.57 to +0.93), 2/6 months | +0.0023 (+0.0006 to +0.0041) |
| PH − meaning, both with | +0.07 | | +0.0007 (4/6 months) |

- Competitor use alone (no other inputs): AUC 0.545 with meaning lists, 0.511 with PH lists. The PH lists are NaN for
  the 44% of launches without a safe list.
- On Oct 31, before tie strength, competitor use added +1.0 top-3 hit. With tie strength in the model it adds +0.1 to
  +0.2: most of it was the same people (team ties overlap with competitor users).

**Launch level** (newsim STAGE5 on psr, + competitor gaps; `pair_score.py`, Jul–Oct, day-clustered):

| Δ, sim + gaps − sim | Top 3 | Pairwise | Competitor pairs | Winner of 3, day / week / month |
|---|---|---|---|---|
| Meaning lists | −0.3 (−2.6 to +2.0) | −0.4 (−0.9 to +0.1) | +0.6 (−0.5 to +1.7) | +0.8 / −0.1 / +0.6 |
| Gemini lists | −0.6 (−3.2 to +2.0) | −0.1 (−0.5 to +0.2) | +0.3 (−0.8 to +1.6) | −1.1 / +0.5 / −0.2 |
| PH lists | +0.9 (−1.4 to +3.2) | −0.3 (−0.7 to +0.1) | +0.3 (−0.6 to +1.3) | −1.7 (−3.2 to −0.1) / +0.0 / +1.0 (+0.0 to +2.0) |

The "launch model + gaps" rows (−1 to −4) are not a clean test: they refit a small model on the launch prediction,
so they are not reported as an effect.

**Verdict:**
- Competitor grounding with the 3×-more-accurate PH lists does not raise predictive value at launch level on any
  metric.
- At person level it adds AUC +0.002 (interval excludes 0) and no top-3 hit.
- The limit is coverage: 62% of listed competitors never launched in our data, so neither their votes nor their
  audiences are visible.
- Next step for this north-star clause: use the PH lists to bring in those competitors' audiences (their PH followers
  and reviewers, who are real people with dated activity). Otherwise grounding stays limited to the 38% we can see.

## E0: where the simulation's error lives (Nov 2, `simlab/e0_shock.py`, pnr, Apr–Oct, 5,081 launches)
**1. Overdispersion.** Per launch, real pool voters R vs the simulation's expected pool picks S, log ratio with the
day's mean removed.
- Observed variance: 0.588.
- Expected if each person's error were independent (≈ Poisson around S): 0.056.
- So **90.5% of the error is a shock shared by a launch's whole audience**, not noise in individual people.
- The simulation ranks the pool's own votes at Spearman 0.478 within day.

**2. Early-sample oracle** (Jul–Oct, 20 random splits, day-clustered paired intervals).
- Setup: a random 10% of each launch's real pool voters is revealed, as a stand-in for early votes.
- Scale: the pool casts 35% of all votes, so this is about 3.5% of a launch's votes. A median launch has 26 pool
  voters, a top-3 launch 158.

| Predictor | Spearman, held-out pool votes | Daily top 3 / 5 / 10 (final rank) |
|---|---|---|
| Simulation only (no launch-day data) | 0.486 | 49.4 / 61.9 / 72.0 |
| 10% sample only | 0.745 | 83.0 / 86.0 / 81.8 |
| Simulation × shock from the sample (shrinkage a = 1, fitted Apr–Jun) | 0.747 | 83.3 / 86.0 / 82.0 |

- Shock-corrected − simulation: top 3 +33.9 (+29.8 to +37.9); top 5 +24.1 (+20.6 to +27.6); top 10 +10.0 (+8.0 to
  +12.2).
- Shock-corrected − sample: top 3 +0.3 (−0.2 to +0.7). Once a sample of real voters is known, the simulation adds
  nothing to the ranking.

**Reading:**
- The gap between the simulation and the real ranking is almost entirely a per-launch shock (makers' outreach,
  launch-day momentum).
- A small sample of who actually showed up reveals it: 3.5% of votes gives 83% daily top 3.
- Caveat: the oracle sample is random across the whole day. Real early votes are not random (they lean to the
  team's network) and come before the late surge, so this is an optimistic proxy for hour-1/2 votes.
- Implications:
  1. The launch-day forecast (direction A) is where the largest gain is, and the comment-trajectory backtest (E1 in
     the PH review) should run next with real early comments instead of a random sample.
  2. Pre-launch gains have to predict the shock itself (direction B: makers' outside audiences, promotion, team
     turnout as a launch-level input). Better person models of the pool cannot.
  3. For the generative vote model (orchestrator's E1), the shock term is the component to model first.

## North star (Shreyas, Nov 2): 90% top 3 / 5 / 10 on the daily, weekly or monthly leaderboard. Re-scored Nov 2 (`lists_score.py`, Jul–Oct)
| Leaderboard (lists) | Launch model | Best simulation (psr, + day standing + page) | Simulation, no page (pnx, deployed) |
|---|---|---|---|
| Daily (116 / 116 / 101) | **65.8 / 72.9 / 80.8** | 62.6 / 71.2 / 79.7 | 58.0 / 70.2 / 79.6 |
| Weekly (17 / 16 / 15) | 51.0 / 55.0 / 56.7 | 33.3 / 38.8 / 46.0 | 31.4 / 38.8 / 44.7 |
| Monthly (3 / 4 / 4) | 55.6 / 50.0 / 57.5 | 0.0 / 30.0 / 35.0 | 22.2 / 30.0 / 42.5 |

Simulation − launch model, top 3: daily −3.2 (−7.5 to +1.1); weekly −17.6 (−33.3 to −2.0); monthly −55.6 on 3 lists.
The simulation's best configuration uses within-day standing and per-day line-up inputs, which do not compare across
days, so it falls apart on weekly and monthly lists. Monthly has 3–4 test lists, so its numbers are anecdotal.

**Early signal across boards** (E0's random 10% of pool voters, ~3.5% of votes; 20 splits; optimistic proxy):

| | Daily | Weekly | Monthly |
|---|---|---|---|
| Launch model | 65.5 / 73.0 / 80.9 | 51.0 / 55.0 / 56.7 | 55.6 / 50.0 / 57.5 |
| 10% pool sample | 82.6 / 85.8 / 80.8 | 51.5 / 64.1 / 72.1 | 40.0 / 54.0 / 48.1 |
| Rank blend of both | 80.6 / 85.5 / 84.7 | 60.6 / 61.8 / 69.7 | 45.6 / 52.5 / 50.9 |

**Where we are against 90:**
- **Daily is closest:** the launch model is 24 / 17 / 9 points away pre-launch. With an early-vote signal the proxy
  reaches 80–86, about 4–10 points away.
- **Weekly gap:** cross-day calibration. A pool sample ranks within a day well but not across days, because pool size
  and day strength vary.
- **Monthly:** too few lists to steer by.
- **Next:** the daily launch-day forecast from real early comments (and from Nov 9, hourly votes), then cross-day
  calibration of vote totals for weekly.

## Launch-day forecast from real early comments (Nov 2, `launchday.py` + `lists_score.py`, May–Oct)
Setup:
- Prior: the pre-launch launch model.
- Readings at hour h after 00:00 PT: non-team comments, distinct commenters, team comments, how established the
  commenters are, and the day's standing and share. Only comments posted before h are used.
- LightGBM on final log votes, rolling monthly, 3 seeds. 102,128 timed comments.
- Share of launches with at least one comment by hour: 1h 33%, 2h 48%, 4h 61%, 8h 72%, 12h 77%.

| Top 3 / 5 / 10 (Δ top 3 vs hour 0, 95% CI) | Daily (175 days) | Weekly (25 / 25 / 21 weeks) | Monthly (5–6 lists) |
|---|---|---|---|
| Hour 0: launch model | 65.3 / 73.9 / 81.2 | 50.7 / 57.6 / 57.6 | 46.7 / 46.7 / 51.7 |
| Hour 1 | 65.9 / 73.7 / 80.9 (+0.6, −2.3 to +3.4) | 49.3 / 62.4 / 60.0 | 20.0 / 43.3 / 45.0 |
| Hour 2 | 70.1 / 74.2 / 81.2 (+4.8, +1.7 to +8.0) | 48.0 / 59.2 / 62.4 | 40.0 / 50.0 / 48.3 |
| Hour 4 | 70.5 / 74.6 / 81.7 (+5.1, +1.9 to +8.4) | 56.0 / 61.6 / 59.5 | 46.7 / 43.3 / 55.0 |
| Hour 8 | 72.4 / 77.8 / 82.8 (+7.0, +3.6 to +10.3) | 58.7 / 63.2 / 63.3 | 26.7 / 43.3 / 53.3 |
| Hour 12 | **74.1 / 78.9 / 82.7** (+8.8, +5.1 to +12.4) | 57.3 / 62.4 / 65.2 | 33.3 / 53.3 / 55.0 |
| Comments only at hour 4 (no prior) | 57.3 / 64.6 / 69.1 | 38.7 / 41.6 / 47.1 | 6.7 / 36.7 / 35.0 |

- **Daily:** real early comments add +4.8 on top 3 by hour 2 and +8.8 by hour 12, with intervals excluding 0. Top 5
  reaches +5.0 and top 10 +1.4 by hour 12. These are the first launch-day gains on real data.
- **Weekly:** +5 to +8 on top 3 from hour 4, with intervals spanning 0 (25 weeks). Top 10 is +7.6 (+1.0 to +14.3) at
  hour 12.
- **Monthly:** 5–6 lists, noise.
- **Compared with E0's random sample** (83 / 86 / 82 daily): comments are sparse early, so they read the shock far
  more weakly than votes would. A top-3 launch has about 158 pool voters but only a few comments by hour 2.
- **Next:** the same model on hourly vote snapshots (Nov 2 onward; 7 days by Nov 9), side by side with this comment
  curve. If votes behave like E0's sample, daily top 3 crosses 80 within the first hours.

## Predicting the shock before launch (Nov 2, `simlab/shock_model.py`, pnr pool simulation)
**Target:** the per-launch shock from E0, log((real pool voters + 1) / (simulated pool picks + 1)), with the day's mean
removed.

**Stage 1: shock from pre-launch inputs only**
- Inputs: the launch model's inputs plus new launch-level turnout features.
- Method: rolling monthly, May–Oct, 3 seeds.
- Within-day Spearman with the real shock: **0.49**. R² 0.009, because the shock has heavy tails across days; within
  day the ranking is what counts.
- Loss in Spearman when each group is dropped:

  | Group | Loss |
  |---|---|
  | `ph_` audience counts (makers' and hunter's followers, team size) | 0.054 |
  | `pf_` page facts | 0.033 |
  | `seg_` follower segments | 0.015 |
  | `hist_` track record | 0.015 |
  | `llm_` | 0.015 |
  | `ps_` page scores | 0.013 |
  | `fol_` pool follows | 0.011 |
  | turnout (new) | 0.011 |
  | `x_` | 0.010 |
  | `promo_` | 0.006 |
  | `vs_` video | 0.004 |

- Data note: stage 1 had 5,181 rows for 5,081 launches (duplicated IDs from a merge). The stage-2 file is unique
  (3,152 launches). To fix on the next run.

**Stage 2: forecast built from the simulation, Jun–Oct, top 3 / 5 / 10**

| | Daily (145 / 145 / 121) | Weekly (21 / 21 / 19) | Monthly (4–5) |
|---|---|---|---|
| Launch model | 65.3 / 73.1 / 81.5 | 49.2 / 57.1 / 56.8 | 58.3 / 52.0 / 52.0 |
| Simulation alone (pool picks, no audience inputs) | 45.3 / 58.3 / 69.5 | 11.1 / 19.0 / 23.7 | 8.3 / 4.0 / 12.0 |
| Simulation + predicted shock | 59.1 / 69.0 / 75.6 | 47.6 / 44.8 / 50.5 | 16.7 / 44.0 / 38.0 |
| Simulation + true shock (ceiling) | **86.4 / 93.1 / 90.1** | 44.4 / 58.1 / 73.2 | 16.7 / 36.0 / 38.0 |

- Predicted shock adds +13.8 to the simulation on daily top 3. It stays 6.2 below the launch model (−9.9 to −2.5).
  The shock model draws on the launch model's inputs, so this row is not a simulation-only result.
- **Ceiling:** with the shock known, daily top 5 is 93.1 and top 10 is 90.1, both above the target; top 3 is 86.4.
  So predicting the shock is the whole problem on the daily board.
- **Weekly ceiling is low** (44 / 58 / 73) because the shock here has the day's mean removed. Weekly needs a cross-day
  version (the day-level shock, plus line-up strength).
- **Where the shock signal is today:** audience counts first, then page facts, then track record. Turnout and X add a
  little each. The pre-launch inputs explain the shock's within-day ranking at 0.49. Closing the rest needs inputs
  that see the makers' outreach: X engagement (sample Nov 3), newsletters and communities, the competitor audiences
  (data spec filed), and from Nov 9 the hour-1/2 votes as the launch-day reading.

## Shock model, re-run: duplicates fixed, day-level shock added for weekly (Nov 2)
**Duplicates:**
- 204 launches sat in two consecutive `data/days` files: Apr 27/28, May 4/5, 6/7, 10/11, 13/14. The earlier file's
  window took in the next day's 00:00 PDT launches; every case matches `featuredAt` on exactly one of the two days.
- In `shock_model.py` each launch is now kept once, on its `featuredAt` (PT) day. 204 rows dropped from the simulation
  files, the build cache and the launch-model predictions alike.
- Upstream, the same duplicates are in the store and every backtest built from `data/days`. That fix is queued
  separately; numbers in this log before this entry include them (204 rows on 10 days).

**Shock prediction:**
- Within-day shock: Spearman 0.504 (was 0.49 with duplicates). Largest losses when dropped: `ph_` 0.055, `seg_` 0.028,
  `pf_` 0.028, `hist_` 0.017, `ps_` 0.016.
- **Day-level shock** (the day's pool turnout vs the simulation; 177 days): predicted from line-up size, active pool
  size, line-up strength by the prior and weekday at **Spearman 0.475**. Spread: 0.317 across days vs 0.758 within day.

**Forecasts, Jun–Oct, top 3 / 5 / 10:**

| | Daily (145 / 145 / 121) | Weekly (21 / 21 / 19) | Monthly (4–5) |
|---|---|---|---|
| Launch model | 65.3 / 73.1 / 81.5 | 49.2 / 57.1 / 56.8 | 58.3 / 52.0 / 52.0 |
| Sim + predicted shock (within day) | 57.2 / 69.0 / 76.0 | 46.0 / 47.6 / 50.5 | 25.0 / 32.0 / 38.0 |
| Sim + predicted shock, cross-day | 57.2 / 69.5 / 76.7 | **52.4** / 49.5 / 50.0 | 33.3 / 44.0 / 44.0 |
| Ceiling: sim + true shock (within day) | 86.0 / 92.6 / 90.2 | 44.4 / 60.0 / 73.7 | 33.3 / 44.0 / 36.0 |
| Ceiling: sim + true shock, cross-day | **89.7 / 94.3 / 90.2** | 52.4 / 68.6 / 80.5 | 33.3 / 48.0 / 52.0 |

- **Weekly:** the cross-day version lifts weekly top 3 from 46.0 to 52.4 (+3.2 vs the launch model, −6.3 to +12.7)
  but not top 5 or top 10.
- **Even the true pool shock caps weekly at 52 / 69 / 81.** The pool casts about 35% of votes. Ranking across days
  depends on the other 65%, whose size varies by day and launch in ways pool turnout doesn't track.
- **Daily:** the cross-day ceiling is 89.7 / 94.3 / 90.2, so knowing the pool shock is enough on the daily board.
- **Next for weekly:** model the shock on *total* votes (the launch model's residual, raw and by day) and predict it
  the same way, because the cross-day signal is in the outside-pool votes. Hour-1/2 vote snapshots (Nov 9) read it
  directly.

## Launch-day forecast from real intraday votes: Wayback homepage captures (Nov 2, `wayback_launchday.py`, Jul–Oct)
**Data:** `raw/ph_homepage_archive/parsed.jsonl` (Data Feeder). 467 homepage captures on 71 days, at random hours,
showing that day's posts with votes at capture time; plus archived daily leaderboard pages for 82 days (near-final).

**Verification** (the archive ends Oct 28, before the hourly snapshots start on Oct 31, so the check is against our
stored finals):
- Leaderboard pages vs our final votes: median ratio 1.00; 60% within 5%.
- Top 3 on the page matches our stored daily rank on 95.5% of days.
- launchDayScore of past days vs our finals: median 0.973.
- **Votes are hidden for the first 4 hours.** Every post shows 0 votes in captures before hour 4 (852 + 970 rows);
  from hour 4 every post has a count.

**Backtest:** the latest capture per day in each bucket of hours since 00:00 PT. Daily top 3 / 5 / 10 against the
final rank, with a bootstrap over days.

| Hours (days) | Votes at capture | Pre-launch prior | Equal-rank blend − prior, top 3 |
|---|---|---|---|
| 0–2 (16) | 27.1 / 35.0 / 50.0 (votes hidden) | 60.4 / 68.8 / 75.0 | 0.0 |
| 2–4 (18) | 24.1 / 35.6 / 52.2 (votes hidden) | 57.4 / 67.8 / 77.8 | 0.0 |
| **4–8 (29; median 6.2 h)** | **85.1 (78.2–92.0) / 95.2 (91.7–97.9) / 91.8 (88.9–94.6)** | 60.9 / 72.4 / 79.6 | +21.8 (+16.1 to +27.6) |
| **8–12 (29; median 11.3 h)** | **93.1 (87.4–97.7) / 95.2 (91.7–97.9) / 96.2 (93.8–98.3)** | 60.9 / 71.0 / 76.7 | +18.4 |
| 12–24 (51; median 21.7 h) | 96.7 / 97.3 / 97.8 | 61.4 / 70.6 / 80.2 | +20.3 |

**Reading (launch-day claim, reported apart from pre-launch):**
- From the moment Product Hunt shows votes (hour 4), the votes alone give daily top 5 and top 10 above 90. Top 3 is
  85 at a median 6 h and 93 at a median 11 h.
- The equal-weight blend with the prior is worse than votes alone after hour 4. The prior only matters before votes
  are visible.
- Caveats: 29 days per bucket and one capture per day, at random hours. `votes` falls back to `latestScore` when the
  displayed count is absent.
- **Open question:** do our API snapshots see votes in hours 0–4, when the page hides them? Nov 1's recorder started at
  hour 7. The Nov 2 run (from 00:05 PT) will answer it.

## Pushing the pre-launch shock predictor with data in hand (Nov 2, `simlab/shock_extra.py`, May–Oct, deduped)
**Persistence:** for launches whose makers have 2+ earlier launches in our data, the makers' mean past shock vs the
current shock has Spearman **0.44** (170 launches). For the hunter's earlier hunted launches it is **0.17** (1,350
launches). Surges persist, especially for makers, but few launches have repeat makers in the data.

**Blocks added cumulatively.** Gate: within-day Spearman of the predicted vs real shock, paired over days. Stage 2:
simulation + predicted shock, Jun–Oct, daily top 3 / 5 / 10. The launch model on the same days scores
65.3 / 73.1 / 81.5.

| Step | Stage-1 Spearman | Δ vs previous (95% CI) | Daily top 3 / 5 / 10 | Top 3 vs launch model |
|---|---|---|---|---|
| Base: launch inputs + turnout | 0.489 | | 56.1 / 67.0 / 75.5 | −9.2 (−12.9 to −5.7) |
| + team surge history (12 inputs) | **0.500** | **+0.011 (+0.002 to +0.021)** | 57.7 / 68.4 / 76.6 | −7.6 (−11.3 to −3.9) |
| + competitor and topic appetite (7) | 0.498 | −0.002 (−0.010 to +0.007) | 58.4 / 69.4 / 76.9 | −6.9 (−10.6 to −3.2) |
| + day context (4) | 0.494 | −0.004 (−0.012 to +0.004) | 58.4 / 69.2 / 76.1 | −6.9 |
| + warm-up (3) | 0.503 | +0.009 (−0.004 to +0.022); vs base +0.014 (+0.000 to +0.029) | 57.7 / 67.6 / 77.5 | −7.6 |

- **Passes the gate:** team surge history only (+0.011, interval excluding 0).
- **No gain:** competitor and topic appetite, and day context.
- **Warm-up:** borderline. Post lead time is always 0 in our data (createdAt equals featuredAt), so that input
  carries nothing.
- **Coming-soon follower counts don't exist:** Product Hunt removed coming-soon pages in Aug 2025 (Grok Bot), so
  that candidate is dropped.
- **Stage 2:** +1.6 to +2.3 on daily top 3 over the base step, inside the noise. The simulation + predicted shock is
  still 6.9–7.6 below the launch model.
- **Reading:** the inputs in hand are close to exhausted for the shock, at about 0.50. The remaining signal is
  outside the data: makers' outreach (X engagement, queued), the competitor audiences (pilot running), and the
  launch-day votes, which from hour 4 already give daily top 5/10 above 90.

## Duplicated launches across two day files: cause and fix (Nov 2)
- **Cause:** Product Hunt's API filters the day window on when a post was *created*. A post created on day d but
  featured at 00:00 PT on d + 1 came back for d as well: 204 launches on Apr 27/28 and May 4/5, 6/7, 10/11, 13/14.
- **Second bug:** `collect_ph.py` hardcoded −07:00 for every day after Mar 8. That is an hour off in PST since Nov 1,
  and the pipeline's `ranks` step re-collects the last 30 days with it every night.
- **Fix** (commit `c70b625`): zoneinfo window, plus a featuredAt-Pacific-day filter (`collect_ph.on_day`) in
  `collect_ph`, `today.py` and `list_check.refetch`.
- **Repairs:** `dedupe_days.py` for the 5 files (backups kept), and `pipeline.fix_launch_days` for the 204 warehouse
  launch rows on the wrong day. The 1,269 upvote events for those launches stay dated a day early (append-only log).
- **Pipeline:** bundle `20261102_window`; Shreyas approved routing it through the orchestrator to Grok Bot, before the
  00:05 PT run on Nov 2.
- **Experiment VM:** the repair of the day files, store, build cache and ctrl, with before/after baselines, waits
  until the other sessions' jobs there finish.
- **Footnote for earlier numbers:** every backtest in this log before Nov 2 includes the 204 launches twice (on 10
  days; on the earlier day they are an extra copy of the next day's launches). The before/after table will follow here.
- **Deploy verified (Nov 2, 04:00 UTC):**
  - Grok Bot deployed `20261102_window` at 03:51 UTC; its reply is in `mailbox/from_grokbot/20261102_window_deploy.reply.md`.
  - The md5 of all 5 files on the VM matches the repo.
  - Nov 2's window is 00:00−08:00 to 00:00−08:00.
  - Re-run dry checks: 0 day files to change, 0 launches in two files, 0 warehouse rows on the wrong day.
  - The 5 original files are in `data/days_backup_dedupe/`.
- **Duplicate recorders:** the Nov 1 runs from 14:07 (PID 47209) and 15:17 (62578) are both still recording, until
  07:55 UTC. Stopping the older one was refused by my permission check.
  - Safe order if done: TERM the older run's main shell 47209 first, so it can't reach its shutdown line; then its
    recorder (47218 → 47220 → 47222).
  - Prevention, commit `4f908e9`, bundle `20261102_lock`: `run_daily.sh` takes an exclusive lock
    (`flock -n`, inherited by the recorder), so a second start exits. `hourly.py` writes at most one snapshot per UTC
    hour per day (file lock + existing-hour check). Both tested.

## Second push on the surge predictor: total-vote target and unused inputs (Nov 2, `simlab/shock_extra2.py`, May–Oct)
**Coverage of the new inputs** (share of launches):
- total-surge history, makers: 11.0%; hunter: 30.8%;
- pool-shock history, makers: 8.7%;
- Wayback velocity history: 12.5%;
- makers' X posts in the 7 days before launch: 5.1%.

**Persistence of the total-vote surge** (final log votes minus the launch model): makers with 2+ earlier launches
Spearman 0.248 (223 launches); hunter 0.02 (1,583).

| Step (cumulative) | Pool-shock target: Spearman, Δ (95% CI) | Total-surge target: Spearman, Δ (95% CI) |
|---|---|---|
| Base (launch inputs + turnout + pool history) | 0.501 | 0.007 |
| + total-surge history | 0.499, −0.002 (−0.008 to +0.005) | 0.005, −0.002 (−0.022 to +0.018) |
| + Wayback velocity history | 0.499, −0.000 (−0.005 to +0.005) | −0.005, −0.009 (−0.019 to −0.000) |
| + makers' X posts | 0.495, −0.004 (−0.010 to +0.001) | −0.002, +0.003 (−0.009 to +0.014) |

**Stage 2, daily top 3 / 5 / 10, Jun–Oct.** The launch model scores 65.3 / 73.1 / 81.5.

| | Top 3 / 5 / 10 | Top 3 vs launch model (95% CI) |
|---|---|---|
| Sim + predicted pool shock, base | 57.5 / 69.0 / 76.0 | −7.8 (−12.0 to −3.9) |
| Sim + predicted pool shock, all blocks | 57.0 / 70.5 / 76.0 | −8.3 (−12.2 to −4.1) |
| Launch model + predicted total surge, base | 66.4 / 72.0 / 81.0 | +1.1 (−1.1 to +3.4) |
| Launch model + predicted total surge, all blocks | 65.7 / 72.3 / 81.8 | +0.5 (−1.6 to +2.5) |

**Verdict:**
- No block passes the gate on either target.
- The total-vote surge is unpredictable from pre-launch inputs (Spearman ≈ 0.0). It is by construction what the
  launch model can't explain from those same inputs. Team history of it persists for repeat makers (0.25), but they
  are 4% of launches, too few to move the day-level metric.
- X posts cover only 5% of launches.
- Pre-launch daily top 3 / 5 / 10 does not move (launch model + surge within ±1.1).
- The pre-launch inputs in hand are exhausted. The next pre-launch signal has to be new data about the makers'
  outreach, with wider coverage: the X engagement sample (queued), and the competitor-audience reviewers (pilot
  running, nothing delivered yet).
- The launch-day route already clears 90 on daily top 5 / 10 from hour 4 (Wayback votes).
- **Duplicate recorders fixed (Nov 2, 04:25 UTC):**
  - Grok Bot deployed `20261102_lock` and stopped the older run (PID 47209); 62578 is kept.
  - Verified: VM files match the repo, the live `run_daily.sh` has the lock, and a helper holds the lock until 62578
    exits. The shutdown line is intact.
  - The doubling covered every hour from 15:00 to 04:00 UTC (38 rows instead of 19).
  - The local `2026-11-01.jsonl` is deduplicated to one row per launch and hour: 285 rows, 19 per hour; the original
    is kept as `.bak_dupes`.
  - The warehouse `vote_snapshots` rows stay doubled (append-only). The read rule is documented in
    `pipeline/DATA.md`.

## Baselines re-scored on deduplicated data (Nov 2, 04:40 UTC)
**Repair on exp-1:**
- `dedupe_days.py`: 5 day files, 204 launches removed.
- `simlab.fix_store_days`: 204 store items moved to their featuredAt day, and their 1,266 upvote events re-dated.
- Build cache rebuilt; `ctrl.py` re-run (5 seeds, Mar–Oct).
- Launch-model predictions: 5,564 rows for 5,564 launches; before, 5,768 rows.

**Launch model, top 3 / 5 / 10, before → after** (scored against the corrected ranks):

| Board | Mar–Oct before | Mar–Oct after | Jul–Oct before | Jul–Oct after (paired Δ, 95% CI) |
|---|---|---|---|---|
| Daily | 62.6 / 71.1 / 79.3 | 63.4 / 71.4 / 79.5 | 65.5 / 73.0 / 80.9 | **65.5 / 73.2 / 81.4** (top 3 +0.0, −1.7 to +1.7; top 10 +0.5, +0.1 to +1.0) |
| Weekly | 50.5 / 53.9 / 55.7 | 49.5 / 52.7 / 55.5 | 51.0 / 55.0 / 56.7 | 47.1 / 53.8 / 56.7 (top 3 −3.9, −9.8 to +0.0) |
| Monthly | 38.1 / 40.0 / 46.2 | 28.6 / 37.5 / 45.0 | 55.6 / 50.0 / 57.5 | 44.4 / 50.0 / 52.5 (3–4 lists) |

**Reading:**
- Daily is unchanged within noise.
- The weekly and monthly moves fall inside their wide intervals (17 weeks, 3–4 months). They also include a small
  data refresh since the Oct 31 run: PR #143's `ctx_features` (288 values changed).
- **Footnote for every earlier number in this log:** earlier numbers include the 204 duplicates. Daily headlines stand
  (Jul–Oct 65.5 / 73.2 / 81.4 now vs 65.8 / 72.9 / 80.8 quoted). Weekly and monthly baselines are now 47.1 / 53.8 /
  56.7 and 44.4 / 50.0 / 52.5 (Jul–Oct).
- Simulation runs (popscore day files) were not rescored. They still hold the 204 extra rows; analyses since
  `shock_model` drop them with `dedupe()`.

## Launch-day votes on all boards, and earlier daily reads (Nov 2, `wayback_boards.py`)
Setup:
- Inputs: Wayback homepage captures (votes hidden before hour 4) + non-team comments + the pre-launch prior.
- LightGBM on final log votes, trained on earlier months; tested Aug–Oct.
- Launches whose day has no capture before the cutoff fall back to prior + comments.
- Capture coverage is partial: 29% of launches by hour 8, 40% by 12, 55% by 24. No week and no month is fully
  captured.

**Test 1: rank by predicted final votes at cutoff H, top 3 / 5 / 10 (Δ vs prior, 95% CI)**

| Board (lists) | Prior | H = 8 | H = 12 | H = 24 |
|---|---|---|---|---|
| Daily (86 / 86 / 78) | 62.8 / 70.7 / 79.9 | 73.3 / 78.8 / 83.8 (top 3 +10.5, +6.2 to +14.7) | 76.4 / 80.0 / 84.9 (+13.6, +8.5 to +18.6) | 83.3 / 84.9 / 88.1 (+20.5, +15.1 to +26.4) |
| Weekly (12) | 50.0 / 55.0 / 55.8 | 52.8 / 53.3 / 63.3 | 58.3 / 56.7 / 63.3 | **63.9 / 66.7 / 72.5** (top 10 +16.7, +11.7 to +21.7; top 3 +13.9, −2.8 to +30.6) |
| Monthly (2–3) | 50.0 / 46.7 / 50.0 | noise | noise | noise |

Daily numbers here mix captured and uncaptured days. On captured days alone, votes give about 95 or more from hour 8
(previous section).

**Test 2: early daily reads**

| H (days) | Prior | + comments | + comments + first votes | Votes alone |
|---|---|---|---|---|
| 2 (86) | 62.8 / 70.7 / 79.9 | 65.9 / 70.7 / 80.4 (top 3 +3.1, −1.6 to +8.1) | same, votes hidden | — |
| 4 (86) | 62.8 / 70.7 / 79.9 | 67.4 / 72.1 / 80.3 (top 3 +4.7, −0.0 to +9.3) | same, votes hidden | — |
| 6 (18 captured days) | 51.9 / 67.8 / 78.8 | 61.1 / 70.0 / 80.0 | 68.5 / 85.6 / 89.4 | **83.3 / 96.7 / 91.2** (top 3 +31.5, +18.5 to +42.6) |

**Reading:**
- Before hour 4, comments add 3 to 5 points on top 3. The first visible votes then dominate.
- At hour 6, votes alone give 83 / 97 / 91 on 18 days. The fitted blend is worse than votes alone: too few captured
  days to learn the weights, so the prior pulls it down. Top 3 does not pass 90 before hour 11 on this data.
- Weekly gains with launch-day votes: top 10 +16.7 at H = 24, interval excluding 0. That is with only 53% of each
  week's launches captured; full hourly coverage (our live snapshots) is the real test.
- **Next:**
  - Whether the API exposes votes before hour 4. The Nov 2 run answers it.
  - The same model on live hourly snapshots: full coverage, every launch, every hour, from Nov 2.

## Pre-launch only (Shreyas, Nov 2: launch-day forecasts don't count toward the north star; launch-day work is a tool)
### Early trajectory as an extra training target (`trajectory_target.py`, Aug–Oct)
Setup:
- Target: early speed = log votes at a Wayback capture (hours 4–12) minus log hours, within day; 1,045 past launches.
- Learned from the launch-model inputs only (pre-launch), trained on earlier months.

Results:
- **The launch model already predicts held-out early speed better** (within-day Spearman 0.686) than a model trained on
  early speed itself (0.619).
- Rank blend of the two vs the launch model, daily top 3 / 5 / 10: 62.4 / 71.2 / 79.2 vs 65.1 / 71.6 / 80.5 (top 3
  −2.7, −6.6 to +1.2).
- Weekly (12 weeks): top 5 −13.3 (−20.0 to −5.0).
- The stacked variant produced no scores: the trajectory data starts in July, so its first test month had no
  training rows.
- **Verdict:** no gain. The early trajectory carries no information the pre-launch inputs lack.

### X launch-post engagement, PARTIAL (`x_engagement_test.py`; Oct 1–25, engagers for 22 launches)
- Of 33 X engagers (reposters, quoters, repliers) matched to Product Hunt people by the profile's X handle, **66.7%
  voted on that launch** (95% CI 50.6–82.8%). The same people voted on each other launch that day at 1.4%: a 47× lift.
- 37.9% of October voters have an X handle on their profile.
- Pre-launch use: only 27 posts on 21 launches are dated before 00:00 PT on launch day, so it is not measurable yet.
  Engagement counts were read at fetch time, so day-0 posts can't count as pre-launch.
- **Reading:** X engagement with the launch post marks real voters strongly. As a pre-launch input it needs posts
  before launch day: teasers, "launching tomorrow". Those are rare in this batch.

## Pre-launch X ties, first partial batch (Nov 2)

Data: Data Feeder's first partial batch (790 pre-launch posts, 183 engager rows, 83 team handles). Coverage counts a launch only when one of its team handles was fetched for that launch's day (fixed from a looser rule that counted 976 launches).

- Covered launches: 68. Engager rows matched to PH people: 19.
- Person level: 8 X-tied person-launch pairs. 75% voted on the launch (95% CI 45–100%), against 0.0% on the same day's other launches (placebo). The direction is right, but n=8 is far too small to rely on.
- Launch level (pre-launch, weekly roll): top 3 is 61.9 for both the launch model and the model with X ties. Not readable yet: there are too few covered launches to train on, and only one weekly line was captured before exp-1 was stopped.
- Next: re-run as batches land. If the person-level lift holds at n≥100 pairs, add an X-tie input to the person model (TIE) and test top 3/5/10 at launch level.

## E5 person model trained on all earlier months (psg_) and the attention-net blend (psv_) (Nov 2)
Setup:
- All sources restricted to the same 3,977 launches (May–Oct, 177 days; tested Jun–Oct). Every model was trained only on earlier months.
- Paired bootstrap over days (10,000 resamples).
- Script: `ph_predict/sim_src_score.py` (pool check; launch model + simulation). `newsim_eval.py NOPAGE=1 STAGE=2 STAGE3=1` with "+day standing" is the live configuration; `pxg`/`png` are pnx/psn2 cut to the same launches.

**Pool check (simulation only):** within-day Spearman with real pool votes, and the hit rate on the pool's own top 3.

| | Spearman ev | Pool top 3 (ev) | vs pnx, Spearman | vs pnx, top 3 |
|---|---|---|---|---|
| pnx | 0.507 | 47.6 | | |
| **psg** | **0.581** | **58.0** | +0.074 (+0.050 to +0.099) | **+10.4 (+7.0 to +13.9)** |
| psv | 0.580 | 58.2 | +0.073 (+0.048 to +0.098) | +10.5 (+6.8 to +14.3) |
| psr | 0.538 | 52.5 | +0.031 (+0.007 to +0.056) | +4.9 (+1.1 to +8.5) |
| psn2 | 0.459 | 44.8 | −0.048 | −2.8 |

**Launch level, pre-launch daily top 3/5/10.**
- Live configuration (simulation + reach + audience + day standing, no page), psg − pnx: top 3 **+3.7 (+0.9 to +6.4)**, better in 4 of 5 months; top 5 +0.8 (−0.7 to +2.3); top 10 +0.2 (−0.7 to +1.2). psv − pnx: +1.6 / +0.8 / −0.7, all intervals span 0.
- That live model is still below the launch model alone: psg 61.1 / 70.6 / 80.1 vs 66.4 / 73.2 / 81.9. Top 3 −5.3 (−9.0 to −1.6).
- Launch model + simulation inputs: no source beats the launch model alone. Launch model + psg: −0.9 (−3.9 to +2.1) / −1.0 (−2.6 to +0.7) / −1.2 (−2.3 to −0.2). Launch model + pnx: −3.0 / −2.5 / −1.0. psg is the least harmful (vs pnx: +2.1 (−0.9 to +5.3) / +1.5 / −0.2).

**Verdict:**
- psg is a clear simulation upgrade: +10 points on the pool's own top 3, and +3.7 on daily top 3 for the live simulation forecast. It should go into the next bundle (popscore train_month on all earlier months).
- It does not improve the headline pre-launch forecast. The launch model alone is still best, and adding any simulation inputs to it doesn't help.
- psv adds nothing over psg.

## Pre-launch X engagers: leakage filter and turnout inputs, coverage check (Nov 2, 07:15 UTC)
- Leakage: engager rows are kept only when their own post (snowflake time of engager_post_id) is before 00:00 PT on launch day. Of 2,698 rows: 1,243 reposts dropped (no time), 92 replies or quotes dropped (posted after launch start).
- Coverage gate: a handle-day counts only when its posts are complete and every post with any engagement has its engagers fetched. Now: 17 handle-days, **16 covered launches** (727 complete posts still lack engager lists).
- Added turnout inputs (distinct pre-launch X engagers, engagers per post, posts) and their no-fit within-day Spearman with the launch model's residual (the shock). Only 4 days have 3+ covered launches, so these numbers mean nothing yet.
- Launch-level top 3/5/10 vs the launch model is not run yet. It runs once there are ≥100 covered launches, then again with each batch.

## Pre-launch X engagers, re-run at 07:07 UTC files (Nov 2)
- Coverage gate: the posts_complete / engagers_fetched flags in the output files lag the fetch job. The gate now comes from the job's state.json (`XGATE`): groups fully paged, launch day Oct 5–23 (Oct 1 / g5 lists still queued), and no open engager list or reply batch. That gives 67 handle-days, which map to **51 covered launches** in the store; Grok Bot counts 152 by its own rule. Dead handles from raw/x_lookup/x_lookup.json (188 not found, 6 suspended) are dropped before matching (`XLOOKUP`).
- Leakage filter: dropped 1,243 reposts (no time) and 100 replies or quotes posted after 00:00 PT on launch day.
- **Person level:** 42 X-tied person-launch pairs (replied to or quoted a team post in the 30 days before launch). 45.2% voted on the launch (95% CI 30–60%), vs 1.2% on the same day's other launches: a 37× lift. This is the first person-level signal with real n.
- **Turnout vs shock** (within-day Spearman with the launch model's residual, 7 days with 3+ covered launches): distinct engagers +0.04, per post +0.03, posts −0.05, X-tied PH people +0.11. No sign of a turnout signal yet; too few days to say more.
- Launch-level top 3/5/10 is still not run (51 < 100 covered launches). It needs tomorrow's X quota (g8/9/11/12 posts, 316 lists).
- **Extra turnout inputs (orchestrator's list), same 51 launches and 7 days.** Within-day Spearman with the launch-model residual:
  - impressions / likes / reposts on team posts, last 7 days: −0.07 / −0.08 / −0.10; last 30 days: −0.02 / +0.02 / −0.07.
  - last 48 h: post count −0.09; tease (text mentions producthunt / launching / tomorrow) +0.09.
  - With about 7 launches a day over 7 days, one standard error is roughly ±0.15, so none of these differ from 0.
  - Caveat: like, impression and repost counts are read at fetch time (Nov 2), so they include engagement after launch. A positive result would have needed a leakage check; a null one doesn't.

## Pre-launch X, re-run at 08:22 UTC files: first launch-level read (Nov 2)
- Gate: built from state.json (groups fully paged, no open list or reply batch). Zero-post handles are kept as real zeros unless x_lookup marks them not found or suspended. x_lookup covers PH-pool handles, so 43 of 48 zero-post maker handles are absent from it and are kept. Result: 86 handle-days → **53 covered launches in the store** (Grok Bot reports 90; its launch count rule differs). No day has every launch covered.
- Leakage filter: dropped 1,280 reposts (no time) and 121 replies or quotes posted after launch start.
- **Person level:** 65 tied pairs; 32.3% voted (95% CI 21–44%) vs 0.9% placebo, a 34× lift.
- **Launch level:** leave-one-day-out ridge on the launch prediction plus a fixed turnout set (engagers, per post, posts, X-tied PH people, 48 h tease), ranked among the covered launches on 7 days. Top 3 is 90.5 vs 90.5, top 5 80.0 vs 80.0: identical rankings, delta 0. With ~7 covered launches a day the task is too easy to tell anything, and there are 0 fully covered days, so this can't speak to the real board yet.
- Turnout vs shock (within-day Spearman with the residual): all between −0.10 and +0.09, inside ±0.15 noise.
- Re-run when the twitterapi top-up closes the 229 open launches; that should give full days.

## Pre-launch X, refreshed build (08:36 files, Grok Bot reports 121 covered): reconciliation and re-run (Nov 2)
- **Why 121 vs 64.** Both rules mark the same 86 handle-days as fully fetched. Grok Bot's ph_gate.py counts a launch as covered when all its handles are done, *on any day*. But each handle's posts were fetched only for the 30 days before its one assigned launch. 76 of the launches it credits fall on a different day from that window (serial makers and hunters), so their pre-launch window wasn't fetched. Under the day-matched rule there are **64 covered launches** (57 with every handle done, 7 with some). That stays below 100 until g8/g9/g11/g12 page.
- Leakage filter: dropped 1,280 reposts (no time) and 121 replies or quotes after launch start (snowflake time; every reply and quote row has engager_post_id).
- **Person level:** 90 tied pairs; 32.2% voted (95% CI 22.6–41.9%) vs 1.0% placebo, a 31× lift. Stable across the last three runs.
- **Launch level** (leave-one-day-out ridge, launch prediction + fixed turnout set, ranked among covered launches, 9 days): top 3 77.8 vs 77.8, top 5 82.5 vs 82.5, identical rankings. The turnout weights are too small to change any order. 0 fully covered days.
- Turnout vs residual: engagers −0.03, X-tied PH people −0.03, 48 h tease +0.03 (noise ±0.15).
- Reading so far: X engagement strongly marks *who* votes, but at launch level it hasn't shown any turnout signal beyond the launch model.
- Full-day coverage: 0 of 25 October days have every launch covered. Launches with no maker or hunter X handle (about half) count as real zeros. Fetch order sent to Grok Bot (launch ids only, gs://…/tmp/ph_ops/x_fetch_order.json): 19 open launches would complete Oct 25, 5, 10, 23 and 24. Most open launches need a fresh window ending on their own launch day.

## Daily check, Nov 2 (run 00:10 PT)
- Steps: all ok except `people`, which failed: 4,420 of 4,420 profile pages blocked (status != 200). Profile pages have returned 0 items since Oct 30; the step now reports that as a failure. list_check for Nov 1: 0 missing. 17 launches at 00:10 PT; launch-model and simulation forecasts both written.
- Nov 1 forecast vs final ranks (launch model): top 3 2/3, top 5 3/5, top 10 8/10. The simulation forecast is scored from tomorrow (first forecast is Nov 2).
- Spend Nov 2: Gemini $0.45, GCP VM $0.07, DataImpulse $0.03 (no 407).
- Monday backtest (32 days), daily top 3/5/10: simulation only 46.7 / 59.9 / 68.3; launch only 64.0 / 70.5 / 76.3; both 58.8 / 67.8 / 74.5; current 64.8 / 71.6 / 76.8.

## pna_ (no-page person model trained on all earlier months) vs pnx, and the four-way with competitor grounding (Nov 2)
`popscore` with `TIE2=1 TRAIN_ALL=1` (no page; E5's TRAIN_ALL ported, Nov model included via TRAIN_EXTRA). 4,877 launches, May–Oct. Paired bootstrap over days (10,000 resamples).

**pna vs pnx**
- Pool check (207 days): Spearman ev 0.513 vs 0.488, +0.025 (+0.009 to +0.042); pool top 3 (fans) +3.2 (+0.5 to +6.0); (ev) +2.7 (−0.2 to +5.5).
- Live sim (newsim NOPAGE STAGE3, +day standing), daily top 3/5/10: 58.8 / 71.3 / 79.8 vs 59.8 / 70.6 / 79.3. Δ −1.0 (−3.3 to +1.3), better in 4 of 6 months (May −4.6, Sep −4.4) / +0.7 (−0.7 to +2.1) / +0.4 (−0.4 to +1.2).
- Launch model + pna vs + pnx: +0.6 / +0.5 / +0.6, all intervals span 0.
- Reading: better on the pool's votes, equal within noise at launch level.

**Four-way, launch model + inputs** (`ph_predict/lm_plus.py`; 3,977 launches, Jun–Oct, 176 days; competitor grounding = PH Similar Products gaps, cmp_features_ph, present for 46.7% of launches). Every variant refits a small model on the launch prediction, so "refit alone" is the control.

| Daily top 3 / 5 / 10 | Score | vs refit alone (top 3 / 5 / 10) |
|---|---|---|
| launch model (raw) | 66.7 / 73.5 / 81.0 | |
| refit alone | 66.1 / 74.1 / 80.4 | |
| + competitor grounding | 65.0 / 72.7 / 79.8 | −1.1 (−3.4 to +1.1) / −1.4 (−3.0 to +0.2) / −0.6 (−1.5 to +0.3) |
| + pna | 64.6 / 72.7 / 80.4 | −1.5 (−4.4 to +1.3) / −1.4 (−3.2 to +0.3) / −0.0 (−1.0 to +1.1) |
| + both | 65.0 / 72.8 / 80.6 | −1.1 (−4.0 to +1.7) / −1.2 (−3.1 to +0.6) / +0.1 (−1.0 to +1.2) |

- None of the inputs beats the control; all intervals span 0 except vs the raw launch model on top 10 (+ competitors −1.2, −2.2 to −0.2).
- The pre-launch headline stays the raw launch model: 66.7 / 73.5 / 81.0.
- **Deployed Nov 2, 11:06 UTC (Grok Bot), verified by PH ops:** bundle 20261102_pna. Model and pnx_features md5 match the bundle, 4,877 entries; popscore has TRAIN_ALL; backup at ~/w/backup_20261102_pna/before.tar; recorder untouched. The live simulation uses the pna_ model from the Nov 3 run.

## Independent re-check of E5's E1 v2 (offset model) (Nov 2, `ph_predict/e1_check.py`)
Rebuilt from my own inputs (ctrl_preds `all` as the Poisson offset, pna_ ev/reach, five audience inputs from build_cached, day terms) with E5's feature list, not E5's code. Rolling monthly, May–Oct, 5 seeds, 3,977 launches, 177 days, 25 weeks. Paired bootstrap over lists. Control: the same offset model with day terms only (day_n, weekday, day_lm_sum). That control cannot reorder a day; it only rescales days against each other.

| | Launch model | Offset control | E1 v2 | E1 v2 − launch model | E1 v2 − control |
|---|---|---|---|---|---|
| Daily top 3 | 66.7 | 66.7 | 65.9 | −0.8 (−2.7 to +1.1), 2/6 months | −0.8 |
| Daily top 5 | 73.5 | 73.5 | 73.2 | −0.3 (−1.6 to +0.9) | −0.3 |
| Daily top 10 | 81.0 | 81.0 | 80.7 | −0.3 (−1.0 to +0.4) | −0.3 |
| Weekly top 3 | 49.3 | **54.7** | 49.3 | −0.0 (−5.3 to +5.3) | −5.3 (−13.3 to +2.7) |
| Weekly top 5 | 56.0 | **59.2** | 57.6 | +1.6 (−1.6 to +4.8) | −1.6 |
| Weekly top 10 | 58.3 | 58.3 | 55.7 | −2.6 (−4.8 to −0.4) | −2.6 |

- **Not reproduced.** E5 reports daily top 3 +1.3 (−0.4 to +3.0) and weekly top 3 +5.3 / top 5 +3.2. My rebuild gets −0.8 daily and 0 / +1.6 / −2.6 weekly. Possible reasons: hyperparameters, E5 training from April, or different audience columns.
- **Where a weekly gain can come from:** the day-terms-only control gives weekly top 3 +5.4 and top 5 +3.2 over the launch model on its own. That matches E5's weekly gains in size. So most of the weekly lift likely comes from rescaling days (busy vs quiet days, weekday), not from the pool or audiences. This is a cheap fix to test directly on the launch model: a day-level calibration for weekly and monthly lists. Only 25 weeks, so it needs confirming.
- The shadow slot is still worth running: live days are the clean test.

## Day-level calibration of the launch model, weekly and monthly boards (Nov 2, `ph_predict/daycal.py`)
Poisson LightGBM, with the launch model's expected votes as the offset and day terms only: weekday, line-up size, the line-up's total predicted votes, and the 7-day trailing real and predicted totals (ending 2 days before, so final by then). A day's launches move together, so the daily order is unchanged (daily Δ = 0, as it must be). Rolling monthly, 5 seeds, paired bootstrap over lists.

| | May–Oct: launch model → calibrated | Δ (95% CI) | Jul–Oct Δ |
|---|---|---|---|
| Weekly top 3 | 49.3 → 53.3 | +4.0 (0.0 to +9.3), 25 weeks; never worse in any month (0 / 0 / +8.3 / +6.7 / +8.3 / 0) | +5.9 (0.0 to +11.8), 17 weeks |
| Weekly top 5 | 56.0 → 57.6 | +1.6 (0.0 to +4.0) | +1.2 (0.0 to +3.7) |
| Weekly top 10 | 57.8 → 57.8 | 0.0 (−1.7 to +1.7) | +0.7 (−1.3 to +2.7) |
| Monthly top 3 | 33.3 → 20.0 | −13.3 (−26.7 to 0.0), 5 months | −22.2, 3 months |
| Monthly top 5 | 43.3 → 46.7 | +3.3 (−6.7 to +13.3), 6 months | 0.0 |
| Monthly top 10 | 48.3 → 51.7 | +3.3 (0.0 to +6.7) | +2.5 |

- **Weekly:** a consistent, never-negative gain on top 3 (+4 to +6) and top 5 (+1 to +2). The interval lower bounds sit at 0, and there are only 25 weeks.
- **Monthly:** only 5–6 lists, so it can't be judged. Top 3 is worse in 2 months (one launch each). Don't ship for monthly.
- **Recommendation:** run it as a shadow weekly forecast next to the launch model; it costs nothing, since it reuses the forecast's own predictions. Ship it for weekly once about 6 more live weeks agree. It doesn't touch the daily board.

## Competitor grounding against the day-calibrated control (Nov 2, `daycal.py EXTRA=cmp_features_ph`)
Same offset Poisson model; the control is day terms only (the day-calibrated weekly forecast). The test adds the PH Similar Products competitor gaps (cmp_features_ph), which can reorder within a day. Coverage: 46.6% of launches May–Oct, 56.0% Jul–Oct. Paired bootstrap over lists.

| Δ, + competitors − day-calibrated | May–Oct | Jul–Oct |
|---|---|---|
| Daily top 3 | −0.2 (−1.5 to +0.9) | −0.3 (−1.7 to +1.1) |
| Daily top 5 | **−1.2 (−2.0 to −0.6)** | **−1.2 (−2.2 to −0.3)** |
| Daily top 10 | −0.1 (−0.5 to +0.4) | −0.1 (−0.8 to +0.5) |
| Weekly top 3 | −4.0 (−9.3 to 0.0), 25 weeks | −3.9 (−9.8 to 0.0), 17 weeks |
| Weekly top 5 | −0.8 (−2.4 to 0.0) | 0.0 |
| Weekly top 10 | −1.3 (−2.6 to 0.0) | −1.3 (−3.3 to 0.0) |

- **Verdict:** competitor grounding hurts or does nothing on every list. Daily top 5 is worse with the interval excluding 0, and it cancels the day calibration's weekly top-3 gain. Keep it out of the forecast. Same conclusion as the earlier tests, now against the stronger control.

## Honesty check of the launch-model baseline (Nov 2, `ph_predict/honest.py`)
The ctrl.py `all` model, same folds and LightGBM, 5 seeds. Leak groups dropped cumulatively. 5,564 launches, 239 days. Daily top 3 / 5 / 10, paired bootstrap over days vs `all`.

| Variant (inputs dropped) | May–Oct | Jul–Oct |
|---|---|---|
| all (published baseline) | 66.5 / 73.6 / 81.0 | 65.5 / 73.2 / 81.4 |
| − followers (9: PH hunter, X maker / hunter / company counts + day ranks) | 66.5 / 73.0 / 80.7 (0.0 / −0.6 / −0.3, all span 0) | 65.8 / 72.3 / 80.8 |
| − … follows (fol_, seg_: 46 inputs from follow lists read Oct 25, undated) | **64.4 / 70.5 / 77.0** (−2.1 [−4.9, +0.8] / −3.1 [−5.2, −1.0] / −4.0 [−5.4, −2.7]) | **65.0 / 69.6 / 77.5** (−0.6 / −3.6 / −3.8) |
| − … promo (16: reaction counts read at fetch; also funding / company age) | 62.7 / 70.6 / 77.2 (−3.8 [−6.8, −0.9] / −2.9 / −3.8) | 63.0 / 69.6 / 77.7 |
| − … x_profile (3) | 62.5 / 70.3 / 77.1 | 63.0 / 69.9 / 77.9 |

- **Yes, the baseline uses post-launch inputs.** Follower counts barely matter (the makers' PH counts weren't model inputs; the hunter's and the X counts move it by ≤0.6). The real leak is **fol_ / seg_**: who follows the team and their segments, from follow lists read Oct 25, undated. People follow makers after a good launch, so for past launches these partly encode the outcome. Dropping them costs −3 to −4 on top 5/10.
- **Honest pre-launch baseline** (followers + follows dropped): **May–Oct 64.4 / 70.5 / 77.0; Jul–Oct 65.0 / 69.6 / 77.5.** If promo reaction counts are leaky too: 62.7 / 70.6 / 77.2 (lower bound).
- **Live check** (launch model, live daily scores Oct 27–Nov 1, 6 days): 61.1 / 70.0 / 81.7. That's consistent with the honest numbers, but 6 days give about ±25 points on top 3, so it can't separate them yet.
- **Consequence:** north-star numbers should be quoted against the honest baseline. Live, fol_ uses follow lists read before the launch (Oct 25), so it is stale but not leaky; its backtest value is overstated. Next: an honest fol_ needs follow snapshots taken before each launch. Data Feeder's daily following fetch (from Nov 2) provides this going forward.

## Honest baseline fixed, and the day calibration / E1 re-checks against it (Nov 2)
**promo_ split** (`promo_features.py`): kept = posts and coverage dated before launch (promo_posts*, promo_cov*). Dropped = values read at fetch, undated (promo_reactions, founder/company LinkedIn and X followers, funding, company age, n_sources).

**Honest pre-launch baseline** (honest.py "honest": no follower counts, no fol_ / seg_, no undated promo_; ctrl LightGBM, 5 seeds; this is the reference from now on):

| | May–Oct | Jul–Oct |
|---|---|---|
| Daily top 3 / 5 / 10 | **64.4 / 70.4 / 76.9** (published 66.5 / 73.6 / 81.0) | 64.7 / 69.6 / 77.5 |
| Weekly top 3 / 5 / 10 (25 / 17 weeks) | **45.3 / 54.4 / 55.2** (published 49.3 / 56.0 / 57.8) | 49.0 / 55.0 / 54.7 |
| Monthly top 3 / 5 / 10 (5–6 / 3–4 months) | **20.0 / 36.7 / 40.0** (published 33.3 / 43.3 / 48.3) | 33.3 / 35.0 / 42.5 |

**Day calibration on the honest model** (offset = honest prediction):
- Weekly top 3: 45.3 → 49.3, +4.0 (0.0 to +8.0), never worse in any month; Jul–Oct +3.9 (0.0 to +9.8).
- Weekly top 5: +1.6 (0.0 to +4.0); weekly top 10: 0.0.
- Monthly: 0.0 / −6.7 / −1.7 (6 lists). Still not for monthly.
- The weekly gain holds on the honest baseline.

**E1 v2 on the honest model:**
- With E5's audience inputs (three follower counts and promo_reactions, all read later, so not honest), for reference only: daily −0.2 / +0.5 / +1.0; weekly +4.0 / +2.4 / +2.2 vs the launch model; −1.3 / +0.8 / +2.2 vs the day-terms control.
- Honest E1 (audience = promo_posts only): daily −1.3 (−3.4 to +0.8) / −0.3 / −0.3. Weekly top 3 +9.3 (+4.0 to +16.0) vs the launch model, but +4.0 (−2.7 to +10.7) vs the day-terms control; weekly top 5 −1.6.
- Beyond day calibration, E1 adds nothing measurable.

**Live and shadows vs the honest set:**
- The live launch-model forecast used every dropped input.
- The live simulation forecast used makers' and hunter's PH followers (nsa_ reach), fol_, X follower counts and all of promo_.
- shadow_e1v2's inputs include three follower counts and promo_reactions.
- Fixed in code, not deployed: model.py `HONEST=1` by default (the honest column filter in `cols`, for training and live alike), and sim_forecast.py applies the same filter and drops nsa_ reach. shadow_daycal inherits whatever the live launch model uses. shadow_e1v2 needs an honest retrain (audience = dated promo posts plus at-launch follower counts once those accumulate), or it should stay off.
- **Deployed and verified (Nov 2):**
  - 20261102_shadow2, 12:31 UTC: the shadow step, weekly scoring, the people step reading Data Feeder's delivery.
  - 20261102_b3, 13:02 UTC: honest model.py (HONEST=1) and sim_forecast.py, the at_launch step, shadow default daycal (E1 v2 off).
  - On the VM: all 7 md5s match; the STEPS line includes at_launch and shadow; one hourly recorder, untouched.
  - at_launch_followers backfilled: 558 rows, Oct 25–Nov 2, 13–31 launches a day, no null counts.
  - Nov 3 is the first run on the honest live forecast; its scores compare with the honest backtest (64.4 / 70.4 / 76.9).

## Verdict: does popscore add daily top-3 lift over the honest, day-calibrated baseline? (Nov 2, PR 143 session)
**No measurable lift, and none expected from more of the same.**
- **The bar:** day calibration moves a day's launches together, so the daily order is the honest launch model's: **64.4 daily top 3 (May–Oct)**.
- **Every logged popscore-on-top-of-the-launch-model test sits at about 0 on daily top 3:**

| Test | Daily top 3, Δ vs launch model (95% CI) |
|---|---|
| Launch model + simulation correction (`sim_resid`, Jul–Oct) | +0.6 (−2.0 to +2.9) |
| Launch model + pna_ ev/reach + day terms (E1 rebuild) | −0.8 (−2.7 to +1.1) |
| E5 pool concentration over the day-calibrated control | +0.2 (−1.7 to +2.1) |
| Launch model + simulation, winner of 3 by day (psx) | −0.4 (−3.5 to +3.0) |

- **Alone it is below the baseline:** psr −3.2, psg live −5.3.
- **Its gains stay inside the simulation:** psg +3.7 over pnx; tie strength at person and pool level.
- **Residual check:** the correlation of the simulation's predicted launch-model misses with the real ones is −0.048 (`sim_resid`). (The near-0 residual from `ai_pitch_score`, −0.015 on the new baseline, is a different score.)
- **Caveat:** apart from E5's test, these ran against the published baseline (66.5). A direct psg + day terms re-test against the honest baseline is worth one run; expect ±2.
- **Why it is stuck:** E0 puts 90.5% of the simulation's error in a per-launch shock shared by the whole audience. No pre-launch person data sees that shock.

## Next experiment: early-vote shock correction on `vote_snapshots`, with popscore predicting the early share (planned Nov 2, ready about Nov 16)
- **Data limit found while building it:** `vote_snapshots` stores counts per launch per hour (votes, comments, rank), not voters, and upvote times are not public (`events` dates every upvote to the launch day). So the planned "weight each early voter by popscore's likelihood of voting" cannot be built.
- **Counts version (built instead):** early votes lean to the team's network, so the expected share of a launch's votes that arrive by hour H should depend on its audience. popscore's tie outputs (pnx_ev_ties / pnx_ev, reach, pmax) predict that share.
  - Shock: log early votes minus their expected value given the honest prior.
  - Control: expected value from the prior alone.
  - Test: the prior plus popscore's tie features.
  - Forecast: prior + fitted weight × shock.
- **Code:** `ph_predict/early_shock.py`.
  - Clean days: honest prior (from Nov 3), a snapshot near each cutoff, line-up coverage, final ranks.
  - Leave-one-day-out fits; cutoffs H = 1, 2, 3, 4, 6, 8, 12.
  - Daily top 3/5/10 with paired bootstrap over days: prior, votes alone, shock (control), shock + popscore.
  - Waits until 14 clean days exist.
- **Pipeline:** the `raw` step now also uploads `results/forecast_<d>.parquet` (the honest prior in log votes) and `data/sim_live/pnx_<d>.json` (popscore's live outputs). A new `earlyshock` step runs the gated backtest daily and writes `backtests` rows once ready. Not deployed yet.
- **Expectation:** E0's random-sample oracle gives 83 daily top 3, and Wayback captures +10.5 by hour 8. Real early votes are skewed, so the shock (control) arm should land well above 64.4 by hour 4–8. The open question is whether popscore's arm beats the control.
- **Deployed and verified (Nov 2, 15:06 UTC):** 20261102_b4.
  - Contents: the early-shock step (`earlyshock` between score and raw, idle until 14 clean days from Nov 3), pipeline/snapshots.py, s_raw uploading the honest forecast parquet and pnx_<d>.json.
  - On the VM: md5s match; run_daily.sh has score,earlyshock,raw; backup at ~/w/backup_20261102_b4/; one hourly recorder, untouched.

## Experiment zero: how predictable is the launch shock from honest pre-launch inputs? (Nov 2, `simlab/shock_model.py` stage 1, `HONEST=0` vs `HONEST=1`)
Same code, same pool simulation (popscore_tie), same folds (rolling monthly, Jun–Oct tested, 3,152 launches, 146 days). The only change: model.py's honest filter (no follower counts, no fol_ / seg_, no undated promo_). Within-day Spearman of the predicted vs real pool shock, paired over days (10,000 resamples).

| | Within-day Spearman | By month (Jun / Jul / Aug / Sep / Oct) |
|---|---|---|
| Leaky inputs (as published) | 0.504 | 0.550 / 0.490 / 0.545 / 0.443 / 0.488 |
| **Honest inputs** | **0.395** | 0.404 / 0.465 / 0.399 / 0.356 / 0.335 |
| Honest − leaky | **−0.109 (−0.142 to −0.078)**, lower in 5 of 5 months | |

- **Drop-one losses, honest run:** ph_ 0.053 (team size, media, hunter account age; follower counts are gone), pf_ page facts 0.034, hist_ 0.020, llm_ 0.019, turnout 0.018, vs_ video 0.014, x_ 0.013, ps_ 0.013. hist_ and turnout matter more once the leaky groups are gone (0.001 → 0.020; turnout first appears).
- **Day-level shock** (day terms only): 0.509 in both runs, unaffected.
- **Reading:** about a fifth of the published shock predictability came from inputs that partly read the outcome. "Inputs exhausted at 0.50" was a leaky ceiling. Honest predictability is 0.395, so there is more unexplained shock than thought, and the signal that is left leans on track record (hist_) and turnout. That supports the review's directions A (the team's full history) and B (the audience as of day−1).
- Stage 2 of this script compares against the leaky launch model (`ctrl_preds`), so it isn't reported here.

## C1, downloads part: npm / PyPI downloads before launch (Nov 2, `ph_predict/c1_user_base.py`, Data Feeder's raw/pkg_downloads/)
- **Own packages only:** sites also link libraries they use, and the biggest "packages" were zod, openai, npm, @stripe/stripe-js and @tiptap/react, which would swamp a max. A repo or package is kept only if a name token (≥3 chars) is shared with the launch's name, slug or website domain: 558 of 1,060 repos and packages kept. PyPI series start around May (pypistats keeps about 180 days); npm goes back to 2015.
- **Coverage:** 96 launches (1.7%) have an own package with downloads before launch day.
- **Gate (honest residual, pooled over covered launches, Holm-corrected):** downloads in the 7 / 30 / 90 days before launch: Spearman 0.31 / 0.34 / 0.32 (95% CI about 0.13 to 0.50), all pass. A launch whose package already has users beats the honest forecast.
- **Boards** (honest day-calibrated control vs + downloads):
  - The trees can't use 96 rows (100 per leaf), so a forward-fitted linear arm was added for sparse inputs.
  - Daily top 3 / 5 / 10: +0.4 / −0.2 / +0.1; weekly 0.0 / −0.8 / 0.0; monthly 0. All within noise.
- **Reading:** real signal per launch, but 1.7% coverage can't move a board. Stars (about 9% of launches link an own repo) are the larger test; Data Feeder's star pass is due ~23:00–00:00 UTC. userbase_eval.py now has the linear arm for sparse inputs.

## Page inputs: honesty check and sensitivity (Nov 2, orchestrator's Fable review; `honest.py PAGE_SENS=1`)
**Where the page inputs come from, for backtest launches:**
- pf_ (page facts), ps_ (page scores), llm_pitch read name, tagline, description, topics and media from `data/days/` (API). Those files were fetched a **median 88 days after launch** (1–182), so post-launch edits to the description or media can be in them. The maker's first comment comes from the timed comments (posted at launch; edits possible).
- Website text (ps_website, ps_links, llm_site, llm_full) uses the live site fetched around Oct 30 where no day-before Wayback snapshot exists. **1.6% of those sites (106 of 6,569) show "Product of the Day", "featured on Product Hunt" or similar wording.**
- llm_full's prompt includes follower counts, including the makers' PH counts that the model itself excludes as leaky.
- So the page inputs are not honest by construction.

**Sensitivity, daily top 3 / 5 / 10, paired vs honest (64.4 / 70.4 / 76.9, May–Oct):**

| Dropped from honest | May–Oct | Δ (95% CI) top 3 / 5 / 10 | Jul–Oct |
|---|---|---|---|
| Web- and follower-derived page inputs (llm_full, llm_site, ps_website, ps_links) | 63.5 / 70.2 / 77.4 | −0.9 (−2.8, +0.9) / −0.2 / +0.6 | 64.4 / 69.4 / 78.0 |
| All page groups (pf_, ps_, vs_, llm_; 103 inputs) | 61.4 / 68.5 / 76.5 | **−3.0 (−5.1, −0.9)** / −1.9 (−3.5, −0.3) / −0.4 | 62.1 / 69.6 / 77.3 |
| **The live forecast's own set** (no pf_ / ps_ / vs_, no llm_full) | **62.7 / 70.4 / 76.6** | −1.7 (−4.1, +0.8) / 0.0 / −0.3 | 64.4 / 69.6 / 77.1 |

- The web-derived and follower-derived page inputs don't inflate the baseline (all within noise). Page content as a whole carries real ranking signal (−3.0 when dropped). Edits made after launch can't be separated from it in the backtest.
- The live forecast doesn't use pf_ / ps_ / vs_, so the **baseline comparable with live scores is 62.7 / 70.4 / 76.6** (May–Oct). The page-aware honest model, 64.4 / 70.4 / 76.9, is an upper reference.
- Going forward: `data/today/<day>.json` holds the name, tagline, description and media as fetched at 00:05 PT, so honest page snapshots accrue from Oct 25. llm_full should join the honest filter (its prompt carries follower counts).

## C1: the product's existing user base before launch, GitHub stars + npm/PyPI downloads (Nov 2, `ph_predict/c1_user_base.py`)
**Reference: the live forecast's honest set, day-calibrated (62.7 / 70.4 / 76.6 daily, May–Oct).** Data: Data Feeder's star history (raw/github_stargazers/star_history_ph_0000.jsonl: 732 repos, daily new stars from /stargazers/history; per-user star times are no longer public) and raw/pkg_downloads/ (draft). Only own repos and packages (a name token shared with the launch) are kept: 558 of 1,060. Every count is strictly before the launch's Pacific day.

- **Coverage:** 255 launches with stars before launch and 96 with downloads; 5.7% of launches have either. By month: May 7.2%, Jun 8.0%, Jul 7.2%, Aug 9.8%, Sep 6.4%, Oct 9.4%.
- **Gate** (Spearman with the honest residual, Holm-corrected across the 6 inputs). Within-day can't be read: only 11 days have 5+ covered launches.

  | Input | Pooled over covered launches (95% CI) | Holm p |
  |---|---|---|
  | Stars as of day−1 | 0.117 (0.002, 0.226), 250 launches | 0.09 |
  | **New stars in the 30 days before** | **0.165 (0.047, 0.277)** | **0.02, passes** |
  | Repo age | 0.007 | 0.91 |
  | **Downloads 7 / 30 / 90 days before** | **0.27 / 0.32 / 0.30** (CI ~0.10–0.49), 95 launches | **≤ 0.02, pass** |

- **Boards**, control (62.7 / 70.4 / 76.6 daily; weekly 50.7 / 54.4 / 55.2; monthly 13.3 / 26.7 / 33.3) vs + C1, paired:

  | | Trees | Linear arm |
  |---|---|---|
  | Daily | −0.2 / −0.2 / −0.1 | −0.4 / 0.0 / +0.1 |
  | Weekly | −1.3 / −0.8 / +0.4 | 0.0 / 0.0 / 0.0 |
  | Monthly | 0 / 0 / 0 | 0 / 0 / +1.7 |

  All within noise.
- **Reading:** a launch whose product already has users (recent stars, package downloads) beats the honest forecast, a real per-launch signal (+0.16 to +0.32). At 5.7% coverage it can't move a board, though. C1 is a valid input to keep (honest, dated), not a route to 90. Wider coverage would need other dated user-base records: Chrome Web Store and app-store counts via Wayback, Discord member counts, newsletter subscribers.
- **Deployed and verified (Nov 3, 00:40 UTC), bundle 5, scoring only (standing rule 2, confirmed by Shreyas in the PH ops session):** the `poolscore` step (pool Spearman and pool share of votes at d−7 complete and d−1 provisional → pool_scores). Dry-run in a /tmp copy on the VM first. Live md5s match the repo (daily.py 1a019b4f, run_daily.sh a94dea22); backup at ~/w/backup_b5/; recorder untouched. The `llm_full` honest filter (changes the headline forecast) waits for Shreyas.

## A1: each team's full launch history as a pre-launch input (Nov 3, `ph_predict/a1_fetch.py` + `a1_team_history.py`)
**Reference: the live forecast's honest set, day-calibrated (62.7 / 70.4 / 76.6 daily, May–Oct; weekly 50.7 / 54.4 / 55.2; monthly 13.3 / 26.7 / 33.3).**

**Data:**
- user.madePosts / submittedPosts return nothing for other users, so the history comes from a paced crawl of the featured-posts list per day for 2024–2025 on usersim-pipeline (approved by Shreyas): 731 days, 12,472 launches, 952 calls, finished 01:54 UTC.
- Merged with our own Jan–Oct 2026 day files: 39,062 username–launch rows, 20,114 people.
- [REDACTED] makers (about 40% from the API) are missing; Data Feeder is resolving them from /products/<slug>/makers.
- Only launches dated strictly before each launch's day count.

**Coverage:** 3,343 of 6,540 launches (51%) have a team member with an earlier launch. Before, our Jan+ files found repeat makers for 4–11%.

**Gate** (Spearman with the honest residual, Holm across 8 inputs; team size is the reference column):

| Input | Within day (95% CI) | Pooled (95% CI) | Holm p |
|---|---|---|---|
| **Mean log votes of earlier launches vs their month** | **0.067 (0.024, 0.110)** | **0.074 (0.035, 0.110)**, 2,878 launches | **0.008, passes** |
| **Share of earlier launches in the daily top 5** | **0.053 (0.009, 0.096)** | **0.060 (0.023, 0.095)** | **0.049, passes** |
| Max relative votes | 0.023 | −0.006 | 1.0 |
| Count of earlier launches / made / days since / first-time | about 0 | about 0 | 1.0 |
| Team size (reference) | −0.043 | −0.015 | 1.0 |

How well a team's earlier launches did predicts where the honest forecast under-predicts, beyond team size. How many launches they had does not.

**Boards** (control vs + A1, paired):

| | Trees | Linear arm |
|---|---|---|
| Daily | +0.6 (−1.1, +2.3) / +0.7 (−0.6, +1.9) / +0.3 (−0.5, +1.2) | −1.7 / +0.6 / −0.2 |
| Weekly | −1.3 / −0.8 / −0.4 | −1.3 / +0.8 / −1.3 |
| Monthly (6 lists) | 0 / −3.3 / +3.3 | 0 / 0 / +5.0 (+1.7, +8.3) |

All within noise. The monthly top 10 is one list moving (Aug +20).

**Reading:**
- A real honest signal at half the launches (within-day 0.07), but small: on top of the honest model, the daily board doesn't move beyond noise.
- The team's track record mostly carries what the launch model already sees. The honest launch model already has hist_ from our Jan+ files.
- Next: rerun with the resolved [REDACTED] makers (Data Feeder). Feed A1 into the shock model as a candidate input to see whether it raises honest shock predictability (0.395).
- **A1 in the honest shock model** (`shock_model.py` stage 1, HONEST=1, EXTRA_FEATS = A1 inputs; Jun–Oct, 146 days): within-day Spearman with the real pool shock **0.402 vs 0.395** without A1, +0.007 (−0.009 to +0.023). Better in 3 of 5 months (Jun 0.404→0.393, Jul 0.465→0.479, Aug 0.399→0.416, Sep 0.356→0.380, Oct 0.335→0.321). Within noise: the team's earlier performance barely adds to the honest shock prediction, consistent with the board result. Rerun with resolved makers when they land.

## A2: the team's own Product Hunt activity in the days before launch (Nov 3, `ph_predict/a2_team_activity.py`)
**Reference: the live forecast's honest set, day-calibrated (62.7 / 70.4 / 76.6 daily, May–Oct).** Per launch, the makers' and hunter's events on other launches strictly before launch day, from the warehouse: events in the 7 / 14 days before, distinct launches touched, active members, days since the last event. Team size is in the honest model already.

**Leak check:** upvotes are dated to the upvoted launch's day, not to when they were cast. A team upvoting older launches on its own launch day (reciprocal upvoting is common then) would count as "before". Comments carry their own date, so the comments-only run is the honest one.

| | All events (upvotes + comments) | **Comments only (honest)** |
|---|---|---|
| Launches with team activity in the 14 days before | 2,740 | 1,322 |
| Gate, within-day Spearman (95% CI), Holm | act14 0.079 (0.041, 0.117); launches14 0.081; all pass | **act7 0.058 (0.020, 0.096); act14 0.056; launches14 0.055; members 0.044; all pass** |
| Daily top 3 / 5 / 10, Δ vs control | **+2.1 (+0.2, +4.0)** / −0.1 / +0.6 (0.0, +1.2) | **+1.3 (−0.2, +3.0)** / 0.0 / +0.1; top 3 better in 5 of 6 months, never worse |
| Weekly top 3 / 5 / 10 | +1.3 / +0.8 / +1.7 | −4.0 (−9.3, +1.3) / −0.8 / +0.4 |
| Monthly top 3 / 5 / 10 (5–6 lists) | +6.7 / 0 / +1.7 | +13.3 / +3.3 / +3.3 |

**Reading:**
- A team that has been active on Product Hunt in the two weeks before its launch (commenting on others' launches) beats the honest forecast.
- It's the first honest pre-launch input whose daily top-3 effect leans positive in every month: +1.3, interval just touching 0.
- The all-events version's +2.1 partly reflects upvotes cast on launch day, so it isn't claimed.
- It is preparation behaviour (organised mobilisation), the shock's mechanism.
- Next: comments at hour precision (the honest cut-off is 00:00 PT on launch day, not the calendar day); the team's upvotes once they're timed by the daily refresh; and A2 in the honest shock model.

## Joint test of the honest small inputs, and A1 + A2 in the honest shock model (Nov 3, `ph_predict/joint_honest.py`, `shock_model.py EXTRA_FEATS`)
**Reference: the live forecast's honest set, day-calibrated (62.7 / 70.4 / 76.6 daily, May–Oct).** Inputs: A1 (team history: mean relative votes, top-5 share, count, first-time), A2 comments only (team comments on other launches 7 / 14 days before, launches touched, active members, days since), C1 (stars, new stars, downloads). One model; paired by list.

| | Trees | Linear arm |
|---|---|---|
| Daily top 3 | **64.6, +1.9 (0.0, +3.8)**; by month May +7.5, Jun +2.3, Jul 0, Aug +1.1, Sep 0, Oct 0 (never worse) | −0.2 |
| Daily top 5 | 69.8, −0.6 (−1.8, +0.7) | −1.7 (−3.2, −0.3) |
| Daily top 10 | 77.2, +0.7 (0.0, +1.4) | −0.3 |
| Weekly top 3 / 5 / 10 | 0.0 / 0.0 / 0.0 | −1.3 / +1.6 / −1.7 |
| Monthly top 3 / 5 / 10 (5–6 lists) | +6.7 / +6.7 / +3.3 | +6.7 / +3.3 / −1.7 |

**Honest shock model** (stage 1, HONEST=1; Jun–Oct, 146 days), with A1 + A2: within-day Spearman **0.413 vs 0.395**, **+0.018 (+0.002, +0.035)**, better in 4 of 5 months (Jun 0.404→0.393, Jul 0.465→0.482, Aug 0.399→0.444, Sep 0.356→0.392, Oct 0.335→0.336). A1 alone was +0.007, so A2 carries most of it.

**Reading:**
- Together the honest inputs add to the shock prediction (interval above 0) and lean positive on daily top 3 (+1.9, lower bound 0.0, never worse by month), with top 10 +0.7 (lower bound 0.0).
- That's below the ±3.5 noise rule for daily top 3, so not a claimed board gain. But it's the first honest bundle whose shock and top-3 intervals sit at or above 0.
- Next: the A2 refinements (00:00 PT cut-off, 24 / 48 h windows, which launches the team commented on), and live recording of A2 from today. A2 needs only dated comments, so it's honest for every live launch.

## A1 with resolved makers, first batch (Nov 3, `a1_team_history.py RESOLVED=…`)
**Reference: the live honest set, day-calibrated (62.7 / 70.4 / 76.6 daily, May–Oct).** Data Feeder resolved 435 of 2,349 products with redacted makers (18.5%; 1,493 pages had no makers block anonymously, 415 were empty).

- **Merge:** 860 history rows added; 412 launches' teams extended.
- **Coverage:** launches with a team member's earlier launch, 3,343 → **3,355** of 6,540 (51.1% → 51.3%). The slope is small: about 0.03 launches with new history per resolved product. Most resolved makers' earlier launches weren't in the crawl window, or their teams were already covered.
- **Gate:** mean relative votes 0.068 (0.024, 0.111), top-5 share 0.053 (0.008, 0.096); both pass, unchanged.
- **A1 alone, daily:** +0.6 / +0.7 / +0.3, as before.
- **Joint A1 + A2 + C1, daily top 3 / 5 / 10:** +1.1 (−0.8, +3.0) / −0.5 / +0.7 (−0.1, +1.4); by month May +7.5, Jun +2.3, Jul −1.1, Aug −1.1, Sep 0, Oct −1.3. Was +1.9 (0.0, +3.8). The ±1 swing from a small input change shows the top-3 effect isn't stable.
- **Weekly:** −1.3 / 0 / −0.4. **Monthly:** +6.7 / +6.7 / +3.3.
- **Honest shock model + A1 (resolved) + A2:** 0.415 vs 0.395, **+0.020 (+0.003, +0.037)**. This is the stable signal.
- **Reading:** the resolved makers barely change coverage. The shock gain holds (+0.02, interval above 0). The board gain is fragile and isn't claimed.

## C2 source 1: domain Wayback captures before launch (2026-11-03 08:20 UTC)
Reference: honest - live set (62.7 / 70.4 / 76.6 daily top 3/5/10, May–Oct). Inputs: distinct capture days of the launch's
domain in the 90 / 365 days before launch day, and domain age (first-ever capture to day−1). Free CDX API from exp-1.
Coverage 64.6% of all launches (88–91% per month May–Oct; Mar–Apr have no targets). No rows on or after launch day.
- Gate: fails on all three (within-day Spearman −0.015 / −0.014 / −0.009, all CIs span 0; Holm p 1.0 / 1.0 / 0.34).
- Boards (trees): daily top 3 −0.9 (−1.9 to 0.0), top 5 −0.1 (−0.6 to +0.3), top 10 −0.3 (−0.8 to +0.2).
  Linear arm: −0.4 / −0.1 / +0.1, all spanning 0. Weekly and monthly unchanged within noise.
- Verdict: null. Whether a domain is archived, and how often, says nothing about the shock beyond the honest model. Drop it.
  Wayback profile captures (Data Feeder's wayback_profiles.jsonl) are scored separately when they land.

## Bundle 6 deployed: shadow_honest_a2 (2026-11-03 09:02 UTC, standing rule 2)
Trial forecast only; headline unchanged. Live offset (forecast_<day>.parquet) + day terms + A1 team history + A2 team
comments 7/14 d before. Package from bucket tmp/ph_ops/shadow_honest_a2/ into ph_predict/data/shadow/honest_a2/;
daily.py SHADOW_DEFAULT = "daycal,honest_a2" (md5 e25d6237); run_daily.sh unchanged (a94dea22). Backup ~/w/backup_b6/.
Checks: live test for 2026-11-03 in a /tmp copy (36/36 launches; A1 history for 14, A2 comments for 6); dry s_shadow
from a /tmp copy of the pipeline ok (72 rows, nothing written); installed run identical. vs live forecast today:
Spearman 0.995, top 3/5/10 identical. First real row: the Nov 4 run; scored Nov 5 as shadow_honest_a2.
Rollback: tar xf ~/w/backup_b6/before.tar -C ~/w/experiments; rm -rf ~/w/experiments/ph_predict/data/shadow/honest_a2

## Bundle 7 deployed: line-up gap counts in daily scores (2026-11-03 09:10 UTC, standing rule 2)
`score` adds late_featured (final featured launches not in the 00:05 PT line-up; they count as misses), late_in_top_k
and dropped_from_featured to each daily_scores row. Scoring only. daily.py md5 d6f4190c (was e25d6237); backup
~/w/backup_b7/. Tested from a /tmp copy with writes stubbed: Nov 2 gives late_featured 1 (redu.cloud, rank 17),
late_in_top_k 0 for k = 3/5/10, dropped 0, and unchanged hits (1/3, 4/5, 9/10). First real row: the Nov 4 run.
redu.cloud: first in vote_snapshots at 10:00 UTC (not at 08:10 / 09:00), old post id, API featuredAt backdated to
08:01Z -> featured late, not an API gap.

## At-launch capture reader (ph_predict/at_launch_reader.py)
raw/ph_at_launch/<day>/ -> ph_userbase rows (launch: post / product / product X and GitHub; people: PH profile counts,
X / GitHub per maker and hunter). Pre-launch = fetched before the launch's first non-zero vote snapshot (and 0 votes
shown, for post rows); otherwise dated to launch day so c2 drops it. Pilot (fetched ~10.5 h after votes started):
0 of 715 rows pre-launch, as it should be. Synthetic checks pass (all four cases). c2_user_base reads both outputs.

## Bundle 8 deployed: at-launch capture trigger (2026-11-03 09:13 UTC, standing rule 2)
`launches` uploads data/today/<day>.json to raw/daily/<day>/today_0005.json right after the line-up read (~00:06 PT),
for Data Feeder's capture to start on (VM at 00:05 PT, fetch by ~00:20). Recording only. daily.py md5 27f0578d (was
d6f4190c); backup ~/w/backup_b8/. Upload command tested on the VM (byte-identical copy, test object removed). First
real trigger: Nov 4 ~00:06 PT. A failed upload marks `launches` failed (the line-up itself is already written).
Reader: labelled relaxed variant for profile-level sources (fetched within 60 min of the launch start; never post
rows), pre_launch_relaxed on every row, RELAXED=1 to score it. Strict rule unchanged and remains the headline rule.

## At-launch capture, first real day (2026-11-03) and a fix to the pre-launch rule
Capture: 36 launches, 74 people, fetched 09:45–09:52 UTC (01:45 PT), ~1 h 45 min into voting. X counts still pending.
Finding: PH hides vote counts for ~4 h, on the page (hide_votes_count, all 36) and in the API (vote_snapshots: 0 votes for
every launch until 12:00 UTC = 04:00 PT on Nov 2; comments are visible from the first 00:06 PT snapshot). So "fetched
before the first non-zero vote snapshot" alone would pass captures made hours into voting. Tightened (never looser):
also fetched within 20 min of the launch start, and post activity counts (votes, comments at fetch) are never pre-launch.
Nov 3 is day 0 (late capture, 0 rows): 0 of 1,144 rows pre-launch (strict) and 0 relaxed, as expected for 01:45 PT.
Rerun on the X-filled version (10:40 UTC): 0 of 1,215 rows (71 X rows added), strict and relaxed.
Rule confirmed by the orchestrator (10:05 UTC): all three conditions kept; relaxed variant stays labelled; bar 00:20 PT. Synthetic checks
(5 cases, incl. a 104-min capture the old rule passed) all behave. From Nov 4 the capture is due by ~00:20 PT.

## Wayback profiles: v1 plumbing dry run (2026-11-03 ~16:30 UTC; partial file, not a result)
v1 partial: 2,806 rows, 513 launches, nearly all May (coverage 59% of May, <3% other months). Four variants ran end to
end (both roles, both within 30 d, hunter-only, maker-only; SEEDS=1). As expected on this coverage: nothing passes the
Holm gate and the daily boards don't move (62.7 / 70.4 / 76.6 vs honest live set). No conclusion until v2.
Fixes found: (1) the file's as_of_date is the capture's UTC date; we date by capture_ts in Pacific time (204 v1 rows are
captured the evening before launch PT but on launch day UTC: kept, as the 00:00 PT rule says); (2) capture_ts is
Wayback's 14-digit form, parsed explicitly; (3) one capture gives all metrics of a person, so ages repeated 3x: now one
age input per role (followers, filled from another metric), 6 -> 2 inputs for Holm.

## Bundle 9 prepared, not deployed: llm_full leaves the headline forecast (needs Shreyas)
model.py one line (1dc0f8a): honest_drop() adds llm_full (its prompt carries follower counts). Deployed model.py is
the pre-change version (md5 3f816494); b9 is 379ff10a. Verified on usersim-pipeline (read-only, /tmp copies): with the
real feature columns + LLM scores, live inputs 46 -> 45, only llm_full removed (filled for 99.3% of launches); imports
and step order ok in a /tmp copy. pipeline/vm/deploy_b9.sh refuses inside 00:05-01:00 PT, checks both md5s, backs up.
Reference backtest: honest.py now has "honest - live set + llm_full" (= the deployed forecast) next to "honest - live
set" (62.7 / 70.4 / 76.6, = after b9), and VARIANTS / HONEST_OUT to run just those two without overwriting
results/honest.*. To run on exp-1 when it is next started.

## Standing instruction from Shreyas (PH ops session, 2026-11-03 ~17:30 UTC)
"Next time don't ask and defer to the prediction agent for all actions": PH ops acts on the orchestrator's decisions
without asking Shreyas first. Fixed safety rules still apply (no credentials, no usernames in commits, nothing in
00:05-01:00 PT, the session's own permission checks). Same message approved resizing exp-1 to e2-standard-8 (done
17:24 UTC) and bundle 9; staging bundle 9 was blocked by the session's permission check (production deploy) and is
handed to the orchestrator / Grok Bot to stage from the repo.

## Day strength (weekly-board magnitude, day level) — 2026-11-03 17:30 UTC, exp-1 (e2-standard-8, 5 seeds)
Reference: honest live set with the day-calibrated control (userbase_eval), May–Oct, 178 days. Leak check passed.
- Gate (day level, out of sample): Spearman of predicted vs actual day strength 0.583 (0.47, 0.68) vs the control's
  implied level 0.261 (0.11, 0.40); difference +0.32 (+0.21, +0.44). MAE 0.088 vs 0.109. Passes clearly.
- Weekly boards vs control (50.7 / 54.4 / 55.2): strength −2.7 (−9.3, +4.0) / −0.8 (−4.0, +1.6) / −0.4 (−1.7, +0.9);
  blend 0.0 (−5.3, +5.3) / +1.6 (0.0, +4.0) / −0.4. Raw (no day level) −5.3 (−10.7, −1.3) on top 3.
  Monthly (5–6 lists, too few): strength +6.7 / 0.0 / 0.0. Daily unchanged by construction.
- Reading: a much better day level does not move the weekly top-k; the weekly board turns on launch-level magnitude
  within days (E5's hourly position-feedback curve). Per-day s_pred (day, fold, s_pred; 178 days) uploaded to
  tmp/e5/day_strength_pred.parquet for the combined arm.

## llm_full reference backtest (bundle 9) — honest live set with vs without llm_full, 5 seeds
May–Oct daily top 3/5/10: 62.7 / 70.4 / 76.6 both ways; Δ 0.0 (−1.9, +1.7) / 0.0 (−1.0, +1.0) / 0.0 (−0.6, +0.6).
Jul–Oct daily: with 63.5 / 69.7 / 77.0, without 64.4 / 69.6 / 77.1; Δ top 3 +0.9 (−1.4, +3.1).
Weekly (no day calibration): Δ top 3 +2.7 (0.0, +6.7), top 5 −1.6 (−4.0, 0.0), top 10 −0.4 (−2.6, +1.7).
Removing llm_full costs nothing measurable; the reference 62.7 / 70.4 / 76.6 stands for the post-b9 forecast.
Procedure (orchestrator, 18:00 UTC, relaying Shreyas): when a permission or safety check blocks an action, don't work
around it or wait in this session; file mailbox/to_grokbot/<UTC>_SECURITY_ph-agent_<topic>.md (what was blocked, the
check's category, why it's needed, the exact unblock step for Shreyas), tell the orchestrator in one line, carry on.
The bundle 9 block is already filed by the orchestrator (20261103T1800_SECURITY_ALERTS_to_grokbot.md).
Bundle 9 deploy request filed with Grok Bot by the orchestrator (to_grokbot/20261103T1810_ph_bundle9_llm_full.md), to
deploy before 00:05 PT Nov 4. At the Nov 4 01:07 PT check: confirm ph_predict/model.py md5 379ff10a on the VM, a
from_grokbot reply, and that the forecast step used 45 live inputs (no llm_full).
**Bundle 9 deployed by Grok Bot (17:59 UTC) and verified by PH ops (~18:05 UTC):** ph_predict/model.py 379ff10a on the
VM (backup ~/w/backup_b9/before.tar holds 3f816494); daily.py 27f0578d and run_daily.sh a94dea22 unchanged; with the
deployed model, real feature columns + LLM scores give 45 live inputs, no llm_full. First forecast without it: Nov 4.
Headline reference from now: honest live set 62.7 / 70.4 / 76.6 (the with/without backtest shows no difference).

## Wayback profiles, v1 final (api makers only) — 2026-11-03 ~18:55 UTC, exp-1 e2-standard-8, 5 seeds
Reference: honest live set 62.7 / 70.4 / 76.6 daily (weekly control 50.7 / 54.4 / 55.2). Pre-launch = captured before
00:00 PT of the launch day (6 launch-day rows dropped). Inputs per launch: max over makers and the hunter of followers,
followings, points at the latest pre-launch capture, plus one age per role.
Coverage (all launches / May–Oct by month): both roles 42.3% (May 70%, Jun–Oct 53–62%); within 30 d 26.5%;
hunter 41.5%; maker 25.7% (34–38% each month).
Gate (Holm): passes only for followings — hunter within-day ρ 0.072 (0.025, 0.119), maker 0.064 (0.008, 0.120);
hunter capture age −0.065 (hunter-only run). Follower counts and points fail. Within 30 d: nothing passes.
Boards vs reference (Δ, 95% CI):
| variant | daily top 3 | top 5 | top 10 | weekly top 3 | top 5 | top 10 |
|---|---|---|---|---|---|---|
| both roles | −0.8 (−2.1, +0.6) | −0.8 (−1.7, 0.0) | 0.0 | 0.0 (−4.0, +4.0) | −0.8 | +0.4 |
| both, ≤30 d | −0.8 (−2.1, +0.6) | −0.1 | +0.1 | +1.3 (−4.0, +8.0) | +0.8 | 0.0 |
| hunter only | −1.3 (−2.8, 0.0) | −0.7 | +0.2 | +2.7 (0.0, +6.7) | +0.8 | +0.9 |
| maker only | +0.4 (−0.9, +1.7) | −0.6 | +0.1 | −2.7 (−6.7, 0.0) | +0.8 | +0.9 (0.0, +2.2) |
Monthly: 5–6 lists, too few. Verdict on v1: a small real signal in followings, but no board gain; dated pre-launch
follower counts add nothing beyond the honest model. v2 (resolved makers) to be run with the same config and
reported side by side with the maker_source split.
