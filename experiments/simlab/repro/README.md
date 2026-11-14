# Stability review reproductions (orchestrator 02:00Z Nov 14), no network
Each script loads the real module from a checkout root and exits 0 when the defect is fixed, 1 while it is present.
- repro_A1.py <ph-website root>: past-day final read must not overwrite site/live_board/latest.json; cold board(today) must fall back to <today>.json.
- repro_A5.py <ph-website root>: payload holds only 0005 / PRE; no unlabelled P345 or P1-P4 shown as the 03:45 prediction; ph.html pre tab has no P* fallback.
- repro_A8.py <ph-ops root>: 12a prereveal writer uses a recorder read stamped 03:45:07 PT.
Baseline (ph-website 83b89e6e, ph-ops 4585dcf2): all three FAIL (exit 1).
