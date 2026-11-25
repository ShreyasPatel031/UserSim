# REVIEW-TRUTH-1 (Nov 25 2026): review truth for product use, and the homepage-only bar

Aggregates only here (`results.json`). Private: `gs://.../simharness/taxonomy/review_truth.parquet` (frozen,
sha256 0d81ad0965c5fd06314394f3e1033c0d87dcfad57efd84a35825124e2889bec9) and `simharness/taxonomy/review_truth_wip/`
(homepages with fetch times, baseline scores, URL list, model-call cache). Code: `simharness/review_truth.py`,
`simharness/run_review_truth.py` (stages reviews, fetch, truth, baseline). Spend: about $2.30 of Gemini.

## Reviews held
`raw/ph_reviews/` does not exist. The reviews come from three sources, merged and de-duplicated:
- every review on a held person's Reviews tab in the store's verbatim records (31,577, the main source);
- simlab `review_text.parquet`;
- `raw/ph_predict_data/competitor_reviews.jsonl.gz`.

That gives 36,017 reviews, of which 15,312 are dated 2025-01-01 or later (after Gemini 2.5 Flash's cutoff), across
4,028 products. Rows keep product slug, date, rating and text only; no reviewer name or id.

## Truth: 537 products with 5 or more reviews from 2025
- 266 products have 10 or more; the median is 9 reviews (at most the 40 most recent are used).
- **Complaints:** E5's complaint prompt (complaints_eval.CT), 3 extractions, merged with E5's consensus prompt (keep
  themes in 2 or more of 3). 341 products get at least one; the mean is 1.9.
- **Likes:** the same procedure with the praise mirror of CT. 535 products get at least one; the mean is 5.0.
- **Rating:** the mean of the reviews' ratings: 4.84 across products. Product Hunt reviews are very positive, so
  complaints are thin.
- **Category:** the product's Product Hunt categories (202). Otherwise the CATEGORY-1 classifier on product text
  (45), or on slug, homepage and like themes (290).
- 6 categories have 20 or more truth products: AI Infrastructure Tools 31, Cloud Computing Platforms 28, Team
  collaboration 25, AI Coding Agents 24, UI frameworks 24, Databases and backend frameworks 20.

## Coverage of the competitor sets
| Competitor sets (CATEGORY-1) | launches | competitor slots with truth | launches with >= 1 | with >= 2 | both of the first 2 |
|---|---|---|---|---|---|
| backtest days (Apr-Nov 22) | 5,081 | 23.0% | 60.3% | 31.3% | 15.7% |
| Nov 23-24 shortlist sets | 69 | 33.9% | 75.4% | 52.2% | 29.0% |
| Nov 24 full line-up (category fallback) | 42 | 32.9% | 69.0% | 47.6% | 31.0% |

For PRODUCT-USE-1, a launch's 2 competitors both have review truth about 3 times in 10. Choosing the 2 nearest
competitors that have truth, among the 5, covers about half the launches.

## Baseline: homepage text only (the bar for the product-use simulation)
- **Homepages:** for the 360 truth products with a known non-Product-Hunt URL (launch-day site capture 95, earlier
  competitor domain list 265), fetched at 2026-11-25 01:48Z with the fetch time saved. 288 kept. Dropped: 30 too
  short, 19 HTTP errors, 18 with a review or testimonial widget, 3 fetch errors, 2 that redirected to Product Hunt.
- **Prompt:** one Gemini Flash call per product sees only the homepage text (first 3,000 characters) and lists the top
  complaints and likes.
- **Scoring:** E5's CJ (complaints) and JUDGE (likes) judge prompts, 3 runs per product. Intervals bootstrap over
  products.

| | complaint recall | complaint precision | like recall | like precision |
|---|---|---|---|---|
| all scored products | **17.8 [14.1, 21.6]** (204) | 10.0 [8.1, 12.1] | **54.6 [50.9, 58.2]** (287) | 33.9 [31.3, 36.4] |
| products with 10+ reviews | 19.1 [14.8, 23.7] (138) | 11.6 | 54.1 [48.9, 59.1] (170) | 33.7 |
| AI Infrastructure Tools (the only category with 20+ scored products) | 4.0 [0, 12.0] (10) | 5.0 | 56.6 [39.5, 73.1] (20) | 31.1 |

Categories with 10-19 scored products are listed in `results.json` as indicative only (for example Team
collaboration: complaint recall 30.6, like recall 47.1).

- The homepage predicts likes well: a product says what it is good at.
- It predicts complaints poorly: reviews complain about specific things a homepage never mentions.
- This is review truth, not launch-comment truth, so it is not on the same scale as the Nov 17 test (25 vs 38 on
  launch comments).
- The product-use simulation has to beat **17.8 complaint recall and 54.6 like recall** on these products.

## Leak checks
- The baseline prompt holds only homepage text; no review text reaches it.
- Every fetched page was checked against that product's 2025 reviews (8-word overlaps): 0 pages quote a review.
- 18 pages with review, rating or testimonial widgets were dropped.
- Pages that redirected to producthunt.com were dropped; no Product Hunt page was fetched.
- Truth uses only reviews dated 2025-01-01 or later.
- Reviewer names and ids are not in any output.

## Limits
- 177 of the 537 truth products have no known homepage URL. Product Hunt's own links are redirects through
  producthunt.com, which we do not fetch.
- The competitor domain list was written earlier; 213 of the 288 scored pages come from it.
- Thin complaint truth (1.9 per product) makes complaint recall coarse; products with 10+ reviews are the better
  test set.
