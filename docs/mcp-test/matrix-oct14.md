# MCP matrix — Oct 14, 2026 (endpoint https://35-202-98-224.sslip.io/mcp, engine 5f789ed)

Report links use the deployed report host; usersim.vercel.app / atelier-sim.com currently serve the atelier-landing app (a305a1e) without /mcp, see Routing.

| Cell | Driver | Site / task | Study id | Result | Report |
|---|---|---|---|---|---|
| e2e smoke | `python -m mvp.e2e_mcp --base https://35-202-98-224.sslip.io --no-watch` | built-in checks | c9a831a6-b421-4fcc-8f4d-6b3e52d2d903 | pass, fails [] | https://usersim.vercel.app/report?study=c9a831a6-b421-4fcc-8f4d-6b3e52d2d903 |
| t1__p1__product | Gemini 2.5 Flash (research mode) | deadmanssnitch.com — monthly price of cheapest paid plan, no account | d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 | judge reached, proof pass, 2 steps, 20 s | https://usersim.vercel.app/report?study=d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 |
| t1__p1__competitor_1 | Gemini 2.5 Flash (research mode) | site24x7.com — same task | d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 | judge reached, proof pass, 23 steps, 135 s | same |
| Composer driver | — | — | — | not run: no Cursor/Composer CLI or API on the test box | — |

The two Gemini cells were started together from one `usersim_start_study` and ran in parallel (overlapping). Study summary: "Proof: 2/2 runs passed". Model cost ≈ $0.021; CapSolver $0. Both sites were never tested before, not Outreach leads; no signup was done.

## Routing
usersim.vercel.app and atelier-sim.com both alias Vercel deployment dpl_J7SKsPspbhvoywfSGdZq87aWQoWg (CLI deploy Oct 13 13:52 PT of branch atelier-landing @ a305a1e). It replaced the proxy deployment whose vercel.json rewrote everything to the VM. a305a1e is a standalone serverless app (rewrites `/(.*)` → `/api/index`) without sim_mcp, so /mcp is 404 and /health has no engine_version. Fix: add `/mcp` and `/mcp/:path*` rewrites to https://35-202-98-224.sslip.io before the catch-all (patch on a305a1e, not applied).

## Proof FAIL on 74b7210f-279e-4bd3-a279-f6d8867f8848
The Plausible cell failed only `beyond_first_screen`: the research task was answered on the opening page (judge goal true). The summary had no reason, and the unstarted Fathom cell had no result row (shown as "—"). Fixed in this branch: proof `reason`, research tasks may answer on the first screen and need no signup proof, skipped cells get a `skipped` row and are left out of the proof count.
