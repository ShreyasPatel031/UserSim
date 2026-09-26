# Linear run 3 — interrupted, not a strict result

This run was stopped on purpose so the integration branch could merge PR #47's shared page read (`ae9758f`). It is not a completed strict gate table and it is not a pass.

- study: `9aeca3a8-1b63-4fae-abd5-9963124c0639`
- product: https://linear.app
- head at start: `2214cf1` (before the shared-read merge)
- observed at ~322s: 24 agents created, 0/24 page open, harness text `missing field ax_tree; missing field page_open_at_ts: 0/24 agents`
- harness then received KeyboardInterrupt before it wrote `result.json` / `failures.json`
- study status after stop: `abandoned` / `Killed by operator` / `kill_requested=true`
- integration Browserbase sessions from this study were released; gates, bisect, and signup sessions were left running
