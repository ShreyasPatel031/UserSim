# Backtest calibration set v1 (built 2026-11-21)

Location: `gs://usersim-bakeoff-347838016394/usersim_sim/results/calibration/backtest_v1/`
Builder: `experiments/calibration/build_backtest_v1.py` (`fetch DATA`, then `build DATA OUT`). It re-runs in seconds.

Purpose: score the simulated-user tests (Atelier Sim plugin) and E5's persona choice against real Product Hunt
outcomes now, from data we already hold. No new Product Hunt requests were made.

Window: the 30 PT days 2026-10-22 to 2026-11-20. It covers 884 featured launches with a final daily rank.

## Files
| file | rows | what |
|---|---|---|
| launches.jsonl | 884 | day, launch_id, name, tagline, product_url (ref/utm stripped), url_kind, web_testable, final rank, votes, n_comments, main_competitor + all held competitor lists |
| comments.jsonl | 884 (8,755 comments) | every held comment per launch: text, created_at, is_reply, is_maker / role, votes; capture_note per day |
| cohort.jsonl | 884 | held backers (complete people who upvoted) and held commenters, counted by E5 segment; n_held_backers, coverage = held backers / votes |
| predictions.jsonl | 884 | the published 00:05 forecast rank (and 03:45 before-reveal where held); E5 explain who / say / competitors where that day exists |
| sample_for_plugin.json | 40 | stratified, web-testable, paste-ready: name, product_url, competitor, day, rank, plus comment count, coverage and explain flag |
| build_stats.json | - | counts behind this README |

## Sources
- Outcomes: warehouse `tables/launches` (newest row per launch). Comment count: `raw/store/days/<day>.json` commentsCount, raised to the held count where the day file was read before the day closed.
- Product URL: `raw/daily/<day>/sites_0005.json` for Nov 11–20; `raw/sites_ph.jsonl` and `ph_at_launch/<day>/products.jsonl` for older days. 684 are resolved. The other 200 have only the PH redirect link (`website`); they are marked `unresolved` and not web-testable.
- web_testable is true for 647 launches (`web` 623, `code_repo` 24). It is false for app stores (15), extension stores (1), blog or news posts (21) and unresolved links (200).
- Competitors: the first source that has one wins. A source's first item is skipped when it is the launch's own product.
  1. PH "Similar Products" (`raw/ph_alternatives`, read Nov 1; launches Oct 22–Nov 1).
  2. `raw/ph_predict_data/competitors.json` (Oct 22–24, with a domain).
  3. E5 explain `competitors` (similar earlier PH launches by embedding; Nov 14–20).
  Nov 2–13 have no competitor held. In total, 489 launches have one.
- Comments: `ph_at_launch/<day>/api_comments`, `api_replies` and `live/comments_ts.jsonl`, deduplicated by comment id. Oct 22–24 come from warehouse `tables/comments`.
  - A comment is marked maker when the commenter's PH user id is in the launch's makers (from the day file or `api_teams.jsonl`), or when the capture flagged it.
  - Text is HTML-stripped. Every @handle becomes `@user`, and makers' usernames found in the text become `[maker]`.
- Comment themes: **not held** (`comment_themes: null`). No E5 or PH-agent theme labels exist for these launches' own comments. E5 explain themes describe competitor launches. `tables/judge_labels` covers older launches only.
- Cohort:
  - People come from store_v3 (published 2026-11-20 09:09Z). A backer is a complete person whose upvote list holds the launch. A commenter is any held person with a comment event on the launch, or whose PH user id matches a captured commenter.
  - Segments use E5's data-driven cut 2026-11-20 (`tmp/e5/private/segments/2026-11-20.parquet`). Names are "Group / Subgroup", the same names as `results/web/segments/2026-11-20.json` and the Nov 20 explain file.
  - For Nov 15–19 explain days, `backers_by_segment_explain_cut` also counts backers under that day's cut, whose names match that day's explain file.
  - **Every cell under 20 people is folded into `other`.**
- Forecasts: `results/web/predictions/<day>_0005.json` when held (model named: clean_nosite, then arm3 from Nov 17). Otherwise `results/web/forecast_0005/<day>.json` (the then-published 00:05 line).
  - `frozen_before_reveal` means the forecast was written before 04:00 PT on the day. It is false for Oct 25–28 and Nov 1.

## Explain predictions (E5)
- Explain files exist for Nov 7–20. **Only Nov 14–20 hold predictions** (who / say / competitors). Those 7 days give 250 launches.
- Nov 7–13 files hold only `who_actually`, which is observed after the day and is not a prediction. They are not used here.
- Nov 15–20 are true frozen predictions:
  - The file was written about 02:00 PT, before the 04:00 PT reveal.
  - `say` was predicted about 01:30 PT.
  - The who model reads data from before 00:00 PT.
- Nov 14 is weaker:
  - Its file was written at 22:31 PT on the day, after the reveal.
  - It uses segment cut Nov 15, so segment membership saw Nov 14 upvotes.
  - Its `say` block was predicted at 01:21 PT on the day.
  - It is flagged `written_before_reveal: false` and `segments_cut_after_day: true`.
- Segment names change between cuts (for example Nov 15 "Tech Innovators", Nov 20 "Experienced Curators"). Compare names within a cut only.

## Sample for the plugin
- 40 launches: 13 ranked 1–3, 14 ranked 4–10 and 13 ranked 11+. They cover 21 days.
- Selection, within each band:
  1. Launches with 20 or more held non-maker comments come first.
  2. Next, launches with 8 or more.
  3. Ties are broken by held-backer coverage.
  4. Each day gets at most one launch per band before any day gets a second.
- Of the 40, 31 have 20 or more non-maker comments, 24 have a competitor and 10 have an explain prediction.

## Gaps
- **Comment text:**
  - None is held for Oct 25, Oct 26 or Nov 5.
  - Oct 27–Nov 2 and Nov 9 hold only the first 20 top-level comments per launch, with no replies.
  - Nov 6–7 are partial.
  - Oct 22–24 are dated only, with no reply links.
- **Coverage is a floor on recent days.** New upvotes reach the store only after the daily Upvotes refresh reaches the voter.
  - The median is 0.505 for Oct 22–Nov 16 but 0.128 for Nov 17–20, and Nov 20 is about 0.
  - Re-run `build` after later store rebuilds before scoring who-they-are on Nov 17–20.
- **Coverage can exceed 1** (43 launches). PH's displayed vote count discounts some voters: accounts 1–12 months old count about half (E5's explain note).
- **No 00:05 forecast is held** for Oct 22–24 or Nov 5–7. 35 launches were missing from their day's forecast list (late featuring).
- **Product URLs:** 200 are unresolved (most on Nov 4–11). Code-repo URLs contain the repo owner's handle, which can be the same as the maker's PH username. It is kept because it is the product's own address.
