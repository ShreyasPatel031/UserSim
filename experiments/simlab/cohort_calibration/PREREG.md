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
