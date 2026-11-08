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
