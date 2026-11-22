# gemini_decisions_shadow on the pipeline VM (orchestrator 05:50Z Nov 22; recording only, never the published 00:05 forecast)

Files on usersim-pipeline:
- ~/w/experiments/ph_predict/gemini_decisions_shadow.py (c9bbb774, new)
- ~/w/tw12a/run.sh 5cd8b9e5 → 208a1587 (adds the job cases gdsw and gdss)
- ~/w/tw12a/sched12a.txt be17d0bd → 5dca79f9 (adds "01:10 gdsw" and "09:30 gdss" PT)

Jobs:
- **gdsw:** `write <today>`. Until Secret Manager "gemini-decisions-key" exists it logs "key missing", writes nothing and exits 0.
- **gdss:** `score <yesterday>`. It logs "no answers" while there are no answers.

Rehearsal on the VM (staging copy, real data read-only):
- write → "key missing", rc 0;
- rehearse 2026-11-21 → 2,190 people, 14 launches, about $0.24/day, baseline fit 482,751 rows;
- a scratch copy of run.sh with uploads stripped ran job gdsw → rc 0, one log line.

Secret access check: the lookup currently returns NOT_FOUND because the secret doesn't exist. Whether the VM service account can read it is confirmed only once it does.

Rollback:
```
cp -p ~/w/backup_tw12a/run.sh.5cd8b9e5 ~/w/tw12a/run.sh
cp -p ~/w/backup_tw12a/sched12a.txt.be17d0bd ~/w/tw12a/sched12a.txt
rm ~/w/experiments/ph_predict/gemini_decisions_shadow.py
```
