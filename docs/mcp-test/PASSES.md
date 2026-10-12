# MCP signup passes counted for PR #65

**Total counted passes: 39** (one per product; 35 through Oct 11 plus 4 on Oct 12).

Bar used (the current one): a product the test account had never seen before, email verified through a mail the server
observed, the run ends signed in, at least 2 judge votes yes (2-of-3 rule; with 2 agreeing votes the third is not
needed), and the server proof check passed (`agent_results[0].page_verdict.signup_verified` = true, verify link or code
opened on the product).

Test inbox: `usersim.signups@gmail.com` only, with a per-site alias of the form `usersim.signups+<tag>`. No Google or
GitHub sign-in.

## Where the study JSONs live

Code: `mvp/gcs_store.py` reads `MVP_GCS_PREFIX` (default `gs://usersim-bakeoff-347838016394`) and writes
`<prefix>/mvp_studies/<study_id>/study.json`.

- Oct 7–8 (box-local MCP server): `gs://usersim-bakeoff-347838016394/mcp-test/mvp_studies/<study_id>/study.json`
- Oct 9 onward (side server on the test VM, `start.sh` sets `MVP_GCS_PREFIX=gs://usersim-bakeoff-347838016394/mcp-test-vm`):
  `gs://usersim-bakeoff-347838016394/mcp-test-vm/mvp_studies/<study_id>/study.json`

All 35 Oct 7–11 counted studies were downloaded from GCS on Oct 11, 2026 (PT). **No counted pass exists only in local or VM logs.**
The Oct 11 offline re-judge outputs (`rejudge-oct11.json` for Raygun/StatusCake and `rejudge-oct11b.json` here, in this
folder) were produced on the VM from the same studies; the re-judge results themselves are not uploaded to GCS.

- Oct 12 onward (test server with `MVP_GCS_PREFIX=gs://usersim-bakeoff-347838016394`, the same location the website
  report page reads): `gs://usersim-bakeoff-347838016394/mvp_studies/<study_id>/study.json`, viewable at
  `https://usersim.vercel.app/?study=<study_id>` and `/api/studies/<study_id>`. The 35 earlier studies were also copied
  there on Oct 12 (originals untouched), so every counted pass opens on the report page.

## Notes on earlier rules

- Oct 7–8 gate passes (heyform, kwesforms, databuddy, litlyx, aptabase, withcabin): judged 3 times offline with
  `judge3.py` (same judge code as the server at the time); all 3/3. The study.json stores the single live verdict only.
  The `driver` field in these study.json files reads `claude-haiku-4-5`: that was the server's default driver label
  before `MVP_MCP_DRIVER` was set, not the model that drove the run. The driver column below is from the run logs
  in `signup-coverage.md`.
- Oct 9–10 passes (Loops 12–16) were judged live with a single vote; the 2-of-3 votes were not stored before
  `0d0997e` (Oct 11). They were re-judged offline on Oct 11 with the current judge (2 votes each) and all counted
  ones are 2/2. Raygun and StatusCake were re-judged earlier on Oct 11 (2/2).
- Oct 11 passes store their votes in `page_verdict.votes` / `votes_yes` in study.json.
- Bugsnag: signup goes through the parent company's auth domain; counted under the parent-company auth rule.

## Counted passes

| # | site | date (PT) | driver model | study_id | judge votes | signup_verified | GCS prefix | note |
|---|---|---|---|---|---|---|---|---|
| 1 | heyform.net | 2026-10-07 14:33 | Gemini 2.5 Flash | `d4daacf8-6c1d-4f9e-b285-4ed2432f99a7` | 3/3 (offline judge3, Oct 7–8 gate) | True | `mcp-test` |  |
| 2 | kwesforms.com | 2026-10-07 14:42 | Gemini 2.5 Flash | `43b91a19-803b-4ecb-8ff3-bb5bdb072409` | 3/3 (offline judge3, Oct 7–8 gate) | True | `mcp-test` |  |
| 3 | databuddy.cc | 2026-10-07 14:36 | Grok Bot MCP client | `02c4d7d6-0b71-415c-8b3e-c6f806ec26db` | 3/3 (offline judge3, Oct 7–8 gate) | True | `mcp-test` | Re-judged 3/3 at 3:00 PM PT Oct 7. |
| 4 | litlyx.com | 2026-10-07 14:54 | Gemini 2.5 Flash | `9f7715a3-3a4e-4b2e-93f8-7b5cb9c28a36` | 3/3 (offline judge3, Oct 7–8 gate) | True | `mcp-test` | 3/3 after the c81f4ff judge fix (Oct 7). The Grok Bot client run 5f319520 also re-judged 3/3; not counted twice. |
| 5 | aptabase.com | 2026-10-08 13:06 | Gemini 2.5 Flash | `16984f5f-e872-4a1a-be1f-edf0685e51b7` | 3/3 (offline judge3, Oct 7–8 gate) | True | `mcp-test` |  |
| 6 | withcabin.com | 2026-10-08 13:06 | Gemini 2.5 Flash | `b2b22814-7f0f-4b0b-b228-d030f4bf7860` | 3/3 (offline judge3, Oct 7–8 gate) | True | `mcp-test` |  |
| 7 | paperform.co | 2026-10-09 11:22 | Gemini 2.5 Flash | `c69dd13c-2573-44aa-a78e-30c49806e737` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 8 | plausible.io | 2026-10-09 11:03 | Gemini 2.5 Flash | `baef6381-93f1-480b-bbc3-c87784c356a6` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 9 | resend.com | 2026-10-09 11:03 | Gemini 2.5 Flash | `63d14215-7d47-44ee-a84b-28c8d68b2f1f` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 10 | app.frill.co | 2026-10-09 11:28 | Gemini 2.5 Flash | `c6a0d668-be31-4ab4-8a75-a0ea7d8d27d4` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 11 | updown.io | 2026-10-09 11:42 | Gemini 2.5 Flash | `262b3bb5-9132-4ae1-9e2d-e36b6f15534d` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 12 | hyperping.io | 2026-10-09 11:43 | Gemini 2.5 Flash | `a40d7428-fd2a-4502-9b3f-a6802c994807` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 13 | openstatus.dev | 2026-10-09 11:48 | Gemini 2.5 Flash | `3c5086e2-ee41-40f0-b9bd-fef14e1ee964` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 14 | axiom.co | 2026-10-09 11:57 | Gemini 2.5 Flash | `0db5a554-b7e4-43cf-9a66-08a4d9d736ab` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 15 | uptimerobot.com | 2026-10-09 12:01 | Gemini 2.5 Flash | `c2a9abf3-cc38-4f5d-a4d3-05cd83e7ef75` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 16 | honeybadger.io | 2026-10-09 12:04 | Gemini 2.5 Flash | `6a5b3563-5e96-4708-9c2a-69b392ed28f1` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 17 | sleekplan.com | 2026-10-09 12:13 | Gemini 2.5 Flash | `3e7d7b4d-ffa7-44e5-b585-fb081a816bc7` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 18 | productlane.com | 2026-10-09 12:14 | Gemini 2.5 Flash | `963db0cf-2bb7-47f9-82af-1828fe0b8994` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 19 | logsnag.com | 2026-10-09 12:21 | Gemini 2.5 Flash | `6179c6d6-079b-4993-8061-2813074c3c59` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 20 | fider.io | 2026-10-09 12:21 | Gemini 2.5 Flash | `307100f4-e717-4d52-93b7-0cdb1bead074` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 21 | console.xata.io | 2026-10-09 12:27 | Gemini 2.5 Flash | `8fbb98c3-9253-4d55-a560-2304a8ca5e57` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 22 | uptimia.com | 2026-10-09 16:43 | Gemini 2.5 Flash | `92c7ca25-207f-46a2-b550-f8386c6f3e8e` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 23 | bugsnag.com | 2026-10-10 09:59 | Gemini 2.5 Flash | `e2a8e2af-4d69-45b1-96f7-fe217e012822` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` | Signup is on the parent company (SmartBear) auth domain; counted under the parent-company auth rule. |
| 24 | changelogfy.com | 2026-10-10 10:09 | Gemini 2.5 Flash | `fb3ef2da-c736-43d9-bf90-60388adc77c9` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 25 | moosend.com | 2026-10-10 10:13 | Gemini 2.5 Flash | `43935abb-a499-4801-9b21-c1c76a5c711c` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 26 | raygun.com | 2026-10-10 14:04 | Gemini 2.5 Flash | `99dcfb6e-6a7d-43de-87ad-9ca7d3629b27` | 2/2 (offline re-judge Oct 11, rejudge-oct11.json) | True | `mcp-test-vm` | Re-judged 2/2 on Oct 11 (rejudge-oct11.json, 0d0997e judge). |
| 27 | marker.io | 2026-10-10 14:15 | Gemini 2.5 Flash | `e14e93e6-a328-40f5-9f13-4ae23406b93f` | 2/2 (offline re-judge Oct 11, rejudge-oct11b.json) | True | `mcp-test-vm` |  |
| 28 | statuscake.com | 2026-10-10 14:20 | Gemini 2.5 Flash | `f349caaf-a7ad-4446-a2d1-497c10d9918c` | 2/2 (offline re-judge Oct 11, rejudge-oct11.json) | True | `mcp-test-vm` | Re-judged 2/2 on Oct 11 (rejudge-oct11.json, 0d0997e judge). |
| 29 | hetrixtools.com | 2026-10-11 06:06 | Gemini 2.5 Flash | `6c0c60d8-a2dd-49d9-9b66-abf67ec6eea5` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 30 | openreplay.com | 2026-10-11 07:15 | Gemini 2.5 Flash | `a084b01e-0847-44e3-ab78-00a9822e80ba` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 31 | checklyhq.com | 2026-10-11 07:32 | Gemini 2.5 Flash | `8e2a2997-40fe-40b5-b78e-17cbf55a9752` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 32 | mouseflow.com | 2026-10-11 07:49 | Gemini 2.5 Flash | `c8e5e7cd-4a29-4cee-85c7-70a0f4ca3d11` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 33 | oneuptime.com | 2026-10-11 08:04 | Gemini 2.5 Flash | `8263dec0-af68-41fa-b8ef-4c2f748d4801` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 34 | mixpanel.com | 2026-10-11 08:21 | Gemini 2.5 Flash | `4df4cb04-66b1-4d4d-a7cb-8bc88cec9e22` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 35 | sentry.io | 2026-10-11 08:32 | Gemini 2.5 Flash | `23764476-bdcc-4f96-8c08-21f2ec1ae195` | 2/2 (live, stored in study.json) | True | `mcp-test-vm` |  |
| 36 | healthchecks.io | 2026-10-12 12:40 | Gemini 2.5 Flash | `65ab825b-aedc-4b7a-902c-97eacc0ebdcc` | 2/2 (live, stored in study.json) | True | root `mvp_studies/` | Retest; earlier runs (e.g. 33b9c7cf) failed the proof gate and were never counted. Passes with the check_token path-token proof (93e8568). |
| 37 | appsignal.com | 2026-10-12 12:44 | Gemini 2.5 Flash | `6c416889-6a1a-4d98-8857-0ba085b5c5a4` | 2/2 (live, stored in study.json) | True | root `mvp_studies/` | New product. Ended on the in-app "goals" setup page. |
| 38 | app.glitchtip.com | 2026-10-12 12:45 | Gemini 2.5 Flash | `a4322904-74f3-4054-affa-616d533732b5` | 2/2 (live, stored in study.json) | True | root `mvp_studies/` | New product. |
| 39 | my.trackjs.com | 2026-10-12 12:48 | Gemini 2.5 Flash | `806c1bef-fa65-4b5f-8f11-17da7bf4a82d` | 2/2 (live, stored in study.json) | True | root `mvp_studies/` | New product. |

## Not counted

| site / study | reason |
|---|---|
| app.koyeb.com `17e0f8ac-ea11-427f-bf35-173172929585` (Oct 9) | Proof passed, but the Oct 11 re-judge voted 0/2: the run ended on the "organization name" onboarding step. It was a pass only through the old server override; fails the current bar. |
| typefully.com `0c771645-db21-494c-b59d-ce02c0ffa3ad` (Oct 10) | Proof passed and judges saw a signed-in page, but the Oct 11 re-judge voted goal 0/2. It was a pass only through the old server override; fails the current bar. |
| Loops 1–4, Oct 7: formspark, plunk, formcarry, tinylytics, umami, emailoctopus, goatcounter, getinsights, basin, pirsch, buttondown, hyvor | Judged by a single vote before the 2-of-3 rule; not re-judged under the current bar. |
| measuremy, yedric, pulsepanda | Outreach sites, excluded. |
| typebot, getform (Forminit) | Proof failed (`opened_on_product`). |
| Loggly `200c7c03` | False verify (false pass). |
| Better Stack `2c54ee69` | Billing wall after verify. |
| Smartlook `af3ebae9` | Proof passed only via the server-fact override; the run ended on "Final step to create your account" (gave_up), not signed in. |
| Hund, Pingdom, NodePing, Inspectlet `b3a67489`, LogRocket, Lucky Orange | No verify mail received. |
| Healthchecks `33b9c7cf` | Failed the proof gate. |
| Fabform, FormBold | FabForm sends no verify mail; FormBold's /dashboard never paints. Loop 5 passes were false positives. |
| litlyx Grok Bot client run `5f319520` | Also 3/3, but litlyx is counted once (`9f7715a3`). |
| Smartlook `584e11fc` (Oct 12 retest) | Verified, but stuck on the "Your role" custom dropdown of the account form: label-only select did not commit the value, then the model typed the zip into the country field until the step cap. Judge 0/2. Open (server select on this widget). |
| Amplitude `888b9d01` (Oct 12, paid captcha on) | reCAPTCHA v2 token solved and injected 3× (CapSolver, $0.0024) but Amplitude still rejected the submit. Site-side; parked. |
| Atatus `7f79275c` (Oct 12) | Reached the dashboard, but the link ranker opened a Calendly demo link from the welcome mail instead of the verify link, so signup_verified=false. Fixed in 7ee3cc7 (demo-booking hosts are never verify links); retest pending. |
| Showcase matrix study (approved Oct 12) | Not a never-seen pass; never counted here. |
