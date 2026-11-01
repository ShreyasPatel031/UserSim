# Product Hunt ops and research agent: runbook (from Nov 1, 2026)

Read first:
- `docs/RESEARCH_PROGRAM.md`: north stars, rules, roles, agenda.
- `docs/HISTORY.md`: what was tried and every number.
- `experiments/simlab/reports/overnight_1030.md`: the running results log. Append to it.
- `AGENTS.md`.

You own day-to-day Product Hunt work. The orchestrator ("Prediction agent", `session_01SLvzW5Wv5eduze15nhtuUT`) sets
research direction and gets data, credentials and blocked actions through Grok Bot. Message it with `send_message`
when you are blocked, finish an agenda item, or hit a question where a stronger model should review direction.

## Machines (GCP project `project-amer-scs-sandbox`)
| VM | Zone | Use |
|---|---|---|
| `usersim-pipeline` (e2-standard-4) | us-central1-a | Daily pipeline. The instance policy `usersim-daily-start-pt` starts it at 00:05 Pacific (08:05 UTC in PST, 07:05 in PDT). On boot, `@reboot sleep 60 && /home/agent/w/run_daily.sh` runs the day, then the hourly vote recorder until 23:55 PT, then shuts the VM down. Code in `/home/agent/w/experiments`; logs in `/home/agent/w/logs/daily_<UTC>.log` (+ `_hourly.log`). |
| `usersim-exp-1` (e2-standard-32) | us-central1-b | Experiments. Start it when needed and stop it when done (about $1.5/h). Code in `~/w/experiments`; Python `/opt/exp/bin/python3`; `SIMLAB_DATA=data_v2`. |

Access (once per container): `gcloud compute ssh agent@<vm> --zone <zone> --tunnel-through-iap` sets up a key.
After that, a long-lived tunnel avoids repeated prompts:
```
while true; do gcloud compute start-iap-tunnel usersim-pipeline 22 --local-host-port=localhost:2225 --zone us-central1-a; sleep 2; done
```
Then `ssh -p 2225 -i ~/.ssh/google_compute_engine agent@localhost`. Deploy code with `tar cf - <files> | ssh … 'cd ~/w/experiments && tar xf -'`.

## Pipeline rules (hard)
- **Only change `usersim-pipeline` through the skip-run procedure** at the top of `run_daily.sh`. The VM must be
  TERMINATED, with no `skip-run` metadata, before 00:05 PT, or the scheduled start does nothing. This happened on
  Nov 1.
- Never `pkill -f` without a bracket pattern (`pkill -f "[p]ipeline.sites"`). Never put the pattern's literal text
  elsewhere in the same ssh command.
- Never decode, print or copy credentials. They live on the VM at `/var/lib/usersim/discovery_keys.json` and are
  read by `run_daily.sh`.
- If a permission check blocks a restart or deploy, don't retry. Message the orchestrator; Grok Bot does it.

## Daily routine (after the run starts, 00:47 PT)
1. **Check the run.** The VM should be RUNNING (hourly recorder) or TERMINATED after 07:00 UTC the next day.
   - Check the newest log: every step `"status": "ok"`.
   - Check for no Traceback, 407 or 403.
   - Check the launch count vs Grok Bot's leaderboard read: `python -m pipeline.list_check <day>`.
2. **Score yesterday's forecast** against final ranks: top 3/5/10, and add it to the log.
3. **Dashboard refresh.** Artifact `https://claude.ai/artifact/MVKkd6uG95hsGpmopJ9jKL`.
   - Upload `gs://…/usersim_sim/dash/*.json` as assets.
   - One `ArtifactData` batch updating `datasets/<id>` `source` and `updated`, each entry pinned with `if_version`.
   - Delete the replaced blobs.
4. **Spend.** Flag if over $2/day, or if DataImpulse returned 407.
5. **Report.** 3–4 plain lines to the user only when something failed or a result changed; otherwise log it.

## Agenda (ordered; details in RESEARCH_PROGRAM.md)
1. **Put tie strength into the daily pipeline.**
   - Popscore with `TASTE=1 TIE=1` gives `psr_features.json`, and the forecast uses it.
   - Then extend: hunter/maker turnout rate, reply threads, recency. Test with `pick_boost` ABLATE and
     `newsim_eval SIM_SRC=psr`, plus a paired bootstrap over days.
2. **Launch-day forecast** from `vote_snapshots` once about 14 clean days exist (Nov 2 onward).
3. **X go/no-go test** when Grok Bot delivers the follow sample.
4. **Competitor winner-of-3 with the "why"**, validated against comments and reviews.
5. **Qualitative layer:** simulated reactions per page element vs real comments and reviews.

## Reporting
Every result goes into `overnight_1030.md`: setup, numbers with 95% intervals, verdict, and the commit. Commit to
your branch and push. Don't open PRs unless asked.
