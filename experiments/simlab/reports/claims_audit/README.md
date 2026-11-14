# Claims audit of origin/claude/ph-website at eca1be31 (E5, Nov 14 ~01:45Z, read-only)

Sources read: mvp/static/ph.html, try.html; mvp/ph_site/claims.json, live.py, try_sim.py, routes.py. Recomputed against E5 reports on
claude/person-model-v2 and the raw recorder / PH ops dumps.

## Mismatches / stale (fix before public)
| # | Where shown | Item | Source | Recomputed | Verdict |
|---|---|---|---|---|---|
| 1 | /ph 00:05 tab accuracy line | 214-day backtest row (arm 2 60.7 / 68.4 / 75.7) | live.accuracy() replaces the track-record "backtest" row with claims.midnight_accuracy rows | 60.7 [57.8, 63.7] / 68.4 / 75.7 (214 d) | DROPPED: the override keeps only "live" from the file; show 214-day row next to Sep-Oct |
| 2 | same | "backtest (Sep-Oct)" row days | claims.midnight_accuracy days: null | 61 days (Sep 1-Oct 31) | set days 61 |
| 3 | /ph 03:45 tab accuracy line | replay 72.7 / 74.5 / 78.2 (11 d) | track_record_v1 (E5 re-implementation of the current hybrid) | 78.2 = current published hybrid (pred_rank_hybrid); bundle 12a (VM-only hybrid) = 72.7 / 74.5 / 77.3 (PH ops) | correct until 12a deploys; switch to 12a replay rows on the first day results/web/predictions/<d>_prereveal.json exists |
| 4 | /try "Full 00:05 launch model (clean offline backtest, 214 days)" | 56 / 68 / 75 | claims.launch_model_backtest (honest_preds_v2) | clean_nosite 56.4 / 67.8 / 75.0 (matches) but the deployed 00:05 model is arm 2: 60.7 / 68.4 / 75.7 | STALE WORDING: relabel "previous 00:05 model" or show arm 2 |
| 5 | /try concerns note, forward check | 0.359 on 13 new launches (Nov 8-12) | claims.concerns_b20.forward (PH ops forward_sim pins ef1a54f4) | team-filter bug fixed (6584bf6f): b20 pasted p@3 33.3 [25, 42] n 32; deployed single item 40.0 [27, 53] n 45 | DIFFERS (-2.6, n 13 -> 32) |
| 6 | /try concerns backtest | "170 past launches" | claims.concerns_b20 | retrieval_rep.json pooled170: n 164 scored; b20 37.2 [32.5, 41.9], page 24.6 | n wording: 164 scored of 170 |
| 7 | /api/ph/today board.lock.reliability (API only, not rendered by ph.html) | "checked against final ranks each day; no tested reliability figure is shown yet" | live.py | old lock text | remove from payload |
| 8 | /api/ph/track-record (public endpoint, not called by ph.html) | PH ops scoreboard rows for P0-R4 points | live.track_record() | more than the two published predictions | retire or restrict to 00:05 / 03:45 |
| 9 | /ph 03:45 tab on days before PRE existed | falls back to the latest P1-P4 'best' ranking | ph.html pointFor("pre") | not the published 03:45 line | label as "earlier method" or hide |
| 10 | /ph accuracy line | "fallback: <raw fallback_used>" | ph.html accLine | bundle-12a fallback names not on a branch I can read | CANNOT VERIFY: map each name to plain words |

## Matches (verified)
| Item | Shown | Recomputed |
|---|---|---|
| rank_band_coverage | 0.797, 5,351 launches | landing_retrieval.json base 0.797, 5,351 |
| try_e2e PH band coverage | 80.5% [77.6, 83.1], 856; 80.0% of 130 | band_calib / band_recal_table: 80.5 [77.6, 83.1] |
| matches_vs_voting | 0.98% vs 1.04%, 114 | voters_eval.json precision top 0.0098, 114 |
| reactions_eval desc / page | 23% / 15% same point | same_point: 23.2 [14.3, 32.7] (28 launches - n not stated on page) / 14.7 (17) |
| person_sim | 22% vs 12%, 275 comments, 88 members | person_sim.json theme2 0.221, 275 pairs, 88 people |
| top_items | 1 in 2 vs 1 in 5; ceiling 1 in 3 | judge_reliability 49.3-49.5; ceiling 33.9-34.5 |
| try_stability | 56% reaction agreement, 47% concern overlap | try_stability README 56 / 47 |
| reactions_vs_humans | 158 launches | ceiling.json launches 158 (ratios not re-derived) |
| withdrawn 0.59 / 89% band | only inside claims.try_e2e.ph_note (not rendered) | gone from pages |

## Cannot verify here
similar_tools_auc 0.692 (person bundle eval not re-run); exp_votes_error (PH ops growth model); page_band 0.279 (site file);
launch_band_card_v2 validation figures (856 page reads); fallback names (item 10).
