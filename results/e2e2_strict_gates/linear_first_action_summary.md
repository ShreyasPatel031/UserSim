# Strict e2e gates

- study: 9512baae-faee-4bad-ba12-ce55f0b7e0ea
- product: https://linear.app
- pass: false
- failure file: /tmp/usersim_e2e2_linear_first_action/failures.json
- failed runs: our infrastructure=0, model timeout=0, stuck=0, product=0, no_first_action=24

| Gate | Value | Threshold | Result |
| --- | --- | --- | --- |
| Full 24-agent matrix (`full_matrix`) | 24 | >= 24 (smaller runs are smoke-only) | PASS |
| Agent count (`agent_count`) | 24 | >= 24 | PASS |
| Persona count (`persona_count`) | 4 | >= 4 | PASS |
| Task count (`task_count`) | 2 | >= 2 | PASS |
| Site count (`site_count`) | 3 | >= 3 | PASS |
| First real screenshot is the product (`vision_yes`) | 24/24 | 24/24 vision YES | PASS |
| Study completed with a summary (`study_complete`) | running aborted | status=complete, summary present, no harness abort | FAIL |
| Study budget (`study_budget`) | 112.0s | <= 480s for the whole study (observed max 408s) | PASS |
| Every agent has a first real screenshot (`first_screenshot`) | missing=0 | missing=0 | PASS |
| Creation to first real screenshot (`first_screenshot_latency`) | max=0.043s slow=0 | <= 5s for every agent | PASS |
| First real action (`first_action`) | 0/24 by 79.1s | >= 50% of agents by 60s and every agent by 90s | FAIL |
| Product task completion (`product_task_completion`) | 0/8 (0%) | >= 50% of product runs (>= 4/8) | FAIL |
| Bland-style report page (`report_page`) | missing | /report?study=<id> shell with overview and trace tabs | FAIL |
| Every task has a completion rate (`task_completion_rates`) | missing no by_task rows; missing task Find how to create a new issue; missing task Look for pricing or how to get started | each task has a product ok/n rate | FAIL |
| Product strength from a run past the first screen (`product_strength`) | 0/0 | >= 1 strength with agent, step, and a screenshot URL that loads | FAIL |
| Product weakness from a run past the first screen (`product_weakness`) | 0/0 | >= 1 weakness with agent, step, and a screenshot URL that loads | FAIL |
| Top weakness is not only the homepage stall (`top_weakness_not_homepage_only`) | (none) | at least one weakness is a real product issue from a run past the first screen | FAIL |
| Run issues listed separately from product friction (`run_issues_separate`) | 0 listed | insights.run_issues is its own list; harness errors are not product weaknesses | FAIL |
| Run issue share (`run_issue_rate`) | 0/24 (0%) | <= 25% of runs | PASS |
| Browserbase and concurrency losses count against the run (`infra_honesty`) | losses=0 silent=0 counted_as_success=0 | 0 silently excluded, 0 counted as task success | PASS |
| First-screen and opening-frame runs stay in the product denominator (`first_screen_not_excluded`) | opening_or_first_screen=8 product_n=8 excluded=0 | excluded=0 (a stuck run is a failure, not a drop) | PASS |

## Competitor task completion

Reported separately. These runs do not count toward the product gate.

- https://asana.com/ (competitor_1): 0/8
- https://trello.com/ (competitor_2): 0/8

## Product task completion

- confirmed: 0/8
- past the first screen (structural): 0
- first screen or opening frame: 8

## Failed gates

- study_complete: value=running aborted threshold=status=complete, summary present, no harness abort (FAIL first_action: 0/24 agents had a real action by 79s (need >= 50% by 60s). t1__p1__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Page is open. Starting the simulated user…; t1__p1__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://asana.com/; t1__p1__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p1__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://linear.app/; t2__p1__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p1__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://trello.com/; t1__p2__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://linear.app/; t1__p2__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://asana.com/?email=; t1__p2__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p2__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p2__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p2__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t1__p3__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t1__p3__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t1__p3__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p3__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p3__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://asana.com/…; t2__p3__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://trello.com/…; t1__p4__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://linear.app…; t1__p4__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://asana.com/…; t1__p4__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://trello.com/…; t2__p4__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://linear.app…; t2__p4__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://asana.com/…; t2__p4__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opening https://trello.com/…)
- first_action: value=0/24 by 79.1s threshold=>= 50% of agents by 60s and every agent by 90s (t1__p1__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Page is open. Starting the simulated user…; t1__p1__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://asana.com/; t1__p1__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p1__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://linear.app/; t2__p1__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p1__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://trello.com/; t1__p2__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://linear.app/; t1__p2__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Opened https://asana.com/?email=; t1__p2__competitor_2 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p2__product phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p2__competitor_1 phase=Live browser agents — 0/24 done · 24 active · 24 steps error= last_action=Browser ready — loading the page…; t2__p2__competitor_2 phase=Live browser agent)
- product_task_completion: value=0/8 (0%) threshold=>= 50% of product runs (>= 4/8) (judge_yes=0 structural_past_first_screen=0 first_screen_or_opening=8 opening_frame=8 stuck=0 bb_losses_in_product=0)
- report_page: value=missing threshold=/report?study=<id> shell with overview and trace tabs (missing markers: data-tab="analytics", data-tab="traces", id="analytics-root", id="tab-traces", Overview, Trace drill-down)
- task_completion_rates: value=missing no by_task rows; missing task Find how to create a new issue; missing task Look for pricing or how to get started threshold=each task has a product ok/n rate
- product_strength: value=0/0 threshold=>= 1 strength with agent, step, and a screenshot URL that loads
- product_weakness: value=0/0 threshold=>= 1 weakness with agent, step, and a screenshot URL that loads
- top_weakness_not_homepage_only: value=(none) threshold=at least one weakness is a real product issue from a run past the first screen (real_weaknesses=0)
- run_issues_separate: value=0 listed threshold=insights.run_issues is its own list; harness errors are not product weaknesses
