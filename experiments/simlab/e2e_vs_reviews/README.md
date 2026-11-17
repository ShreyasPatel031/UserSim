# E2E engine against real users

E5, Nov 17 2026.

## Part 1: the Tally / Fillout / Typeform study, against WEAK truth

**Study.** ab3c9656 on the seed-VM engine, finished 09:11Z: 108 cells (6 personas × 6 tasks × 3 sites).

**Truth: weak.**
- **What is held:** none of the three products has G2, Capterra or TrustRadius reviews in held data. Product Hunt reviews are held only for Typeform (about 15 unique, nearly all praise); for Tally and Fillout we hold review records with no text.
- **Live reads:** the review pages refuse automated reads (403). Apify is not available.
- **What was used instead:** themes from public comparison pages, review snippets and community posts found by web search, listed in `part1.py`. No Reddit or Hacker News threads surfaced. Broad themes only; no rank agreement.

**Arms, each giving up to 8 complaints and up to 5 praise themes per product:**
- **Study:** themes drawn by Gemini from the 36 run results per product (task, goal reached, ending, judge reason), plus the study's own summary for Tally.
- **Baseline:** the plain persona-free prompt on each product's homepage text, read through safe_fetch.

**Matching:** one Gemini call per product and kind matches predicted themes to the truth themes by topic (broad rule). Intervals are bootstraps over themes, pooled across the three products.

| | Complaint recall | Complaint precision | Praise recall | Praise precision |
|---|---|---|---|---|
| E2E study | 25% [6, 50] (n 16) | 19% [5, 38] (n 21) | 10% [0, 30] (n 10) | 17% [0, 50] (n 6) |
| Plain prompt on the homepage | 38% [19, 62] (n 16) | 29% [12, 50] (n 24) | 40% [10, 70] (n 10) | 33% [13, 60] (n 15) |

**On this weak truth the study does not beat the plain prompt;** the point estimates are lower, and the intervals are wide (16 complaint themes, 10 praise themes in all).

**Why.** The study's findings are mostly about getting through the test, not about the product.
- **Goal reached:** Tally 13 of 36 cells, Typeform 5, Fillout 4.
- **Proof checks:** 0 of 108 passed.
- **Endings by product:**
  - Tally: {'gave_up': 15, 'blocked': 7, 'completed': 13, 'abandoned': 1}
  - Fillout: {'completed': 14, 'gave_up': 11, 'blocked': 8, 'abandoned': 3}
  - Typeform: {'gave_up': 21, 'completed': 6, 'blocked': 3, 'abandoned': 6}
- **The derived "complaints" are dominated by test artefacts:**
  - sign-up and log-in walls;
  - captchas;
  - usage limits;
  - being unable to find features.
- **Real users talk about other things:**
  - price and response caps (Typeform);
  - HIPAA compliance, reporting and support (Tally);
  - support speed, templates and uploads (Fillout).

**What the study did find that real users also raise:** design and customisation limits, and conditional logic (positively, for Fillout).

**Caveat.** The truth is weak: second-hand themes, partly from vendors' own comparison pages. Read this as a first look, not a measurement.

## Part 2: the real test

Proposed to the orchestrator: Asana as the target, ClickUp and Basecamp as competitors. Each has 100 held G2 / Capterra / TrustRadius reviews with pros and cons text, and Capterra ease-of-use ratings (n 44 / 23 / 69). It waits on that study being run.

Files: `part1.py`, `part1_result.json` (themes, matches, per-product detail).
