# Arm 1 — widget primitives

Read `README.md` first. Runs at `MAX_ACTIONS=60`, same as arm 0.

**This is the arm with the strongest published evidence.** Invariant Labs applied
essentially this fix set and moved WebArena-OpenStreetMap from 30% → 46% and
ShoppingAdmin from 24% → 31% — the largest measured single-fix deltas in this literature.
Source: https://invariantlabs.ai/blog/what-we-learned-from-analyzing-web-agents

## Hypothesis

Our agent fails on filters, dropdowns, and date pickers not because it cannot reason about
them but because the action primitives don't fit the widgets. Giving it primitives that
match the DOM removes whole classes of wasted steps.

## Evidence

- Published taxonomy over 8,864 failed traces: continuous calibration 20.2%, transient
  state loss 19.9%, missing commit 11.6%, target acquisition 11.2%, repetition 11.2%.
- Filter & Sorting is the single largest error class in the OM2W paper's own taxonomy at
  **57.7%** for the best agent of its time.
- Our traces: one run clicked index 6580 six times; another did
  `InputTextAction(index=6022, text='', clear=True)` then retyped. 32% of our runs repeat
  the same exact call ≥3×. 27% of all our actions are DOM-groping
  (`Evaluate` 11.0% + `FindElements` 8.6% + `SearchPage` 7.8%).
- Playwright's accessibility tree does not expose `<option>` children until the control is
  expanded, which is *why* agents click a combobox repeatedly. This is an upstream
  behaviour, not a model failure.

## Changes

There is currently **no `Tools`/`Controller` registered** — `agent_kwargs` in
`_run_async` (`src/capability/mistral_browser_use_runner.py`) passes no `tools=`. You will
need to create one and inject it. Check the installed `browser-use==0.13.8` for the correct
class name and decorator (`Tools` vs `Controller`; `@tools.action` vs `@controller.action`)
rather than trusting any example. Put the registry in a new
`src/capability/widget_tools.py` so arms 2 and 3 can reuse it.

Gate the whole thing behind `BROWSER_USE_WIDGET_TOOLS=1`, default off.

Implement, in descending order of expected value:

1. **`select_option(index, label)`** — resolve the element, then set the value directly on
   the underlying `<select>` via Playwright's `select_option`, dispatching `input` and
   `change` events. Do not click to expand first. Handle the custom-ARIA case too: Radix
   and Headless UI report `role="combobox"` identically to a native `<select>` but render
   options only after the trigger click, so detect which you have and take the matching
   path.

2. **Clear-before-type in the existing input action** — send `Ctrl+A` (or set value to `""`
   and dispatch `input`) before typing, instead of appending. The agent is already paying
   two steps to emulate this, so this is a pure step-cost saving.

3. **`set_date(index, iso_date)`** — for `<input type="date">` and friends, set the value
   programmatically and dispatch `input`/`change`. Never click through a calendar grid.
   This is the concrete version of what Webwright means by expressing a date as a program.

4. **`assert_filter_applied(expectation)`** — after a filter, verify it is visibly
   reflected in the result set before continuing. This directly targets the "missing
   commit" class (11.6%) and the official rubric's criterion 1, which fails a task when a
   filter was selected but never confirmed or had no visible effect.

5. **Loop breaker** — detect N (start with 3) identical consecutive action calls and
   inject a message forcing a different strategy. **Bundle it here, not as its own arm:**
   55.8% of failed traces end in a repeated-action loop but they are distributed evenly
   (48–67%) across every underlying mechanism, so loop detection alone just fails faster.
   It only pays off next to the widget fixes.

6. **Prompt: prefer filter UI over the search box.** Extend `extend_system_message` in
   `stage1_agent_kwargs` (`src/capability/browser_use_harness.py`): use the site's filter
   controls rather than typing constraints into search, and apply an explicit sort for any
   superlative ("best", "cheapest", "closest"). The official rubric's criterion 3 fails a
   run that types all requirements into a search box even when the visible results look
   right, so this may be worth points on its own. Cheapest item on the list — consider
   validating it alone first.

Add every flag to `stage1_config_snapshot()`.

## Run

```bash
STAGE=full100 \
FLEET_TAG=mistral-small-2603_arm1_widgets \
FLEET_PREFIX=usersim-bu-arm1 \
MAX_ACTIONS=60 \
EXTRA_ENV='BROWSER_USE_WIDGET_TOOLS=1' \
  ./scripts/vm/fleet_bakeoff.sh
```

Smoke-test locally on 2–3 tasks before spending a fleet run — a broken custom action will
fail all 100 tasks identically and waste $11:

```bash
PYTHONPATH=src BROWSER_USE_WIDGET_TOOLS=1 python -m capability.run_mistral_bakeoff \
  --stage full10 --model mistral-small-2603 --workers 2 --max-actions 60 --tag arm1_smoke
```

(`full10` is fine for a smoke test. It is not fine for measuring the result.)

## Report

- `success_rate_scored` and `n_scored` vs arm 0, against arm 0's seed-to-seed spread.
- Action mix vs arm 0. The DOM-groping share (`Evaluate` + `FindElements` + `SearchPage`,
  currently 27%) should fall. **This is your mechanism check** — if success moves but the
  mix doesn't, something else caused it.
- Exact-repeat rate (currently 32% of runs have a ≥3× repeated call).
- Median `num_actions` for successes. Should drop if the primitives are saving steps.
- Per-fix attribution if you can get it cheaply; item 6 is prompt-only and separable.

## Success criteria

- `success_rate_scored` beats arm 0 by more than arm 0's seed spread.
- DOM-groping action share drops materially.
- Fewer steps per success.

## Watch out

- A custom action that throws will be silently absorbed as a failed action and look like a
  reasoning failure. Log exceptions from your tools into the trace dir explicitly.
- Don't switch observation mode. ComponentBench shows `browser-use`'s DOM mode already
  leads on Date & Time (83.4%) and dropdowns (97.2%); screenshots/SoM would regress you.
- Shadow DOM will defeat naive selectors — one of our own runs failed on Newegg filters
  "due to shadow DOM". Pierce it or detect and report it.
- Six changes in one arm means a flat result is uninformative about *which* failed. If
  budget allows, split item 6 (prompt) and item 1 (`select_option`) into their own tags.
