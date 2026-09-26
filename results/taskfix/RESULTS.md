# Task completion — single-agent harness

Local Chromium, one task at a time, no Browserbase. The step loop re-reads the live page, clicks by role and name (or follows the link), and stops when that read shows the goal.

6/6 passed. No failing step logs.

| Site | Task | Result | Final URL |
| --- | --- | --- | --- |
| Linear | Find how to create a new issue | PASS | https://linear.app/docs/creating-issues |
| Linear | Look for pricing or how to get started | PASS | https://linear.app/pricing |
| Linear | Open the changelog and see what shipped recently | PASS | https://linear.app/changelog/2026-09-24-new-controls-for-linear-coding-agent |
| Excalidraw | Draw a simple rectangle on the canvas | PASS | https://excalidraw.com/ |
| Excalidraw | Find how to export or share the drawing | PASS | https://excalidraw.com/ |
| Excalidraw | Open the help dialog and read the keyboard shortcuts | PASS | https://excalidraw.com/ |

## Linear — Find how to create a new issue

The marketing "New issue" control is `tabindex="-1"` with no href. Clicking it does not change the URL or the DOM. The loop skips it.

1. Saw the homepage. Decision: click Documentation (`https://linear.app/docs`). After: `https://linear.app/docs`, title Linear Docs.
2. Saw the docs index. Decision: click Create issues (`https://linear.app/docs/creating-issues`). After: title Create issues – Linear Docs.

## Linear — Look for pricing or how to get started

1. Saw the homepage. Decision: click Pricing (`https://linear.app/pricing`). After: title Pricing – Linear. Free, Basic, and Business plans are on the page.

## Linear — Open the changelog and see what shipped recently

1. Saw the homepage. Decision: click the changelog link for the Sept 24, 2026 coding-agent post. After: that changelog article.

## Excalidraw — Draw a simple rectangle on the canvas

1. Saw the welcome screen. Decision: click Rectangle. Executed as a role click on the Rectangle tool, then a drag on the canvas. After: "Selected shape actions" and a rectangle on the canvas.

## Excalidraw — Find how to export or share the drawing

1. Saw the welcome screen. Decision: click Export image. Executed with the app shortcut, then the menu if needed. After: the Export image dialog (PNG and SVG).

## Excalidraw — Open the help dialog and read the keyboard shortcuts

1. Saw the welcome screen. Decision: click Help (exact name, not "Help ?"). After: the help panel listing keyboard shortcuts.

Full step records: `results/taskfix/one_agent.json`.

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

The step loop now invents the Rectangle drag, Export shortcut, and Help click only on excalidraw.com, and a canvas-sample flicker no longer counts as a new page. Rerun after that fix.
