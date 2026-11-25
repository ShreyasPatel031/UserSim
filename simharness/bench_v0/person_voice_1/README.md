# PERSON-VOICE-1 (Nov 25 2026): tuned Qwen vs Gemini Flash vs untuned Qwen on person match

**Result: closed for person voice.** On the 1,450 test + forward Task C rows with a second commenter, tuned Qwen 2.5 7B
equals Gemini Flash with history on person match: +0.4 [-1.2, +2.5]. Both beat untuned Qwen by about 6 points, and
the person's own last comment still beats all of them.

## Arms
All four arms use the same rows (benchmark + FORWARD-C-1 overlays, Nov 11-24, `run_person_voice rows`).
- **tuned Qwen 2.5 7B:** the qwen7b-c adapter (4,000 training comments to Oct 31), generate-only GPU job.
- **untuned Qwen 2.5 7B:** from the same job.
- **Gemini 2.5 Flash:** `PromptComment` with history, temperature 0.7, regenerated on these rows so its history
  includes the stream comments.
- **Reference:** the person's own last comment.

Scoring: `task_c.TaskC.score` with tau 0.7497. Pairs use a day-clustered bootstrap, 2,000 resamples.

| Rows | n | tuned | untuned | Flash | own last comment | tuned - Flash | tuned - untuned | Flash - untuned |
|---|---|---|---|---|---|---|---|---|
| all | 1,450 | 61.4 [59.0, 64.1] | 55.2 [53.7, 57.0] | 60.9 [58.6, 62.9] | 66.1 [62.9, 69.8] | +0.4 [-1.2, +2.5] | +6.1 [+4.1, +8.4] | +5.6 [+3.2, +7.9] |
| test days, new rows from the stream | 941 | 59.9 | 54.9 | 59.9 | 64.5 | -0.2 [-2.1, +2.3] | +5.0 [+3.1, +7.0] | +4.9 [+2.3, +7.3] |
| test days, rows already in the benchmark | 383 | 62.4 | 55.4 | 62.3 | 66.4 | +0.0 [-4.2, +2.5] | +7.0 [+2.2, +10.8] | +7.1 [+3.2, +10.2] |
| forward days Nov 23-24 (2 days: interval not meaningful) | 126 | 69.0 | 57.1 | 63.2 | 75.8 | +5.6 | +11.9 | +6.4 |

The cells are person match (own_vs_other, %). Content match (sim >= tau): tuned 25.9, untuned 34.8, Flash 40.7, own
last comment 13.2. Tuned minus Flash on content is -14.8 [-17.0, -12.4]. The tuned model writes short comments (0.74 x
real length) that restate the product less. Tuned minus own last comment on person match: -3.3 [-6.4, +0.2].

**Clean test.** Every row is dated Nov 11-24 2026. That is after Gemini 2.5 Flash's and Qwen 2.5's knowledge cutoffs
and after the fine-tune's training window (training rows end Oct 31). All 1,450 rows are therefore out of sample for
every arm; the split by row origin is shown above.

## Leak checks (`rows_info.json`)
- 0 history events on or after the row's day, and 0 timed after the day's start.
- The launch itself never appears in its own history.
- 0 rows on or before the training set's last day.
- 9 prompts contain the first 60 characters of the real comment. All are generic phrases ("Congratulations on the
  launch", "@someone Congratulations ...") that the person had already written earlier: history repetition, not a leak.

## Cost
- GPU: one spot a2-highgpu-1g in us-central1-f for 34 minutes. Standard A100s and L4s were out of stock in every
  us-central1, us-east1 and us-west1 zone tried. About $0.7 at spot price ($2.1 at the standard price at most).
- The VM deleted itself (checked: no `ft-pv1` instance remains).
- Gemini Flash: $0.73, estimated from characters.
