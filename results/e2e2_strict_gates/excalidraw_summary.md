# Strict e2e gates

- study: 5c4a39b4-acc7-4f22-8a0c-3a7655c5e7ed
- product: https://excalidraw.com
- pass: false

| Gate | Value | Threshold | Result |
| --- | --- | --- | --- |
| Full 24-agent matrix (`full_matrix`) | 24 | >= 24 (smaller runs are smoke-only) | PASS |
| Agent count (`agent_count`) | 24 | >= 24 | PASS |
| Persona count (`persona_count`) | 4 | >= 4 | PASS |
| Task count (`task_count`) | 2 | >= 2 | PASS |
| Site count (`site_count`) | 3 | >= 3 | PASS |
| First real screenshot is the product (`vision_yes`) | 24/24 | 24/24 vision YES | PASS |
| Study completed with a summary (`study_complete`) | complete | status=complete, summary present, no harness abort | PASS |
| Elapsed time (`elapsed`) | 314.3s | <= 360s | PASS |
| Every agent has a first real screenshot (`first_screenshot`) | missing=0 | missing=0 | PASS |
| Creation to first real screenshot (`first_screenshot_latency`) | max=0.069s slow=0 | <= 5s for every agent | PASS |
| Product task completion (`product_task_completion`) | 0/8 (0%) | >= 50% of product runs (>= 4/8) | FAIL |
| Bland-style report page (`report_page`) | http://127.0.0.1:3000/report?study=5c4a39b4-acc7-4f22-8a0c-3a7655c5e7ed | /report?study=<id> shell with overview and trace tabs | PASS |
| Every task has a completion rate (`task_completion_rates`) | 2 tasks | each task has a product ok/n rate | PASS |
| Product strength from a run past the first screen (`product_strength`) | 0/0 | >= 1 strength with agent, step, and a screenshot URL that loads | FAIL |
| Product weakness from a run past the first screen (`product_weakness`) | 0/1 | >= 1 weakness with agent, step, and a screenshot URL that loads | FAIL |
| Top weakness is not only the homepage stall (`top_weakness_not_homepage_only`) | No product run got past the first screen (3 of 3 stopped on the homepage), so feature-level weaknesses are not in these traces. | at least one weakness is a real product issue from a run past the first screen | FAIL |
| Run issues listed separately from product friction (`run_issues_separate`) | 13 listed | insights.run_issues is its own list; harness errors are not product weaknesses | PASS |
| Run issue share (`run_issue_rate`) | 13/24 (54%) | <= 25% of runs | FAIL |
| Browserbase and concurrency losses count against the run (`infra_honesty`) | losses=13 silent=0 counted_as_success=0 | 0 silently excluded, 0 counted as task success | PASS |
| First-screen and opening-frame runs stay in the product denominator (`first_screen_not_excluded`) | opening_or_first_screen=8 product_n=8 excluded=0 | excluded=0 (a stuck run is a failure, not a drop) | PASS |

## Competitor task completion

Reported separately. These runs do not count toward the product gate.

- https://www.tldraw.com/ (competitor_1): 0/8
- https://miro.com/ (competitor_2): 0/8

## Product task completion

- confirmed: 0/8
- past the first screen (structural): 0
- first screen or opening frame: 8

## Failed gates

- product_task_completion: value=0/8 (0%) threshold=>= 50% of product runs (>= 4/8) (structural_past_first_screen=0 vision_confirmed=0 first_screen_or_opening=8 opening_frame=8 bb_losses_in_product=5)
- product_strength: value=0/0 threshold=>= 1 strength with agent, step, and a screenshot URL that loads
- product_weakness: value=0/1 threshold=>= 1 weakness with agent, step, and a screenshot URL that loads
- top_weakness_not_homepage_only: value=No product run got past the first screen (3 of 3 stopped on the homepage), so feature-level weaknesses are not in these traces. threshold=at least one weakness is a real product issue from a run past the first screen (real_weaknesses=0)
- run_issue_rate: value=13/24 (54%) threshold=<= 25% of runs
