# Handoff: which Capterra + G2 review data helps predict a user's experience

For an agent that runs UserSim tasks and wants context on how a given kind of user experiences a product.
All numbers are from held-out products: each product's own reviews were excluded, and strategies were chosen on
other products (`router_eval.py`, `g2_merge.py`). Prediction outputs are judged against the real reviewer's
ratings and review text. Text outputs were judged by Gemini 2.5 Flash; nothing was checked by a human.

## Data

| Source | Size | Per-reviewer fields that matter |
| --- | --- | --- |
| Capterra (FreshCrawl snapshot `fc7c316c`) | 56,606 reviews, 66 products, 9 categories | role, industry, company size (9 bands), **time used**, 6 ratings, pros, cons, switched-from, reasons |
| G2 (FreshCrawl snapshot `d8a82cb5`) | 111,441 reviews, 79 products | role (50%), company size (3 bands), star rating, likes, dislikes, problems solved |

G2 has no time-used field and only 3 size bands. Those two fields carried most of Capterra's signal.

## What to give the agent (per person: role, industry, company size, time used, task, previous product)

| Context piece | Built by | Helps |
| --- | --- | --- |
| **People-like-them rating averages**: mean rating of reviewers with the same role family / size / time used / industry across other products, shrunk to the overall mean | `corpus.sections()["averages"]`, `ux_mcp.people_like_them` | All ratings. Use the number directly for overall, value, support and recommend |
| **Competitor complaint-topic rates**: share of same-category competitor reviews mentioning pricing, support, learning curve, reporting, customization, integrations, etc. | `sections()["competitors"]` | Cons; predicting a new product's complaint profile (reporting error −46%, support −36% vs a blind guess) |
| **8 reviews from the most similar people on competitor products** (role > size > time used > industry) | `sections()["similar_reviews"]` | Pros, cons, overall experience in words |
| **Competitors' user mix** (counted shares of roles, sizes, industries) | `usage.py` `distributions()` | Who will use a new product: 2–3× closer than the agent guessing |

## Per output: what to send (router `out/router/router.json`, chosen on 25 dev products)

| Output | Best strategy | Agent alone → with data (10 held-out products, 120 people) |
| --- | --- | --- |
| Overall rating | agent + averages | error 0.96 → 0.55 |
| Value for money | **averages as the answer** | 0.96 → 0.69 |
| Customer support | **averages as the answer** | 1.22 → 0.78 |
| Recommend (0–10) | **averages as the answer** | 1.92 → 1.34 |
| Ease of use | agent + averages; merged Capterra + G2 averages did best | 0.86 → 0.68 (merged 0.58) |
| Functionality | averages | 0.72 → 0.59 |
| Pros | full package | 32% → 38% matched |
| Cons | full package; G2 reviews did best | 22% → 26% (G2-only data 28%) |
| Overall experience in words | agent + averages | 10% → 23% same sentiment and main point |
| Spotting unhappy users | none works | 0.51 → 0.53 AUC (coin flip) |

G2 replication (8 held-out G2 products): G2 data cut overall-rating error 1.01 → 0.83. Capterra data barely helped
G2 reviewers, but it never made things worse, so it is kept.

## What did not help, or hurt

- **The product's own website and O*NET occupation data**: no gain, and sometimes worse ratings.
- **Raw competitor reviews alone, with no averages**: much weaker than the averages.
- **The agent guessing ratings on its own**: it under-predicts by 0.5–0.8 stars, because review-site ratings skew to 4–5.
- **Feeding raw browser-run feedback into predictions**: worse on every output (overall error 0.60 → 1.55).
  - Those runs were logged out and never reached the product.
  - Their "frictions" were mostly the agent's own loops ("stuck clicking Products").
  - Never pass run feedback on unless the run was signed in and reached the product. Separate agent failures from product friction first.

## How to use it in a task run

1. Before writing feedback, attach the package for the persona as **outside evidence**:
   - `mvp/review_context.py::review_context`, or `corpus.sections(person, category, {"capterra", "g2"}, exclude_product, mask)`.
2. Observed frictions must still come only from the session.
   - Reviews may shape overall sentiment, conversion, and a separate `likely_frictions_from_similar_users` field.
3. For ratings, report the people-like-them average (or the agent's number given it). Don't let the agent guess raw.
4. When the product is in the datasets, exclude its own reviews if you are evaluating against them.

## Caveats

- One run per setup, and 80–120 test people per dataset.
- The per-output **source** choice (merged for ease, G2 for cons) was read off test results. Unlike the strategy choice,
  it isn't validated yet.
- Helps calibrate the *level* of experience for a kind of user. It does **not** reliably tell individuals apart.
