# Parallel ceiling probe — one browser

- GO token: `run:ceiling-20261108t015200z-wb`
- Arms: feeder-strat-20261107t170953z-{a–d} → 16 / 32 / 48 / 64 tabs
- Window: first ~15 min after identity (America/New_York: Fri Nov 7, 2026 ~8:51–9:09 PM)

## Verdict

| tabs | json | paged_v2 pulls | BLOCK | max fan-out pages |
|-----:|-----:|---------------:|------:|------------------:|
| 16 | 5 | 25 | 0 | 16 |
| 32 | 3 | 16 | 0 | 32 |
| 48 | 1 | 6 | **1** | 48 |
| 64 | 1 | 6 | 0 | 64 |

- **Mechanical ceiling:** **64** parallel in-browser pages works on e2-standard-2 + 1 Camoufox (log shows `tabs=64 rate=200` and `offset pages 64`).
- **Did none get blocked?** **No.** Arm C (48) hit `BLOCK challenge not cleared … (status 403)` at +838s on `/@han_circle`.
- **Clean so far:** 16 and 32 (most throughput, zero blocks). 64 also still zero blocks in this short window (only 1 person finished — treat as provisional).
- Practical read: fan-out to 64 is viable; block risk shows up in the mid/high band quickly. Prefer **32** if you want high parallel without an early 403 in this probe.

## Setup fixes applied for a valid probe

1. Instance metadata `ph-strategy-env` was still A/B/C/D and overwrote ceiling env on every supervisor launch — updated to ceiling_*.env.
2. Inline SSH `pkill` was killing the session (exit 255) — switched to GCS-hosted `ceiling_relaunch.sh`.
3. `week_bytes()` was scanning ~66 status jsonl files via sequential `gsutil cat` before first claim — skipped when `PH_STRATEGY=ceiling`.
