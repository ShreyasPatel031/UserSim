# Forward browser test (launch 3 gate)

Status on Nov 17 2026, 05:35Z: **not started. Two blockers, neither in this code.**

## What the test is

Each night, for launches in the 00:05 PT line-up with a reachable site, a simulated user operates the live product in UserSim's recorded cloud browser (the engine plans 6 users and 6 tasks; only the cells on the launch's own product are run). Findings are frozen and uploaded with a timestamp, then scored the next day against real comments with the strict same-issue rule from `../complaint_recall/`. Paired baseline: the plain prompt on the pitch (13.5% complaint recall on 300 past launches). Stop at 30 scored launches or 7 days.

## Blockers

1. **The cloud browser will not start.** The engine's Browserbase account is on the free plan and out of minutes. Every `usersim_start_session` returns: `402 Payment Required: Free plan browser minutes limit reached`. No browser run of any kind is possible until the plan is upgraded.
2. **No product site address since Nov 12.** The line-up carries only the Product Hunt redirect link, which E5 may not fetch. The resolved addresses in `raw/sites_ph.jsonl` have failed (status −2) for every launch since Nov 12 and for 10 of 25 on Nov 11.

## What exists

- `driver.py`: the driver. Gemini 2.5 Flash looks at each real screenshot and sends one action at a time through the public MCP server (plain JSON-RPC). It uses the engine's signup inbox tools, refuses any step that mentions producthunt.com, caps steps per cell (default 25), records every finding with a UTC time, and reports minutes, steps, outcomes and cost per launch.
- Debugged as far as study planning (the engine planned 108 cells for the pilot product). No cell has run in a browser, so there are no measurements of minutes, steps, stuck rate or cost yet.

## Side effects so far

Three pilot studies were created on the server for one already-launched product while debugging. No browser opened, no account was created on any product, and no spend was recorded.
