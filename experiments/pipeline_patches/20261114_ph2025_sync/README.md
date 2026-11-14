# 2025 history: sync the 26 missing days + day-end boundary fix (UNDEPLOYED; changes arm 2's live training set: Shreyas's word first)

1. `sync_2025.sh`: ~/w/ph_history/2025 on the VM has 339 of the bucket's 365 days (Dec 6-31 were fetched after the Nov 13 copy). The
   script copies the missing days (post count checked against raw/ph_history/manifest.jsonl, md5s logged to sync_2025_md5.tsv, never
   overwrites), rebuilds the private H25 data dir and scores llm_pitch / llm_brand for the new rows (h25_llm.py score; Gemini).
   Dry run 13:45Z Nov 14 into an isolated copy (/home/agent/w/phops_h26): 26 days synced, LLM scored for all 365 days, $0.09.
2. `fix_boundary.py`: drops posts whose featuredAt (PT) is not the file's day (collect_ph.on_day's rule; the Data Feeder's pull used an
   inclusive postedBefore). On the 365 bucket files: 2 posts (2025-06-23 16 -> 15; 2025-07-28 12 -> 11, one ranked). The 2026 store already
   applies on_day: 0 of 7,045 posts in data/days/ sit on the wrong day (the 204 the audit saw are the pre-fix originals kept in
   data/days_backup_dedupe/, which no build reads).
Backtest effect of (1): see results in the orchestrator report (arm 2 with 365 vs 339 days of 2025, paired, 183-day rule).
