# Linear 24-agent study to grade

Study `70557bae-83af-4bf9-9bbb-3135046193cd`. Report: http://127.0.0.1:3000/report?study=70557bae-83af-4bf9-9bbb-3135046193cd. Final screenshots: `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/<agent>/screenshots/final.png` (8 product paths in `results/taskfix/linear24_grade.md`).

This is not an independent pass until PR #46 grades that id. Browserbase for the study is released. Gates should run `--grade-study 70557bae-83af-4bf9-9bbb-3135046193cd`.

# #46 harness — product Gemini YES

`MVP_BB_OWNER=gates`. Eight product agents per site. The independent judge in `mvp/e2e2_gates.py` scored the final screenshot.

| Site | Study | Product Gemini YES | Report |
| --- | --- | --- | --- |
| Linear | `a437acc0-1586-45e6-a574-4099c73299ff` | 8/8 | `results/taskfix/linear8g_summary.md` |
| Excalidraw | `4ac26c20-0711-4609-a86e-3cf7222279b5` | 8/8 | `results/taskfix/excal8g_summary.md` |

Linear: create-issue agents landed on `https://linear.app/docs/creating-issues`. Pricing agents landed on `https://linear.app/pricing`. Excalidraw: draw agents left a rectangle on the canvas. Export agents opened the menu to Export image. No agent repeated a dead New issue click.

The overall harness `pass` flag is false because strength/weakness evidence is still short of the gate (Linear strengths 0/0, Excalidraw strengths 0/0 and weaknesses 0/0). Product task completion is 8/8 on both. Gate files were not edited. Those wide runs are not repeated: prime count is 0, and only the integration agent runs 24-wide.

# Task completion — single-agent harness

Local Chromium, one task at a time, no Browserbase session. Prime count is 0 (`prime_sessions` returns immediately; the server defaults `MVP_PRIME_SESSIONS` to 0). Running `taskfix` Browserbase sessions at the start of this run: 0. Every step re-reads the live page and asks the model. Clicks use role and name, then coordinates. A drawing counts only after a drag changes the canvas ink. Log: `results/taskfix/harness_prime0.log`.

4/4 passed. No failing step logs.

| Site | Task | Result | Final URL |
| --- | --- | --- | --- |
| Linear | Find how to create a new issue | PASS | https://linear.app/docs/creating-issues |
| Linear | Look for pricing or how to get started | PASS | https://linear.app/pricing |
| Excalidraw | Draw a simple box | PASS | https://excalidraw.com/ |
| Excalidraw | Find how to export or share | PASS | https://excalidraw.com/ |

## Linear — Find how to create a new issue

The homepage preview (New issue, Inbox, My issues) is marked inert and is not offered to the model.

1. Saw the homepage. Decision: click Documentation. After: `https://linear.app/docs`.
2. Decision: click Docs. The URL stayed `https://linear.app/docs`.
3. Saw the docs sidebar. Decision: click Issues. After: the Issues section expanded, still on `/docs`.
4. Decision: click Create issues. After: `https://linear.app/docs/creating-issues`, title Create issues – Linear Docs.

## Linear — Look for pricing or how to get started

1. Saw the homepage. Decision: click Pricing. After: `https://linear.app/pricing`, title Pricing – Linear. Free, Basic, and Business plans are on the page.

## Excalidraw — Draw a simple box

1. Saw the welcome screen. Decision: click Rectangle (role). After: the rectangle tool's selection chrome. The canvas ink had not changed, so this was not done.
2. Decision: drag. The loop pressed `r` and dragged on the canvas. After: the ink sample changed and a rectangle is on the canvas.

## Excalidraw — Find how to export or share

1. Saw the welcome screen. Decision: click Menu (the unlabeled main-menu button, by coordinates). After: the menu lists Export image...

Full step records: `results/taskfix/one_agent.json`.

The 24-agent studies below were scored on the earlier scripted planner. They were not re-run after this model loop.

## Server study — Linear 24 agents

Study `70557bae-83af-4bf9-9bbb-3135046193cd`. Strict harness `mvp/e2e2_matrix.py`, owner `taskfix`, competitors Asana and Trello. Independent Gemini vision judge.

Product task completion **8/8**. Full gate table: `results/taskfix/linear24_summary.md`. Harness log: `results/taskfix/linear24.log`.

| Agent | Task | Judge | Final URL |
| --- | --- | --- | --- |
| t1__p1__product | Find how to create a new issue | YES | https://linear.app/docs/creating-issues |
| t1__p2__product | Find how to create a new issue | YES | https://linear.app/docs/creating-issues |
| t1__p3__product | Find how to create a new issue | YES | https://linear.app/docs/creating-issues |
| t1__p4__product | Find how to create a new issue | YES | https://linear.app/docs/creating-issues |
| t2__p1__product | Look for pricing or how to get started | YES | https://linear.app/pricing |
| t2__p2__product | Look for pricing or how to get started | YES | https://linear.app/pricing |
| t2__p3__product | Look for pricing or how to get started | YES | https://linear.app/pricing |
| t2__p4__product | Look for pricing or how to get started | YES | https://linear.app/pricing |

Headline: time to first value 2.1s, study 115s, page open 24/24 within 5s, `ALL_PASS`. The 8 failed runs are competitor issue tasks (Asana and Trello have no public create-issue page). They do not count toward the product gate.

An earlier 8-wide Linear slice (study before this one) judged the six scheduled product agents YES. Two extra live sessions were published before the task list was capped and had no final screenshot. That slice is in `results/taskfix/linear8.log` and `results/taskfix/linear8_verdicts.json`. The 24-agent run above is the graded result.

## Server study — Excalidraw 24 agents (aborted)

Study `617d8ef9-2991-4532-a70a-b7b8d03367a8` was killed by the harness at 32s. Product agents had already reached the goal (rectangle on the canvas, Export image dialog) but the vision judge never ran because the study was aborted.

Failure: `t2__p1__competitor_2` on Miro repeated `click Export image` (steps 1–9). The planned action invented Excalidraw's export shortcut on a site that does not have it. A flickering hero-image canvas sample counted as progress, so the repeat check never fired. The harness aborts the whole study at the third identical action. Log: `results/taskfix/excalidraw24.log`.

The step loop now invents Rectangle, drag, and Export image only on `excalidraw.com`. A Miro (or any other host) action with those names is refused before it is written to the trace, and a canvas sample is stored only for an Excalidraw drawing. Owner `taskfix` holds at most 2 sessions and does not create primes.

That run's step loop invented the Rectangle drag, Export shortcut, and Help click only on excalidraw.com, and a canvas-sample flicker no longer counted as a new page. A click or accessibility read that does not return is capped (8s read, 12s action). The model loop above replaces those invented actions.

## Server study — Excalidraw 24 agents

Study `38deb1cc-8bf3-4d6a-a5b4-ca147c8cf160`. Same strict harness, owner `taskfix`, competitors tldraw and Miro. Independent Gemini vision judge.

Product task completion **8/8**. `ALL_PASS` in 35.6s. Full gate table: `results/taskfix/excalidraw24d_summary.md`. Harness log: `results/taskfix/excalidraw24d.log`.

| Agent | Task | Judge | Final URL |
| --- | --- | --- | --- |
| t1__p1__product | Draw a simple rectangle on the canvas | YES | https://excalidraw.com/ |
| t1__p2__product | Draw a simple rectangle on the canvas | YES | https://excalidraw.com/ |
| t1__p3__product | Draw a simple rectangle on the canvas | YES | https://excalidraw.com/ |
| t1__p4__product | Draw a simple rectangle on the canvas | YES | https://excalidraw.com/ |
| t2__p1__product | Find how to export or share the drawing | YES | https://excalidraw.com/ |
| t2__p2__product | Find how to export or share the drawing | YES | https://excalidraw.com/ |
| t2__p3__product | Find how to export or share the drawing | YES | https://excalidraw.com/ |
| t2__p4__product | Find how to export or share the drawing | YES | https://excalidraw.com/ |

An intermediate rerun (study `2f21dab5-7e45-4044-a6af-c97821a6fce9`, log `results/taskfix/excalidraw24c.log`) also judged product 8/8, then failed the strength and weakness gates because six agents found the goal already on the shared page and the trace still held the one-word opening title. Stamping the live read fixed that. Miro competitor export tasks are 0/8; they have no logged-out export dialog. They do not count toward the product gate.
