# Direction review 2, Nov 2, 2026 (Fable, PH ops session, at Shreyas's request)

Scope: the pre-launch daily board on the honest baseline. Sources: `docs/RESEARCH_PROGRAM.md`, `docs/RESEARCH_LOG.md`,
`experiments/simlab/reports/overnight_1030.md` (Nov 2 sections), `x_prelaunch_e1.md` (E5), the first review
(`2026-11-02_direction_review_ph.md`). Every number is from those logs.

## 1. Where things stand

| Fact | Number | Where |
|---|---|---|
| Honest pre-launch baseline, daily top 3 / 5 / 10 (May–Oct) | **64.4 / 70.4 / 76.9** (published was 66.5 / 73.6 / 81.0) | honest.py |
| Honest weekly / monthly | 45.3 / 54.4 / 55.2; 20.0 / 36.7 / 40.0 | honest.py |
| Share of the simulation's error that is a per-launch shock | 90.5% | E0 |
| Ceiling with the true pool shock known | daily 89.7 / 94.3 / 90.2 | shock_model |
| Shock from pre-launch inputs, within-day Spearman | 0.50, **measured on leaky inputs** (`ph_` counts, `seg_`, `fol_` were its top three groups) | shock_model |
| Total-vote surge (launch-model residual) from pre-launch inputs | Spearman ≈ 0.0 | shock_extra2 |
| Maker surge history, persistence | 0.44 pool / 0.25 total, but 4–11% of launches have a repeat maker in our data | shock_extra, shock_extra2 |
| Person models (psg, psa, pna, pool concentration), E1 v2, competitor gaps, competitor outcomes | all within ±1.5 of the launch model on daily top 3 | Nov 2 sections |
| Pre-launch X engagement (16 full days, honest) | +0.0 / −3.1 / +0.0; no-go | x_prelaunch_e1 |
| Day calibration (honest) | weekly top 3 +4.0 (0.0 to +8.0), never worse by month | daycal |
| Live launch-day readings | comments: +4.8 top 3 by hour 2, +8.8 by hour 12; Wayback votes: top 5 / 10 above 90 from hour 4 | launchday, wayback_boards |
| What's leaky and why it matters | `fol_` / `seg_` carried 3–4 points on top 5 / 10; follows are undated and people follow makers after a good launch | honest.py |

Read together: the daily board is decided by a per-launch shock that is the makers' launch-day mobilisation. The inputs
in hand don't see it, every model re-fit over those inputs lands on the same number, and the one input family that did
move the score (who follows the team) turned out to be partly reading the outcome. The honest pre-launch question is
now sharply posed: **what dated, pre-launch, wide-coverage information measures a team's capacity to mobilise?**

## 2. Critique of the approach

**1. The program kept re-fitting models over the same inputs after E0 had said that cannot work.** E0 (Nov 2, early)
showed 90.5% of the error is a shock shared by a launch's whole audience, and that no pre-launch *person* data sees it.
After that, psg, psa, pna, pool concentration, E1 v2, launch model + simulation, and launch model + competitors were all
scored on daily top 3. Every one came in within ±1.5, as E0 predicted. That is five or six null results and several
deploys bought with a day of compute, on a question whose answer was already in the log. The program's own rule
("feature tuning for ±2 is noise and is no longer the program's work") was written on Nov 1 and not followed on Nov 2.
The person-model work has real value for the *simulation* (psg +10 on the pool's own top 3, pna +3 and shipped), and
should be reported as that. It should stop being scored as a route to the daily board.

**2. The leak audit came last, so several conclusions rest on leaky inputs.** The shock predictor's three strongest
groups (`ph_` follower counts, `seg_`, `fol_`) are exactly the groups the honest audit dropped. So "pre-launch inputs
predict the shock at 0.50 and are exhausted" is not established. The honest shock predictability is unmeasured and is
probably lower. The same goes for E1 v2's +1.7 (four leaky audience inputs) and the 66.5 baseline. The audit itself was
done well and is the most valuable result of the day; it should have been experiment zero, and from now on every new
input must be dated before it is scored (the rule exists; the follow lists and follower counts slipped through because
they were snapshots, not events).

**3. The X test asked the right question of the wrong slice.** The shock is what the team does privately on the day:
DMs, email lists, Slack and Discord communities, LinkedIn posts to their own network. What was fetched is public
engagement with the team's X posts in the 30 days before launch. Only about half the teams have an X handle, 5% posted
in the week before, and engagers tied to the pool vote at 13.7× but are a handful. The honest no-go is a no-go on
*public X engagement as a proxy*, not on *the team's outreach capacity*. The decision rule (10 full days, interval above
0) was fixed in advance, which is right; the instrument was weak.

**4. The daily top-3 gate cannot see what is being hunted, and the better gate already exists.** ±3.5 on daily top 3
needs an effect that is itself near the whole remaining gap. `x_prelaunch_e1.py` used the right development gate:
within-day Spearman of the candidate input with the honest residual, paired over days, with a pre-registered rule.
On 176 backtest days that gate detects 0.05; on 30 live days it detects about 0.10. Daily top-k stays the north-star
report; it is not the selection metric.

**5. Keep.** The honest audit and its baseline; the fail-loud pipeline; the at-launch follower snapshots (recording since
Oct 25, honest by construction); day calibration as a weekly shadow (+4.0, honest, cheap); the early-vote shock backtest
waiting on clean days; the discipline of out-of-sample, paired, pre-registered tests.

**6. Stop.** Person-model variants scored on daily top 3; refits of the launch model over its own inputs (E1-style
offsets, pool sums, concentration); competitor gaps and competitor outcomes as launch inputs; public X engagement as
fetched. Each has been null twice or more.

## 3. The 2–3 most promising honest pre-launch sources, each with a concrete experiment

The shock is mobilisation capacity. Honest, dated measures of it fall into three kinds: the team's track record of
mobilising (history), the team's audience as it stands the day before (snapshot), and the product's existing user base
(external, dated). Each is tested with the same gate: within-day Spearman with the honest launch-model residual, paired
over days, interval excluding 0 and point estimate ≥ 0.05 to be worth the daily top-k run; then the honest model with
and without the input on daily top 3 / 5 / 10, paired, by month.

### A. The team's full Product Hunt history (dated; backtestable May–Oct now)

`hist_` is built only from our own launch files (from January), so a repeat maker is found for 4–11% of launches. Product
Hunt's API returns every past launch a user made or hunted, with final votes and dates, for the whole history of the
site. Maker surge persistence is 0.44 on the pool shock and 0.25 on total votes in our data; the question is how much of
the daily board those makers decide once coverage is complete, and whether "ever launched before, and how it went" is
itself a strong input (first-time teams are 53% of launches and the simulation's weakest group).

- Experiment A1: for every May–Oct launch, fetch each maker's and the hunter's earlier launches from the API (dated
  strictly before the launch day), build `hist_` over the full history: count, max and mean of log votes relative to
  that day's median, share that reached the daily top 5, days since the last launch. Report coverage (share of launches
  with any history), then the gate, then daily top 3 / 5 / 10. Cost: API only, no fetch ladder, about a day. Honest by
  construction. Expected: coverage 30–40%; a real but modest effect concentrated in the top of the board.

### B. The team's audience as it stands the day before (honest `fol_`, at-launch counts; forward-only)

The leaky `fol_` / `seg_` block carried 3–4 points on top 5 / 10. Part of that was the outcome; part is the team's real
pre-launch audience on Product Hunt. The honest version is now being recorded twice over: at-launch follower counts for
makers and hunter (from Oct 25; the makers' own count was never an input), and Data Feeder's daily following lists for
the active pool (from Nov 2), which date new follows to a day. From those, "pool people following the team as of
day−1" and their segments are honest for every launch from Nov 3.

- Experiment B1 (30 live days, early December): honest `fol_` (followers among the pool as of day−1, by role) plus
  at-launch counts, gate on the live residual (30 days detect 0.10). B2 (60 days): daily top 3 / 5 / 10 paired. Nothing
  to build beyond a feature file; the data accrues by itself. This is the one input family with a known effect size,
  so it is the most likely to move the board honestly, and the slowest to confirm.
- Backfill is not possible: the Oct 25 snapshot post-dates every backtest launch. Don't try to date old follows from
  list order.

### C. The product's existing user base, dated (GitHub stars at launch; backtestable now)

A launch's day-one votes come from people who already use the product. For developer tools, that base is countable on
a dated public record: GitHub stargazer timestamps give stars as of the day before launch. `external.py` already has
`gh_stars_before` (binary search over stargazer pages); it was never a model input, and the GitHub audience pilot tested
a different thing (matching voters to GitHub profiles: 3.4% coverage, correctly dropped). Stars-at-launch is an
audience-size input, not a person match. Coverage is whatever share of launches link a repo (`web_has_github` is already
a feature; dev tools are over-represented at the top of the board).

- Experiment C1: with a GitHub token (needs the user's OK; the public API returns 401 without one), `gh_stars_before`
  for every May–Oct launch with a repo link, plus `gh_created` age and forks. Coverage, gate, daily top 3 / 5 / 10.
  Honest and backtestable. Cost: one token, about 5,000 requests per hour free, a few hours. Extend the same idea to
  other dated user-base records where a link exists: npm / PyPI weekly downloads (dated), Chrome Web Store user counts
  via Wayback.

### Experiment zero (before A–C): the honest shock ceiling

Re-run `shock_model.py` stage 1 on the honest input set. It costs an hour and gives the number that the rest hinges on:
how predictable the pool shock is from honest pre-launch inputs. If it is near 0.50, the inputs were real and the
leak was elsewhere; if it drops to 0.3, there is more room than "exhausted" suggested, and A–C are where it comes from.

## 4. On the boards

Daily, weekly or monthly, whichever first. Day calibration lifts weekly top 3 by +4 honestly and the weekly board is at
45 / 54 / 55; monthly is at 20 / 37 / 40 on 5–6 lists. The weekly and monthly boards are decided by magnitude across
days, which the pool's votes don't track (true-pool-shock ceiling on weekly is 52 / 69 / 81). The audience-size inputs
in A and C are magnitude inputs: the month's top 10 are the launches with an existing user base. So A and C are tested
on weekly and monthly top 3 / 5 / 10 as well, with the honest day-calibrated forecast as the control. Once 14 clean
days of `vote_snapshots` exist, a day-strength and position-feedback magnitude model fitted on them, applied pre-launch
as a transform of the prior, is the natural next step for weekly (it cannot change a daily ranking).

## 5. Summary

- The daily board is a mobilisation shock; models over the current inputs are done, and the leak audit moved the honest
  bar to 64.4 / 70.4 / 76.9.
- Three honest sources of mobilisation capacity are testable: the team's full PH history (A, now), the team's audience
  as of day−1 (B, accruing from Nov 3), and dated user-base counts such as GitHub stars at launch (C, now with a token).
- Gate every candidate on within-day residual Spearman first; score daily top-k second.
- Run experiment zero (honest shock predictability) first; it tells how much room there is.
