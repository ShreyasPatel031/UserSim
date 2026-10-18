# UserSim human-experience prediction — phase B, core 6 (first run)

**Bottom line: inconclusive. No execution run could start, so this run cannot answer whether UserSim or generic execution helps.** All 24 browser runs were blocked by product access (no usable signed-in session on Asana, Trello or ClickUp). The four execution cells therefore ran as the pack's *intent-to-run* fallback: the same forecast prompt plus a "run blocked, no observations" note. Context-only cells (B0, B1) are complete. The run also measured a noise floor larger than every context effect observed.

Run date 2026-10-18. Branch `experiment/usersim-human-experience`, pushed to `claude/ecstatic-einstein-3e3aq5`. All figures are on 6 purposeful cases (2 per product), unweighted, single replicate.

## First table

| Cell | Context | Execution | n | Ease MAE / RPS | Func MAE / RPS | Overall MAE | Qual partial recall (all / task) | Strict recall | Disagree | Unconfirmed | Blocked runs | Forecast cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | base | none | 6 | 0.550 / 0.091 | 0.717 / 0.123 | 0.642 | 0.472 / 0.431 | 0.292 | 0.00 | 0.75 | n/a | $0.015 |
| B1 | O+C+T | none | 6 | 0.508 / 0.091 | 0.692 / 0.118 | 0.642 | 0.528 / 0.611 | 0.194 | 0.00 | 0.67 | n/a | $0.025 |
| B2 | base | generic (blocked) | 6 | 0.708 / 0.111 | 0.558 / 0.107 | 0.825 | 0.319 / 0.181 | 0.111 | 0.00 | 0.80 | 6/6 | $0.014 |
| B3 | O+C+T | generic (blocked) | 6 | 0.525 / 0.091 | 0.708 / 0.124 | 0.708 | 0.542 / 0.528 | 0.264 | 0.00 | 0.64 | 6/6 | $0.026 |
| B4 | base | UserSim (blocked) | 6 | 0.550 / 0.095 | 0.650 / 0.112 | 0.750 | 0.319 / 0.181 | 0.111 | 0.00 | 0.83 | 6/6 | $0.015 |
| B5 | O+C+T | UserSim (blocked) | 6 | 0.533 / 0.089 | 0.683 / 0.116 | 0.717 | 0.514 / 0.528 | 0.194 | 0.00 | 0.67 | 6/6 | $0.025 |
| Evidence C distribution | — | — | 6 | 0.641 / 0.119 | 0.807 / 0.148 | 1.037 | — | — | — | — | — | $0 |
| Evidence T distribution | — | — | 6 | 0.593 / 0.106 | 0.760 / 0.146 | 0.907 | — | — | — | — | — | $0 |

Qualitative: mean over benefit/friction types of one-to-one match recall against claims extracted from the hidden review. "Partial" counts scores of 1 or 2; "strict" counts 2 only. Labels and matches are automated and provisional (no human audit).

## Noise floor (read this before any contrast)

B2 and B4 received **byte-identical prompts** in all 6 cases (same packets, same blocked-run note; the prompt hash in `predictions.jsonl` matches), and so did B3 and B5. Gemini 2.5 Flash at temperature 0 still returned different rating vectors in 2 of 6 cases for each pair. So:

- **B4−B2 = −0.158 ease MAE** and **+0.092 functionality MAE** are *pure model nondeterminism*.
- **B5−B3** (−0.025 functionality, −0.028 qualitative) is likewise noise.

The largest context effect observed (B1−B0 ease −0.042) is about a quarter of the noise gap between identical prompts. With n=6 and one replicate, no rating contrast here can be separated from noise. A future run needs several replicates per cell.

## Required contrasts (intent-to-run, n=6 paired; negative = first cell better)

| Contrast | Question | Ease Δ | Func Δ | Qual partial Δ | Read |
|---|---|---|---|---|---|
| B1−B0 | Context without execution | −0.042 (2 better / 2 worse) | −0.025 (2/1) | +0.056 (3 better / 2 worse) | Within noise |
| B3−B1 | Generic execution beyond context | +0.017 | +0.017 | +0.014 | No execution happened; only the blocked note differs |
| B5−B1 | UserSim execution beyond context | +0.025 | −0.008 | −0.014 | Same: not an execution test |
| B5−B3 | UserSim vs generic, same info | +0.008 | −0.025 | −0.028 | Identical prompts, so this is noise |
| B4−B2 | UserSim vs generic, no enrichment | −0.158 | +0.092 | 0.000 | Identical prompts, so this is noise |
| B5−B4 | Context inside UserSim | −0.017 | +0.033 | **+0.194** (4 better / 1 worse) | Context effect on blocked-run prompts |
| (B5−B4) vs (B1−B0) | Interaction | ease −0.017 vs −0.042 | | qual +0.194 vs +0.056 | Not interpretable: no execution |

Matched-successful-run analyses have **n = 0** for every execution contrast (`paired_deltas.csv`, `analysis=matched_successful_runs` has no rows).

Takeaways the data can support, weakly:
- **Ratings.** No source or cell shows a rating gain outside the noise floor. Every model cell beats the two evidence-review baselines on ease and functionality MAE (for example B0 ease 0.550 vs T distribution 0.593), but by margins inside the noise.
- **Qualitative.** Adding O+C+T raised partial recall in all three paired comparisons (B1−B0 +0.056, B3−B2 +0.22, B5−B4 +0.19), with the larger gains where the base prompt also carried a blocked-run note. Strict (specific) recall did not rise reliably (B1 0.194 < B0 0.292). Reviews mostly made frictions broader, not more specific. No predictions contradicted their reviews.

## Answers to the plan's conclusion question

- **Context helps:** weak, provisional sign for qualitative partial recall; none for ratings beyond noise. *Inconclusive.*
- **Generic execution helps:** *not tested* (0/12 runs executed).
- **UserSim adds value:** *not tested* (0/12 runs executed).
- **Overall:** **evidence is inconclusive.** No positive finding is claimed.

## Three illustrative cases

1. **Where execution was the only route: `case_4164789dd7` (ClickUp, Machine Learning Engineer).** The hidden review's main friction is task-specific: tasks created directly in the current sprint "just disappear", so the reviewer creates them in the backlog and moves them. No context cell predicted this. B0 guessed generic "steep learning curve" and integration gaps (0 matches). B1 got two broad partial matches ("overwhelming at first", "confusion finding items"). This is exactly the kind of claim a live run of the frozen task could have observed or failed to observe. The run was blocked, so the question stays open.
2. **Evidence reviews helped a little: `case_140855addc` (Trello, Sales Manager).** The reference friction is missing automation (follow-up emails, detailed reports) and weak contact management. B0 matched "reporting less robust" (partial). B1 matched "struggle with setting up automation… as other users have found" (partial), lifted from target evidence reviews. Neither reached a specific match, and both put ease at 4–5 with 80% probability (actual ease 4, functionality 3).
3. **Context shifted ratings the wrong way: `case_f692c7793d` (Asana, Sr. HR Specialist).** Actual ease 4, functionality 4. Adding reviews moved ease probability toward 5 (P(5) from 0.25 to 0.40), worsening the ease error. Qualitatively, B1 matched both reference frictions (features confusing at first, wish the interface were cleaner) at partial level; B0 matched one.

## Blocked runs (24 of 24)

| Product | Runs | Exact blocker |
|---|---|---|
| Asana | 8 | Account created and signed in (`usersim.signups+asana@gmail.com`), but the session capture failed twice (`BrowserContext.storage_state: … closed`). The saved state's 88 cookies hold no Asana login cookie, and both runner smoke tests landed on `app.asana.com/-/login`. |
| Trello | 8 | Atlassian sign-up blocked by reCAPTCHA v3 Enterprise (no CapSolver key, so `host_not_paid` in the captcha ledger). A second attempt ended not signed in after 23 steps. |
| ClickUp | 8 | No test account: the repo marks `clickup.com` as retired (live account on the base mailbox; credentials not on this VM). Overriding that rule was not permitted in this session. |

No execution trace exists for any scored run. The two smoke-test traces (Asana reset task, not a test case, both engines) live under `mvp/runs/hx_20261018/smoke__*` (gitignored, local to this VM) and only confirm the harness and the login wall.

## Engine difference (as implemented, ready for the next run)

Both engines call `mvp.browser_agent.run_browser_agent` unchanged: same Browserbase session, saved-cookie injection, browser-use 0.13.8 Agent, action model `gemini-2.5-flash-lite`, tools, 20 steps × ≤2 actions (≤40 actions) and a 300 s wall clock. They also receive the identical task packet (Q plus the permitted context). Generic differs **only** in text:
- removes three task lines: `You are <role>: <recorded facts>`, `Customer segment: …`, and `Behave like this persona would — note confusion, pricing concerns, and UX friction.`;
- replaces the system sentence `You are a real user in a usability study, not an optimizer. Prefer obvious UI paths; comment on clarity and trust.` with `You are a web agent completing the task efficiently and accurately.`

The smoke test confirmed the swap on the actual serialized prompts. Same model and tools, so a future result would isolate persona/simulation prompting.

**Note on "existing UserSim":** the production study path (`mvp/a11y_agent.py`, `complete_task_on_page`) passes **no persona into its action prompt**; the persona is used only for sign-up. The persona-conditioned runner is the browser-use path used here. Phase B therefore tests UserSim's persona prompting, not the a11y loop.

## Limitations

- n=6 purposeful cases, one replicate; the measured temperature-0 nondeterminism exceeds every observed effect.
- Capterra ratings are review-level overall experience. Tasks are neutral reconstructions (audit in `task_audit.md`: all pass, two scope notes). Today's product pages may differ from the reviewer's version.
- Qualitative reference claims and matches come from the same model family as the forecaster (Gemini 2.5 Flash). They are automated and provisional; no human audit (the pack asks for at least 12 audited reviews).
- Added context adds tokens (B1 ≈ 3× B0 prompt: 7.7k vs 2.5k input tokens); gains cannot be separated from length.
- Development rows were not used to tune the qualitative codebook in this run. Prompts were frozen in commit `025a119` before any outcome was read.

## Provenance

- Source: FreshCrawl Capterra snapshot, sha256 `867bea84…436a` verified. Splits: 36 test, 18 development, 90 evidence; disjoint.
- Context: offline frozen packets (no context service). D pages captured 2026-10-18 (asana.com, /features; trello.com, /tour; clickup.com, /features), testimonials and adoption numbers stripped. O*NET 31.0 (occupation, task statements, task ratings), mapping by model from P only. C/T are the first 10 evidence IDs per product; C has target-naming sentences removed (1 sentence per Asana case, 0 otherwise). Hashes and token counts are in `packets/manifest.json`.
- Forecaster: `gemini-2.5-flash` on Vertex, temperature 0, thinking off, no model fallback (`llm.py`). Prompts in `results/prompts/` (gitignored: they quote review prose).
- Cost: model calls $0.22 (forecasts $0.118, O*NET mapping $0.068, qualitative $0.032), plus browser-use calls during sign-up and smoke tests (≈$0.05 measured for smoke; sign-up runs not metered) and about 45 Browserbase session-minutes. $0 CAPTCHA spend. Wall time about 1 h 50 min.
- Annotation audit status: goal audit by the evaluating agent (not a human); qualitative labels automated, unaudited.

## Files

`results/predictions.jsonl` (36), `results/rating_metrics.csv` (pack scorer), `results/qualitative_metrics.csv`, `results/paired_deltas.csv` (case IDs and complete-case n per contrast/analysis), `results/evidence_baselines.csv`, `results/summary.json`, `results/execution/*.json` (24 blocked-run records), `results/qualitative_reference_labels.json` (spans verified against review text; gitignored), `results/qualitative_matches.json`, `packets/manifest.json`, `task_audit.md`, code `build_packets.py`, `predict.py`, `run_exec.py`, `score_phase_b.py`, `llm.py`.

Commands:
```
cd experiments/human_experience
python -I pack/scripts/prepare_reviews.py           # verifies checksum, materializes splits
python build_packets.py --all-12
python predict.py --cells B0,B1 --cases core
python run_exec.py --product Asana                   # once a signed-in session exists
python predict.py --cells B2,B3,B4,B5 --cases core
python score_phase_b.py
```

## To unblock the execution cells

1. Asana: re-capture the session so the saved state holds the login cookie (the account exists). `auto_signup` currently loses it when the browser closes before `storage_state`.
2. Trello: add `MVP_CAPTCHA_API_KEY` (CapSolver) and allow paid solving for trello.com.
3. ClickUp: approve a sign-up with the VM's `usersim.signups` mailbox, or supply a session for the existing account.

Then delete `results/execution/` and the B2–B5 rows, re-run, and use ≥3 replicates per cell so effects can be told apart from the noise floor. Only reusable fix proposed for production: the Asana storage-capture race in `mvp/auto_signup.py`. Nothing else from this branch should merge.
