# MCP loop review: Oct 13

Haiku agents (Claude Code `claude -p --model haiku`) used the public MCP at `https://atelier-sim.com/mcp`
as simulated users in full studies on sites never seen before: 1 product, 2 rivals, 6 personas, 6 tasks,
two of each aimed at each site, 108 runs. After each study I read the traces, fixed the MCP and the
harness, deployed, and ran the next study on new sites.

- Driver: `scripts/mcp_loop/run_study.py` (one `claude -p` per cell, 8 in parallel, only the usersim tools,
  the server's own `usersim_simulate_user` prompt, every trace kept).
- Trace summary: `scripts/mcp_loop/analyze.py`. Deploy: `scripts/mcp_loop/deploy_vm.sh`. Specs: `scripts/mcp_loop/specs/`.
- "Unseen": not in any of the 1,166 studies in `gs://usersim-bakeoff-347838016394/mvp_studies/`, not in any
  branch of the repo, and no mail from the site in the shared signup inbox (checked on the VM over IMAP).
  fillout.com was dropped for this reason: the inbox had two of its signup mails from Oct 8.

## Results

| # | Study | Sites (product first) | Build | Goal reached (judge) | Proof pass | Agent cost |
|---|---|---|---|---|---|---|
| 1 | [f80f043a](https://atelier-sim.com/report?study=f80f043a-b884-4856-bb74-50c4a04f9aff) | tally.so · youform.com · formbricks.com | 2ed920b | 45/108 | 74/108 | $4.25 |
| 2 | [e7c5d942](https://atelier-sim.com/report?study=e7c5d942-9b0f-4870-b05b-e2d8847c831f) | baserow.io · nocodb.com · teable.io | 77929a5 | 103/108 | 69/108 | $6.67 |

Per site, study 1: Tally 23/36, Youform 19/36, Formbricks 3/36. Study 2: Baserow 33/36, NocoDB 35/36, Teable 35/36.

How to read study 1: almost every Tally and Youform failure was a harness bug, fixed before study 2 (below).
Formbricks is a real product finding: it refuses every gmail.com address ("Please sign up with your company
email address."), so with one shared Gmail inbox no agent can sign up there.

How to read study 2's proof column: 18 of the 39 proof failures are teable.io redirecting to teable.ai on
first load (fixed after the study, so they stay failed in this report).

## Fixes, in the order the traces found them

| Commit | Found in | Problem in the traces | Fix |
|---|---|---|---|
| 4c11209 | study 1 | Every "find out what it costs" run failed: the judge saw the price, then the billing-wall rule overrode it | Billing-wall rule applies to signup goals only |
| 4c11209 | study 1 | Judge saw only 1,500 chars of the final page; Tally's GDPR answer was just past the cut | MCP keeps and judges 8,000 chars (per-step text stays 1,500) |
| 4c11209 | study 1 | Formbricks: agents kept trying no-plus aliases on a company-email-only form | `work_email_required` from inline errors; hint says stop and report blocked |
| 97e5275 | study 1 | Youform let agents into the builder before verifying; they finished unverified and the verified-signup bar failed real accounts | `usersim_finish` on an unverified completed signup asks once to open the mail; prompt says always verify |
| 97e5275 | study 1 | Haiku sent `action` as a string / flattened | JSON string accepted; otherwise a one-object example instead of a pydantic error |
| 77929a5 | study 1 | Haiku sent key "BackSpace" | Key names normalised (BackSpace, ctrl, Cmd, Return, Esc, ...) |
| 77929a5 | study 1 | 2 of 108 agents never got the usersim tools (MCP connect failed at client start) | Driver reruns a cell whose agent never called start_session |
| 0586dc6 | study 2 | teable.io redirects to teable.ai; proof said "not the product" on 18 good runs | Server records the opening redirect before any action; proof accepts it |
| 0586dc6 | study 2 | Claude Code gives a tool 60 s; agents asked the mail wait for 180 s and the client timed out | Each wait returns within 50 s (`MVP_MCP_WAIT_MAX_S`) and says call again |
| 657ff0f | study 2 | Haiku garbled Baserow's long verify token when copying it; every open refused | `link_number=1` opens the first link; a near-exact copy of exactly one link opens it |

Deploys: 2ed920b (Oct 13 00:47), 77929a5 (07:13), 68c8b0c (07:50). Each via `deploy_vm.sh`, only between studies.

## Open questions for you

1. **Verified-signup bar.** A signup only passes when the server saw the verification link or code used.
   That is right for apps that send one, but fails apps that never send a verification mail (Cronitor,
   earlier) even when the account is real and signed in. Keep the bar, or allow "signed in, no mail ever
   arrived" as a pass?
2. **Company-email-only sites (Formbricks).** With one shared Gmail inbox these can never pass. Leave them
   as "blocked" findings (current behaviour), or pick rivals that accept Gmail?

## Known issues not fixed

- The `select` action sometimes picks the wrong open list (Baserow field type: it saw the sidebar's
  database list). Agents recovered by scrolling, but it wastes steps.
- One `usersim_act` call took over 60 s and the client timed out (1 of 108 in study 2).
- Haiku sometimes calls `usersim_signup_identity` with no `session_id`; it recovers after the error.
