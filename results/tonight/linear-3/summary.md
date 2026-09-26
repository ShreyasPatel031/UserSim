# Linear run 3 — FAIL, and not the specified task list

Not a pass. The harness aborted before a report was ready. This run also did not execute the requested Linear tasks, because the tmux command line concatenated `--tasks` into `--competitors`. The study used model-written tasks and swapped in monday.com.

- study: `9aeca3a8-1b63-4fae-abd5-9963124c0639`
- product: https://linear.app
- code head: `2214cf1` (before the shared accessibility-tree merge)
- elapsed: 322.5s
- pass: false
- agents: 24, sites recorded: 3, task bases: 2
- competitors actually used: https://asana.com/ and https://monday.com/
- tasks actually used: "Skim the homepage and note what stands out" and "Find something to open or watch and try it"
- early abort: `missing field ax_tree; missing field page_open_at_ts: 0/24 agents`
- failures.json counts: our infrastructure=0, model timeout=0, stuck=0, product=6, no_first_action=0 (6 failed runs recorded at abort)

| Gate | Value | Result |
| --- | --- | --- |
| time_to_first_value | not recorded | FAIL |
| total_time | not ready | FAIL |
| page_opened | missing ax_tree and page_open_at_ts, 0/24 | FAIL |
| study_complete | running aborted | FAIL |
| time_to_first_action | missing page_open_at_ts | FAIL |
| phase_ms | missing on 24 agents | FAIL |
| final_screenshot | missing final_screenshot_url | FAIL |
| judge_inputs | missing state_sig.text | FAIL |
| failed_step | missing phase and reason | FAIL |
| product_task_completion | 0/10 (0%) | FAIL |
| report_page | missing shell markers at abort | FAIL |
| task_completion_rates | no by_task rows | FAIL |
| product_strength | 0/0 | FAIL |
| product_weakness | 0/0 | FAIL |
| top_weakness_not_homepage_only | none | FAIL |
| run_issues_separate | 0 listed | FAIL |

The study was then abandoned (`kill_requested=true`) and its integration Browserbase sessions were released. gates, bisect, and signup sessions were not touched.

The next Linear run uses a script file so the task override and trello.com competitor stay intact, on the head that includes the shared accessibility read.
