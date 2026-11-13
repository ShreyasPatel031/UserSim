# Displayed votes vs distinct store upvoters (orchestrator 11:54Z Nov 13)

Script: vote_weight.py. Data: the official store_v3 (all upvote rows) and 1,223 ranked launches, Oct 1 – Nov 10. Displayed votes = warehouse launches.votes (latest read).

## (1) Size

Store upvoters exceed displayed votes on **62 launches**. Every one of them is in the top quartile by size except one.

| final rank | median displayed / store upvoters | launches with store > displayed |
|---|---|---|
| 1–3 | 1.14 | 43 of 123 |
| 4–10 | 1.75 | 19 of 286 |
| 11+ | 3.00 | 0 of 814 |

By month: October 51 of 908, November 11 of 315.

## (2) Which votes do not count

**Timing does not explain it.** Comparing the last read before day end with the latest read (365 launches, Oct 31 – Nov 12): the median latest / day-end ratio is 1.026. Only 3.8% of launches went down, and 14.8% grew by more than 10%. The displayed count keeps rising after the day; it is not trimmed.

**Relaunches do not explain it.** Over-covered top-3 launches are relaunches in 28% of cases, against 36% for the other top-3 launches. Over / displayed is about the same for relaunches and first launches (0.89 vs 0.87).

**Voter-type weights are not identified.** Non-negative least squares on 84 near-complete launches (store upvoters at least 0.9 × displayed), with 17 cells (upvote-count bucket × burst × has followers, plus not-complete):
- weights run from 0 (the 10–99-upvote cells, 35% of upvoters) to above 1 (1000+: 1.9; low-activity cells 2.8 – 13);
- weights above 1 cannot come from a discount, so the fit is absorbing uncovered votes and collinearity;
- cross-validated R² is 0.67 against 0.55 for one constant weight; median absolute error 12% vs 15%;
- the store has no Product Hunt account age, so new-account discounting cannot be tested.

## (3) "Zero-weight" share

Cells with weight below 0.2 hold a median 29% of top-3 launches' listed upvoters. Their launch share relates to final rank beyond clean with partial −0.14 [−0.22, −0.06] for (−share). In other words, launches with more of these voters rank better, the opposite of a discount. This confirms the weights are an artifact and not evidence of uncounted voter types.

## (4) Coverage

Of displayed votes, raw complete-upvoter counts: the seeded week covers 0.70 overall / 0.97 on top 3; Oct 1 – 24 covers 0.50 / 0.84. The weighted versions (0.65 / 0.85 and 0.47 / 0.68) rest on the unidentified weights; do not quote them.

## Verdict

The excess is real and concentrated in the largest launches. It is not timing (displayed counts only grow) and not relaunches. Voter-type weights from store traits cannot explain it.

The remaining candidates need data the store lacks:
- Product Hunt discounting new or low-trust accounts in votesCount (needs account creation dates);
- store upvote lists that include removed or invalidated votes (needs a second read of the same people).

The next useful pull is profile join dates for the voters of the 62 over-covered launches.
