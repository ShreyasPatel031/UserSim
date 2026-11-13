# Working with the Claude agents (for the Cursor extraction agent)

You do the Product Hunt person extraction. The Claude agents (orchestrator + population agent) fill your queue
with the highest-priority people and verify everything you save before it counts. Everything goes through the
shared GCS bucket you already use: `gs://usersim-bakeoff-347838016394/usersim_sim/`.

## 1. Talk to us: webhook messages (same platform as Grok Bot)

- **You -> Claude agents:** POST JSON to the Grok Bot webhook, the same one the Claude agents use
  (URL + bearer key in `gs://usersim-bakeoff-347838016394/usersim_sim/secrets/grokbot_webhook.env`; never print or
  commit the key). Body: `{"agent": "cursor-extract", "need": "<one-line topic>", "details": "<message>",
  "ts_utc": "<YYYY-MM-DDTHH:MMZ>"}`. Grok Bot relays it to `mailbox/from_grokbot/` and to the orchestrator.
  Send one for: run start/stop, each block, every hour's counts (VMs, people saved, blocks, build md5, bytes), and
  any question.
- **Claude agents -> you:** we POST to your own webhook with the same JSON shape (`agent` = who is writing, e.g.
  `orchestrator` or `population`). Save your webhook URL + key as `secrets/cursor_extract_webhook.env`
  (`CURSOR_WEBHOOK_URL=...`, `CURSOR_WEBHOOK_KEY=...`); we send with `tools/cursor_post.sh`.
- **Record copy:** every webhook message is also written as a file (`mailbox/from_cursor/<stamp>_<topic>.md` by you,
  `mailbox/to_cursor/<stamp>_<topic>.md` by us), so nothing is lost if a webhook call fails.

## 2. What to pull: the queue

- Pull from `raw/_cursor/queue.txt` (one handle per line, highest priority first). The population agent rebuilds it
  every hour at :40 from last week's voters (`priority_lastweek.txt`) plus re-pull requests, minus people already
  complete and minus people held for the follow-list fix. Do not pull from `people_live/need_list.jsonl`.
- Claim before pulling, as today (`claim` files), so VMs do not pull the same person.

## 3. How to pull (non-negotiable rules from AGENTS.md)

1. **Whole person or nothing.** Every tab (about, upvotes, activity, forums, reviews, collections + items, stacks,
   hunted, made, followers, following) read to Product Hunt's own end, plus header counts. Use the audited build
   `raw/population/builds/full18d_candidate.tgz` (md5 `T3OI+xr3iAvoMDMZrdryhA==`), which has the save gate and the
   follower/following offset re-page. Do not run `vm/_code/reuse.tgz` (md5 `7bAxaq8n…`): it has no save gate and
   saves incomplete people.
2. **No block evasion.** No IP/port rotation, no VM recreation, no fingerprint changes, no challenge clearing after a
   403/429/Cloudflare challenge. On a block: stop that VM, pause 10 min on the same IP (doubling per further block, cap
   2 h), resume at half the workers, step back up after an hour clean. Remove `patch_soft_open_rotate.py`,
   `patch_soft_block_rotate.py`, `portscreen.py` rotation and the "keeper recreates VM" logic.
3. **Keep the safety caps.** Do not bypass the weekly DataImpulse byte stop (remove `patch_week_bytes.py`).
   Paid data budget is $200/week (195 GB); GCP spend stays under $50/day.
4. **Save to staging, not live.** Write each person to `raw/_pacetest/shared/<handle>.json` (`PH_SAVE_B`), never to
   `people_live/vm/`. The population agent checks every staged person against the whole-person rule within the hour
   and merges only complete ones into the live store; incomplete ones go back on your queue with the reason in
   `mailbox/to_cursor/`.

## 4. What you get back

- `mailbox/to_cursor/audit_<stamp>.md` every hour: staged / passed / failed, fail reasons per handle, and which
  build or VM produced them.
- Progress is counted only as complete people merged into the store.

## Fleet bands: how IPs move between daily reads and historical pulls (Shreyas, Nov 13 2026)

Principle (Shreyas): daily reads are the priority. Incoming data must never be dropped because we pulled too slowly;
historical pulls may take longer. Long term the goal is the most data from the fewest IPs. A band never caps what is pulled:
it only decides how many IPs a job gets. Every freed IP goes to historical pulls.

### Bands (Pacific time). Each daily job has a measure, a band, and what to do outside it.

| Job | Measure | In band | Below band: expand | Above band: reduce |
|---|---|---|---|---|
| 1. Launch teams, pulled whole | time the last hunter/maker of the day's line-up is complete | between 00:35 and 01:00 | at 00:30, if the projected finish is after 01:00, add 1 IP now and re-check every 10 min; also start the next night with 1 more | finished before 00:35 on 2 nights running: 1 IP fewer next night (never below 1) |
| 2. Daily pipeline reads (comments, sites, people) | share of the day's launches read without a block, and finish time of each step | 100% read, each step done within 15 min of its start | any step blocked or late: add a second fixed IP for that run and keep it the next night | 7 nights at 100% on one IP: stay at 1 |
| 3. Hidden-window upvote re-read | share of panel tier 1 (1,000 most active) re-read at least once between 02:30 and 03:45, and of tier 1+2 (2,000) between 00:30 and 03:45 | tier 1: 100% and read no more than twice; tier 1+2: 100% | at 02:00, if tier 1+2 is projected under 100% by 03:45, add 1 IP now, re-check every 15 min; start the next night with 1 more | tier 1 read 3 or more times AND the re-read reached beyond 6,000 people, 2 nights running: 1 IP fewer next night (never below 2) |
| 4. Daily upvote refresh of complete people | age of the newest upvote read: people who voted in the last 30 days, and all complete people | active people: 95% read within 24 h; everyone: 95% within 72 h | either share under 95% at the hourly check: add 1 IP; re-check hourly | active 95% within 12 h AND everyone within 36 h, for 2 days: 1 IP fewer (never below 1) |

Jobs 1-3 share the same night IPs in sequence (teams first, then the hidden window); job 4 uses whatever daily IPs are free.
Starting allocation: 6 daily, 14 historical (see the split note of Nov 13). The bands move it from there.

### Rules for moving IPs
- Expand at once on a below-band reading, one IP at a time. Take it from the new-people pull first, the completion queue last.
- Reduce only after the stated number of consecutive in-excess readings (hysteresis), one IP at a time, and only between runs.
- A VM that is down or backing off after a block counts as zero: replace it from historical immediately and return the IP when it recovers.
  A blocked IP backs off on the same IP (10 min, doubling, cap 2 h) and resumes at half the workers; no rotation, ever.
- Check jobs 1-3 every 10-15 minutes while they run; job 4 hourly.
- If the daily reads need more than 12 of the 20 IPs to stay in band, or historical gets none for 6 hours, tell Shreyas the same hour.
- Write every move to from_cursor/status.json: time, job, measure, from/to IP counts, reason.
- Nothing here limits what a pull fetches. If a daily job cannot stay in band even with all 20 IPs, it still pulls everything it can and reports the shortfall; nothing is skipped silently.

### Long term: the most data from the fewest IPs
1. Measure, per job and per IP, every day: people (or pages) per IP-hour, requests per person, blocks per 1,000 requests, back-off minutes, idle minutes. Publish it in status.json. These replace the orchestrator's estimates (600 whole pulls per IP per day; 300 one-tab re-reads per IP per hour).
2. Find each IP's sustainable rate and sit just under it: step workers up slowly while the block rate stays flat, step down on the first rise, and remember the level per IP and per hour of day. The best rate is the one Product Hunt allows without a block, never one reached by evasion.
3. Do not fetch what cannot have changed. Re-reads stop at the first item already held (upvotes, activity, followers are newest-first where the paging record shows it); tabs that only grow are read incrementally; a person pulled whole today is skipped by that day's refresh. Every field is still pulled at least once and kept: this is about not re-reading unchanged pages, not about dropping anything.
4. Order work by how fast it goes stale and how much it matters: people active in the last 30 days first, then by last-activity date; launch-day reads before everything.
5. Use the quiet hours: schedule historical pulls for the hours with the lowest block rate; keep 00:00-04:00 for the daily jobs.
6. Remove idle time: no IP waits on a queue; when a job finishes early its IPs move to historical the same minute.
7. Weekly review (the orchestrator files it, the fleet supplies the numbers): for each job, IPs used, data per IP-hour, band breaches, moves made; then one proposal: the smallest IP count that kept every band for the last 7 days with one spare, and how long the historical queue takes at that count. Changing the total of 20 is Shreyas's decision.
8. When the historical queue is empty and all bands have held for 7 days, propose reducing the total. When a band cannot be held at 20, propose the increase with the measured shortfall.


## Ownership (Shreyas, Nov 13 2026, 20:48Z)

Long-term pulls are the Cursor fleet's: the 15-minute launch-day capture, day-close (23:45-23:59 PT) and 00:07 PT comment reads,
weekly and monthly close reads, daily jobs 1-5, 2024/2023 day lists, comment backfills, people completion. The Data Feeder runs
one-off experimental pulls only. Handover: mailbox/to_cursor/20261113T2052Z_URGENT_long_term_pulls_are_yours.md. Live-feed band:
snapshot lateness <= 120 s, no gap over 20 minutes; on a breach machines move from historical to live at once and an incident
file is written to from_cursor/. The population agent audits every feed every 15 minutes and keeps raw/_audit/downtime_ledger.jsonl.
