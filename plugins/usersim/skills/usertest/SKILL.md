---
name: usertest
description: User-test a web product (site or web app) with simulated users in real cloud browsers. Use when the user asks to user-test, usability-test, dogfood or QA their product or a page with real-looking users, asks how their users or customers will use it, or wants to compare their onboarding with competitors. Runs a plain tester plus 2-3 user groups from UserSim's bank of real Product Hunt users in parallel, replays the runs, finds where groups diverge, and proposes changes to approve.
---

# UserSim user test

Goal: show the user how their real users will use their product, given what those users already know from
competitors, and turn every place they diverge from a plain test run into a change the user can approve.

Work in a run folder `.usersim/<YYYYMMDD-HHMM>/` in the user's project (add `.usersim/` to `.gitignore` if the
project has one and it isn't there). Everything below is written there.

## 1. Plan (one confirmation from the user)

Work out these four things from the user's message and the repository, then show them in one short message and ask
the user to approve or edit them (AskUserQuestion when available). Do not start browsers before they approve.

- **Product URL.** Public or preview/staging URL. Localhost is not reachable from the cloud browsers. If only
  localhost exists, ask for a preview deploy URL (or offer to deploy one if the project already has a deploy command).
- **Tasks.** 1–3 goals in a user's words, the product's core flows: e.g. "Sign up and create your first form",
  "Find out what the paid plan costs and what it adds". Read the README, routes and pricing page to choose them.
- **Competitors.** 1–2 products this product's users already use. Take them from the user, the README or your own
  knowledge. They shape what each persona expects ("in Typeform I'd expect a template gallery first").
- **Who tests.** Always a **plain tester** (the usual methodical end-to-end check: tries to finish every task, notes
  anything broken). Plus **2–3 user groups** chosen from `references/groups.json`:
  - read the file; start from the 3 `main_groups` (each has a `persona_brief`) and pick the groups or subgroups whose `topics`, `votes_for` and `over_represented_roles` best fit
    the product's audience; prefer subgroups when one fits well;
  - turn each into a persona of 2–3 sentences: who they are (from `who`, roles, account age), how they talk and judge
    products (from `says`), and the competitors they use today with what they expect from them;
  - keep the group's name and size (`people`) so the user sees the persona is drawn from N real people.

Cells = testers × tasks. Keep it at most 12 cells (for example 4 testers × 3 tasks). Save the approved plan as
`plan.json`:

```json
{"product_url": "…", "competitors": ["…"], "tasks": ["…"],
 "testers": [{"label": "plain-tester", "kind": "plain", "persona": "…"},
             {"label": "group-1", "kind": "group", "group": "Product Makers › Design-Focused Founders",
              "people": 1200, "persona": "…"}],
 "groups_snapshot": "<snapshot field of groups.json>", "accuracy": "<accuracy field of groups.json>"}
```

## 2. Run every cell in parallel

Start one `sim-user` agent (from this plugin) per tester × task, all in the same message so they run in parallel. Give
each one: `product_url`, `task`, `persona`, `label`, and `out_file` = `.usersim/<run>/runs/<label>__task<k>.json`.
Tell the user the run has started and how many browsers are running. Each agent returns a `watch_url`; pass these on
to the user as they arrive, so the user can watch live.

If the server says capacity is full or a cap is hit, run the remaining cells in a second wave after the first finishes.
If a cell fails to start twice, record it as `not run` with the reason. Never fake a run.

## 3. Compare: where do the groups diverge?

Read all `runs/*.json`. For each task, use the plain tester's run as the baseline path, and compare each group run:

- **Outcome divergence:** the plain tester completed but a group gave up or got blocked (or the reverse).
- **Path divergence:** the first step where a group went somewhere the plain tester did not (another page, another
  button, the docs, the pricing page) and why, in their own `thought`.
- **Expectation divergence:** a group expected something from a competitor they use (a template, an import, a free
  tier, a keyboard shortcut) and the product didn't have it or hid it.
- **Effort divergence:** many more steps, backtracks or repeated actions than the baseline.
- **Shared problems:** friction every run hit, including the plain tester's (these are plain bugs or UX problems).

Each divergence needs evidence: run label, step number, the persona's thought (quoted), and the screenshot link from
the report. Do not invent divergences without a step to point at.

## 4. Variations to approve

For each divergence (most severe first, at most 8), propose 1–2 **variations**: concrete changes to this repository
that would remove it. For example, change the CTA copy in `app/page.tsx`, show the price on the landing page, or add a
"start from template" step. For each, give the files and a short description of the edit, and which groups it is for.
Do not edit anything yet.

Save the divergences and variations as `divergences.json`:

```json
{"divergences": [{"id": "d1", "task": 1, "kind": "outcome|path|expectation|effort|shared",
  "groups": ["group-1"], "summary": "…",
  "evidence": [{"run": "group-1__task1", "step": 7, "thought": "…", "screenshot": "…"}],
  "variations": [{"id": "v1", "title": "…", "files": ["…"], "change": "…", "status": "proposed"}]}]}
```

## 5. Replay

Build the replay page:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/replay.py" .usersim/<run>
```

It writes `.usersim/<run>/replay.html`: one lane per tester for each task, step by step with screenshots and thoughts,
divergences marked where they happen, and the variations listed below. Open it for the user (on macOS `open`, on Linux
`xdg-open`, otherwise give the path). In the chat, give a short summary:
- outcomes per tester and task;
- the top divergences, one line each;
- the accuracy note from `groups.json`, worded honestly.

## 6. Approve and apply

Ask the user which variations to apply (AskUserQuestion, multi-select, one option per variation). Apply only the
approved ones, on a new git branch if the project uses git. Set their `status` to `applied` (others `declined`) in
`divergences.json`, and rebuild the replay. Offer to re-run only the affected testers and tasks once the change is
deployed to a preview URL, so the user can see whether the divergence closed.

## Honesty rules

- Every number you show comes from a run file. Say "N of M runs" rather than percentages for small counts.
- The groups describe who real Product Hunt users are. They are not a validated forecast of how a given product's
  users will behave. Always show the `accuracy` note next to group results.
- A run that was blocked by a captcha or the server is a limitation of the test, not a finding about the product,
  unless the plain tester saw the same block.
