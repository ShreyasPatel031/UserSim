# Cohort calibration: who backs and comments, and what they say, predicted vs real

Orchestrator 08:53Z and 08:54Z Nov 21 (Shreyas). Written and committed **before** the first truth (Nov 22) and before the backtest is scored.

## Units and truth

**Groups** are the data-driven segment cut current on day D: private person→group map `tmp/e5/private/segments/<cut>.parquet`, latest cut ≤ D. Cuts exist from Nov 15. Days before Nov 15 use the Nov 15 cut and are flagged "groups fit after the day": the predictions are frozen, only the labelling is later.

**Real backer cohort** of a launch: held complete people (`persons.complete`) whose own upvote list contains the launch. Only people whose profile was re-read after the day closed (PT) can show the vote, so only they count. **Coverage** = real backers found ÷ the launch's PH votes; it is reported beside every number.

**Real commenter cohort:** non-team commenters of the launch (`raw/ph_at_launch/<D>/api_comments*`; team = makers in `api_teams` plus the hunter) matched to held people by PH user id. Coverage = matched ÷ non-team commenters.

## Metrics

### WHO

**Segment-mix distance.** Jensen–Shannon distance (base 2, 0–1) between the predicted and the real group mix.
- Scored per launch with ≥ 20 real backers.
- Commenters are pooled per day (≥ 20 matched commenters), because a launch rarely has 20.
- Predicted mixes, each compared with the same real mix:
  - **P1** — the explain file's frozen `who.groups_expected` shares (written before results; Nov 15 on);
  - **P2** — the frozen CF backer list (`tmp/e5/private/backer_pred/<D>`, p summed by group; Nov 8 on);
  - **BASE** — each group's share of held upvotes in the 30 days before D.
- **Pass:** P1 (and P2) beats BASE, i.e. the paired per-launch difference (pred − BASE) has a day-bootstrap 95% upper bound < 0. Absolute bar for "calibrated": mean JSD ≤ 0.10.

**Backer recall@N.** Published line (raw most-active) and CF shadow, complete people, from `raw/_audit/backer_prediction/<day>.json`, with coverage.

**Persona origin** (daily, once the plugin sends its persona list). Share of the plugin's personas whose source group is among the groups that together hold ≥ 80% of the launch's real backers. **Pass:** ≥ 0.8.

**Which launches we pick wrong.** Per-launch JSD (P1 or P2) against:
- the launch's main topic family (developer / AI / marketing / design / other);
- final daily rank (1–5, 6–10, 11+);
- PH votes;
- the share of real backers who are new to the store (first read ≤ 30 days ago).
Reported as means with intervals. Descriptive only, no pass bar.

### WHAT THEY SAY

**Theme precision and recall** of the explain `say` block against real comment themes. Applies to:
- reactions, top concerns and top questions (the deployed /try simulator, frozen before comments);
- the persona panel;
- the plugin's simulated users, once received.

**Method.** Gemini 2.5 Pro judge at temperature 0, as in `forward_sim.py`:
- one pooled, blinded call per launch per kind;
- real top points extracted with flash;
- precision = share of predicted items matching a real point;
- recall = share of real points matched;
- launches with ≥ 5 non-team comments.

**Per segment:** the same judge, using only the comments of held commenters of that group against that group's panel items, where a group has ≥ 20 matched commenters pooled over days.

**Pass:** precision@3 minus a constant base-rate list > 0, day-bootstrap lower bound. This is the running forward rule.

## Output and history

- **Daily file:** `results/calibration/<D>/cohort_scorecard.json`, versioned as `cohort_scorecard.v<k>.json` plus a `history.jsonl` line per scoring run, so tuning shows over days. Aggregates only, groups of 20+, no usernames or person ids.
- **Backtest:** `results/calibration/backtest_v1/cohort_backtest.json`, with the per-day series.

## Leak rules

- Predictions are only files frozen before the launch day (explain, `backer_pred`), or computed from data dated before D (BASE).
- Real cohorts use reads after the day closed.
- The segment labelling for days before Nov 15 is flagged as above.

## Addendum, 09:19Z Nov 21 (orchestrator: "calibrated user traces are our core IP")

Written before either new metric is scored.

### LIKELIHOOD TO VOTE
**Prediction:** the per-person vote probability `p` from the frozen backer list (`tmp/e5/private/backer_pred/<D>.parquet`, top 2000 held people per launch, reads before 00:00 PT). It is scored two ways:
- (a) as written;
- (b) after an isotonic recalibration fit only on earlier scored days, as in `expected_voters.py`.

**Truth:** the person voted for the launch.

**Who counts:** only held complete people on the list who were re-read after the day closed, since only they can show the vote.

**Report**, overall and per group of the day's cut (groups with ≥ 20 scored people and ≥ 20 votes):
- a reliability curve (10 equal-count bins of predicted p: mean predicted vs observed rate, with counts);
- Brier score and log loss (p clipped to [1e-4, 1 − 1e-4]);
- the same two scores for a constant-rate baseline (the earlier days' observed rate);
- backer recall@N alongside.

**Pass:** (b) beats the constant baseline on both Brier and log loss, day-bootstrap upper bound of the paired difference < 0, and the reliability-curve slope is in [0.8, 1.2].

### SENTIMENT
**Labels:** each predicted say item and each real non-maker comment is labelled positive, neutral or negative. Gemini 2.5 Flash, temperature 0, one call per launch per side, blinded to which side is which. Predicted items cover the explain say reactions, concerns and questions, the persona panel items, and the plugin personas' feedback when received.

**Report:**
- per launch with ≥ 5 real comments, the Jensen–Shannon distance between the predicted and real sentiment distributions;
- agreement: the share of launches where the majority sentiment matches;
- per group, where held commenters of that group number ≥ 20 pooled.

**Baseline:** the real sentiment distribution of all earlier days' comments, as a constant prediction.

**Pass:** the predicted distance is below the baseline distance (paired, day-bootstrap upper bound < 0).

### Versions
Every scorecard version is kept as `cohort_scorecard.v<k>.json` plus `history.jsonl`. Metrics are only added or tuned, never dropped.

## Addendum 2 (2026-11-21): size-weighted topic blend (WHO) and sentiment re-weight (WHAT)
**Blend.** P6 = w·P3 + (1−w)·BASE, w = f(expected rank band) with bands from the then-published 00:05 forecast predicted rank (1-5, 6-10, 11+, none).
w per band chosen on a 0..1 grid (step 0.1) minimising mean JSD on Oct 22–Nov 10; tested once on Nov 11–20. Priors use only cohorts of days < D.
Pass = P6 minus BASE and P6 minus P3 both have day-bootstrap upper bound < 0 on the test days. Report overall and by final rank band.
Caveat: the 00:05 forecast files before Nov 17 were written after the fact by the then-published model (frozen_before_reveal false).
**Sentiment re-weight.** Fit on real comment labels from days before Nov 15 (backtest_v1 days with labels): per-launch predicted label shares are
mapped by s' = normalise(s · r), r = (real mean share / predicted mean share) where the predicted side for the fit comes from the Nov 15 prompt outputs only if earlier ones are absent (then r fit by leave-one-day-out on Nov 15–20 and flagged).
Pass = JSD paired vs unadjusted predicted, upper bound < 0, on Nov 15–20 out of sample. Prompt changes follow the same bar.

## Addendum 3 (2026-11-21): broad-theme precision and the plain-prompt baseline (WHAT)
forward_says.py (same TRUTH/JUDGE/CT/CJ prompts as the harness) on Nov 15-20 frozen persona panels vs real non-team comments (>= 5).
Plain arm: one Gemini 2.5 Flash call per launch with only name, tagline and description: "write N short comments Product Hunt users would leave"
(N = panel size), judged with the same prompts. Pooled over days, day bootstrap. Thresholds: broad-theme recall >= 70 with precision >= 50 (panel);
specific issues = complaint recall, panel minus plain, pass = lower bound > 0.

## Addendum 4 (2026-11-22, Shreyas): LLM vote simulation for active users vs real votes
Days Nov 14-16 (the latest days with people re-read after close). Per day: 60 active people sampled at random (seed 0) among complete people
held before the day, re-read after the day's close, with >= 20 upvotes on launches in the 30 days before. Each person: one Gemini 2.5 Flash call
(Gemini API key given by Shreyas Nov 22), given their 40 most recent upvoted launches before the day (name + tagline + topics) and the day's
line-up (name + tagline + topics), returns a 0-100 likelihood per launch. Truth: the person's upvotes on that day's launches.
Baselines on the same person x launch cells: (CF) frozen CF list p (0 if not listed); (POP) the frozen 03:45 pre-reveal rank (Nov 14+);
(TOPIC) share of the person's history sharing a topic with the launch. Metrics: pooled AUC, mean per-person AUC, recall@5, day bootstrap.
Pass: LLM minus best baseline AUC lower bound > 0. Also report LLM+CF rank average.
Addendum 4b (2026-11-22, Shreyas: "give it the signals that already work"): same people, days and cells; the prompt also gets each launch's frozen
03:45 predicted rank, the share of the person's history sharing a topic with it, and the person's average upvotes per active day (asked to make
likelihoods sum to about that). Pass: LLM-v2 minus POP pooled AUC lower bound > 0; also report rank-average(LLM-v2, POP).

## Addendum 5 (2026-11-23): BACKER-v2 — beat "N most active" at naming backers
Test days Nov 8-21; truth = upvotes on D's launches by complete people held before D's start and re-read after D's close (same subset for every
candidate). Per launch N = number of such backers; recall@N, launch mean weighted by N (vote-weighted), all launches and final top-3.
Candidates: (1) most active (upvotes on launches in the 30 days before D, read before D's start); (2) frozen CF list p (tmp/e5/private/backer_pred,
unlisted people ranked after listed, by (1)); (3) logistic P(vote) on [ln(1+recency-weighted upvote count, 7-day half-life), topic match, follows
hunter/maker (follow edges read before D's start), ln(1+rw) x topic match], fit walk-forward on days from Oct 25 to D-1 only (negatives subsampled
5%, seed 0); (4) = (3) with people active in the last 7 days ranked first. Paired difference vs (1), day bootstrap 95%.
Pass: lower bound > 0 -> published backer list (rule 5), old list kept as shadow.

## Addendum 6 (2026-11-23): SIM-RERANK-1 Stage A (no language model)
Structural order = the then-published 00:05 forecast (results/web/forecast_0005/<D>.json, run ~00:15 PT); shortlist = its top 20.
Features from the BACKER-v2 list for D (tmp/e5/private/backer_pred_v2/<D>.parquet, top 2000 per launch): F1 expected held voters = sum p;
F2 propensity-weighted = sum p x (share of the 30 days before D with >= 1 upvote, reads before D's start); F3 sum p over people in top-3-prone
groups (segment cut in force on D; groups whose share of held backers of final top-3 launches in the 30 days before D is >= 1.1x their share of all
held backers then). Blend score = z(-structural rank) + w x z(ln(1+F)) within the day; w from {0, 0.1, 0.25, 0.5, 1, 2, 4} maximising the mean of
top-3/5/10 capture on earlier test days only (w = 0 until 3 earlier days). Metric: |re-ranked top k ∩ real top k| / k for k = 3, 5, 10, paired vs the
structural order, day bootstrap 95%; near-miss recovery (structural rank 4-6 that finished top 3 and moved into the re-ranked top 3) and cost
(real top 3 in the structural top 3 pushed out). Days: Nov 8-22 (v2 lists frozen as walk-forward replays) plus Oct 27-Nov 4 (labelled: v2 lists
built later as replays from upvote/follow history read before each day). Pass: a candidate's top-3 or top-5 capture minus structural lower bound > 0.
Addendum 6b (2026-11-23, before scoring): F4 = expected voters over the whole held complete pool (v2 logistic, subsampling-corrected, no top-2000
truncation); F5 = F4 restricted to people active in the last 7 days. Same blend, weights and pass rule. Added after F1-F3 showed the truncated lists
make F1 nearly flat; F1-F3 results stand as reported.

## Addendum 7 (2026-11-24): SIM-RERANK-1 Stage B (language-model agents, forward only)
Nightly, frozen to results/calibration/<D>/rerank_frozen.json before 03:45 PT. Shortlist = results/structural/<D>/shortlist.json top 20 (reported at 10 / 15 / 20).
Per launch: 50 people sampled (seed = launch id) from the top 200 of the BACKER-v2 list for D, plus 20 at random from the active pool (complete,
held before D's start, >= 1 upvote on launches in the 30 days before D). One agent per person, built only from that person's own last 30 upvoted
launches before D (name, tagline, topics) and up to 5 of their own comments on launches before D (@handles removed). The agent sees the launch's
page read (the /try nightly read, else the 00:05 name, tagline and description). No vote counts, ranks or comments of others. Output per agent:
vote yes/no, probability 0-100, one-line comment, sentiment pos/neu/neg. Model: Gemini 2.5 Flash (temperature 0) behind sim_model.call().
Features per launch: yes share, mean probability, sentiment shares (BACKER-top and random sub-panels kept separately).
Fixed rule: re-ranked key = structural_rank - 2 x z(yes share of all 70 agents), z within the shortlist; ties by structural rank.
Metric: top 3 / 5 / 10 capture by the re-ranked shortlist (10 / 15 / 20) vs the structural order, paired by day, day bootstrap; near-miss recovery
and cost; launches featured after 00:05 count as misses for both orders. First read at 7 scored days; weights fit only after that.
Also scored: agent votes vs held re-read backers (WHO), agent comments vs real comments with the WHAT judge (beside the persona panel).
Addendum 7b (2026-11-24, before the first frozen run): a dry run on 3 Nov 23 launches gave 87% yes (real base rate a few %). The prompt now also states
the person's own average upvotes per active day over the 30 days before D, and the day's line-up size, and asks the agent to keep that rate in mind.
Rule, panels and metric unchanged.
Addendum 6c (2026-11-24): long Stage A on the PH agent's structural backtest (Apr 15-Oct 31; arm 3 where present). Lenient as-of features: complete
people's upvotes on launches dated before D (no read-time cut, no follows: the store was read in Oct-Nov, so a read-time cut would empty these days;
store membership was chosen later, a selection caveat). Per day: logistic on [ln(1+rw), topic match, interaction] fit on the 14 previous days
(negatives 2%, seed 0); F6 = expected voters over the active pool (>= 1 upvote in the 60 days before D), subsampling-corrected. Same blend rule
(walk-forward w), shortlist 10 / 15 / 20, same metric and pass rule. Truth = final daily rank (structural file truth block).

## Addendum 8 (2026-11-24): Stage B v2 "pick k" arm (beside v1)
Same days, people panel (per launch: 50 from the v2 top 200 + 20 random active, pooled and de-duplicated across the shortlist), history and page
text (one line per launch: name - tagline, page-read summary first 160 chars). Each agent sees the whole shortlist, shuffled per agent (seed = hash
of person id), and picks the k launches it would upvote, k = round(own average upvotes per active day over the 30 days before D), min 1, max 5.
Feature = pick share per launch (picks / agents). Fixed rule: key = structural_rank - 2 x z(pick share). Same metric, freeze, first read at 7 days.
Addendum 8b (2026-11-24, orchestrator conditions, before the first frozen v2 run): each launch line uses only line-up fields that exist for every
launch at 00:05 PT (name, tagline, up to 4 topics, the launch's own description text cut to 160 chars; total cap 300), never the page read.
Order shuffled per agent with a recorded seed (md5 of person id + D); order and pick positions stored per agent; pick rate by position reported.
k stored per agent. Every prompt and raw response is stored in the private agent file. Secondary read (no waiting): agreement between each agent's
picks and the same person's real upvotes on the shortlist that day, for held re-read people who voted (Task V on the shortlist).
Both arms run in a fresh scheduled session (stageb_nightly.sh), not in E5's session; v1 there has no /try page reads, so its page text falls back
to the 00:05 name, tagline and description (recorded per launch as page_source).

## Addendum 9 (2026-11-24): person-built panel deployed (WHAT-PANEL-3 decision, orchestrator 14:29Z)
Nightly step 4b (person_panel.py) writes say.person_built_panel (15 comments per launch, no person keys) into results/web/explain/<D>.json.
Selection = simharness/run_what_panel.py build (parity: Nov 23 panel reproduced exactly, 27/27 launches, 810/810 rows) on the bench_v0 tables
(no forward overlays, so no day-of data); draw of 15 from the top 30 by md5(launch id + D); gemini-2.5-flash at temperature 0.7; FT_PROMPT with
the last sentence replaced by "Do not mention your own name, employer or products" + JSON instruction. Privacy guard: drop maker-like or
self-naming comments and comments that name a launch from the person's own rendered history, then take the next person in the draw.
forward_says.py main WHAT line = persona + person-built merged; persona-only = shadow, paired difference reported daily.
Revert rule (fixed): after 7 scored live days, revert to persona-only if merged precision is not above the shadow (paired interval includes 0)
or merged recall is clearly below it. Nov 24 = rehearsal (flagged rehearsal_late_unscored, not merged in the forward series).
Caveat: the bench tables are static (built ~Nov 23); people's histories after that are not in the prompts until the harness bench is refreshed.

## Addendum 10 (2026-11-24): CF+intensity shadow arm, tie-break bug fixed (orchestrator 23:18Z)
**Bug.** In `experiments/simlab/backer_arms.py`, the CF+intensity feature `bk_recent` ("backed the team's most recent launch") picks that launch with `max(set_of_team_launch_ids, key=launch_day)`. When several of the team's launches share the latest day, the winner depends on the set's iteration order, which depends on the per-process string hash seed. Found by comparing the off-session explain rehearsal (Nov 24) with the session run: CF+intensity kept the same people (99.98% set overlap per launch), but p differed by up to 0.079, so ranks shifted. CF-only, CF+back and A7 agree to 1e-14.
**Fix.** Deterministic tie-break: latest launch day, then smallest launch id. Gated on the test day, `D >= 2026-11-26`. The status line records `tie_break: day,min_id` (or `legacy_hash_order`). Check: two runs on D=2026-11-24 with the fix forced on and different PYTHONHASHSEED gave the same person at every rank in all four arms (max |dp| 1.8e-14).
**First night it applies.** The Nov 26 nightly (test day 2026-11-26). Nov 25 runs unchanged.
**Change point.** 2026-11-26 is a change point in the CF+intensity series. Rank-sensitive measures (precision/recall at k, rank of true backers) are not pooled or compared across it; each side is read on its own. Nights before Nov 26 were hash-order dependent, and their stored lists stay as they are. The other arms (CF-only, CF+back, A7) and the published v2 list are untouched.

## Addendum 11 (2026-11-25): PRODUCT-USE-1, simulated users use the product and two same-category competitors (orchestrator 00:17Z + amendment 00:23Z)
**Question.** When simulated users from a launch's likely cohort actually use it and its two nearest same-category competitors on the
category's core task, do (1) their preferences explain the structural model's miss, and (2) their problems and likes match what real users say?
**Line-up (frozen before 03:30 PT, before any rank is visible):** `experiments/simlab/product_use/lineup.py`
- Launches: the night's structural top 15 (results/structural/D/shortlist.json). Launch text is name, tagline, description and topics only (the 00:05 file's votes, comments and ranks are never read).
- Product URL: Gemini 2.5 Flash with Google Search grounding (url_source recorded). The Feeder's /r/ resolution has returned nothing since Nov 17.
- Category, in order:
  1. CATEGORY-1 table (simharness/taxonomy) when present.
  2. Otherwise a bge-small shortlist of 12 over every PH category held (91 pasted with descriptions, plus 248 from Similar Products), then a Gemini pick at temperature 0. Source and confidence are recorded; "no pick" falls back to the embedding top 1 with confidence low.
- Competitors (2), in order:
  1. Nightly PH Similar Products that share the category.
  2. CATEGORY-1 competitor sets.
  3. The category's 10 most-reviewed live products, ranked by embedding closeness to the launch.
  Each is resolved by grounded search and checked live through safe_fetch plus competitor_urls' same-site and product-host rules. The source of each competitor is recorded.
- Core task: one per category, written once by Gemini from the category description and frozen (category_tasks.json). Every product in a category is judged on the same job.
- Users: 4 per launch, the first 4 kept people of the person-built panel's pre-D selection. The profile is pre-D activity only (quoted comments removed). Person ids are hashed with D and stay private.
**Runs:** `runner.py`
- One MCP session per launch × user × product, on the seed VMs (Camoufox, own static IPs, producthunt.com blocked in the browser context).
- Driver: Gemini 2.5 Flash (scripts/mcp_runner_gemini.py, run_cell), at most 30 turns and $0.09 per session, $14 per night.
- Cells run launch by launch in structural order, so a budget stop cuts from the bottom of the top 15 and keeps 4 users per launch.
- One debrief per user (Gemini, temperature 0, reads only that user's own three step logs), per product:
  - completion;
  - artefact tag: signup_wall | captcha | block | js_only | timeout | engine | none, with evidence;
  - would-use 0-1;
  - top 3 problems and top 3 likes;
  - preference ordering with reasons.
- Steps to the first value moment come from the driver's VALUE_REACHED marker; error steps and seconds come from the log.
- Artefact-tagged sessions are excluded from product findings. The artefact rate is reported per launch.
- Full traces go to tmp/e5/private/product_use/D/traces (core IP, private). Frozen outputs go to results/calibration/D/product_use/ with the code commit and frozen_at.
**Simulation score:** sim_score = would-use × preference (launch's mean over non-artefact users). Preference = (n_ranked − rank)/(n_ranked − 1).
**Metrics** (forward days only; paired by day; day-bootstrap 95% intervals):
1. Residual:
   - (a) capture of the real top 3 / 5 when the structural top 15 is re-ordered by sim_score, minus the structural order's capture;
   - (b) within-day Spearman of sim_score with (real rank − structural rank).
2. Product reaction: recall and precision of real complaints, praise and competitor comparisons in D's comments, on the frozen consensus-theme scorer (forward_says.judge; truth extracted 3× and merged, kept if found in at least 2 of 3).
3. Calibration on competitors: problems and likes, and the preference ordering, against PH reviews of the competitor products dated after Gemini 2.5 Flash's training cutoff (2025-01-31). Source: raw/ph_predict_data/competitor_reviews.jsonl.gz plus any later review pulls.
**Controls on the same launches:** Stage B text-only agents (rerank_b / rerank_b2 scores), and the plain homepage prompt (e2e_vs_reviews/part1.py baseline: homepage via safe_fetch → themes).
**Scorecards:** overall, paired by day. Per category only for categories with ≥ 20 scored launches.
**Read:** first at 7 scored forward days (first frozen night: the Nov 26 PT launches), reported once. Nov 24 is a rehearsal (line-up built on Nov 25, after results), never scored.
**Leak checks:** no launch-day comments, votes or ranks in any input; commit and freeze time recorded; seed egress blocks producthunt.com.
**Known limits:**
- The URL and competitor resolution use live web search at freeze time.
- Similar Products before the nightly feed is up to Nov 1 only.
- Browser capacity is pending the orchestrator: anonymous MCP caps allow about 40 sessions/day per IP, and a night needs 180.
- 11a (Nov 25, before the first frozen night, from the Nov 24 rehearsal):
  - Sessions run in two waves: each launch's first user on every site first, then users 2–4 log in to that account (MCP same_account_as) instead of signing up again. Four signups per site from one IP caused rate limits and captchas.
  - Session cap raised from 30 to 40 turns (about 1/3 of rehearsal sessions hit 30 mid-signup) and from $0.09 to $0.12.
  - A budget or freeze-deadline stop in wave 2 removes users 2–4 of the bottom launches first. Expected nightly spend (about $9) is under the cap.
