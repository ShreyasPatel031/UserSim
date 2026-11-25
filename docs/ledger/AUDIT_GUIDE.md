# How an independent agent audits this work

## What to give it
1. **Code, log and ledger**: GitHub repo `ShreyasPatel031/UserSim`, branch `claude/cool-volta-l5nuo4`.
   - `docs/ledger/experiments.jsonl` and `decisions.jsonl`: the audit ledger (schema in `simharness/ledger.py`).
   - `docs/RESEARCH_LOG.md`: every event, newest last. `docs/SOCIAL_SIM_PLAN.md`: designs and leaderboards.
   - Code for each experiment at the commit named in its row (`git show <commit>:<path>`).
   - E5's own rows are written on branch `claude/person-model-v2` and copied here hourly.
2. **Output files** (results, per-row files, scores): bucket `gs://usersim-bakeoff-347838016394/usersim_sim/`
   (GCP project number 347838016394). Read-only access is enough: an account or service account with
   `roles/storage.objectViewer` on that bucket. Private rows (people, client data) are under `.../private/` and
   `client_qa/`; the auditor may read them but must not copy them anywhere public.
3. **What the agents actually did** (strongest check: compare actions with reports): the session transcripts, readable
   by a Claude Code cloud session on Shreyas's account with the claude-code-remote `list_events` / `get_event` tools:
   - orchestrator: session_01SLvzW5Wv5eduze15nhtuUT
   - E5 (simulation experiments): session_01WkCrUR5nAGq7eAywSViRcR
   - PH agent (launch model, pipeline): session_01WkCrUNGGrvzNTXL69TVZ2w
   - population agent (data feeds): session_01WkCrUNzmycpWe5dkydHRnU
   - client QA agent: session_01WkCrUQdW7Y5jfEq8Qg5c6z

## How to audit one experiment
1. Read its ledger row: design, what_ran, deviations, results, reported_as.
2. Check the design was written before the run: log line time vs output file time (`gsutil ls -l`).
3. Re-derive the headline number from the output file; compare with `results` and with what was reported.
4. Read the code at the commit: data window, sample sizes, resamples, model, prompt, metric. Anything not in `design`
   or listed in `deviations` is an undocumented deviation.
5. Read the transcript around the run (list_events with kinds ["assistant","user"]): look for settings changed mid-run,
   runs restarted and only the better one reported, results dropped, or numbers in the report that no tool output shows.
6. Write findings as new ledger rows with `"corrects": "<id>"` (never edit old rows), or as a separate audit file.
