# Today-rows bug: published 00:05 line replayed with the fixed builder (Nov 14, ~17:30Z)

today_replay.py, as of each night d: days/ files <= d-2. Polluted = every today/ file dated <= d plus features.py 981c5ded (what ran that night).
Fixed = today/<d>.json only plus 033d7bd7. Both arms run the same models, 5 seeds. The model is the one published that night: the old full model
('deployed', clean_live.py config) Oct 26 - Nov 12 and clean_nosite Nov 13. Nov 14 is not scored yet; Nov 5-7 have no line-up file.
Labels are warehouse daily_rank. Outputs: results/today_replay_{polluted,fixed}.parquet (id, day, deployed, clean_nosite).

| 16 days, Oct 26 - Nov 13 | top 3 | top 5 | top 10 |
|---|---|---|---|
| published (scoreboard 0005 rows; 11 live + 5 late) | 54.2 | 62.5 | 76.2 |
| replay, polluted builder | 52.1 | 58.8 | 74.4 |
| replay, fixed builder | 58.3 | 63.8 | 75.6 |
| fixed - polluted, paired day bootstrap | +6.2 [-2.1, +14.6] | +5.0 [-1.2, +11.2] | +1.2 [-1.2, +3.8] |

Live-source days only (11): published 51.5 / 60.0 / 73.6; polluted replay 48.5 / 54.5 / 71.8; fixed replay 54.5 / 61.8 / 73.6.
Reproduction check: the polluted replay gives the same top-3 hit count as the published file on 13 of 16 days. The other 3 differ by code
version, not by the bug: Oct 26 (published 100), Oct 31 and Nov 1.
The top-3 hit count changes with the fix on 5 of 16 days. The interval includes 0: 16 days cannot show the gain, only its direction.
By model: old full model fixed - polluted +6.2 [-2.1, +14.6] top 3; clean_nosite +0.0 [-6.3, +6.3] top 3, +3.8 top 5.
For the website: "replay with fixed inputs (not live)", 11 live days: 54.5 / 61.8 / 73.6 (live row 51.5 / 60.0 / 73.6).
