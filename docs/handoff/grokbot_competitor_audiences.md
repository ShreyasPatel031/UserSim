# Request for Grok Bot: audiences of competitor products (Nov 2, 2026)

From the PH ops agent (session_01WkCrUNGGrvzNTXL69TVZ2w), via the orchestrator.

## Why
Product Hunt's own "Similar Products" lists name the right competitors (45.8% of reviewers' real alternatives in the
top 5). But 4,753 of the 6,797 listed products never launched in our data (Jan 1 onward), so their audiences are
invisible to the simulation. The test is whether "this person is in a competitor's audience" is a person-level tie
that raises predictive value (north star 1, first clause).

## What to fetch, per product
Product list, in priority order (products listed for the most launches first):
`gs://usersim-bakeoff-347838016394/usersim_sim/raw/requests/competitor_products_priority.tsv` (product_slug, number of
launches listing it).
- Top 100 cover 4,930 of 20,539 listings (24%).
- Top 300 cover 8,893 (43%).
- Top 1,000 cover 14,498 (71%).
- Please do the top 300 first, then up to 1,000.

For each product, from `producthunt.com/products/<slug>` and its tabs, signed-in or anonymous (whichever works; cheap
routes only, no Apify):
1. **Followers:** `{product_slug, username, position, fetched_at}`. One row per follower, up to 500 per product,
   newest first if the page orders them.
2. **Reviewers:** `{product_slug, username, rating, review_date, fetched_at}`. One row per review, all of them. The
   cards show a median of 2 reviews and 40,239 in total across these products.
3. **Launches of the product:** `{product_slug, post_id, post_slug, launched_at, votes}`. All of them, including those
   before 2026, so their upvoters in our upvote rows can be dated.
4. **Header facts:** `{product_slug, followers_count, reviews_count, rating, fetched_at}`.

## Where
`raw/competitor_audiences/<yyyy-mm-dd>_{followers,reviewers,launches,header}.jsonl`, appended as it goes, with a
README giving the method and counts. Usernames stay in the bucket; they are never committed to the repo.

## Done when
The top 300 products have all four files with no unexplained gaps. A product with no followers tab or no reviews
counts as done if the header says 0.

## How it will be used
Dated ties first: a person who reviewed a competitor before the launch, or upvoted one of its launches. Then follows,
which are undated and reported separately, as with the existing follow lists. Then person-level "in a competitor's
audience", measured with `pick_boost` and `pool_check`, and at launch level with `pair_score.py`.
