# Stability review reproductions (orchestrator 02:00Z Nov 14), no network
Each script loads the real module from a checkout root and exits 0 when the defect is fixed, 1 while it is present.
- repro_A1.py <ph-website root>: past-day final read must not overwrite site/live_board/latest.json; cold board(today) must fall back to <today>.json.
- repro_A5.py <ph-website root>: payload holds only 0005 / PRE; no unlabelled P345 or P1-P4 shown as the 03:45 prediction; ph.html pre tab has no P* fallback.
- repro_A8.py <ph-ops root>: 12a prereveal writer uses a recorder read stamped 03:45:07 PT.
Baseline (ph-website 83b89e6e, ph-ops 4585dcf2): all three FAIL (exit 1).

## Bundle 12a residuals (d9b9a96f, Nov 14)
All four take the ph-ops checkout root and exit 0 when fixed.
- repro_A9.py: stale before-reveal read.
- repro_A10.py: 01:30 midnight slot and done_ok.
- repro_A11.py: rollback inside 00:05–01:00 PT, both deploy scripts.
- repro_A12.py: import_gate.py on the Nov 14 missing ctrl/honest case.

All pass on d9b9a96f (two_predictions.py 0f17e09e). A9–A11 fail on 263785f8 as expected; A12 tests a file new in d9b9a96f.
