# Weekly close — Mon Nov 24 PT 23:45 (`ph-weekly-close-2345pt`)

| Field | Value |
|-------|--------|
| **PT read date** | `2026-11-24` |
| **UTC** | `2026-11-25T07:45–07:49Z` |
| **Fleet slots 9 / 27** | **MISSING** (no GCE instances; route-4 SSH failed, rc=1) |
| **Fallback** | `official_api_weekly_ranks` (`ph_weekly_close_api.sh`, fleet-cursor) |
| **Output** | `gs://…/usersim_sim/raw/ph_at_launch/2026-11-24/weekly_close/20261124T2349PT_api.jsonl` (**260** lines) |
| **Meta (stale)** | `weekly_close_source.json` still says `route4_boxbrowser` slot 27 — use API path above |

**Action for orchestrator:** Treat weekly close as **API** for `2026-11-24` (Last week ranks). Route-4 needs slots **9** or **27** recreated before next Sun 23:45 PT.

**Live:** `critical_stale=false`; LIVE_PRIORITY_HOLD unchanged.