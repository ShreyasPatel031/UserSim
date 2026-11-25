# WHAT-PANEL-4 (Nov 25 2026): does panel + 15 keep its WHAT gain on more days?

**Read: the precision gain holds, the complaint-recall gain does not replicate, and recall is unchanged.** On 85
launches over 6 new days (Nov 15-20), adding the 15 person-built Flash comments to the persona panel raises theme
precision by +11.3 points [+6.8, +14.7]. Theme recall is -1.2 [-4.1, +1.2] and complaint recall -1.3 [-5.4, +3.4]:
the +8.7 complaint-recall gain of WHAT-PANEL-3 does not come back. Nothing is clearly worse, so no revert alarm. The
live 7-day rule decides as planned.

## Method
- **Person-built comments, as the deployed job writes them** (E5's person_panel.py): the run_what_panel build
  selection (30 held people per launch, bench_v0 Nov 23 tables), a draw of 15 ordered by md5(launch id + day), one
  gemini-2.5-flash call each at temperature 0.7 with the privacy line, and the privacy guard (maker-like, self-named or
  own-history-product comments are dropped and the next person is taken).
  - 1,817 calls over 109 launches; 238 comments dropped (maker-like 138, own-history product 31, self-named 9,
    empty 4); 15 kept per launch.
  - Code: `simharness/run_what_panel4.py`. Arm files: `results/calibration/<day>/what_panel/person_built_flash_deployed15.json` (bucket, private).
- **Scorer:** E5's frozen consensus truth (`truth_<D>.v1.json`) and the JUDGE / CJ prompts (bfbed0a3 lineage,
  branch claude/person-model-v2). Gemini Flash at temperature 0, 3 judge runs per launch and arm; the launch value is
  their mean.
- **Arms:** "panel" = the persona panel items (`results/web/explain/<D>.json`); "panel + 15" = the same items followed
  by the 15 comments (the deployed forward_says merge).
- **Launches:** those E5's forward_says v1 scored (5+ non-team comments) that have truth and a panel.
- **Pairing and intervals:** paired by launch; day-bootstrap and launch-bootstrap 95% intervals.
- **Re-scoring the WHAT-PANEL-3 days:** WHAT-PANEL-3 published only pooled numbers, so Nov 21-23 were re-generated and
  re-scored with this exact protocol. That gives launch-level values to pool.

## Results (paired difference panel + 15 minus panel, %; [day-bootstrap 95%] / launch-bootstrap 95%)

| Days | Launches | Theme recall | Theme precision | Complaint recall |
|---|---|---|---|---|
| Nov 15-20 (new) | 85 / 6 days | -1.2 [-4.1, +1.2] / [-4.5, +2.0] | **+11.3 [+6.8, +14.7]** / [+6.5, +16.4] | -1.3 [-5.4, +3.4] / [-5.6, +2.7] |
| Nov 21-23 (WP3 days, re-scored) | 24 / 3 days | +0.3 [-4.2, +3.1] / [-4.9, +5.5] | **+15.4 [+7.3, +20.7]** / [+7.5, +24.7] | +4.3 [-3.6, +18.4] / [-5.9, +14.4] |
| pooled Nov 15-23 | 109 / 9 days | -0.9 [-3.4, +1.2] / [-3.6, +1.8] | **+12.2 [+8.5, +15.3]** / [+7.9, +16.7] | -0.0 [-3.8, +4.4] / [-4.2, +3.7] |
| WHAT-PANEL-3 as published (3 random draws of 15, no guard) | 24 | +2.3 [-1.9, +6.6] | +8.5 [+0.3, +16.5] | +8.7 [+2.9, +14.7] |

Levels for Nov 15-20, panel vs panel + 15: recall 73.9 vs 72.7, precision 53.4 vs 64.6, complaint recall 33.8 vs 32.6.

Per day, the precision gain is positive on 8 of 9 days. The exception is Nov 20 (6 launches): -3.3. The
complaint-recall difference swings by day from -7.2 (Nov 17) to +18.4 (Nov 22, 5 launches).

The judge has drifted: this run's panel-only scores sit above E5's forward_says v1 values for the same launches
(Nov 15-20: recall +5.3, precision +4.1, complaint recall +8.9). Both arms were judged together in this run, so the
paired differences are not affected. Levels should not be compared across runs.

## Leak checks
- 3,270 prompts checked: 0 history lines dated on or after the launch day.
- 19 comment lines name a launch of the same day. All are on earlier launches with the same name (readywhen, OpenBot,
  Freebuff relaunches, earlier dates in the item table): the history renderer only shows items of earlier days and
  comments written before the day starts.
- No launch-day comment reaches any prompt.

## Spend
$2.27 in total: generation $0.61, judging $1.66.
