# Pre-registration: per-launch calibration of CF scores (orchestrator 02:56Z Nov 15; miss bucket (c) "taste-near" = 22.6% of misses)

Written before any arm output exists.

- **Lists:** the frozen CF-only lists (top 2,000 held people per launch, logistic p; reads before 00:00 PT of D). Days: every frozen day the store can score (Nov 8 onward; nightly days enter when re-read).
- **Arms:**
  1. **CF:** rank by p within each launch (current).
  2. **ASSIGN-EXP:** per person, compute the within-person z-score of p across the day's launches where they are listed. Each person "spends" a vote budget b = max(1, round(Σ_L isotonic-calibrated p)) on their top-b launches by z. The calibration is fit on the other scored days (leave-one-day-out).
     - Each launch's list = people who spent a vote on it, ordered by p, followed by everyone else on the list, ordered by p.
  3. **ASSIGN-30D:** same, with b = max(1, round(upvotes on launches of the 30 days before D / 30)), from reads before the freeze.
- **Metric:** strict, as in backer_arms_score.py. Recall at N, N = observed voters among held-before-freeze AND re-read-after-close people. Ranked within re-read people; pooled; DAY bootstrap 2000; paired vs CF.
- **Realistic N:** N̂ = round(Σ calibrated p × tail factor over the listed re-read people). This uses only model quantities, not the observed count. Report recall = hits / observed and precision = hits / N̂.
- **Adopt** an arm if its paired recall-at-N difference vs CF has a day-bootstrap lower bound > 0.
- No Gemini.
