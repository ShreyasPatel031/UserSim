# MCP matrix — Oct 14, 2026 (endpoint https://35-202-98-224.sslip.io/mcp, engine 5f789ed)

Report links use the deployed report host; usersim.vercel.app / atelier-sim.com currently serve the atelier-landing app (a305a1e) without /mcp, see Routing.

| Cell | Driver | Site / task | Study id | Result | Report |
|---|---|---|---|---|---|
| e2e smoke | `python -m mvp.e2e_mcp --base https://35-202-98-224.sslip.io --no-watch` | built-in checks | c9a831a6-b421-4fcc-8f4d-6b3e52d2d903 | pass, fails [] | https://usersim.vercel.app/report?study=c9a831a6-b421-4fcc-8f4d-6b3e52d2d903 |
| t1__p1__product | Gemini 2.5 Flash (research mode) | deadmanssnitch.com — monthly price of cheapest paid plan, no account | d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 | judge reached, proof pass, 2 steps, 20 s | https://usersim.vercel.app/report?study=d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 |
| t1__p1__competitor_1 | Gemini 2.5 Flash (research mode) | site24x7.com — same task | d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 | judge reached, proof pass, 23 steps, 135 s | same |
| Composer driver | Cursor cloud agent, composer-2.5 | — | — | not run (Oct 15): see "Composer" below | — |
| Grok Bot cell | Grok Bot (this assistant) as MCP client | plausible.io vs usefathom.com — research task | 74b7210f-279e-4bd3-a279-f6d8867f8848 | Plausible: judge reached, proof FAIL (only `beyond_first_screen`, answered on the opening page); Fathom: never started, shown "—" | https://usersim.vercel.app/report?study=74b7210f-279e-4bd3-a279-f6d8867f8848 |
| Haiku cell (Oct 15) | Claude Haiku 4.5 (Vertex, `claude-haiku-4-5@20251001`), native tool use over MCP; system prompt = server prompt `usersim_simulate_user`, tools observe/act/finish | tidycal.com — "Without creating an account, find the price of TidyCal's paid plan and whether it is a one-time payment or a subscription." | e0bfc0c5-59a2-447b-b816-9c75f415cac9 | judge reached, proof pass, 5 steps; found Individual Lifetime $29 one-time, Agency Lifetime $79 one-time, Pro $12/month; Haiku $0.048 | https://usersim.vercel.app/report?study=e0bfc0c5-59a2-447b-b816-9c75f415cac9 |
| Parallel start | one `usersim_start_study`, 2 Gemini cells launched together | deadmanssnitch.com vs site24x7.com | d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 | overlapping runs (20 s and 135 s, same start); "Proof: 2/2 runs passed" | https://usersim.vercel.app/report?study=d6fcb7ea-0da0-46f7-aabf-0c2b6da8cb14 |
| Skipped-cell finish (Oct 15) | 2-cell study, only the product cell run, then `usersim_finish_study` | usemotion.com vs reclaim.ai — research | a3e1aa87-d07d-44be-a34b-72886f9123ec | finish_study wrote the report with the unstarted Reclaim cell; prod 5f789ed shows it as "—" with 0 steps and counts proof as 0/1 (the skipped cell is left out). The `skipped` row (91b2b7c) is not on prod yet, only unit-tested (mvp/test_sim_mcp_oct14.py). The product cell FAILED because of a box-side driver credential error (DefaultCredentialsError, no model call), not the site | https://usersim.vercel.app/report?study=a3e1aa87-d07d-44be-a34b-72886f9123ec |

The two Gemini cells were started together from one `usersim_start_study` and ran in parallel (overlapping). Study summary: "Proof: 2/2 runs passed". Model cost ≈ $0.021; CapSolver $0. Both sites were never tested before, not Outreach leads; no signup was done.

## Routing
usersim.vercel.app and atelier-sim.com both alias Vercel deployment dpl_J7SKsPspbhvoywfSGdZq87aWQoWg (CLI deploy Oct 13 13:52 PT of branch atelier-landing @ a305a1e). It replaced the proxy deployment whose vercel.json rewrote everything to the VM. a305a1e is a standalone serverless app (rewrites `/(.*)` → `/api/index`) without sim_mcp, so /mcp is 404 and /health has no engine_version. Fix: add `/mcp` and `/mcp/:path*` rewrites to https://35-202-98-224.sslip.io before the catch-all (patch on a305a1e, not applied).

## Proof FAIL on 74b7210f-279e-4bd3-a279-f6d8867f8848
The Plausible cell failed only `beyond_first_screen`: the research task was answered on the opening page (judge goal true). The summary had no reason, and the unstarted Fathom cell had no result row (shown as "—"). Fixed in this branch: proof `reason`, research tasks may answer on the first screen and need no signup proof, skipped cells get a `skipped` row and are left out of the proof count.

## Composer (Oct 15)
Not run. The plan was a Cursor cloud agent on composer-2.5 acting as an MCP client of https://35-202-98-224.sslip.io/mcp
through a small HTTP JSON-RPC script, on a 1-cell study.
1. The agent that ran this matrix has no CloudAgent launch tool (its tool catalog has no cloud-agent namespace), so it could not
   start one.
2. A cloud agent can only reach the token through the prompt (plaintext, forbidden) or a secret configured in the Cursor
   dashboard for the repo. None is configured, and adding one is a user action.
To run it: add `MCP_CLIENT_TOKEN` as a Cursor cloud-agent secret, then launch composer-2.5 with a prompt that references the env
var only. For example, a 30-line Python script that POSTs initialize, tools/call usersim_start_study (1 persona × 1 task, no
competitors), then loops usersim_observe/usersim_act and calls usersim_finish.

## Consolidation (Oct 15)
`origin/claude/hopeful-keller-uuebrn` is still at 5f789ed (last commit Oct 13 09:30 UTC), so it has not moved since PR #65 merged it
at 420250c. 5f789ed is an ancestor of mcp-signup-parity 7cc3402: **already superset**, no merge needed. Prod
https://35-202-98-224.sslip.io/health reports `engine_version` 5f789ed (config_hash 0bd10154b212), so prod runs nothing that
is not in mcp-signup-parity. mcp-signup-parity adds code that is not on prod yet: proof reason / research / skipped rows
(91b2b7c), click by text (fcb9f43) and the code-only mail fix (7411185).

## Vercel preview for /mcp (Oct 15)
The rewrite patch (a517d60 on atelier-landing a305a1e) is packaged for the cloud agent to push as the new branch
`atelier-landing-mcp-rewrite`. The Vercel project `usersim` (prj_3440zMYOyQjdHkSIdYADPcr3vG1v) is linked to
ShreyasPatel031/UserSim with production branch `main`, so a push of that branch builds a preview only.
Deployment protection is `ssoProtection: all_except_custom_domains`, so the preview URL answers 401 to an anonymous MCP client.
e2e_mcp against `<preview>/mcp` needs the project's protection-bypass secret (one exists) sent as the
`x-vercel-protection-bypass` header. That is the user's call; protection was not disabled.

Haiku client: `docs/mcp-test/clients/haiku_vertex_client.py` (needs `anthropic[vertex]` and `mcp==1.30.0`; args: MCP URL, site,
task, persona, max turns; reads MCP_CLIENT_TOKEN from the environment, never prints it).
