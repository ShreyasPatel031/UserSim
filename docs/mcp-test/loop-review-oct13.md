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
| 3 | [008b395c](https://atelier-sim.com/report?study=008b395c-d66f-40d4-904c-fd371be95b42) | koalendar.com · zcal.co · harmonizely.com | 68c8b0c | 37/108 | 38/108 | $1.32 |
| 4 | [2e8d7db5](https://atelier-sim.com/report?study=2e8d7db5-f4eb-4aea-ad88-400771648f3a) | instatus.com · hund.io · statuspal.io | 52e9b7a | 54/108 | 70/108 | $2.83 |

Per site, study 1: Tally 23/36, Youform 19/36, Formbricks 3/36. Study 2: Baserow 33/36, NocoDB 35/36, Teable 35/36.

How to read study 1: almost every Tally and Youform failure was a harness bug, fixed before study 2 (below).
Formbricks is a real product finding: it refuses every gmail.com address ("Please sign up with your company
email address."), so with one shared Gmail inbox no agent can sign up there.

How to read study 3: harmonizely.com serves an HTTPS certificate for another host, so none of its 36 runs
could open (now refused when the study is created). Every Koalendar signup failed on our side: Koalendar
mails its code as "935-413" and the code finder did not read grouped codes, so agents waited 10 minutes for a
mail that had arrived (fixed, checked against the real mail on the VM). Zcal refused several signups with
"too many accounts were created": it likely treats every alias of the one Gmail inbox as the same person.

How to read study 4: Instatus 25/36, Statuspal 22/36, Hund 7/36. 14 Statuspal failures are its
company-email-only signup (gmail.com refused). Instatus showed a puzzle captcha ("match the animals") in 3
runs. Hund's signup runs an Altcha proof-of-work check, then often renders a broken half-page; 4 parallel
agents also invented the same subdomain ("already taken"; fixed by using the identity's unique name). 6 Hund
and 3 Instatus "find out whether it monitors automatically" runs were failed by a too-literal judge (the page
said yes; the judge wanted a demonstration). Re-judged with the new prompt on the VM: the 2 Hund runs tried
flipped to pass, the controls stayed failed.

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
| a871229 | study 3 | A cell whose browser failed to open stayed "error"; every retry said "already run" | Back to the queue (3 tries) with a "call again" message |
| a871229 | study 3 | harmonizely.com has a bad certificate; all its cells failed | `usersim_start_study` refuses a site with a TLS or DNS failure |
| 52e9b7a | study 3 | Koalendar's code "935-413" was never read | Grouped codes (3-4 + 3-4 digits) are read, as digits only |
| 8d1d4be | studies 1-4 | 16 of 3,992 act calls were flattened (`"action":"click","x":"888"`) | Rebuilt into the action object |
| 83c1f14 | study 4 | Judge failed find-out tasks whose page stated the answer ("does not demonstrate the tool") | Judge prompt: a research task passes when the final page states the answer, yes or no (shared with the website judge) |
| 83c1f14 | study 4 | Parallel agents invented the same subdomain on Hund | Prompt and identity reply: use the identity's unique username / workspace |
| 657ff0f | study 2 | Haiku garbled Baserow's long verify token when copying it; every open refused | `link_number=1` opens the first link; a near-exact copy of exactly one link opens it |

Deploys: 2ed920b (Oct 13 00:47), 77929a5 (07:13), 68c8b0c (07:50), 52e9b7a (08:45), 83c1f14 (09:25). Each via `deploy_vm.sh`, only between studies.

## Open questions for you

1. **Verified-signup bar.** A signup only passes when the server saw the verification link or code used.
   That is right for apps that send one, but fails apps that never send a verification mail (Cronitor,
   earlier) even when the account is real and signed in. Keep the bar, or allow "signed in, no mail ever
   arrived" as a pass?
2. **Company-email-only sites (Formbricks, Statuspal).** With one shared Gmail inbox these can never pass. Leave them
   as "blocked" findings (current behaviour), or pick rivals that accept Gmail?

## Known issues not fixed

- The `select` action sometimes picks the wrong open list (Baserow field type: it saw the sidebar's
  database list). Agents recovered by scrolling, but it wastes steps.
- One `usersim_act` call took over 60 s and the client timed out (1 of 108 in study 2).
- Haiku sometimes calls `usersim_signup_identity` with no `session_id`; it recovers after the error.
- Hund's Altcha proof-of-work signup often ends on a half-rendered page in our cloud browser; not
  diagnosed (could be the site or Browserbase). `usersim_solve_captcha` does not know Altcha.
- Zcal: the first-name field sometimes did not keep typed text; agents retyped it.
- The loop's own MCP calls from this cloud sandbox hit intermittent connection errors (sandbox egress);
  the driver retries, and reruns a cell whose agent never connected.
