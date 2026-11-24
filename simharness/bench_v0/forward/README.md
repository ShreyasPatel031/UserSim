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
- Overlay: `items.parquet` (the 00:05 line-up: item_id, day, title, summary, description, tags), `comments.parquet`
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

## Spend
$0.41 of the $1 cap (item-only prompt 0.10, history prompt 0.31; estimated from characters, as in run_taskc).
