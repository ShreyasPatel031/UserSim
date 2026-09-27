# Strict e2e gates

## Headline

- `time_to_first_value`: not recorded (threshold <= 10s from URL submit until the first click, type, or scroll is visible in the live UI) FAIL
- `total_time`: not ready (threshold <= 480s from URL submit until the report is ready) FAIL

- study: d91bbd66-5d5f-46ce-9a64-c8d873058bab
- product: https://linear.app
- pass: false
- failure file: /workspace/results/tonight/linear-2/failures.json
- failed runs: our infrastructure=0, model timeout=0, stuck=0, product=24, no_first_action=0

| Gate | Value | Threshold | Result |
| --- | --- | --- | --- |
| Time to first value (`time_to_first_value`) | not recorded | <= 10s from URL submit until the first click, type, or scroll is visible in the live UI | FAIL |
| Total time (`total_time`) | not ready | <= 480s from URL submit until the report is ready | FAIL |
| Full 24-agent matrix (`full_matrix`) | 24 | >= 24 (smaller runs are smoke-only) | PASS |
| Agent count (`agent_count`) | 24 | >= 24 | PASS |
| Persona count (`persona_count`) | 5 | >= 4 | PASS |
| Task count (`task_count`) | 2 | >= 2 | PASS |
| Site count (`site_count`) | 3 | >= 3 | PASS |
| Page opened on the assigned site (`page_opened`) | 0/24 within 5s | <= 5s from agent creation, URL host matches the assigned site, accessibility tree present | FAIL |
| Study completed with a summary (`study_complete`) | running aborted | status=complete, summary present, no harness abort | FAIL |
| Study budget (`study_budget`) | 42.9s | <= 480s for the whole study (observed max 408s) | PASS |
| First real action (`first_action`) | not measured | live abort is time_to_first_action | PASS |
| Time to first action (`time_to_first_action`) | median=n/a max=n/a n=0/24 | median <= 5s and max <= 10s at 24 agents | FAIL |
| Product task completion (`product_task_completion`) | 0/10 (0%) | >= 50% of product runs (>= 5/10) | FAIL |
| Bland-style report page (`report_page`) | http://127.0.0.1:3000/report?study=d91bbd66-5d5f-46ce-9a64-c8d873058bab | /report?study=<id> shell with overview and trace tabs | PASS |
| Every task has a completion rate (`task_completion_rates`) | missing no by_task rows; missing task Find how to create a new issue; missing task Look for pricing or how to get started | each task has a product ok/n rate | FAIL |
| Product strength from a run past the first screen (`product_strength`) | 0/0 | >= 1 strength with agent, step, AX or URL, and the final screenshot | FAIL |
| Product weakness from a run past the first screen (`product_weakness`) | 0/0 | >= 1 weakness with agent, step, AX or URL, and the final screenshot | FAIL |
| Top weakness is not only the homepage stall (`top_weakness_not_homepage_only`) | (none) | at least one weakness is a real product issue from a run past the first screen | FAIL |
| Run issues listed separately from product friction (`run_issues_separate`) | 0 listed | insights.run_issues is its own list; harness errors are not product weaknesses | FAIL |
| Run issue share (`run_issue_rate`) | 0/24 (0%) | <= 25% of runs | PASS |
| Browserbase and concurrency losses count against the run (`infra_honesty`) | losses=0 silent=0 counted_as_success=0 | 0 silently excluded, 0 counted as task success | PASS |
| First-screen and opening-frame runs stay in the product denominator (`first_screen_not_excluded`) | opening_or_first_screen=10 product_n=10 excluded=0 | excluded=0 (a stuck run is a failure, not a drop) | PASS |

## Competitor task completion

Reported separately. These runs do not count toward the product gate.

- https://asana.com/ (competitor_1): 0/7
- https://trello.com/ (competitor_2): 0/7

## Product task completion

- confirmed: 0/10
- past the first screen (structural): 0
- first screen or opening frame: 10

## Failed gates

- time_to_first_value: value=not recorded threshold=<= 10s from URL submit until the first click, type, or scroll is visible in the live UI
- total_time: value=not ready threshold=<= 480s from URL submit until the report is ready (8-minute study budget.)
- page_opened: value=0/24 within 5s threshold=<= 5s from agent creation, URL host matches the assigned site, accessibility tree present (FAIL page_opened: 0/24 agents opened the assigned site within 5s (no accessibility tree=6))
- study_complete: value=running aborted threshold=status=complete, summary present, no harness abort (FAIL page_opened: 0/24 agents opened the assigned site within 5s (no accessibility tree=6))
- time_to_first_action: value=median=n/a max=n/a n=0/24 threshold=median <= 5s and max <= 10s at 24 agents
- product_task_completion: value=0/10 (0%) threshold=>= 50% of product runs (>= 5/10) (judge_yes=0 structural_past_first_screen=0 first_screen_or_opening=10 opening_frame=10 stuck=0 bb_losses_in_product=0)
- task_completion_rates: value=missing no by_task rows; missing task Find how to create a new issue; missing task Look for pricing or how to get started threshold=each task has a product ok/n rate
- product_strength: value=0/0 threshold=>= 1 strength with agent, step, AX or URL, and the final screenshot
- product_weakness: value=0/0 threshold=>= 1 weakness with agent, step, AX or URL, and the final screenshot
- top_weakness_not_homepage_only: value=(none) threshold=at least one weakness is a real product issue from a run past the first screen (real_weaknesses=0)
- run_issues_separate: value=0 listed threshold=insights.run_issues is its own list; harness errors are not product weaknesses
