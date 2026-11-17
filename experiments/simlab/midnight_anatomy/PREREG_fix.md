# Pre-registration: one fix for the largest midnight miss class

Written 2026-11-17, before the fix is run; committed before the backtest.

## Anatomy so far

Arm-3 rebuild, month-forward, 195 days (Apr 1 – Nov 12 2026), top 10 = 77.7. There are 864 top-10 misses.

- **The largest class is "hunter record": 357 misses; oracle top 10 is 87.4 if all were fixed.**
  - False negatives: 190, of which 124 (65%) are hunters with no record. Launches with no hunter record reach the real top 10 22.3% of the time; the model puts them in its top 10 17.2% of the time.
  - False positives: 167, all hunters with a record (median past top-5 share 0.60). Launches with a record reach the real top 10 59.4% of the time; the model puts them there 65.5% of the time.

The model over-trusts hunter records and under-rates newcomers.

## The one fix

Each test month, add a fixed offset δ to the arm-3 prediction of every launch whose hunter has no record (hist_hunter_n = 0 or missing).

- δ is the mean month-forward residual of no-record launches minus the mean residual of launches with a record. Residual = the training target (logv) minus the month-forward prediction.
- δ is fitted on all earlier test months only.
- No new input and no Gemini.
- April has no earlier test month to fit δ, so the test runs from May 1 to Nov 12.

## Test

- Paired against arm 3 on the same days (May 1 – Nov 12), bootstrap over days (2,000).
- Primary: top 10. Secondary: top 5 and top 3.

## Adopt if

- the top-10 paired interval is above 0, **and**
- top 3 does not fall by more than 1 point on the point estimate.
