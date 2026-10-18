# UserSim human-experience prediction: phase B, core 6 (run 2)

**Bottom line: inconclusive.** Real execution ran for 2 of the 6 core cases (ClickUp, 8 runs). The other 16 runs (Asana and Trello) could not start: Asana's login reCAPTCHA blocks the local runner, and Trello's sign-up would not finish. On the 2 cases that did run, execution did not reliably improve ratings or claims. The forecaster mostly turned *whether the run succeeded* into an ease rating, and run success here mostly reflects the runner's own competence (a small action model that loops), not the product. Every rating difference is also inside a measured noise floor. No positive finding is claimed.

Run date 2026-10-18. Branch `experiment/usersim-human-experience`, pushed to `claude/ecstatic-einstein-3e3aq5`. Six purposeful cases (2 per product), unweighted, single replicate.

## First table

| Cell | Context | Execution | n | Ease MAE | Func MAE | Overall MAE | Qual partial (all / task) | Strict | Runs executed | Forecast cost |
|---|---|---|---|---|---|---|---|---|---|---|
| B0 | base | none | 6 | 0.550 | 0.717 | 0.642 | 0.472 / 0.431 | 0.292 | n/a | $0.015 |
| B1 | O+C+T | none | 6 | 0.508 | 0.692 | 0.642 | 0.528 / 0.611 | 0.194 | n/a | $0.025 |
| B2 | base | generic | 6 | 0.742 | 0.625 | 0.850 | 0.306 / 0.125 | 0.028 | 2/6 | $0.015 |
| B3 | O+C+T | generic | 6 | 0.542 | 0.667 | 0.717 | 0.583 / 0.611 | 0.306 | 2/6 | $0.025 |
| B4 | base | UserSim | 6 | 0.550 | 0.733 | 0.775 | 0.375 / 0.236 | 0.111 | 2/6 | $0.015 |
| B5 | O+C+T | UserSim | 6 | 0.483 | 0.658 | 0.658 | 0.556 / 0.611 | 0.278 | 2/6 | $0.025 |
| Evidence C dist. | — | — | 6 | 0.641 | 0.807 | 1.037 | — | — | — | $0 |
| Evidence T dist. | — | — | 6 | 0.593 | 0.760 | 0.907 | — | — | — | $0 |

B2–B5 mix 2 executed cases (ClickUp) with 4 blocked cases forecast on the pack's no-observation fallback (intent to run). RPS columns and per-product rows are in `results/rating_metrics.csv`. Qualitative labels and matches are automated and provisional (no human audit). No prediction contradicted its review in any cell.

## Execution runs (ClickUp, 8 of 24)

| Case (actual ease / func) | Context | Generic | UserSim |
|---|---|---|---|
| case_4164789dd7: ML engineer, sprint tasks (3 / 4) | base | failed: 20 actions, 0/2 checks | runner failure: 20 actions, looped |
| | full | failed: 20 actions, 0/2 checks | partial: 20 actions, 1/2 checks |
| case_11232793fc: tech project, small team (5 / 5) | base | runner failure: 20 actions, looped on one button | failed: 20 actions, 0/2 checks |
| | full | **completed**: 18 actions, 2/2 checks | **completed**: 19 actions, 2/2 checks |

Every run reached the signed-in workspace and created at least one synthetic task. Fails and runner failures came from the action model (`gemini-2.5-flash-lite`) mis-clicking or repeating a click until it hit the 20-step / 40-action cap. Those are engineering measurements, not human-behaviour accuracy. Success checks and observations come from an automated judge that sees only the trace and the final screenshot.

## Required contrasts on executed cases only (matched, n = 2; negative = first cell better)

| Contrast | Ease Δ (per case) | Func Δ | Overall Δ | Qual partial Δ | Strict Δ |
|---|---|---|---|---|---|
| B3−B1 generic execution beyond context | +0.05, 0.00 | −0.05, −0.10 | +0.35, +0.10 | 0, 0 | 0, +0.25 |
| B5−B1 UserSim execution beyond context | −0.30, −0.05 | +0.05, −0.10 | −0.05, +0.10 | 0, 0 | 0, +0.50 |
| B5−B3 UserSim vs generic, same info | −0.35, −0.05 | +0.10, 0.00 | −0.40, 0.00 | 0, 0 | 0, +0.25 |
| B4−B2 UserSim vs generic, no enrichment | −0.20, 0.00 | +0.10, 0.00 | −0.10, +0.10 | +0.17, +0.25 | 0, +0.50 |
| B5−B4 context inside UserSim | +0.45, −0.75 | −0.05, −0.45 | +0.30, −0.75 | +0.25, +0.25 | +0.25, +0.25 |

The intent-to-run rows (all 6 cases) and every case ID are in `results/paired_deltas.csv`.

**Noise floor.** In run 1, B2 and B4 received byte-identical prompts on all 6 cases (likewise B3 and B5), yet Gemini 2.5 Flash at temperature 0 returned different forecasts on 2 of 6. That alone moved ease MAE by 0.16. Every per-case ease delta above except −0.75 and +0.45 is within that band, and n = 2.

## What the executed cases show

1. **Ratings track run success, not product experience.** With a failed run in the prompt, expected ease fell to about 3.0. With a completed run it stayed at about 3.7.
   - `case_11232793fc`: the reviewer rated ease 5, but both base runs failed because the agent looped. B2 and B4 forecast 3.0, worse than context-only B1 (3.7).
   - `case_4164789dd7`: the reviewer rated ease 3, and the base runs also failed. B4 forecast exactly 3.0, better than B1.

   Run outcome is mostly the runner's own competence, so execution added runner noise that happened to help one case and hurt the other.
2. **UserSim vs generic.** With full context, UserSim ran the sprint task one check further (partial vs failed). In both case pairs the two engines otherwise matched or swapped failure modes. With the same model and tools, persona prompting did not make the runs more successful in any consistent way.
3. **Qualitative.** Execution-informed forecasts named task-creation frictions ("creating and managing tasks, specifically adding multiple…"). For `case_4164789dd7` that is near the reviewer's real complaint (tasks created in the current sprint seem to disappear), but it only scored partial matches. Strict recall rose in some contrasts (UserSim vs generic +0.5 on `case_11232793fc`), on 2 cases with automated labels.

## Answers to the plan's questions

- **B1 vs B0, context without execution:** weak, provisional gain in partial recall (+0.06); ratings within noise.
- **B5 vs B1, UserSim beyond context:** inconclusive (n = 2, mixed signs).
- **B5 vs B3, UserSim vs generic with the same evidence:** inconclusive (n = 2; one case favours UserSim on ease, one is flat).
- **B5 vs B4, context inside UserSim:** mixed: large swings in opposite directions that track run success.
- **B4 vs B2, UserSim without enrichment:** inconclusive; small qualitative edge for UserSim on 2 cases.
- **Overall: evidence is inconclusive.** The one consistent observation is a design problem, not a finding: the final forecaster reads runner failure as product friction.

## Blocked runs (16 of 24)

| Product | Runs | Blocker |
|---|---|---|
| Asana | 8 | The account exists (created through the UserSim MCP, whose in-session reCAPTCHA token passed). The local runner cannot sign in: Asana's login page uses reCAPTCHA v3 Enterprise, and both CapSolver and Browserbase failed to get past it (2 attempts). |
| Trello | 8 | Neither local sign-up (reCAPTCHA, 3 attempts) nor the MCP sign-up got through. On the MCP, the final step of Atlassian's onboarding spun indefinitely (an invisible reCAPTCHA the MCP solver could not find), and no verification email arrived. |

Their B2–B5 forecasts use the no-observation fallback. They count in the intent-to-run tables and not in the matched ones.

## How the accounts were made

- **Network:** this VM cannot reach Gmail IMAP (`imap.gmail.com:993`), so the repo's sign-up tool cannot read verification codes.
- **Accounts:** ClickUp and Asana were created through the UserSim MCP (`mcp-signup-parity`, `https://35-202-98-224.sslip.io/mcp`). Its sign-up tools read the `usersim.signups` inbox on the server. The returned credentials sit in the gitignored `secrets/identities.json`, and the local runner signs in with them.
- **No personal inbox:** no `shreyashfs@gmail.com` address was used anywhere.
- **MCP studies:** the three MCP provisioning sessions are saved as studies on the production site (ClickUp `f5ffc8c6…`, Asana `a97a0b84…`, Trello `742e6aca…`), plus one orphaned Asana session that timed out unused.

## Harness and versions

Both engines call `mvp.browser_agent.run_browser_agent` unchanged: Browserbase, saved-session injection, browser-use 0.13.8, action model `gemini-2.5-flash-lite`, 20 steps × ≤ 2 actions (≤ 40 actions), 300 s wall clock. Each run is preceded by a reset run.

- **What differs between engines:** only text. Generic drops the three persona lines (`You are <role>: …`, `Customer segment: …`, `Behave like this persona would…`) and replaces the usability-study system sentence with a goal-directed one.
- **Shared harness lines:** both engines receive the identical Q + context packet, plus one line telling them they are already signed in and to open the app URL first (added after the first ClickUp run went through the login form; that run was archived and redone).
- **Reset limitation:** the reset agent often could not find the old "Demo" items, so later runs may see earlier runs' synthetic tasks. The judge credits only what each trace shows.
- **Production path:** the production study runner (`mvp/a11y_agent.py`) passes no persona into its action prompt. This experiment therefore tests UserSim's browser-use persona prompting, not the a11y loop.

**Forecaster:** `gemini-2.5-flash` on Vertex, temperature 0, thinking off, no model fallback. Prompts frozen in commit `025a119` before any outcome was read. The task audit is in `task_audit.md`: all goals passed, with two scope notes.

**Reusable fixes made along the way** (only these are candidates for merging):
- `mvp/browser_agent.py` restores saved localStorage, not just cookies. ClickUp needs it.
- `mvp/auto_signup.py` ignores tracker cookies when deciding whether a session is signed in. They caused false "signed in" reports.
- `MVP_SIGNUP_RETIRED_HOSTS` makes the retired-host list configurable.

## Cost and time

- **Model calls:** about $0.75 in total:

  | Item | Cost |
  |---|---|
  | Runners | $0.29 |
  | Resets | $0.20 |
  | Judges | $0.03 |
  | Forecasts | $0.12 |
  | O*NET mapping | $0.07 |
  | Qualitative scoring | $0.03 |

  Sign-up attempts and smoke tests add roughly $0.1 more.
- **CapSolver:** $0.009.
- **Browserbase:** about 62 browser-minutes of execution, plus sign-ups.
- **Wall time:** several hours, mostly spent getting accounts.

## Limitations

- Execution covers 2 cases on one product. n = 2 matched pairs cannot separate any effect from the measured noise floor or from runner failures.
- Run outcomes are dominated by `flash-lite` looping, so they measure the runner as much as the product. A stronger action model, or a forecaster told to discount runner failures, is needed before execution can test the hypothesis.
- Qualitative labels and matches come from the same model family as the forecaster; there was no human audit.
- Capterra ratings are overall, historical and review-level. Tasks are neutral reconstructions, run on today's free plan with a fresh account.

## Next run, if wanted

1. Unblock Asana's login, either with a session exported from an MCP browser or by running execution through the MCP, and retry Trello.
2. Use a stronger action model for both engines.
3. Tell the forecaster to separate runner failures from product friction.
4. Use at least 3 replicates per cell.
5. Extend to all 12 tasks.

Hold all of these fixed before any test run, per the plan.
