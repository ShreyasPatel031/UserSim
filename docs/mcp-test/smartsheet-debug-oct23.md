# Smartsheet study 75183a40: why 30% of cells ran to the step cap (Oct 23)

Source: the server's own copy of the study (`GET /api/studies/<id>`, every step's thought, click args and screenshot url).
The runner's local cell files only kept tool and action name, which is why the loops looked like "stuck clicks".

- **The long click runs are image CAPTCHAs.** Example `t2__p3__competitor_2` (Asana): the agent fills the email, a
  reCAPTCHA grid opens, it clicks tiles ("fire hydrant", "traffic light", "bicycle") and VERIFY, gets a new grid, and
  repeats for 95 steps. Clicks register; the agent is solving challenges that never end.
- 24 of 108 cells ran 90+ steps; 19 of those spent 30% or more of their steps on CAPTCHA, median share 52%.
  Judge or feedback text mentions a CAPTCHA in 28 of 108 cells (Smartsheet 10/36, Monday 6/36, Asana 12/36).
- `docs/E2E_TEST.md` says to stop and report on a CAPTCHA. Nothing enforces it: the prompt says "solve it like a person",
  and `usersim_solve_captcha` refuses only after 3 calls per page.
- **10 cells were abandoned, not failed**: all of persona p6 (8 cells) plus `t6__p5__product` and `t6__p5__competitor_1`
  ended "Timed out (no action from the client)". The runner died, `--resume` found them still "running" on the server
  (summary.json: "was already run (status running)"), so they were never replayed. They count in the 108 with partial
  traces (1 to 94 steps). `t4__p6__product` is one of them: 1 step, then the `ConnectError:` (empty message) that killed the runner.
- The 99 local cell files are the cells the runner finished itself; the 10 above exist only on the server.

Runner logging added (scripts/mcp_study_runner.py): per step `args`, the model's `thought`, and the server's reply
(`url`, `captcha`, `action_error`, `rejected`); a per-cell `stall` summary (longest identical-action run on one url,
CAPTCHA steps); `traceback` in `*.error.json`; a gzip copy of the server's study saved as `server_study.json.gz`.

Not changed: CAPTCHA behaviour. Options are a runner-side guard (finish as blocked after N CAPTCHA steps) or a server
prompt change; both alter results, so they need a decision.

## Live test and root causes (Oct 23, three fresh Smartsheet sessions through the public MCP)

- **CAPTCHA:** all 3 sessions got an image grid right after the second Continue (one showed "Try again later: your computer
  or network may be sending automated queries", i.e. the cloud browser's IP is flagged). `usersim_solve_captcha` reported
  audio refused and never tried the paid solver: `captcha_state` said `token_ready: true` (a non-empty
  g-recaptcha-response field) while `challenge_open: true`, and both the paid solve and the act-time presolve skip when a
  token is ready. Fixed: an open challenge counts as unsolved.
- **Plus alias:** Smartsheet answers "Invalid email address." to `+` addresses; the agents then use a dot-variant of the
  shared inbox. 20 of 36 cells got as far as the confirm page (`provconfirm`), but only 1 confirmation mail arrived
  (matched by exact dotted address, so matching works). Most likely Smartsheet treats all dot-variants of one Gmail as one
  address (15 cells saw a 500, 9 "already exists"), so only one confirmation was ever sent. Not proven: the mail inbox
  is not readable from here.
- **Fix for the signup load:** `study_shared_accounts` (limits.json, default on): one signup per site per study. The first
  cell creates the account; later cells of that study get it from `usersim_signup_identity` and log in. A cell whose owner
  ended without a verified signup takes over.
- Not tested live: the paid-solve fix and shared accounts need the server deployed (merge to main). Test plan after deploy:
  run `scripts/mcp_study_runner.py <smartsheet> --smoke` and check `captcha_paid_log` in the study JSON.

## Smoke runs 3 to 6 (Oct 23, through the runner; each fix found by the previous run's logs)

- Run 3: 26 clicks on "Accept All" at the wrong spot. Runner downscaled screenshots to 1024 px, the browser is 1280: fixed (full width).
- Run 4: `captcha_paid_log` said ledger `skip: host_not_paid`. The MCP never registered the site under test as a paid host
  (`allow_study_host` was only called by the website driver): fixed in `usersim_start_session`.
- Run 5: the model acted on the first page's screenshot for the whole run. The runner refreshed it only after `usersim_observe`:
  fixed for every tool that returns an image.
- Run 6: CAPTCHA fixed: 4 paid solves ($0.0008 each), every one `site_accepted: true`, account creation reached the
  confirm page. `mail_debug` then showed the inbox received NO Smartsheet mail in 8 waits (only an unrelated Monday
  marketing mail): not a matching problem. The shared Gmail already holds a Smartsheet account (study 75183a40, cell
  t2__p1__product, verified through `app.smartsheet.eu`, i.e. the EU data region); Smartsheet treats all dot-variants as that
  one address, so later signups get no mail. Fix: a per-site account registry. `usersim_signup_identity(no_plus=true)` on a
  site that already holds this inbox's verified account returns that account to log in with (`save_host_account` /
  `load_host_account`, seeded by a verified signup finishing, or by `same_account_as`).

## Result (Oct 23, builds up to 61f396ba7e89)

| Run | Study | Outcome | Haiku $ | Paid CAPTCHA |
|---|---|---|---|---|
| Asana, fresh signup + email code (smoke) | `a8738b67` | signup verified, landed on a project page, judge goal reached, proof pass, 40 steps | 1.23 | 3 solves, all accepted, $0.009 |
| Smartsheet (smoke 8) | `83aaf9cd` | reused the site's account via the registry, switched to the EU region, reached `app.smartsheet.eu/b/home`, 30 steps | 0.80 | 1 solve, accepted |
| Smartsheet (smoke 9) | `45177f9c` | same, scored as a login run (no signup_email); judge: reached the workspace but "did not complete a new signup" because the task text says sign up | 0.74 | 1 solve, accepted |

A brand-new Smartsheet signup is not possible from this inbox (every dot-variant is the one address that already holds the
account); Asana and Monday (plus aliases) get genuine fresh signups. Cost: a cell costs about $0.75 to $1.25 in Haiku, so a
108-cell study is roughly $80 to $135 before shared accounts shorten the signup part.
