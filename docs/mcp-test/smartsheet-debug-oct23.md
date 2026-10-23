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
