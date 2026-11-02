# Direction review 2 (Fable, orchestrator), Nov 2, 2026, 21:10 UTC

Asked by Shreyas: was today's work correct, is this the right direction, and what are the big bets. Sources read:
`ph_predict/honest.py`, overnight_1030.md (E0, shock_model, honest baseline, daycal, experiment zero, C1),
vote_model2.md, x_prelaunch_e1.md, hn_sim/RESULTS.md (15 min, misses, exposure clock, gap15), RESEARCH_LOG.md.

## 1. Was the work correct?

Verified, and I'd stand behind each:
- **The leak audit (honest.py).** Column groups dropped cumulatively, same folds, 5 seeds, paired over days. The
  reasoning is right: follow lists read on Oct 25 are undated and people follow makers after a good launch. Honest
  pre-launch daily 64.4 / 70.4 / 76.9 is the number to quote. The most valuable result of the week.
- **E0.** Variance of the within-day log(real/sim) ratio 0.588 vs 0.056 expected from independent errors. 90.5% of the
  simulation's error is one per-launch shock. Oracle: 10% of real pool voters → 83 daily top 3. Correct, and correctly
  labelled optimistic.
- **Experiment zero.** Honest shock predictability 0.395 vs 0.504 leaky, lower in 5/5 months. So "inputs exhausted at
  0.50" was wrong; the honest number is lower and the room is larger.
- **The X no-go.** Rule fixed beforehand, forward-only fit, 16 full days, coefficients shrink to 0. Valid as a no on
  *public engagement with the team's own X posts*. Not a no on mobilisation: 64% of launches have a handle, 5% posted
  in the final week, the per-day training sets were tiny. Weak instrument, honest test.
- **Day calibration +4.0 weekly top 3.** Lower bound 0.0, never worse by month. Not established; the live shadow decides.
- **HN 26.5% at 15 min (full period), 29.6% Oct 2–14.** Rank-only honest base, leak checks on the vote series, flags =
  winners. Correct. The exposure-clock 35.6% is a different checkpoint and is reported as such.
- **Null results.** Person models, E1, competitor gaps and outcomes: each within ±1.5 of the launch model, as E0
  predicted. True, and most of that compute should not have been spent (see 2).

Not verified, flagged to the PH agent (21:08 UTC):
- **Page-derived inputs** (pf_, llm_, ps_, vs_) are now the top honest shock groups. If backtest pages were fetched
  months after launch, they carry post-launch state (badges, edits, review counts). Sensitivity requested. If leaky,
  the honest baseline drops further.
- **promo_ funding and company age** were dropped as undated. Both are re-datable (funding rounds have dates; age at
  launch = age at fetch − elapsed). Cheap honest recovery for the magnitude boards.

## 2. Is it the right direction?

The diagnosis is right and sharply posed: the daily board is decided by one number per launch, the team's launch-day
mobilisation, and honest pre-launch inputs rank it at 0.395 within day. The oracle says ~0.75 gets to 83. Everything
that re-fits the same inputs lands on the same board number; that was known by 03:00 UTC and cost the rest of the day.

What the direction still gets wrong:
- **Every strong honest signal accrues forward only** (at-launch follower counts, dated follows). Backtests can't be
  rebuilt for them. So the fastest honest gain on the daily board is bounded by how much at-launch state we record from
  today, and how soon 30 live days exist (early December for a gate read; 14 days for a provisional one, ~Nov 16).
- **A and C are right but small.** Team history covers maybe 30–40% of launches; stars/downloads 9–14%. Each can add a
  point or two; neither targets the campaign itself.
- **The campaign was never measured.** The X test looked at the team's own posts and their engagers. The actual
  pre-launch campaign is cross-channel: "launching on Product Hunt tomorrow" on LinkedIn, Reddit, Indie Hackers, Bluesky,
  newsletters, communities. Nobody has counted it.
- **HN at 15 min is bounded by what exists at 15 min.** 53% of winners (late risers + re-ups) have a 15-min state
  identical to non-winners. The levers that moved it (votes, who commented, exposure) all live in the other 47%.

## 3. Big bets

### Product Hunt
1. **Record the whole at-launch state at 00:05 PT, every day, from tomorrow.** Not only follower counts: each maker's
   and the hunter's PH profile (followers, past launches, reviews, links), the post page (makers, media, offer, maker
   intro), X/GitHub/app-store/Chrome-store counts for every linked handle. Data Feeder's route-4 fetch already costs
   ~$0.17 for 4,369 pages; this is ~70 pages/day. This is the honest version of the block that carried 3–4 points leaky,
   plus everything else. Compounding asset; every day not recorded is lost. Gate at 14 days, decide at 30.
2. **The campaign sweep (backtestable Jul–Oct, free routes).** For each launch, dated public mentions of the product
   (name, domain, "product hunt") in the 7 days before launch across Reddit, Indie Hackers, HN, Bluesky, dev.to/Substack
   RSS, LinkedIn public posts via search, X on free quota. Count distinct authors and their reach. Gate on the residual
   first, then boards. This is the test the X no-go didn't run.
3. **A magnitude model for the weekly board** (whichever board first counts). Weekly is decided by cross-day vote
   totals; day calibration already gave +4 top 3. Fit day strength + position feedback on clean hourly snapshots
   (14 days by Nov 16), apply pre-launch as a transform of the honest prior. Re-date funding and company age for it.
4. **A1 and C1 as planned** this week; score daily, weekly, monthly against the honest day-calibrated control.

### Hacker News
1. **The front-page dynamics simulator** (E5, running on exp-2): vote arrival by exposure and hour, HN's rank formula,
   Monte Carlo forward from the 15-min state. The one bet that models the mechanism instead of adding features.
2. **Second-chance pool prediction with live labels** (2 weeks of /pool reads): re-ups are 16% of winners and all missed
   at 15 min. If moderator picks are predictable from content, those become catchable.
3. **A definition question for Shreyas, not a bet:** the exposure clock (judge a post 15 min after it first gets real
   exposure) gives 35.6% vs 29.6%. It removes the structural blindness to late risers. Whether that is the 15-min
   checkpoint is his call; I report both until he decides.
4. **GitHub stars before posting** (lands ~22:00 UTC): tested tonight.

## 4. Process
- Gate every candidate on within-day residual Spearman (176 days detect 0.05) before any top-k run.
- One experiment per VM per north star, always running; queue the next before the current finishes.
- Paid data only from a measured pilot (cost per full day), never from read estimates.
