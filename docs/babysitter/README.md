# Data babysitter (branch `claude/data-babysitter`)

Verifies every Data Feeder feed daily against its ask, measures throughput, finds the throttling edges and
files precise speed-up asks. Started 2026-11-03 19:45 UTC on Shreyas's request (orchestrator: `session_01SLvzW5Wv5eduze15nhtuUT`).

- Daily scorecard: `docs/babysitter/<day>.md` here and `gs://usersim-bakeoff-347838016394/usersim_sim/raw/_babysitter/<day>/scorecard.md`.
  A PASS feed also gets a `VERIFIED_<day>_babysitter.md` marker in its raw folder (the Feeder's README stays as written).
- Throttling edges: `docs/babysitter/limits.md` (source, route, safe rate, edge rate, what the block looks like, recovery).
- FAIL on any feed goes to the orchestrator at once (send_message); PASS summary once a day at ~09:30 UTC.
- Asks to Data Feeder go to `mailbox/to_grokbot/<UTC>_babysitter_<topic>.md`; urgent ones through the orchestrator's webhook.
- Rules kept: no secrets in git; Product Hunt usernames stay in GCS; Gemini only in pipelines; never touch
  usersim-pipeline / usersim-grokbot-web / grokbot-hn-recorder or VMs I don't own; nothing 00:05–01:00 PT; GCP $50/day soft,
  $100 hard; paid data $30/week across agents (tell the orchestrator before any spend above $2); stepping a rate up to find
  an edge is measurement, but once a block is hit: honour Retry-After, back off, never rotate IPs or accounts; one PH account.

Verification script (schema, timestamps, dedupe, coverage; prints no usernames): `tools/babysitter_verify.py`.

## No-caps rule (Shreyas, 2026-11-04; RESEARCH_PROGRAM.md d9444ee3)
Every piece of data for every person, no caps of any kind. The only allowed limits are Product Hunt's own (e.g. ~200 signed-out
upvotes), recorded as such. In the daily scorecard, any tab or list that stopped short of its header for any reason other than PH's
server ending it (our paging stopped, item/page caps, enrichment caps, budgets that never resume) is a **FAIL**, reported by person
(in GCS) and tab. Verify every cap list against the code, and alert Shreyas directly on any knowingly added cap.
