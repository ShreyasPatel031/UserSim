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
