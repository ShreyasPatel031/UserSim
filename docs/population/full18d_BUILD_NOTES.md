# full18d (population agent, 2026-11-08)

full17 (Ku9PrVAfo8f+uDrIVfW8Bg==) plus paging_v2.py, pdeep.py, ph_batch.py and tests/test_paging_v2.py.

- paging_v2: follow lists whose endCursor chain ends short of the header by > 2 and > 2% are re-paged by offset from 0, in full passes, merging by id.
  - Closure (server_end_offset) needs three things on a full-depth pass (rows served >= 98% of the union):
    - the union reaches the full header, or 3 zero-new full-depth passes in a row (2 for lists <= 1,000 with the union >= 98% of the header);
    - Chao1 unseen < 0.5;
    - full18d (E5): no closing on a 98%-of-header shortcut.
  - Not-whole ends: repage_short_end, _stalled, _max_passes (8 per attempt), _exhausted (24 across attempts; to review/), _offset_clamped / _ignored / _runaway, _stopped / _budget / _blocked / _error.
  - State (union, per-id pass counts, passes) lives in <PH_SAVE_B>/_repage_state/; entries expire after 7 days; nothing is saved for runners named "_*".
- pdeep.whole: such a list needs server_end_offset, a full-depth closing pass and chao1_unseen < 0.5.
- Run the tests: `cd tests && python3 -m pytest -q test_paging_v2.py`.

Remaining risks (E5):
1. Rarely-served accounts. An account PH serves in few passes can still be missed. In simulation, about 1 account in roughly 50 closed lists.
2. Profiles still gaining followers. New followers arrive during the passes, so a pass rarely adds zero new on very active profiles. These end stalled or max_passes and are resumed.
3. The class-3 cause is not yet measured. It is unproven whether short lists come from hidden accounts or from paging. The first real run (one 1k-10k profile reporting its repage record) should show which.
