# Backward browser test (interim, not the forward test)

E5, Nov 17 2026. **Backward**: the sites were visited on Nov 17, days to months after each launch, by this container's own Chromium. It is not the UserSim engine and not the forward test.

**Result: the browser arm is far below the 13.5% baseline. A no-account visit to the live site finds almost none of what real commenters raised.**

## Set-up

- **Launches:** the 154 launches of the complaint-recall test that have a resolved product address (launched Aug 1 – Nov 10 2026, each with 8 or more real non-team comments). All 154 were visited; 120 had at least 4 of 6 tasks run without a browser failure and are scored.
- **Six tasks per launch, none needing an account:**
  1. What it does and who it is for.
  2. Price, free tier and limits.
  3. Docs or help.
  4. Platforms and downloads.
  5. Contact, makers and privacy.
  6. Try it without an account.
- **Visitor:** Gemini 2.5 Flash, one persona per task, looking at the real screenshot plus the visible clickable elements. At most 10 steps per task.
- **Hard rules, enforced in the browser:**
  - No typing, sign-up, log-in or form submission; any non-GET page load is aborted.
  - Top-level navigation stays on the product's own site.
  - producthunt.com is never loaded: 464 embedded requests to it were blocked.
- **Arms on the same launches:**
  - browser findings turned into 10 complaints and 10 questions;
  - the plain prompt on the pitch (the 13.5% arm, reused unchanged);
  - the two merged.
- **Scoring:** the same truth, strict same-issue rule and blind pooled judge as `../../complaint_recall/`.
- **Hand check:** 30 new pairs (15 judged matches, 15 judged non-matches). E5 agreed with 27 (90%): two matches were too loose and one non-match was a real match.

## Recall and precision (%), same launches

| Arm | Complaint recall, top 5 | Complaint recall, top 10 | Question recall, top 5 | Question recall, top 10 | Complaint / question precision, top 10 |
|---|---|---|---|---|---|
| Browser findings | 2.1 [0.2, 4.7] | 3.7 [1.0, 7.2] | 0.7 [0.2, 1.4] | 1.3 [0.6, 2.1] | 1.4 [0.4, 2.7] / 1.2 [0.6, 1.8] |
| Plain prompt on the pitch | 10.6 [6.6, 15.5] | 18.3 [12.6, 24.7] | 7.3 [5.3, 9.2] | 13.0 [10.1, 15.8] | 5.4 [3.8, 7.2] / 9.5 [7.6, 11.6] |
| Browser + plain prompt, merged | 3.7 [0.9, 7.3] | 9.3 [5.1, 13.9] | 3.5 [2.3, 5.0] | 8.7 [6.5, 11.2] | 3.1 [1.8, 4.5] / 6.4 [4.9, 8.2] |

n = 94 launches for complaints and 119 for questions. The plain prompt scores 18.3% here against 13.5% on all 300; this subset is easier, not the method better.

Paired differences, top 10: browser minus plain prompt **-14.5 [-21.3, -8.0]** points on complaints and **-11.7 [-14.5, -8.9]** on questions. Merging the browser findings in makes the plain prompt worse: -9.0 [-15.7, -2.2] and -4.3 [-7.3, -1.3].

## Why

- **The visitor finds site problems; commenters raise product problems.** Of 330 findings, 124 are bugs (dead links, failed requests, pages that do not load), 93 missing information and 70 stuck. Real comments are about what the product does once used: accuracy, integrations, data handling, limits of the core feature.
- **No account means no product.** Most of these products sit behind a sign-up, which this test forbids, so the visitor never reached the thing commenters talked about.
- **Visited after launch.** Issues raised on launch day may already be fixed. This biases against the browser arm, but cannot explain a gap this large: browser recall is near zero on questions too, which do not get "fixed".

## Operations (the numbers for the browser decision)

| | |
|---|---|
| Wall time per launch (6 tasks in parallel) | median 0.8 min, 90th percentile 1.2 min |
| Browser time per launch (sum over 6 tasks) | about 4 min |
| Steps per launch | 38.8 (cap 60) |
| Tasks the visitor finished on its own (completed, gave up or blocked) | 55.4% |
| Tasks completed | 34.9% |
| Tasks that hit the step cap (stuck) | 34.6% |
| Tasks lost to a browser failure | 10.0% |
| Gemini cost | about $0.06 per launch for the visit, $0.003 for scoring |
| Browser cost | none (this container); the engine's browser time would be about 4 minutes per launch for these 6 tasks |

**The 9-of-10 gate fails: 55% of tasks finished on their own, 35% completed.**

| Task | Completed | Step cap | Browser failure | Mean steps |
|---|---|---|---|---|
| What it does and who for (home page) | 67% | 19% | 11% | 5.5 |
| Price, free tier, limits, card | 48% | 29% | 8% | 6.2 |
| Docs or help, getting started | 36% | 29% | 15% | 6.1 |
| Platforms, OS, downloads | 36% | 42% | 10% | 6.2 |
| Contact, who makes it, privacy | 15% | 56% | 8% | 8.1 |
| Try it without an account | 8% | 32% | 9% | 6.7 |

Task completion falls from 67% on the home page to 8% for "try it without an account", which is where real use would begin.

## What this does and does not show

- It shows that a no-account visit to a product's public site does not predict launch-day comments, and that adding it to the plain prompt hurts.
- It does not test the forward engine run with signups, which is the launch-3 gate. That run reaches the product itself and may behave differently. This result lowers the prior, not to zero.
- The visitor here is weaker than the engine's: no typing, 10 steps per task, a local browser without proxies (about 10% of tasks were lost to browser failures).

Files: `bridge.js` (the browser and its safety rules), `run.py`, `score.py`, `results.json`, `per_launch_operations.json`, `handcheck_30_pairs.json`. Visit transcripts are not committed.
