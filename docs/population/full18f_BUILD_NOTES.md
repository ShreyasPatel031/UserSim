# full18f (population agent, 2026-11-10 ~03:50Z; rebuilt ~04:00Z with E5's changes)

full18e plus one fix, after Data Feeder's capcheck (mailbox/from_grokbot/20261110T0253_URGENT_capcheck_full18e_98pct_complete.md)
flagged `paging_v2.py:210` in the live full18e package.

- Package: `raw/population/builds/full18f_candidate.tgz`
- md5 (gsutil base64): `uYYdW17hoPBJjpMGoR7lKw==`
- sha256: `6c9dfce23a5a8499cf4a12e10e8ea5c97a732f3349a9c761d33ea93458e88cc6`
- Same 16 files as full18e; only `paging_v2.py` and `tests/test_paging_v2.py` differ.

## Change

`paging_v2.py:210`: when paging left `ended` unset, a list was labelled `complete` at 98% of the header (non-follow lists)
or within 2 of the header (follow lists). It is now labelled `complete` only when `len(items) >= goal`; otherwise
`stopped` (if R.stop) or `unknown`, never exhausted. E5 (03:38Z Nov 10): a stop before the chain now keeps the saved
resume cursor (`nxt = nxt or start_saved` when ended == "stopped"). The header-2 slack for follow lists applies only
after a recorded `server_end_offset` (checked in quality.py). A list short of its header ends only at PH's own server end.

`paging_v2.py:212`: the signed-out upvote flag (`upv_capped`) is set for any upvote list that ends at the server short of
the header (was: short by more than 2%). This only flags more people for the signed-in pass.

In practice `ended` is unset only when the offset phase already read the full header, so the old 98% label could not fire
below the header in this code path. The fix removes it anyway so capcheck passes and no future path can rely on it.

## Merge gate (tools/population/quality.py)

The data-side check now matches: a tab is `complete` only with the full header; anything short needs PH's own end
(`ph_limit`), and follow lists short by more than 2 still need the offset re-page end. The collector's `complete`
label is no longer counted as a PH end. Tests: 21 paging tests (new: `test_98pct_without_server_end_is_not_complete`, `test_stop_before_chain_keeps_saved_cursor`)
and 13 store tests pass.

## Rebuild 2 (~04:00Z, E5 non-blocking notes 03:40Z)

- `ph_batch.py:989`: the signed-out upvotes merge clears the cap labels only at the full header (was 0.98 x header).
  Diff: `docs/population/full18f_ph_batch.diff`. Same 16 files; only `paging_v2.py`, `ph_batch.py` and the test differ from full18e.
- `quality.py` `ph_limit` (and `signed_out_end`) now require a recorded PH end (`ended in SERVER_END`);
  `complete_not_visible` alone no longer passes. Follow lists short by more than 2 already need the offset end with
  chao1_unseen < 0.5 (`_offset_depth_ok`), as `pdeep.whole` does.

## Store re-score (local snapshot ~02:55Z, every saved file, no sampling)

Old rule complete and new rule complete: 33,394. Old complete, new incomplete: 75 (re-queued in
`raw/population/requests/rerun_whole_20261110T0355Z_full18f_rule.txt`; per-person reasons in `raw/_cursor/fix_rule_full18f.txt`).
Reasons: upvotes signed-out end not queued for signed-in 41, followers short 13, collections short 9 (index short 9),
following short 7, stacks short 6, upvotes short 4. No person flipped the other way.
