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
