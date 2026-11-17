# How optimistic are the published backtest numbers? A little (≈ +1.6 at top 10, ≈ +3.5 at top 3), and not beyond noise

Orchestrator request 12:44Z Nov 17. Scripts: `opt.py` (the run) and `score.py` (writes `result.json`). Counts and launch ids only.

## Design

**Days.** 19 days have both a held 00:05 line-up and the later re-read of the day: Oct 25 – Nov 4 and Nov 8 – Nov 15. The 00:05 files for Nov 5–7 are missing, and Nov 16 has no re-read yet. Data is the VM input snapshot `raw/model_inputs/arm2/20261116`.

**Training and seeds.** Training rows are identical in every view: 2026 day files before d plus the 2025 lists. Seeds 0–4, with the deployed arm-2 / arm-3 code (h25_live rules plus arm3_feats, norm strong).

**The six views of day d.** Each step changes one thing, so the steps split the gap:

| view | what it is |
|---|---|
| V0 | as captured at 00:05 |
| V1 | V0 + re-read text (name, tagline, description, topics) |
| V2 | V1 + re-read makers |
| V3 | V2 + re-read hunter profile |
| V4 | the full re-read record for every launch present at 00:05 (still the 00:05 line-up) |
| V5 | the re-read day file as the test day: the backtest condition, including launches added after 00:05 |

**Scoring.** Top 3 / 5 / 10 against the final daily rank. A launch absent from a view cannot be picked. Day bootstrap, 4,000 draws.

## 1. Paired gap, re-read (V5) minus as-of (V0), 19 days

| | top 3 | top 5 | top 10 |
|---|---|---|---|
| arm 2 | +3.5 [0.0, +8.8] | 0.0 [−4.2, +4.2] | +1.6 [−1.1, +4.2] |
| arm 3 | +3.5 [−3.5, +10.5] | −2.1 [−5.3, 0.0] | +1.6 [−1.1, +4.7] |

## 2. Where the gap comes from

Mean step changes, top 3 / 5 / 10:

| step | arm 2 | arm 3 |
|---|---|---|
| text edits (V0→V1) | 0 / 0 / 0 | 0 / 0 / 0 |
| makers added (V1→V2) | **+3.5** / +1.1 / 0 | **+3.5** / 0 / 0 |
| hunter profile (V2→V3) | 0 / 0 / 0 | 0 / 0 / 0 |
| other fields: media, links, counts (V3→V4) | 0 / −1.1 / 0 | +1.8 / 0 / 0 |
| line-up and day-file handling (V4→V5) | 0 / 0 / **+1.6** | −1.8 / −2.1 / **+1.6** |

**Line-up changes.** 24 launches were added after 00:05 over 19 days (10 of them on Nov 11), and 2 were removed. Of the final top-10 places, 4 of 190 (2.1%) went to launches not present at 00:05 (Oct 29 ×2, Nov 11, Nov 15). These cannot be picked live, so they cap the as-of top 10 by about 2 points. This is the main, structural part of the top-10 gap.

**Makers added after 00:05.** This is the only content edit that moves the top 3. Makers join a launch's team after midnight, and the re-read shows the larger team: team-size and maker-history inputs. It affects 2 of the 19 days.

**Text and hunter-profile changes** move nothing.

## 3. Honest labels: 00:05 view, 19 days

| | top 3 | top 5 | top 10 |
|---|---|---|---|
| arm 2 | 59.6 [50.9, 68.4] | 70.5 [62.1, 78.9] | 74.2 [68.4, 79.5] |
| arm 3 | 59.6 [50.9, 68.4] | 70.5 [63.2, 77.9] | 73.7 [67.9, 78.9] |

The site's labels are arm 3 56.3 / 66.5 / 77.3 and arm 2 58.0 / 65.2 / 76.5 (184 re-read days). Both lie inside these intervals, so the 19 as-of days do **not** differ from the labels beyond noise.

**Recommendation: keep the 184-day labels and add one line.** For example: "measured on the day's later re-read; on 19 days with the 00:05 view the same model scored about 1.6 lower at top 10 (−1.1 to +4.7) and 3.5 lower at top 3, mostly from launches and makers added after midnight."

A straight 184-day correction cannot be computed, because the 00:05 view exists only for those 19 days. Subtracting the measured gap would give about 75.7 at top 10 for arm 3, but that correction is itself uncertain.

## Arm 3 vs arm 2

| view | top 3 | top 5 | top 10 |
|---|---|---|---|
| as-of (V0) | 0.0 [0, 0] | 0.0 [−3.2, +3.2] | −0.5 [−2.6, +1.1] |
| re-read (V5) | 0.0 [−5.3, +5.3] | −2.1 [−5.3, 0.0] | −0.5 [−2.6, +1.6] |

- On these 19 days arm 3 does not beat arm 2 in either view.
- The arm-3 gain is not a re-read artifact: the difference is the same in both views, and the gap from the re-read is the same for both arms.
- These 19 days just don't show the 184-day gain (top 10 +0.9 [+0.1, +1.8]), and their interval [−2.6, +1.1] still contains it.
- **Decision input:** this run gives no evidence to unpublish arm 3 on optimism grounds. It also gives no new evidence for it; the case rests on the 184-day backtest.

## Leak checks

- The as-of view uses only `today/<d>.json` (captured at 00:05) plus day files before d.
- The re-read fields enter only in V1–V5, as labelled.
- The LLM scores are the stored per-launch scores, the same in every view (as in `e5_asof_0005.py`).
