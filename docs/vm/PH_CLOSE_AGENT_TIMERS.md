# Weekly / monthly close — Cloud Agent timers (America/Los_Angeles)

`ph_at_launch_close_cron.sh` gates on **PT** `H%M` (`2345` / `2350`). Cloud Agent `cursor-subscriptions` cron uses **UTC** unless the environment sets a LA timezone.

## Correct UTC cron (PST, UTC−8)

| Local (PT) | UTC cron | Timer name |
|------------|----------|------------|
| 23:45 daily | `45 7 * * *` | `ph-weekly-close-2345pt` |
| 23:50 daily | `50 7 * * *` | `ph-monthly-reread-2350pt` (pre-close; not day-end) |
| 01:45 daily | `45 9 * * *` | `ph-post-close-month-0145pt` (day-end: yesterday `_official_reread`) |

During **PDT** (UTC−7), use `45 6` / `50 6` or re-subscribe after DST.

## Fleet weekly VM

- **Primary:** `PH_WEEKLY_CLOSE_SLOT=9` (Camoufox; `sudo chown -R ubuntu:ubuntu ~/.cache` before capture)
- **Backup:** `PH_WEEKLY_CLOSE_FALLBACK_SLOT=27`
- Dry run: `PH_WEEKLY_CLOSE_MAX_POSTS=1 bash scripts/vm/ph_weekly_close_fleet.sh`