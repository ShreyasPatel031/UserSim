# Pre-registration: does the persona panel predict where a launch lands? (orchestrator, 01:38Z Nov 15)

Written before any appeal score exists.

- **Launches:** the 5,034 arm-2 test rows for 2026-04..10 (the same rows as e5_ring_feat / e5_makers0).
  - Also the ranked warehouse launches of 2026-01..03, so the model has appeal in its training rows from the first test month on.
- **Cards:** built with persona_cards_hist.py rules: team past backers if there are ≥ 20, else same-topic backers in the 30 days before.
  - Only upvotes on launches dated strictly before D are used. The launch's own votes and comments never enter.
  - Segments come from Nov-2026 profile reads (headline and bio). Upvote lists are dated by launch day, not by read time.
- **Panel:** the live 12-group prompt (persona_prompt.py), Gemini 2.5 Flash, temperature 0.
  - It is given only the launch's name, tagline, description and topics, from the warehouse.
  - Any sentence with outcome words (product of the day/week/month, #1, ranked, upvotes, launched yesterday) is masked first. The number of masked launches is reported.
- **Features:**
  - appeal_high: the share of personas with interest "high".
  - appeal_mean: the mean interest, with high = 2, medium = 1, low = 0.
  - Launches without a panel are NaN.
- **Spend:** a hard stop at $20.
- **Test 1 (descriptive):** the within-day Spearman of appeal_mean with arm 2's residual (logv − arm2 prediction, month-forward). It is averaged over days with ≥ 5 paneled launches, with a day bootstrap of 2000.
- **Test 2 (decision):** arm 2 + appeal_high + appeal_mean vs arm 2. Month-forward, 5 seeds, deployed columns, training from 2025-01-01, rows sorted by (day, id).
  - Appeal is present in training for 2026-01 onward and NaN before.
  - Scored with score_makers0.py on 2026 truth: top 3 / 5 / 10, paired, day bootstrap.
- **Adopt as an arm-2 input** if the top-5 difference has a lower bound > 0.
- **Otherwise:** keep the panel as an explanation, labelled with its measured predictive value: the Spearman and the top-5 difference.
