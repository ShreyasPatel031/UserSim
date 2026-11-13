# Live feed downtime budget (from agent mailbox / GCS)

## Authoritative simulation cadence (Grokbot orchestrator)

From `fleet-cursor` inbox (`grokbot`, 2026-11-12):

- Store **`monthly_rank_at_fetch` on every live `posts_ts` row at every 15-minute snapshot** (official Product Hunt API only), from the Nov 12 PT day onward.
- Day-boundary fixes for `posts_ts` likewise assume **continuous snapshot writes** into `raw/ph_at_launch/<pt-day>/`.

**Implied maximum acceptable gap between live snapshots: 15 minutes** (one missed bucket breaks the regular time grid the prediction/simulation model expects). Operational grace for upload skew is handled in fleet scripts as `LIVE_FEED_MAX_GAP_SEC=900` plus `LIVE_FEED_GRACE_SEC=180` (18 minutes wall clock).

There is **no separate numeric SLA** in mailbox text beyond this **15-minute sampling contract**. Hours-long gaps (Data Feeder report 2026-11-12: no API snapshot since ~3:00 AM PT) are **not** acceptable for live simulation input.

## What the model needs

| Stream | Role | Freshness |
|--------|------|-----------|
| `live/posts_ts.jsonl` | Launch vote/rank time series + `monthly_rank_at_fetch` | ≤15m between updates |
| `snapshots/*_api.jsonl` | Official API 15m buckets | New object each bucket |
| `api_comments/*` | Comment API sidecar per bucket | New object each bucket |
| `live/coverage_ts.jsonl` | Coverage companion to live pull | Tracks `posts_ts` cadence |

Historical fleet people pulls (Population `people_live/vm`) are **backfill**; they may run slower but must **not** steal sticky IPs or VM budget from daily/live capture when any row above is stale (`ph_fleet_live_priority.sh`).

## Daily browser jobs (Data Feeder, not 15m)

- Once/day heavy page pass and daily people page1 are **browser** jobs with **2 reserved IPs** (`IPROYAL_DAILY_IPS`, see `daily_ip_sizing.md`).
- Official API loop uses **0 proxy IPs** on the Data Feeder host.

## Enforcement (fleet-cursor)

`scripts/vm/ph_fleet_optimize_checkin.sh` runs `ph_fleet_live_priority.sh` first each 15m:

- Any stale monitored feed → `PH_FLEET_LIVE_PRIORITY_HOLD=1`, lower `FLEET_MAX_VMS`, skip keeper / block-rotate / utilization recovery until GCS objects are fresh again.

