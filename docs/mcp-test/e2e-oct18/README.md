# No-token MCP e2e: 3 new products (Oct 17–18, 2026)

Every run went through the public MCP at `https://35-202-98-224.sslip.io/mcp` with **no token**, the way an outside agent would. Each product had one study: a signup cell, then 3 core-task cells that log back in to the account the signup cell created (`usersim_signup_identity same_account_as=`). Signup was email + password where the product allows it, never Google or GitHub. Aliases came from the MCP.

| Product | Signup and verification | Report |
|---|---|---|
| [Clockify](clockify.md) (time tracking) | email only (Clockify has no password field), 6-character **emailed code** | [https://usersim.vercel.app/report?study=eb205e50…](https://usersim.vercel.app/report?study=eb205e50-1cba-4b4c-84c5-f39747abd7c3) |
| [KanbanFlow](kanbanflow.md) (kanban) | name + email + password, 6-digit **emailed code** | [https://usersim.vercel.app/report?study=72c2fd88…](https://usersim.vercel.app/report?study=72c2fd88-e7a0-41f7-8bed-864142e1a5e6) · task 4 final pass: [e1be2256…](https://usersim.vercel.app/report?study=e1be2256-d0ed-4da9-9b97-f14d13cf0fe2) (earlier reruns [91651b7e](https://usersim.vercel.app/report?study=91651b7e-338f-4183-b3b9-b799e3b74e11), [9fe4e35e](https://usersim.vercel.app/report?study=9fe4e35e-c57e-4853-8821-837b057964d6)) |
| [Dynalist](dynalist.md) (outliner) | name + email + password, **emailed confirmation link** | [https://usersim.vercel.app/report?study=ab9fa612…](https://usersim.vercel.app/report?study=ab9fa612-f223-4ec8-bcff-5087400f3420) · task 4 final pass: [4ab5be34…](https://usersim.vercel.app/report?study=4ab5be34-d6b4-4848-aa69-cae94dba97f7) (earlier rerun [6782d34e](https://usersim.vercel.app/report?study=6782d34e-d9d1-4789-914a-4e1f98b15ac3)) |

(The same pages are at `https://atelier-sim.com/report?study=<id>`.)

## Pass / fail

"Done in the browser" means the end state was on screen and still there after a page reload (see screenshots). "Judge" is UserSim's independent vision judge. "Proof" is the server's proof checks.

| Product | Task | Done in browser | Judge | Proof |
|---|---|---|---|---|
| Clockify | Sign up + verify | ✅ | ✅ reached | ✅ |
| Clockify | Create project *Acme Website Redesign* for new client *Acme Co* | ✅ | ✅ | ✅ |
| Clockify | Log 1:30 today, "Homepage wireframes" | ✅ | ✅ | ✅ |
| Clockify | Weekly report shows hours per project | ✅ | ✅ | ✅ |
| KanbanFlow | Sign up + verify | ✅ | ✅ | ✅ |
| KanbanFlow | Create board *Client Website Launch* | ✅ | ✅ | ✅ |
| KanbanFlow | Add *Write homepage copy*, move it to In progress | ✅ | ✅ | ✅ |
| KanbanFlow | Mark it done (Done column) | ✅ | ✅ on rerun e1be2256 (the first 3 runs hit judge bugs, now fixed) | ✅ |
| Dynalist | Sign up + verify (link) | ✅ | ✅ | ✅ |
| Dynalist | Create document *Website Redesign Plan* | ✅ | ✅ | ✅ |
| Dynalist | Outline: Research, Wireframes › Homepage sketch, Launch | ✅ | ✅ | ✅ |
| Dynalist | Check off *Research* | ✅ | ✅ on rerun 4ab5be34 (the first 2 runs hit judge bugs, now fixed) | ✅ |

**Final: signups 3/3 pass, tasks 9/9 pass (judge reached + proof PASS on all 12 cells).** KanbanFlow task 4 and Dynalist task 4 first failed on judge false negatives (the browser work was always done). They were root-caused, fixed, deployed, and passed on rerun.

## MCP / engine issues found and fixed

| PR | SHA on main | What |
|---|---|---|
| [#76](https://github.com/ShreyasPatel031/UserSim/pull/76) | c0fd1ab | The report showed **Proof FAIL on runs that passed** (1×1×1 studies read a summary field that was never written). `usersim_get_report` crashed on studies loaded from disk. `usersim_start_study` now has a typed schema (persona `bio` required, task `prompt` required, with examples) |
| [#77](https://github.com/ShreyasPatel031/UserSim/pull/77) | 75c35ae | Anon caps in `mvp/sim_mcp/limits.json`: `anon_daily_usd_per_ip` 2→6, `anon_daily_usd_global` 10→20 (12+ sessions in one night were blocked) |
| [#78](https://github.com/ShreyasPatel031/UserSim/pull/78) | e4b0c4a | **"unknown study_id" right after start_study**: anon ownership was keyed by client IP, which rotates behind NAT/relay pools. The session id is now the credential; caps stay per IP |
| [#79](https://github.com/ShreyasPatel031/UserSim/pull/79) | b63f3d3 | No way for later cells to log in to the signup account → `same_account_as`. Clockify's `cakeExchangeToken` **JWT was visible in public trace URLs** → secret query values are redacted. A fonts.googleapis.com link was offered as "verification link 1" → web-font and CSS links are skipped |
| [#80](https://github.com/ShreyasPatel031/UserSim/pull/80) | 5c5550a | Judge sees the server's action log. Wait tool: a **code-only mail no longer says "open link 1"**. `same_account_as` survives a server restart (the account is saved at signup, mode 600, keyed by a hash of the session id, 30-day TTL) |
| [#81](https://github.com/ShreyasPatel031/UserSim/pull/81) | 01ca5d6 | Saved accounts live in `/var/lib/usersim/mcp_accounts`, because each deploy replaces the app dir |
| [#82](https://github.com/ShreyasPatel031/UserSim/pull/82) | 3f2b4fb | Judge end-state rule placed next to the task goal (KanbanFlow "already in Done") |
| (see below) | 352f4ed | Judge: a group inside the requested column (KanbanFlow's "Today" date group in Done) is still that column. `select` is shown in the trace with its option. On the exact server inputs: 10/10 FAIL before, 8/8 PASS after; the In-progress negative stays 0/6 |
| (see below) | 9928cd7 | Judge: the server reads done-state that innerText drops (**struck-through text, ticked checkboxes**) into the judge's facts, and the prompt treats struck-through as checked off. Dynalist frame: 6/6 FAIL before, 6/6 PASS after; the unstruck negative stays 0/6 |
| (see below) | b0f7eec | Done-state reader: the struck text sits in a child of the struck wrapper (computed text-decoration isn't inherited), and apps mark done by class (Dynalist `.Node.is-checked`). It now reads the wrapper's text and done-like classes. Rerun 6782d34e saw no mark; checked on the live Dynalist page; rerun 4ab5be34 passed |

**Live engine: `b0f7eecd`** (/health `engine_version`, /static/build.txt), deployed from branch `mcp-judge-subgroup` (main 3f2b4fb + 352f4ed + 9928cd7 + b0f7eec). The box lost GitHub push access mid-run, so the last three commits and this docs branch are merged to main through a cloud agent from a git bundle; see that PR for the merge SHAs.

## Still open (MCP)
- The captcha hint can stay "turnstile not passed" on the next page (Clockify OTP page). It's cosmetic; I didn't fix it.
- Native `<select>` inside KanbanFlow's Move popover was not listed in `fields`, but `select` by label worked.
- Some buttons (Dynalist's Sign up, KanbanFlow's card side icons) are not listed in `fields`, so agents have to work from the screenshot.
- Study ids are public, so any no-token caller who has one can run that study's queued cells. This is a documented trade-off; a per-study key is the follow-up.

## Evidence
- `shots/`: final frame of every cell plus key moments
- `calls.redacted.jsonl`: every MCP call and response from the night. Passwords, verification codes, verification links and JWTs are replaced with `<redacted>`
- `reports/`: `usersim_get_report` markdown per study
