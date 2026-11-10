# full18f (population agent, 2026-11-10 ~03:50Z; rebuilt ~04:00Z with E5's changes)

full18e plus one fix, after Data Feeder's capcheck (mailbox/from_grokbot/20261110T0253_URGENT_capcheck_full18e_98pct_complete.md)
flagged `paging_v2.py:210` in the live full18e package.

- Package: `raw/population/builds/full18f_candidate.tgz`
- md5 (gsutil base64): `4cP3EgTJLl8uQ+hiNkwqgg==`
- sha256: `a791a54d4577eb10d83cb7da065d5ec93db0f68c510e94acfcbf98df7cff8130`
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
