# Strict e2e gates

## Headline

- `time_to_first_value`: 3.113s (threshold <= 10s from URL submit until the first click, type, or scroll is visible in the live UI) PASS
- `total_time`: 119.539s (threshold <= 480s from URL submit until the report is ready) PASS

- study: 748a1b0a-5cb2-4f8a-8a81-72ebcca23c17
- product: https://excalidraw.com
- pass: false
- failure file: results/tonight/excalidraw-20260926T072849Z/failures.json
- failed runs: our infrastructure=0, model timeout=0, stuck=0, product=16, no_first_action=0

| Gate | Value | Threshold | Result |
| --- | --- | --- | --- |
| Time to first value (`time_to_first_value`) | 3.113s | <= 10s from URL submit until the first click, type, or scroll is visible in the live UI | PASS |
| Total time (`total_time`) | 119.539s | <= 480s from URL submit until the report is ready | PASS |
| Full 24-agent matrix (`full_matrix`) | 24 | >= 24 (smaller runs are smoke-only) | PASS |
| Agent count (`agent_count`) | 24 | >= 24 | PASS |
| Persona count (`persona_count`) | 5 | >= 4 | PASS |
| Task count (`task_count`) | 2 | >= 2 | PASS |
| Site count (`site_count`) | 3 | >= 3 | PASS |
| Page opened on the assigned site (`page_opened`) | 24/24 within 5s | <= 5s from agent creation, URL host matches the assigned site, accessibility tree present | PASS |
| Study completed with a summary (`study_complete`) | complete | status=complete, summary present, no harness abort | PASS |
| Study budget (`study_budget`) | 120.0s | <= 480s for the whole study (observed max 408s) | PASS |
| First real action (`first_action`) | not measured | live abort is time_to_first_action | PASS |
| Time to first action (`time_to_first_action`) | median=0.343s max=2.278s n=24/24 | median <= 5s and max <= 10s at 24 agents | PASS |
| Per-phase milliseconds (`phase_ms`) | 24/24 | each agent has phase_ms.session_ready, page_open, first_action, final_screenshot | PASS |
| Final screenshot (`final_screenshot`) | 24/24 | each agent has final_screenshot_url (one async capture for the judge) | PASS |
| Final URL and page text for the judge (`judge_inputs`) | 24/24 | final_url plus state_sig.text or ax_tree on every agent | PASS |
| Failed-step phase and reason (`failed_step`) | 16 failed runs | every failed run has failed_step.phase and failed_step.reason | PASS |
| Product task completion (`product_task_completion`) | 4/8 (50%) | >= 50% of product runs (>= 4/8) | PASS |
| Bland-style report page (`report_page`) | http://127.0.0.1:3000/report?study=748a1b0a-5cb2-4f8a-8a81-72ebcca23c17 | /report?study=<id> shell with overview and trace tabs | PASS |
| Every task has a completion rate (`task_completion_rates`) | 2 tasks | each task has a product ok/n rate | PASS |
| Product strength from a run past the first screen (`product_strength`) | 0/0 | >= 1 strength with agent, step, AX or URL, and the final screenshot | FAIL |
| Product weakness from a run past the first screen (`product_weakness`) | 2/2 | >= 1 weakness with agent, step, AX or URL, and the final screenshot | PASS |
| Top weakness is not only the homepage stall (`top_weakness_not_homepage_only`) | click Menu changed nothing on https://excalidraw.com/ | at least one weakness is a real product issue from a run past the first screen | PASS |
| Run issues listed separately from product friction (`run_issues_separate`) | 0 listed | insights.run_issues is its own list; harness errors are not product weaknesses | PASS |
| Run issue share (`run_issue_rate`) | 0/24 (0%) | <= 25% of runs | PASS |
| Browserbase and concurrency losses count against the run (`infra_honesty`) | losses=0 silent=0 counted_as_success=0 | 0 silently excluded, 0 counted as task success | PASS |
| First-screen and opening-frame runs stay in the product denominator (`first_screen_not_excluded`) | opening_or_first_screen=0 product_n=8 excluded=0 | excluded=0 (a stuck run is a failure, not a drop) | PASS |

## Competitor task completion

Reported separately. These runs do not count toward the product gate.

- https://www.tldraw.com/ (competitor_1): 4/8
- https://miro.com/ (competitor_2): 0/8

## Product task completion

- confirmed: 4/8
- past the first screen (structural): 8
- first screen or opening frame: 0

## Failed gates

- product_strength: value=0/0 threshold=>= 1 strength with agent, step, AX or URL, and the final screenshot
