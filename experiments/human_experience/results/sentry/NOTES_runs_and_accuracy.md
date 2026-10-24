# Sentry runs, rating accuracy vs simple baselines, and the next eval plan (18–24 Oct 2026)

## Sentry simulated users (`sim_runs_6.json`)

- Six runs through the live MCP (`scripts/mcp_study_runner.py --smoke`, Haiku on Vertex), one task for all six:
  "Sign up for Sentry and set up error tracking for your team's JavaScript web app: create the project and get to
  the step where you have the SDK install snippet and DSN to add to the code."
- Personas: role, company size and time used from six real Capterra reviewers (#0–#5 in the Capterra rows of
  `sentry_reviews_317.json`). The one-line backstory in each persona ("trying Sentry for the first time", "not a
  developer", etc.) was written by the agent, not taken from the review.
- Result: 6/6 reached the snippet and DSN (independent judge pass), 33–40 steps, 242–294 s. No difference between
  user types. The report "friction" lines are the agent narrating its own clicks, not product friction.
- The task stops at sign-up, so it cannot test what these reviewers complained about (missed alerts in batches,
  data retention, WordPress docs, login limits). A longer task would be needed.

## Data problem in `sentry_reviews_317.json`

16 of the 23 Capterra rows (Capterra indexes 6, 7 and 9–22) are a different product: an insurance-agency system also
called Sentry (clients, policies, texting). Exclude them. The handoff's segment and complaint numbers include them.

## Sentry: per-person rating vs Sentry's plain average (leave-one-out, 223 reviewers with a title)

| Prediction | Overall-rating error (stars) |
| --- | --- |
| Sentry's average of the other reviews | 0.437 |
| `agent_mode.rating_estimates` + `personalize` (role, size, tenure) | 0.443 |
| `most_likely` whole star | 0.478 |

Complaint topics do differ by role (keyword counts on cons): learning curve / UI 40% of non-engineers vs 28% of
engineers; pricing 17% vs 24%; integrations 4% vs 14%.

## Rating accuracy as exact match, vs always guessing the common answer

From `results/agent_mode_eval_no_own/per_person.csv` (new-product mode, on main). "Always" picks the most common real
answer, so it is a generous baseline.

| | Ours exact | Model alone exact | Always guess | Ours within 1 | Always-4 within 1 |
| --- | --- | --- | --- | --- | --- |
| Capterra overall (420) | 66% | 44% | 66% (5) | 92% | 98% |
| Capterra ease (420) | 57% | 40% | 61% (5) | 90% | – |
| Capterra recommend (415) | 22% | 20% | 40% (10) | 70% | – |
| G2 overall (200) | 27% | 44% | 55% (4) | 72% | 86% |

Real Capterra overall ratings: 5 = 66%, 4 = 26%, 3 = 6%, 1–2 = 2%. Ratings do not beat a trivial guess. The MAE gains
reported earlier (0.96 → 0.59) come from fixing the model's habit of guessing low. Don't use rating accuracy in a pitch.
What beats its baseline: user mix (roles, size) and the words (cons, overall experience).

## Next: forward-facing eval sets (agreed plan, not built yet)

| # | Eval | Answer key | Baseline |
| --- | --- | --- | --- |
| 1 | Find competitors | Capterra `switched_from` (16% of rows) + `alternatives_considered` (9%); AlternativeTo / G2 alternatives | category + popularity |
| 2 | Who uses it | reviewers' role / size / industry mix | category average mix |
| 3 | What they use it for | G2 `problems_solved` | category top use cases |
| 4 | Likes / dislikes | pros / cons theme mix | category average themes |
| 5 | Reception vs rivals | rank within category | category median |
| 6 | Product Hunt launch | upvote percentile in day / topic | launch features only |
| 7 | Traction 6–12 months | reviews appear, review growth, stars, YC status | launch upvotes |

Evals 1–4 can be built from the snapshots now (66 Capterra + 82 G2 products, 11 categories, 21 on both). They score
held-out products, not true new launches: the snapshots keep each product's most recent reviews, so the first review
date is not a launch date. Eval 5 needs more products (≈300 via Apify, about $150–200). Eval 6 needs a Product Hunt
token, and eval 7 needs months of logged forward predictions.
