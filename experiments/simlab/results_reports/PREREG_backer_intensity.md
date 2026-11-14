# Pre-registration: backer prediction arm 5 "CF+intensity" (orchestrator 23:16Z Nov 14), written before any result
Arm: CF-only (ln1p n30, ln1p n90, ln1p days since last upvote, cf) + 4 backing-intensity features, all from reads fetched before 00:00 PT of D
and upvotes on launches dated before D, team = this launch's hunter + first maker:
  bk_recent : upvoted the team's most recent launch before D (0/1)
  bk_n      : ln(1 + number of the team's earlier launches the person upvoted)
  bk_days   : ln(1 + days since the person's last upvote on a team launch); 365 when never
  bk_share  : team upvotes / all of the person's upvotes (before D)
Logistic, 30 training days, negatives 10% re-weighted, same as CF-only. No follows. SVD as CF-only (upvotes dated before D).
Metric: recall at N (N = observed backers: held before the freeze AND re-read after the day), pooled; arm ranked within re-read people.
Days: Nov 8-12 backfill + every nightly day scored. Paired difference vs CF-only, launch bootstrap 2000, 95%.
DECISION RULE: adopt (replace CF-only as the forward line) only if the 95% interval of (CF+intensity - CF-only) is entirely above 0.
Otherwise CF-only stays; CF+intensity becomes a shadow arm.
