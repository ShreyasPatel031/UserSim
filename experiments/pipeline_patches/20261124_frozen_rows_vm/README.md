# 20261124_frozen_rows_vm: frozen shadow rows written from code on the VM

Requested by the orchestrator at 13:35Z Nov 24. This is a timing-only change: inputs, features and scoring are unchanged.

## What changed

**VM.** The bundle-12a job `frozen` runs at 01:25 PT, with a retry at 02:45 PT (both before the 03:45 PT cut). It runs:

```
promo_posts_shadow.py freeze <d>
four_inputs_shadow.py freeze <d>
```

Both run from `~/w/frozen_rows`, which holds copies of the two frozen rule files. Each line's row is built by the unchanged `write()` code and uploaded once to `gs://.../results/frozen_rows/<line>/<d>.json`. That file is never rewritten. Each row carries `on_time` (written before 03:45 PT) and `frozen_by`.

**Session.** At 03:07 PT the session runs `pull` for each line. It appends bucket rows that are not yet in the repo files, unchanged:

```
results/promo_posts_shadow.jsonl
results/four_inputs_shadow.jsonl
```

- promo_posts skips late rows, because its scorer has no on-time filter.
- four_inputs keeps its own flag; `score()` counts on-time rows only.

## Files

| File | md5 change |
| --- | --- |
| run.sh | 8f032a1c → 8c4805e7 |
| sched12a.txt | 73c5b085 → 6d2dcc76 |
| promo_posts_shadow.py | 38a0e7db |
| four_inputs_shadow.py | f8375555 |

## Checks (13:46–13:48Z Nov 24)

- `check`: OK.
- `selftest` (install and rollback on scratch copies): deploy gave `8c4805e7 6d2dcc76 38a0e7db f8375555`; rollback gave `8f032a1c 73c5b085` and the new folder was removed.
- `rehearse 2026-11-24` (the real job case run from scratch, uploads captured to scratch): rc=0, 42 launches for each line. The four_inputs shadow_order md5 was 5c40d6a6, the same as the row already in the repo. Locally, a promo row rebuilt for Nov 23 matched the logged row on every field except written_at.

## Rollback

```
bash ~/w/stage/20261124_frozen_rows_vm/deploy_frozen.sh rollback
```

This restores `~/w/backup_tw12a/{run.sh.8f032a1c, sched12a.txt.73c5b085}` and removes `~/w/frozen_rows`.
