# Parallel arms: OM2W harness experiments

Baseline to beat: `full100_mistral_mistral-small-2603_m33_stage1_fleet.json`
— **6/50 scored = 12.0%**, 88 tasks (12 lost to Spot preemption), $5.57 all-in.

Reference point: the official `browser-use` + GPT-4o entry on the OM2W leaderboard
scores **30.0% human / 26.0% WebJudge at a 25-step budget** — fewer steps than our 33.
So our deficit is not the step budget. Budget is *masking* our other changes, not causing
the gap.

## Read this before designing an arm

Three things we assumed were missing are **already in browser-use 0.13.8**. Do not
rebuild them:

| Assumed gap | Reality in 0.13.8 |
|---|---|
| Overwrite-before-type (Ctrl+A) | `InputTextAction.clear` defaults to `True` |
| `select_option` bypassing the AX tree | `select_dropdown` + `dropdown_options` actions; clicking a `<select>` auto-returns options; combobox settle delay |
| Loop detection | `ActionLoopDetector`, `loop_detection_enabled=True`, 20-step window; plus stagnant-page nudge at 5 |
| Datepicker awareness | DOM serializer detects jQuery/Bootstrap/AngularJS pickers and extracts `expected_format` |

Two claims from the literature that are weaker than they look:

- Invariant Labs' WebArena 30%→46% **also swapped GPT-4o for Claude-3.5-Sonnet in the
  same run**. It is not a clean widget-fix delta.
- Loop detection alone is not expected to help: 55.8% of failed traces end in a loop, but
  the loops are distributed evenly (48–67%) across every underlying mechanism. Loops are a
  symptom. Bundle loop work with a mechanism fix or it just fails faster.

## Shared protocol (every arm must follow this)

- **Task set**: the same 100-task set, all arms. Never A/B on full10 — at n=8 the standard
  error is ±17 points, which is what made the last two sessions look like progress.
- **Step budget: 60 in every arm, including baseline.** 93% of our failures died at the old
  33 cap and 3 of 6 successes finished *at* it. Until this moves, every arm measures the cap.
- **Metric**: `success_rate_scored` (excludes `BLOCKED` and `JUDGE_ERROR`). Always report
  `n_scored` alongside it — a rate over a shrinking denominator is not an improvement.
- **Judge**: unchanged across arms. Our judge is not comparable to the official WebJudge, so
  treat all numbers as internal-relative only, never as leaderboard-comparable.
- **Report**: `success_rate_scored`, `n_scored/n`, the `by_status` split, the fraction hitting
  the step cap, and $ cost.
- Expect ~$10–12 per arm at budget 60. GCP compute is under $1; tokens are 91% of spend.

## Arms

### arm-0 — budget only (control)
Budget 60, `max_history_items=6` (matches the 12% run), `max_actions_per_step=2`,
`allowed_domains` on. Run **twice** with different seeds for an error bar.

```bash
export BROWSER_USE_ARM=0 BROWSER_USE_FAST=0
# budget defaults to 60 via CAPABILITY_MAX_ACTIONS
```

### arm-1 — uncapped text history  *(implemented)*
`max_history_items: 6 → None`. See `experiments/arm1_uncapped_history.md`.

```bash
export BROWSER_USE_ARM=1 BROWSER_USE_FAST=0
```

### arm-2 — action space width and domain fencing
`max_actions_per_step: 2 → 4`, `allowed_domains` off by default.

```bash
export BROWSER_USE_ARM=2 BROWSER_USE_FAST=0
# re-enable domains: BROWSER_USE_ALLOWED_DOMAINS=1
```

### arm-3 — self-verification gate before `done`
Note `use_judge` is **not** this. It calls `_judge_and_log()` *after* `is_done()`, so it
logs a verdict but never blocks completion or triggers a retry. A real gate needs to be
built: on `done`, re-verify every task constraint against the live page, and if verification
fails, reject the `done` and let the agent continue.

Webwright and Operator both treat this as load-bearing, and it targets the documented
"missing commit" mode (11.6% of failures — form filled, Submit never clicked). Also add the
post-filter assertion here: verify a filter is visibly reflected in results before
proceeding, since the official rubric scores an off-by-one range the same as doing nothing.

### arm-4 — code as the action space  *(separate track, largest build)*
Let the agent write Playwright/Python instead of predicting one primitive click at a time.
Highest ceiling by a wide margin: Webwright reached **86.7%**, the top open-harness score,
and browser-use's own writeup calls this switch "the biggest improvement." A date range or a
full form becomes one compact program instead of a 15-step chain that accumulates error.

Note browser-use already exposes `Evaluate` and Python-based extraction, and those were 11%
of our actions — so this is an expansion of an existing surface, not a greenfield build.

## Out of scope for these arms (not harness work)

- **~45% of the set is unreachable** from GCP IPs (36 `BLOCKED` + 4 more filed as failures
  with anti-bot reasons). Needs residential IPs + stealth, not harness changes. Note blocked
  tasks die early (median 12 steps) so they are *cheap*; fixing this raises cost per run.
- Final-state capture re-navigates in a **fresh browser**. URL and query string survive
  (0/85 mismatch) but cart, login, and JS-applied filter state do not. Fix it to reuse the
  agent's session and save per-step screenshots — we only keep `final.png`, which is why no
  screenshot-based scoring is possible on existing data.
- Model swap. If arms 1–3 all come back flat, the remaining gap is the model, and
  `browser-use/bu-30b-a3b-preview` (OSS) or `ChatBrowserUse` (hosted) are purpose-tuned for
  this loop.

## Reading the results

ComponentBench found browser-use's DOM mode is already the **best** available substrate for
our worst components (Date & Time 83.4%, dropdowns 97.2%, versus 59.4/79.0 for pixels), and
that its advantage is largest for weaker models. So the substrate is not the problem. If
arms 1–3 come back flat, stop tuning the harness — it is the model or the action space.
