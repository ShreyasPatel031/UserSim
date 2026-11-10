# full18f (population agent, 2026-11-10 ~03:50Z)

full18e plus one fix, after Data Feeder's capcheck (mailbox/from_grokbot/20261110T0253_URGENT_capcheck_full18e_98pct_complete.md)
flagged `paging_v2.py:210` in the live full18e package.

- Package: `raw/population/builds/full18f_candidate.tgz`
- md5 (gsutil base64): `PU9LpI43fvU98ctFrFF95g==`
- sha256: `dbb72c6f89a646db5ced9792b59d177b7be7b09f8f8b08081ef0b35e87e96837`
- Same 16 files as full18e; only `paging_v2.py` and `tests/test_paging_v2.py` differ.

## Change

`paging_v2.py:210`: when paging left `ended` unset, a list was labelled `complete` at 98% of the header (non-follow lists)
or within 2 of the header (follow lists). It is now labelled `complete` only when `len(items) >= goal`; otherwise
`unknown` (not exhausted; the resume cursor is kept). A list short of its header ends only at PH's own server end.

`paging_v2.py:212`: the signed-out upvote flag (`upv_capped`) is set for any upvote list that ends at the server short of
the header (was: short by more than 2%). This only flags more people for the signed-in pass.

In practice `ended` is unset only when the offset phase already read the full header, so the old 98% label could not fire
below the header in this code path. The fix removes it anyway so capcheck passes and no future path can rely on it.

## Merge gate (tools/population/quality.py)

The data-side check now matches: a tab is `complete` only with the full header; anything short needs PH's own end
(`ph_limit`), and follow lists short by more than 2 still need the offset re-page end. The collector's `complete`
label is no longer counted as a PH end. Tests: 20 paging tests (new: `test_98pct_without_server_end_is_not_complete`)
and 13 store tests pass.
