# CATEGORY-1 (Nov 25 2026): launch categories, competitor sets, and the structural miss by category

Aggregates only here (`results.json`). Per-launch files (categories, competitors, residual rows, product table) are
private under `gs://.../simharness/taxonomy/`. Code: `simharness/taxonomy.py`, runner `simharness/run_category.py`
(stages `labels`, `competitors`, `residual`, `leak`, `lineup`). No model calls, $0.

## 1. Launch -> category
Vocabulary: the 248 categories Product Hunt puts on the 6,797 products seen as Similar Products (the 91 pasted
categories, all with descriptions, are among them). Priority: (a) the launch's own product carries Product Hunt
categories (it appears as someone's Similar Product): 2,407 launches; (b) majority of its Similar Products'
categories, with the share: 4,236; (c) the embedding classifier: 787 (launches after Nov 1, or with no Similar
Products). All 7,430 item-table launches get a primary category; 225 categories used, 99 with 20 or more launches.
Where (a) and (b) both exist, the (b) majority is one of the product's own categories 85% of the time.

**Classifier (c), validated against (b) by time** (choose on Jul-Aug, fit on launches before Sep 1, test on 1,619
launches Sep 1 - Nov 1; day-bootstrap 95%):

| Classifier | top-1 = majority | majority in top-3 | top-1 is any Similar-Products category |
|---|---|---|---|
| zero-shot (category name + description) | 19.7 [18.0, 21.5] | 35.4 [33.0, 37.9] | 38.5 [35.9, 41.1] |
| centroids of earlier labelled launches (chosen) | 41.5 [39.1, 44.0] | 64.6 [62.2, 67.0] | 64.8 [62.2, 67.3] |

Top-1 agreement rises with how clear the majority is (share >= 0.8: 51%). Per category (20+ launches, 91
categories with test rows), the median top-1 recall is 46%. It is good for concrete categories (App switcher 77%,
Customer support 70%, Online learning 67%, Calendar 67%, Video editing 65%) and poor for broad or overlapping ones
(Automation tools 4%, Productivity 7%, Project management 11%, Team collaboration 15%). The most common confusions
are near-synonyms (Productivity / App switcher, AI Infrastructure / Foundation Models, Automation tools / AI Workflow
Automation, AI Dictation / AI notetakers). Product Hunt's 248-category list overlaps a lot, so top-3 is the fairer
number for competitor search.

## 2. Competitor sets
For the 5,150 launches on the 191 backtest days and the 2 shortlist days held (Nov 23, 24): 5 competitors each
(99.9%), on average 4.1 from PH Similar Products that share a category with the launch (93% of launches have at least
one), the rest the most-reviewed online products of the launch's primary category. Each competitor records its
source, categories, shared categories, reviews, rating, URL and tagline. Products marked no_longer_online and the
launch's own product are dropped. 6.4% of these launches have no Similar Products row (after Nov 1): category
fallback only.
Nightly: `run_category lineup --lineup today_0005.json --day D` gives categories and competitors for a new line-up
(tested on Nov 24: 40 of 42 by the classifier, 2 by the product's own label).

## 3. Structural miss by category (frozen arm-3 backtest, 191 days, Apr 1 - Nov 22, 5,073 launches)
Miss = real rank - structural rank (positive = finished below its structural rank). Overall: mean absolute miss 6.4
places; the structural top 3 captures 56.2% [52.9, 59.5] of the real top 3 (571 real top-3 launches).

- **Category carries a little of the miss.** The between-category share of the miss variance is 3.8% against 1.9% for
  shuffled labels (permutation p < 0.002), over 4,044 launches in 76 categories with 20+ launches. 11 of 76
  categories have a mean miss clear of zero at 95%; about 4 would be expected by chance.
- **Better than the model expects (mean miss below 0):** Games -6.0 [-9.3, -2.7], Screenshots and screen recording apps
  -4.1 [-6.1, -2.3], Chrome Extensions -2.6 [-4.3, -1.0], Note and writing apps -2.2 [-3.8, -0.9].
- **Worse than the model expects:** No-Code AI Agent Builder +6.2 [+2.8, +10.0], GEO Tools +4.1 [+0.9, +7.2], AI
  Workflow Automation +3.2 [+1.6, +5.0], SEO tools +3.2 [+0.4, +6.5], Lead generation +3.1 [+0.6, +6.0], Marketing
  automation +2.6 [+0.5, +4.4], Foundation Models +2.4 [+1.1, +3.8].
- **Top-3 capture by category** (real top-3 launches the structural top 3 caught): from 80.0% [64, 92] for AI Workflow
  Automation (25 real top-3) and 77% for AI Chatbots and AI Generative Media, down to 52.8% [36, 69] for AI Coding
  Agents (36) and 0 of 5 for Note and writing apps. Most categories have under 10 real top-3 launches, so their
  intervals are wide. Every category's numbers, spread, IQR and the 3 largest over- and under-performers (launch ids,
  private copy) are in `results.json` / `category1_results_full.json`.
- **Same-day category competition** (other launches of the same category that day; 31-41% of launches have one).
  Within-day regression of the miss on that count, controlling for structural rank, day-bootstrap 95%:

| Category label used | places per same-category launch | Spearman (raw) |
|---|---|---|
| Similar-Products label (read Nov 1; not knowable at 00:05) | +0.14 [-0.22, +0.50] | -0.001 |
| classifier fit on launches before Apr 1 (knowable at 00:05) | +0.36 [+0.09, +0.62] | +0.036 |
| zero-shot classifier (knowable at 00:05) | +0.20 [-0.09, +0.48] | +0.037 |

  With 3+ same-category rivals, launches finish about 3% of the line-up lower than predicted. That is small, and clear
  only with one labelling.

## Leak checks: Similar Products were read on Nov 1
- **Competitors that did not exist yet.** The share of a launch's dated Similar Products whose first post is after
  the launch is 0% for launches read within 12 days (the most recent 300). It rises with age: 0.8% at 13-30 days,
  1.9% at 31-90, 4.2% at 91-180 and 7.8% at 181+ (21% of the oldest launches have at least one). Backtest competitor
  sets for old days therefore include some later products; for PRODUCT-USE-1 (forward) this does not apply.
- **Popularity of the listed competitors.** Mean log reviews of the listed products barely moves with age (2.35 to
  2.49). Competitor popularity correlates with the miss (launches whose competitors are well reviewed finish below
  their structural rank): Spearman +0.24 [+0.14, +0.35] on the recent 300 and +0.08 [+0.05, +0.11] on older
  launches. That is weaker, not stronger, for lists read long after the launch, so later popularity does not create
  the effect.
- **Category labels.** Per-category mean misses with the Similar-Products label and with the 00:05-knowable label
  correlate at Spearman 0.60 over 67 categories, while the two labels agree on 37% of launches. Per-category
  conclusions should be quoted with the label used; the 00:05 label is the one a live feature may use.
- Only the classifier labels, the line-up and same-day launch counts from the line-up are knowable at 00:05. Backtest
  line-ups are the backtest's launch lists (they include launches featured later that day).

## For PRODUCT-USE-1
- **Category:** the product's own Product Hunt label when the slug is a known product. Otherwise the classifier's top 3
  (not top 1: the list overlaps heavily) from `run_category lineup`.
- **Competitors:** for launches with Similar Products, the first 2 that share a category (PH's own order, the
  nearest). For new launches, Similar Products from the fleet's nightly read once it exists (from Nov 26). Until then,
  the most-reviewed online products of the category, which are the category leaders, not the nearest rivals. Prefer a
  launch's own PH list whenever it exists.
- **Score by category:** compare within categories with 20+ launches. Start with those where the structural model is
  clearly off: under-performers (agent builders, GEO / SEO, AI workflow, lead generation, marketing automation,
  foundation models) and over-performers (games, screenshot / recording apps, Chrome extensions, note apps). The
  north-star question is whether use-and-compare findings explain those misses.
