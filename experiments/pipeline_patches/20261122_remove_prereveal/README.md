# Remove the published 03:45 forecast (Shreyas "remove it", via orchestrator 03:55Z Nov 22)

Change on usersim-pipeline: ~/w/tw12a/sched12a.txt goes from 4cec4d5e to be17d0bd. It drops the "03:47 prereveal" and "03:52 prereveal" runs, so two_predictions.py prereveal no longer writes results/web/predictions/<d>_prereveal.json.

Unchanged:
- "03:45 rec" (the recorder read: PH's hidden order, kept as raw data, baseline and truth);
- the midnight and lineup runs;
- two_predictions.py itself, run.sh and tick.sh.

Rehearsal: in a scratch copy on the VM, the tick's awk was replayed for every scheduled minute against the old and new files. Only 03:47 and 03:52 lost their (prereveal) job.

Deploy: base-md5 gated, with the old file backed up to ~/w/backup_tw12a/sched12a.txt.4cec4d5e.

Rollback: `cp -p ~/w/backup_tw12a/sched12a.txt.4cec4d5e ~/w/tw12a/sched12a.txt`
