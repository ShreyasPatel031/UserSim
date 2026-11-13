# Live-feed freshness audit: run note

`tools/population/freshness_audit.py` is a standalone script with no LLM and no Claude session. It reads GCS and alerts
when a live feed stops. It detects only; it never changes, restarts or scales anything.

## What it checks (limits are in the script)

| Feed | Source | Limit |
|---|---|---|
| live capture heartbeat | `mailbox/from_grokbot/` and `mailbox/from_cursor/ph_live_capture.status.md`, "updated:" (newer of the two) | 20 min |
| posts_ts | `raw/ph_at_launch/<PT day>/live/posts_ts.jsonl`, `snapshot_ts` | 20 min |
| comments_ts | `raw/ph_at_launch/<PT day>/api_comments/<tag>PT.jsonl` | 20 min 00:00–02:00 PT, else 60 |
| fleet status | `mailbox/from_cursor/status.json` `utc`, alive slots vs 20 | 20 min, 20 VMs |
| vote_snapshots hourly load | `tables/vote_snapshots/*.parquet` newest part upload time (one part per load; VM off 23:00–00:05 PT) | 75 min |
| vote_snapshots export | `raw/vote_snapshots/<PT day>.jsonl` (daily export) | previous PT day by 08:00Z |

Not yet covered: store build cadence, and daily
people jobs 1–5.

## Run it every 15 minutes on an always-on machine

The machine needs `gsutil` and `gcloud` with read access to the bucket and write access to `raw/_audit/`, plus
Python 3.9 or later. Check out this repo, then:

```
mkdir -p /var/lib/usersim/freshness
*/15 * * * * cd /path/to/UserSim && python3 -I tools/population/freshness_audit.py /var/lib/usersim/freshness run >> /var/log/usersim_freshness.log 2>&1
```

`/var/lib/usersim/freshness/freshness_state.json` records open breaches and when each was last alerted. Keep it on
local disk. Run only one cron runner, so that alerts aren't sent twice.

## What one run writes

- `raw/_audit/checks/<UTC>.jsonl`: one row per breached feed (`status: open`, `open_since`, gap, limit) and one per
  recovered feed (`status: closed`, `minutes_open`). Nothing is written when every feed is fresh.
- `raw/_audit/ALERT_<UTC>.md`: written when a feed first breaches, then at most every 30 minutes while it stays down.
- Grok Bot webhook: `tools/grokbot_post.sh` is called at the same times as the ALERT file, if
  `/root/.usersim/grokbot_webhook.env` exists (or the file named by `GROKBOT_WEBHOOK_ENV`). Never commit that file.
- Exit code 1 if any feed is over its limit, else 0. A failed check is itself reported as a breach.

## Other modes

- `W check`: print breaches only.
- `W backfill D0 D1`: gaps per PT day.
- `W first_comment D0 D1`: time of the first comment read after midnight PT, per day.
