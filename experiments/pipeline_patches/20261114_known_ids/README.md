# 20261114_known_ids: known launches stay in tonight's line-up; forecasts table ids from the parquet (UNDEPLOYED)

Bug sweep (orchestrator 18:35Z / 18:40Z Nov 14). It goes in the next live-code build and needs Shreyas's direct word.
- Item 1, known launches (forecast.py 61538501 -> forecast.py here; arm2_live/h25_live.py e3af37b4 -> h25_live.py here).
  - Before: a launch Gemini flags "known" was dropped from tonight's test rows, so it vanished from the published order.
  - Now: it stays in the ranked line-up with every llm_* input blank, and is dropped from training only.
  - The .md row says "(known to the LLM; ranked without LLM inputs)" and the parquet has a `known` column.
  - Measured (results/known_audit.json): 1 known launch in all 317 labelled 2026 days (Apr 24, finished #1); 0 on live nights. The backtest is
    unchanged (58.1 / 65.2 / 76.9 under either truth rule), so the quoted figures stand.
- Item 4, ids not names (pipeline/daily.py 27f0578d -> daily.py here; forecast.py adds `published_rank` to the parquet).
  - s_forecast now writes the forecasts table from the parquet's id + published_rank. It falls back to the .md name parse only for older parquets.
  - Oct 29 had 2 duplicated names, so 2 launches lost their id in the forecasts table (the P-point LM input and the dash export read it).
- Item 2 note: forecast.py trains on every labelled day with no day < d bound. It was never triggered: every published forecast was written
  before its day ended. With the today-rows fix (033d7bd7), a re-run after days/<d>.json exists gets 0 test rows and writes nothing.
Overlap: forecast.py is also changed by input_guards, arm3_shadow, repro and today_rows (callers). Separate hunks; merge in one build and run
`patch --dry-run` on the VM copy. h25_live.py is also changed by repro and today_rows (callers).
