# Deploy request — MCP / website shared signup core (Oct 7, 2026)

**Status: GATE MET. Awaiting Shreyas's go-ahead via Grok Bot. Ships d663865 / tree 4ecb8e761d14 (origin PR #65 tip d2ce23d). Nothing has been deployed** (not usersim.vercel.app, not the prod VM).
- Gate (Grok Bot's ruling, 3:25 PM PT): Litlyx rerun plus 3 new sites, all PASS 3/3 under the 2-of-3 judge rule. FabForm (sends no verification mail) and FormBold (/dashboard never paints after verification) count as correct site-side fails and are dropped from the gate.
- Loop 6 evidence (local 127.0.0.1:8787):
  - Litlyx 9f7715a3-3a4e-4b2e-93f8-7b5cb9c28a36 (3/3) + Grok Bot 5f319520-d9ef-4e9d-b222-e7ba1441242d (3/3 after the c81f4ff judge fix)
  - heyform d4daacf8-6c1d-4f9e-b285-4ed2432f99a7 (3/3)
  - kwesforms 43b91a19-803b-4ecb-8ff3-bb5bdb072409 (3/3)
  - databuddy 02c4d7d6-0b71-415c-8b3e-c6f806ec26db (3/3)
  - e2e_mcp 74e19cd7-7800-4099-b6b5-f31d8d18518b (PASS, fails [])
  - parallel 3-cell start_study bbc9ff3b-b3fc-4b08-898d-6bdfdc07c75f
  - site-side fails: FabForm 39ee0b4c-bec7-45d3-b01e-3b52a789d6c3, FormBold 1985d18d-e420-4344-ac77-c0e1a8d30a11
- PR #65: the 6 commits after b212561 landed on origin at 3:27 PM PT as a fast-forward from 6a09830 (no force push). **Origin tip: d2ce23d03d23b931c12bf43604f3f9483e1facba (d2ce23d)**. `git am` gave new SHAs: ecf28f8, 46ed523, 7b1b3c3, 7f7f69a, e0264b5, d2ce23d, the same content as local c81f4ff, 2d60c4c, c8859f0, e588c57, 50ba514, d663865. The tree id should equal 4ecb8e761d14 (check with `git rev-parse d2ce23d^{tree}`; not checked from the box, because remotes are untouched here). Cloud-side tests with full deps on d2ce23d: **74 passed, 0 failed**.

## What ships
- **PR #65** (`mcp-signup-parity` → main, head 0a3c1d6 / origin 8b01968, same content as local 65256f8): 13 commits after bff8080:
  - shared core `mvp/signup_tools.py`, imported by both the website (`signup_in_session`) and the MCP
  - `DRIVER` read from env `MVP_MCP_DRIVER` (default `mcp_client`); the hardcoded `claude_code` is gone
  - the-old-personal-inbox scrubbed from code; the inbox allowlist and sha guard refuse any other inbox
  - Google/GitHub sign-in blocked
  - MCP signup tools (identity, code/link wait, open-link-once, SMS, free captcha: Turnstile click + reCAPTCHA audio)
  - `fields`/`captcha` observations; new actions press_and_hold, drag, triple_click, select, type at x,y
  - judge evidence + `signed_in_app_page` + `signup_verified` proof check; Browserbase proxies + built-in solve
- **Commits after PR #65 (65256f8), not in the PR yet.** `2c109fc` is already delivered in `mcp-after-65256f8.patch` (regenerated to cover all 10 commits). The 9 commits after it are in **`/workspace/product/mcp-test/mcp-after-2c109fc.patch`** (`git am` on top of 2c109fc). Final local HEAD: **3aad4a0** (engine_version `3aad4a0c4df6`).
  - `2c109fc`: paid CapSolver path through the metered ledger. **OFF by default** (needs `MVP_MCP_PAID_CAPTCHA=1` plus a host in `MVP_CAPTCHA_PAID_HOSTS`; total cap `MVP_CAPTCHA_TOTAL_CAP_USD`).
  - `f4996a3`: required bearer token on `/mcp` (`MVP_MCP_TOKEN` or `MVP_MCP_TOKEN_FILE`); e2e_mcp sends it. With no token configured, /mcp stays open, so **prod must set a token with this deploy**.
  - `0e63480`: `reload` action, a `disabled`/busy flag on fields, prompt hints for a stale "verify your email" state and double submits (getinsights fix).
  - `9ae1703`: refuses typing any email other than the signup inbox.
  - `5895754`: flags invisible reCAPTCHA; the hint no longer says submit will fail, and solve_captcha says there is nothing to solve.
  - `ef2f632`, `f8d7d10`: fields list `<select>`/datalist options; `select` finds the nearest native select, fuzzy-matches the option and drives it through Playwright `select_option`.
  - `8e2dd02`: solve_captcha waits out Cloudflare "Just a moment" and refuses after 3 tries per page.
  - `ad203be` (**shared website + MCP**): the email link ranker matches social/CDN skips on the host. Before, `x.com/` matched `sendfox.com/…` and dropped verify links for any host ending in "x".
  - `3aad4a0` (**shared website + MCP inbox**): wait returns the verification mail before a newer welcome mail. In the MCP proof, `signup_verified` now requires the opened link to look like a verify/sign-in link (closes two SendFox false passes).

- **Loop 5 fixes after 3aad4a0** in **`/workspace/product/mcp-test/mcp-after-3aad4a0.patch`** (`git am` on top of 3aad4a0). **Final local HEAD: b212561** (engine `b212561bb4ea`):
  - `02e90c0` (**shared website + MCP**): `verification_link` accepts click-tracking redirects (Brevo, SendGrid, Mailchimp, …) via confirm/verify anchor text, the browser's redirect chain, or a safe Location-only resolver that never requests the verify hop.
  - `b29cbd2`: judge hard rules (an unverified signup or a blank/spinner final frame never passes); a dim backdrop is no longer counted as blank; proof details differ for pass and fail.
  - `a7371fb`: 1280x800 viewport forced on every page/step and screenshots normalized; password masked in fields, traces and observations; `page_errors`; hidden terms checkboxes listed; wait for click-triggered navigation; `clear_cookies` action; anchor text + redirect chain recorded per opened link.
  - `7b3d4b6`: tests. `b212561`: judge treats in-app onboarding as signed-in; verification enforced server-side only.

- **Loop 6 fixes after b212561** in **`/workspace/product/mcp-test/mcp-after-b212561.patch`** (6 commits, `git am` on top of b212561). b212561 has the same content as origin 6a09830. **Final local HEAD: d663865** (`/health`: `engine_version` `d663865ed08b+tree.4ecb8e761d14`, `content_id` `4ecb8e761d14`):
  - `c81f4ff`: typing waits for load, checks the field kept the text and retypes once (the first field after a navigation was wiped on formbold/fabform/litlyx). The navigation wait follows main-frame navigation requests (~3 s) and adopts new tabs; `observe` adopts late tabs. `page_errors` only reports real errors. `fields` lists only painted, on-screen, hit-testable controls; invisible/off-screen/bot-trap inputs go to `hidden_fields` with no x,y. Task-independent signed-in second look for verified signups (Litlyx install page). `engine_version` now carries the git tree id.
  - `2d60c4c`: controls covered by a chat widget / cookie banner / modal are named in `hidden_fields` (Formester Crisp chat).
  - `c8859f0`: alias-rejected hint says "retype" once a no-plus address exists; repeat `signup_identity` calls are refused after 3 (FormBold 30-call loop).
  - `e588c57`: the second look treats "account under review / suspended" as not signed in.
  - `50ba514`: `unfilled_fields` names the empty boxes of a half-filled form (Formester Confirm Password).
  - `d663865`: finish re-takes final.png for up to 12 s when the last frame is blank/spinner; a page still unrendered stays a fail.

## Test evidence (all local, 127.0.0.1:8787; study ids in gs://usersim-bakeoff-347838016394/mcp-test)
| check | result | study id |
|---|---|---|
| `python -m mvp.e2e_mcp` (local, bearer on, d663865) | PASS, fails [] | 74e19cd7-7800-4099-b6b5-f31d8d18518b |
| Loop 6 Litlyx rerun (Gemini) | PASS 3/3 (true/true/true) | 9f7715a3-3a4e-4b2e-93f8-7b5cb9c28a36 |
| Loop 6 Litlyx rerun (Grok Bot), re-judged after the fix | PASS 3/3 | 5f319520-d9ef-4e9d-b222-e7ba1441242d |
| Loop 6 heyform.net (new, Gemini) | PASS 3/3 | d4daacf8-6c1d-4f9e-b285-4ed2432f99a7 |
| Loop 6 kwesforms.com (new, Gemini) | PASS 3/3 | 43b91a19-803b-4ecb-8ff3-bb5bdb072409 |
| Loop 6 databuddy.cc (new, Grok Bot) | PASS 3/3 | 02c4d7d6-0b71-415c-8b3e-c6f806ec26db |
| Loop 6 fabform.io rerun | FAIL by design: no verification mail exists | 39ee0b4c-bec7-45d3-b01e-3b52a789d6c3 (+27b5bdf2) |
| Loop 6 formbold.com rerun | FAIL: /dashboard spinner after verify (×3) | 1985d18d-e420-4344-ac77-c0e1a8d30a11, 299b3718, d923beb7, 659b1598, dd65d630, 827826d9 |
| Loop 6 formester.com (new) | BLOCKED: invisible reCAPTCHA v3 "Recaptcha verification failed" | 8b0fc4f6, e75483d0 |
| Loop 6 formbricks.com (Grok Bot) | BLOCKED BY POLICY (company emails only) | 1aadbc7a |
| Loop 6 parallel-cell start_study (3 cells at once, Gemini) | complete, proof pass ×3; goal true/false/true | bbc9ff3b-b3fc-4b08-898d-6bdfdc07c75f |
| Offline safety check of the second look (verified but signed-out runs) | getinsights 72a5cc90, plunk e94fa71b, pirsch 7c0c186d stay FAIL 0/3 | — |
| unit tests loop6 + loop5 + test_sim_mcp | 56 passed | — |
| `python -m mvp.e2e_mcp` (local, bearer on, Loop 5 code, engine 7b3d4b6) | PASS, fails [] | f619b5cc-2019-4d90-9350-88867c8fb1e1 |
| `python -m mvp.e2e_mcp` (local, bearer on, 3aad4a0) | PASS, fails [] | 1dde69cd-acd0-403b-b067-121996985884 |
| Offline re-judge of all 71 MCP rows under the Loop 5 rules | FormBold, Fabform, SendFox ×2 flip to FAIL (correct). Litlyx is now verified and its proof passes, but the judge still says no. Other signup passes hold. Variance: pug.sh 55b62ac6 (no signup) now false | see signup-coverage.md, Loop 5 fixes |
| `python -m mvp.e2e_mcp` (local, bearer on, f4996a3) | PASS, fails [] | 4d365718-5d0a-4563-92b9-ea70a778248d |
| ↳ first attempt | FAIL, watch iframe only (watch_url pointed at prod; fixed by `MVP_PUBLIC_BASE_URL`) | 25095cb2 |
| Formspark signup (Haiku) | PASS | e4e1eac5 |
| Plunk signup retest (Haiku) | PASS | 81918860 |
| Formcarry signup (Haiku) | PASS (onboarding incomplete) | d63804e8 |
| Tinylytics signup (Gemini 2.5 Flash) | PASS | d5721a6f |
| Umami signup (Gemini 2.5 Flash) | PASS | 9aafddbe |
| Parallel matrix + finish_study with a skipped cell | PASS (2 cells overlapped, 1 skipped, report generated) | 05de7ed1-7bcf-4ec7-836b-8890bfe3d7c7 |
| EmailOctopus signup (Gemini) | PASS (onboarding combobox still open) | f5a47714, e1e9fee1 |
| GoatCounter signup (Gemini) | PASS | 5610aa30 |
| getinsights retest with the reload fix (Gemini) | PASS | a673957b |
| Gemini parallel matrix + skipped cell | PASS (cells overlapped; product proof `beyond_first_screen` false, answer was on the first screen) | ca39eee4 |
| Website vs MCP: pug.sh pricing / rejourney crashes | website 6/6 & 0/6; MCP Haiku pass/pass, Gemini fail/fail | 3b8310aa, 55b62ac6, e513cab8, d289183f |
| False-pass audit after 3aad4a0 | only SendFox f03cb437 / 17625fad flip to not verified | — |
| ~~FormBold 945f1ccf / Fabform d80aecdd judge passes~~ | false positives, now FAIL under the hard rules | 945f1ccf, d80aecdd |
| unit tests `mvp/test_sim_mcp.py` + `test_signup_in_session.py` + `test_sim_mcp_loop5.py` + `test_page_verdict.py` | 74 passed (test_signup_sms.py: 4 failures that predate these changes) | — |

Known open items: EmailOctopus onboarding combobox; sites that send no verify mail (Swetrix, OpenPanel, counter.dev) can't pass `signup_verified` by design. UserJot (invisible reCAPTCHA v3) and Tinybird (Auth0 Turnstile) are blocked and parked. Typebot fails the cross-domain proof check on purpose (kept strict). Formcarry normalizes Gmail aliases.

## Deploy steps (when approved)
0. Gate: met on d663865 (Litlyx + heyform, kwesforms, databuddy, all 3/3; FabForm and FormBold dropped as site-side fails). Go-ahead from Shreyas via Grok Bot is still required.
1. Apply `mcp-after-65256f8.patch` (10 commits), `mcp-after-3aad4a0.patch` (5 commits) and `mcp-after-b212561.patch` (6 commits) to `mcp-signup-parity`, then merge PR #65. After `git am`, check that `git rev-parse HEAD^{tree}` equals `4ecb8e761d14…` (the same code as local d663865).
2. Prod env: set `MVP_MCP_TOKEN` (or `MVP_MCP_TOKEN_FILE`), `MVP_MCP_DRIVER`, `MVP_SIGNUP_ALLOWED_LOCAL=usersimsignups`. Leave `MVP_MCP_PAID_CAPTCHA` unset.
3. Redeploy the VM/Vercel. Check that `/health` shows the new `engine_version`.
4. Smoke test: `/mcp` without a token → 401; `python -m mvp.e2e_mcp` against prod with the token → fails [].

## Rollback
- Redeploy the previous `engine_version` (the commit before the merge), or `git revert` the merge commit and redeploy.
- Fast kill switches with no code change: unset `MVP_MCP_PAID_CAPTCHA` (already off by default). Point `MVP_MCP_BB_PROXIES=0` to turn off proxies/solve.
- The bearer guard is env-only. Unsetting the token reopens /mcp; if needed, rotate the token instead.
- No data migrations: GCS layout and study.json schema are unchanged (new fields are additive). Rollback is code only.

## Oct 8 security hygiene (GitGuardian incident 37980789)
- Local commit 2f662b0 (tree ea6821608bda) on top of d663865 (same tree as origin d2ce23d): hardcoded test password replaced by runtime fake, real identities redacted, guard test mvp/test_no_real_identities.py added.
- Patch: mcp-secret-hygiene.patch (git am onto d2ce23d). NOT pushed yet: needs the cloud agent. Still no deploy.
- Leaked value belongs to the getinsights.io run (study 72a5cc90). Rotate it before closing the incident; old commit a3f26c4 stays in history unless Shreyas approves a rewrite.
- Oct 8 ~7:39 AM PT: the hygiene patch landed via cloud agent bc-d330a8e8. PR #65 tip is now 1ceff108a1ccc613567101cb62c05b764be270cd (d2ce23d → 1ceff10, fast-forward, no force). Cloud tests: 70 passed, 5 skipped.
- GitGuardian on 1ceff10 still fails, only because a3f26c4 is still in the PR history (incident 37980789). The current tree is clean. To clear it, resolve the incident in the GitGuardian dashboard (credential rotated), or Shreyas approves a history rewrite.
- getinsights.io credential rotated Oct 8 ~7:39 AM PT: password reset through the site's emailed link (headless Playwright), then a headless login with the new password reached /dashboard. The reset replaces the leaked value (old password not tested separately). The new password is kept in a local secrets file outside the repo (never committed).
- Still open: real passwords for the-old-personal-inbox+linear/+notion/+todoist accounts (linear.app, notion.so, todoist.com) have been public in main history since 9486350 (Sep 5). They are redacted in the tree but should be rotated.

## Oct 11 addendum: study-view auth (case A: public by unguessable id, like the website)

Read-only checks on the live site (Oct 11, about 6:05 AM PT, no changes made):
- `GET https://usersim.vercel.app/api/studies/<random uuid>` → 404 `{"detail":"Study not found"}` with no auth header. The route has no auth check; only the id gates it.
- `GET /api/studies/<random uuid>/live` → 200 `{"missing":true,...}`, no auth.
- The watch link the product hands to humans is `https://usersim.vercel.app/?study=<id>`, and the report link is `/report?study=<id>`. Both are public pages that read the study JSON by id.
- `GET /mcp` and `POST /mcp` → 404: /mcp is not deployed on the live site.

Decision: the MCP side server serves the same `/api/studies/<id>` route (same app, same code) public by unguessable study UUID, matching the website's share/watch link. No change to the study view.

/mcp (every tool call) must carry the bearer token:
- Commit "sim_mcp: /mcp fails closed without a configured bearer token" (Oct 11). POST/GET/DELETE /mcp with no token, a wrong token or a non-Bearer scheme → 401. If MVP_MCP_TOKEN / MVP_MCP_TOKEN_FILE is unset, /mcp now refuses everyone (before, it was open); MVP_MCP_ALLOW_OPEN=1 is for local dev only.
- Tests: mvp/test_sim_mcp_auth.py (no/wrong/Basic token, GET/DELETE → 401; right token → 200 initialize; unset token → 401; study view public by id).
- Deploy note: when /mcp ships to the live site, set MVP_MCP_TOKEN_FILE (mode 600) in the service env, or /mcp will answer 401 to every caller.
