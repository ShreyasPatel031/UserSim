# full18e (population agent, 2026-11-08 ~20:45Z)

full18d (T3OI+xr3iAvoMDMZrdryhA==) plus one no-cap change (Data Feeder capcheck from_grokbot/20261108T1948_URGENT_capcheck_full18d_98pct_repage.md; orchestrator decision 20:34Z):

- paging_v2.py: a follow list (followers/following) whose chain ends short of its header is re-paged by offset whenever it is short by
  more than 2. The `len(items) < 0.98 * goal` condition is removed; under full18d a 10k list up to 200 short was never re-paged.
  The <=2 slack stays (deleted accounts).
- paging_v2.py: a follow list with no recorded end is labelled `complete` only within 2 of its header (other lists keep 98%).
- pdeep.py whole(): the same rule. A follow list short by more than 2 needs server_end_offset with a full-depth closing pass and
  chao1_unseen < 0.5.
- Tagged, unchanged: `need = 3 if goal > 1000 or union < 98%` (nocap2: only makes closure stricter); MAX_PASSES 8 / TOTAL_PASSES 24
  (not-whole stops: saved NOT whole and resumed or reviewed, never counted complete).
- tests/test_paging_v2.py: + test_short_by_one_percent_is_repaged (9,900 of 10,000). 19 pass: `cd tests && python3 -m pytest -q`.

Matching audit change: tools/population/quality.py tab_state (branch claude/population-data).
Not deployed. First-run audit (one 1k–10k-follower repage record plus a 5-person sample) is still required before use.
