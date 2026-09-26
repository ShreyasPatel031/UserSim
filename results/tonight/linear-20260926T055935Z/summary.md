# Strict e2e gates

## Headline

- `time_to_first_value`: 3.092s (threshold <= 10s from URL submit until the first click, type, or scroll is visible in the live UI) PASS
- `total_time`: not ready (threshold <= 480s from URL submit until the report is ready) FAIL

- study: 97b35b35-2018-485c-81fc-e3b2dc971a00
- product: https://linear.app
- pass: false
- failure file: results/tonight/linear-20260926T055935Z/failures.json
- failed runs: our infrastructure=0, model timeout=0, stuck=0, product=1, no_first_action=0

| Gate | Value | Threshold | Result |
| --- | --- | --- | --- |
| Time to first value (`time_to_first_value`) | 3.092s | <= 10s from URL submit until the first click, type, or scroll is visible in the live UI | PASS |
| Total time (`total_time`) | not ready | <= 480s from URL submit until the report is ready | FAIL |
| Full 24-agent matrix (`full_matrix`) | 24 | >= 24 (smaller runs are smoke-only) | PASS |
| Agent count (`agent_count`) | 24 | >= 24 | PASS |
| Persona count (`persona_count`) | 5 | >= 4 | PASS |
| Task count (`task_count`) | 2 | >= 2 | PASS |
| Site count (`site_count`) | 3 | >= 3 | PASS |
| Page opened on the assigned site (`page_opened`) | 23/24 within 5s | <= 5s from agent creation, URL host matches the assigned site, accessibility tree present | FAIL |
| Study completed with a summary (`study_complete`) | running aborted | status=complete, summary present, no harness abort | FAIL |
| Study budget (`study_budget`) | 13.1s | <= 480s for the whole study (observed max 408s) | PASS |
| First real action (`first_action`) | not measured | live abort is time_to_first_action | PASS |
| Time to first action (`time_to_first_action`) | median=1.689s max=1.741s n=24/24 | median <= 5s and max <= 10s at 24 agents | PASS |
| Per-phase milliseconds (`phase_ms`) | 24/24 | each agent has phase_ms.session_ready, page_open, first_action, final_screenshot | PASS |
| Final screenshot (`final_screenshot`) | missing field final_screenshot_url | each agent has final_screenshot_url (one async capture for the judge) | FAIL |
| Final URL and page text for the judge (`judge_inputs`) | 24/24 | final_url plus state_sig.text or ax_tree on every agent | PASS |
| Failed-step phase and reason (`failed_step`) | 24 failed runs | every failed run has failed_step.phase and failed_step.reason | PASS |
| Product task completion (`product_task_completion`) | 0/8 (0%) | >= 50% of product runs (>= 4/8) | FAIL |
| Bland-style report page (`report_page`) | missing | /report?study=<id> shell with overview and trace tabs | FAIL |
| Every task has a completion rate (`task_completion_rates`) | missing no by_task rows; missing task Find how to create a new issue; missing task Look for pricing or how to get started | each task has a product ok/n rate | FAIL |
| Product strength from a run past the first screen (`product_strength`) | 0/0 | >= 1 strength with agent, step, AX or URL, and the final screenshot | FAIL |
| Product weakness from a run past the first screen (`product_weakness`) | 0/0 | >= 1 weakness with agent, step, AX or URL, and the final screenshot | FAIL |
| Top weakness is not only the homepage stall (`top_weakness_not_homepage_only`) | (none) | at least one weakness is a real product issue from a run past the first screen | FAIL |
| Run issues listed separately from product friction (`run_issues_separate`) | 0 listed | insights.run_issues is its own list; harness errors are not product weaknesses | FAIL |
| Run issue share (`run_issue_rate`) | 0/24 (0%) | <= 25% of runs | PASS |
| Browserbase and concurrency losses count against the run (`infra_honesty`) | losses=0 silent=0 counted_as_success=0 | 0 silently excluded, 0 counted as task success | PASS |
| First-screen and opening-frame runs stay in the product denominator (`first_screen_not_excluded`) | opening_or_first_screen=7 product_n=8 excluded=0 | excluded=0 (a stuck run is a failure, not a drop) | PASS |

## Competitor task completion

Reported separately. These runs do not count toward the product gate.

- https://asana.com/ (competitor_1): 0/8
- https://trello.com/ (competitor_2): 0/8

## Product task completion

- confirmed: 0/8
- past the first screen (structural): 1
- first screen or opening frame: 7

## Failed gates

- total_time: value=not ready threshold=<= 480s from URL submit until the report is ready (8-minute study budget.)
- page_opened: value=23/24 within 5s threshold=<= 5s from agent creation, URL host matches the assigned site, accessibility tree present (FAIL page_opened: 23/24 agents opened the assigned site within 5s (opened after 5s=1))
- study_complete: value=running aborted threshold=status=complete, summary present, no harness abort (FAIL page_opened: 23/24 agents opened the assigned site within 5s (opened after 5s=1))
- final_screenshot: value=missing field final_screenshot_url threshold=each agent has final_screenshot_url (one async capture for the judge)
- product_task_completion: value=0/8 (0%) threshold=>= 50% of product runs (>= 4/8) (judge_yes=0 structural_past_first_screen=1 first_screen_or_opening=7 opening_frame=0 stuck=0 bb_losses_in_product=0)
- report_page: value=missing threshold=/report?study=<id> shell with overview and trace tabs (missing markers: data-tab="analytics", data-tab="traces", id="analytics-root", id="tab-traces", Overview, Trace drill-down)
- task_completion_rates: value=missing no by_task rows; missing task Find how to create a new issue; missing task Look for pricing or how to get started threshold=each task has a product ok/n rate
- product_strength: value=0/0 threshold=>= 1 strength with agent, step, AX or URL, and the final screenshot
- product_weakness: value=0/0 threshold=>= 1 weakness with agent, step, AX or URL, and the final screenshot
- top_weakness_not_homepage_only: value=(none) threshold=at least one weakness is a real product issue from a run past the first screen (real_weaknesses=0)
- run_issues_separate: value=0 listed threshold=insights.run_issues is its own list; harness errors are not product weaknesses
