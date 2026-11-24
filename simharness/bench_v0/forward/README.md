# FORWARD-C-1 (Nov 24 2026): Task C grows every day from the live comment stream

A day's comments are linked to held people the next morning through the commenter id on the live stream, instead of
waiting for a profile re-read. Each day becomes an overlay under `gs://.../simharness/bench_v0/forward/<day>/`
(private); this folder holds aggregates only.

**Result:** Task C rows on test + forward days go from 413 to 1,572 (+1,159), 1,450 of them with a second commenter
on the same launch. The new rows score like the old ones with the existing Flash prompts.

## How it works
- Builder: `simharness/domains/ph_live_comments.py`, run with `python -m simharness.run_forward_day --day D ...`.
  A stream comment is kept when it is unique by comment id, top-level, written on D (PT), by a complete held person,
  on a launch of D's 00:05 PT line-up, not by a maker or the hunter of that launch (ids from the line-up), at least
  15 characters, and the first by that person on that launch. Text: HTML removed, @handles replaced.
- Overlay: `items.parquet` (the 00:05 line-up: item_id, slug, day, title, summary, description, tags), `comments.parquet`
  (person_idx, item_id, item_idx, day_ord, ts, text; only rows that are not already in the benchmark), `meta.json`.
- Loader: `Benchmark(BENCH, overlays=[...])` or `bench.add_overlays([...])`. New launches are appended as items, new
  comment rows go into `comments` and the history. Days after the test split get the split name "forward", so
  `TaskC(bench).rows("forward")` works with its references. `simharness/task_c.py` needed no change.
- A person's history for day D sees their stream comments from earlier days, and only those written before D starts
  (the same filter as every other history event).
- Note: with overlays loaded, `rows("test")` also grows (413 to 1,428), because rows are split by day. Load only the
  overlays of forward days to keep the test rows as they were (their histories then miss Nov 11-22 stream comments).
- Launches of forward days carry the line-up description; benchmark items from Oct 26 to Nov 22 have none, and the
  loader leaves them empty unless `fill_descriptions=True` (that would change the prompts of existing rows).

## Per day

| Day | Split | Comments in stream | Kept by the builder | Already in benchmark | New rows | New rows with a second commenter | People (new rows) | Task C rows before | Task C rows now |
|---|---|---|---|---|---|---|---|---|---|
| Nov 11 | test | 388 | 80 | 43 | 36 | 35 | 24 | 55 | 91 |
| Nov 12 | test | 522 | 157 | 84 | 73 | 71 | 48 | 82 | 155 |
| Nov 13 | test | 306 | 122 | 57 | 65 | 64 | 34 | 55 | 120 |
| Nov 14 | test | 209 | 72 | 37 | 35 | 33 | 20 | 37 | 72 |
| Nov 15 | test | 264 | 81 | 47 | 34 | 34 | 22 | 50 | 84 |
| Nov 16 | test | 498 | 157 | 60 | 97 | 89 | 50 | 58 | 155 |
| Nov 17 | test | 691 | 214 | 23 | 191 | 180 | 110 | 23 | 214 |
| Nov 18 | test | 634 | 128 | 17 | 111 | 99 | 59 | 18 | 129 |
| Nov 19 | test | 583 | 198 | 17 | 181 | 174 | 128 | 17 | 198 |
| Nov 20 | test | 306 | 115 | 8 | 107 | 91 | 48 | 8 | 115 |
| Nov 21 | test | 239 | 55 | 4 | 51 | 46 | 32 | 5 | 56 |
| Nov 22 | test | 128 | 38 | 4 | 34 | 25 | 19 | 5 | 39 |
| Nov 23 | forward | 379 | 104 | 0 | 104 | 99 | 54 | 0 | 104 |
| Nov 24 (stream to 06:07 PT only) | forward | 120 | 40 | 0 | 40 | 27 | 19 | 0 | 40 |

Totals: test 413 -> 1,428 rows (466 people, 332 launches, 1,324 with a second commenter); forward 144 rows on 2 days
(65 people, 46 launches, 126 with a second commenter); test + forward 1,572 rows. From Nov 17 on, the profile reads
had brought in 5 to 23 rows a day; the stream gives 100 to 200.

Nov 24 was built from a stream that stopped at 06:07 PT: rebuild it tomorrow morning. On Nov 20, 22 and 24 the
stream holds top-level comments only (no reply rows), which is all the builder uses.

## Do the new rows behave like the old ones?
gemini-2.5-flash, the existing prompts (`PromptComment`, `PlainComment`, temperature 0.7), same match threshold
(tau 0.751, fitted on training comments). New rows: a fixed subsample of 600 of the 1,159 (all 144 forward rows + 456
test-day rows) to stay inside the cap. Old rows: the 413 test rows, texts taken from the earlier generation cache (no
new calls). Day-clustered 95% intervals.

| Rows | n | item-only prompt: match | history prompt: match | history - item-only (match) | history: own vs other | history - item-only (own vs other) |
|---|---|---|---|---|---|---|
| new rows, all | 600 | 36.7 [32.2, 40.0] | 45.0 [40.0, 50.5] | +8.3 [+4.5, +13.4] | 61.6 [58.3, 65.7] | +9.6 [+8.0, +11.9] |
| new rows, test days | 456 | 36.0 [30.6, 40.4] | 43.6 [38.0, 50.3] | +7.7 [+3.0, +14.0] | 61.9 [57.7, 66.7] | +10.1 [+8.1, +13.0] |
| new rows, forward days (2 days: interval not meaningful) | 144 | 38.9 | 49.3 | +10.4 | 60.3 | +8.0 |
| old test rows | 413 | 36.3 [31.4, 40.4] | 41.2 [34.0, 46.0] | +4.8 [+0.9, +7.3] | 60.2 [55.4, 64.1] | +11.5 [+7.7, +14.3] |

References on the new rows: a real comment from another launch matches 3.3% (floor, 5% by construction on training
rows), the person's own previous comment 13.0%, another commenter on the same launch 23.3%. On the old rows: 4.4%,
10.3%, 20.4%. The new rows sit at the same levels, and the history prompt beats the item-only prompt on both sets.

## Checks
- Linking: on 3 days, 201 (person, launch) pairs are in both the stream and the benchmark; 200 have the same text and
  the same timestamp. So the platform id -> person link is right and stream text equals profile text.
- 400 rows checked: 0 history events on or after the row's day, 0 timed after the day's start, the row's launch never
  in its own history; 167 of them have an earlier stream comment in their history.
- Overlay files hold person_idx, launch ids, day, time and text only: no platform user id, no username; 0 @handles in
  comment or launch text. 30 comments by a maker or the hunter and 65 on launches that were not on the 00:05 line-up
  were dropped.

## Nightly refresh (`python -m simharness.run_refresh --store STORE --out BENCH [--day D]`)
Rebuilds the benchmark tables from the current store and writes the overlays into them, so a history for day D holds
everything dated before D that the store and the stream hold. Not scheduled anywhere.

- **Inputs:** STORE = a local copy of the store (persons, tabs, events and `records/part-*.parquet` for comment text,
  2.3 GB); `--forward-root` = the overlay folders; `--lineup` = day D's 00:05 line-up, so D's launches are items
  before D's overlay exists; `--prev` only on the first run.
- **Output:** `BENCH/<UTC stamp>/` with the same six tables (same columns and types, same salted ids) plus
  `item_keys.parquet`, and `BENCH/latest`, a one-line pointer file. `Benchmark(BENCH)` follows the pointer.
  With `--sync gs://...` the build is copied first and the remote pointer last.
- **Stable keys:** every person and item of the previous build keeps its index; people complete now and new launches
  are appended. Row files from earlier rounds (HARD, CHOICE, ties) stay valid by index. `bench_v0/data` is untouched
  and remains the frozen reference for the round-1 numbers (pools in a new build differ by the few new people).
- **Checks before the pointer moves:** people, items, history (in total and per kind) and comments not lower than in
  the previous build; no person_idx or item_idx reassigned; same columns and types; no event dated on or after D in a
  history for D (the day state equals an independent count, and 400 sampled histories and their rendered text hold
  nothing from D or later); the build loads. On any failure the build is kept as `<stamp>.failed`, the pointer stays,
  exit code 1. Tested: a store copy without the records folder fails on the comment count and leaves the pointer.
- **Cost:** 76 and 82 seconds on this 4-core box in two runs (61 to 67 s of it reading comment text from the 48
  record files), peak memory 2.7 to 2.8 GB. Add about 1.5 minutes to download the store and 5 s to upload the
  build (28 MB). No model spend.
- **First builds (Nov 24):** people 93,595 -> 93,598; items 7,361 -> 7,430 (the Nov 23 and 24 line-ups); history
  658,220 -> 660,513; comments 53,631 -> 54,797 (1,160 from the stream overlays). Task C rows from the refreshed
  tables: test 1,428, forward 144, the same as loading the overlays on the old tables. Current build:
  `bench_v0/builds/20261124T182417Z` (pointer `bench_v0/builds/latest`).
- **Limits:** the store targets comments by launch slug and the item table is keyed by id. The refresh recovers
  slugs from the store itself (matching earlier comment rows by person and time) and carries them forward in
  `item_keys.parquet`; 7,313 of 7,430 items have one (the rest never had a held comment and were in no capture).
  Upvotes still arrive only through profile reads: the refresh cannot make histories fresher than the store.

## Spend
$0.41 of the $1 cap (item-only prompt 0.10, history prompt 0.31; estimated from characters, as in run_taskc).
