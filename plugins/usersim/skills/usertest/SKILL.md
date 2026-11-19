---
name: usertest
description: Full user test of a web product with simulated users in real cloud browsers - a plain tester plus 2-3 user groups from UserSim's bank of real Product Hunt users, on the product AND a competitor, in parallel, with a replay page, divergences and ranked changes to approve. Use only when the user asks for a full or thorough user test, a comparison with competitors, or runs /usersim:test. For a quick "how would a user use this / what would they say" question, use the ask skill instead.
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

## 2. Run every cell in parallel, on the product and a competitor

Start one `sim-user` agent (from this plugin) per tester × task × product, all in the same message so they run in
parallel. Run every tester on the user's product (`out_file` = `.usersim/<run>/runs/<label>__task<k>.json`) and on the
main competitor (`.usersim/<run>/runs/<label>__comp<k>.json`), with the same task. Seeing the same person on both is
what makes the comparison believable. Give each agent `product_url`, `task`, `persona`, `label` and `out_file`.
Tell the user how many browsers are running, and pass on each `watch_url` as it arrives.

If the server says capacity is full, run the rest in a second wave. If a cell fails to start twice, record it as
`not run` with the reason. Never fake a run.

## 3. Read every step, then analyse

Read every step of every run file (action, thought, outcome, notes, friction). Use the plain tester's run on the
user's product as the baseline. Find:

- **Outcome splits:** someone completed on one product and not the other, or a group failed where the plain tester didn't.
- **Path splits:** the first step where a group went somewhere the plain tester didn't, and why, in their own thought.
- **Expectation splits:** a group expected something from a tool they use and didn't find it.
- **Effort splits:** many more steps, backtracks or repeats.
- **Shared friction:** what most testers hit.

The cloud browsers are 1280×800. Before you rank a layout finding (a hidden label, a collapsed menu), check whether the product changes that element at wider widths: open the page yourself at 1440 or 1920 if you can, or say in the finding that it was seen at 1280px only. Put the browser size in `method`.

Every claim needs a step to point at, and the quotes you show must support the claim. Re-read the quotes under each
claim before you keep it. If a tester's words contradict the claim, change the claim.

## 4. Write session.json

Write `.usersim/<run>/session.json`. `${CLAUDE_SKILL_DIR}/references/example_session.json` is a complete real example.
Copy its shape exactly. The fields:

- `date`, `headline`, `lede`, `race_title`, `disclosure`, `method` (list of sentences): the verdict first, in plain words,
  with the real step counts. `race_title` states the step gap.
- `products`: `{"task1": {"name","url"}, "comp1": {"name","url"}}`. The keys are the run-file suffixes.
- `testers`: `label`, `name`, `short`, `slot` (0 to 3, for colour), `people` (group size, omitted for the plain tester), `who`.
- `stage_order`: one ordered list of the screens or stages a run passes through (for example Blank canvas, Drawing,
  Labelling, Connecting, Share dead end, Sign-in & captcha, Share dialog, Link copied), keyed by product key, with the
  same list for both. `stages`: for every run, `{step: stage}` for every step.
- `friction_steps`: `{run: {step: "short friction note"}}`.
- `voices`: per tester, `summary`, 3 `quotes` (`run`, `step`, `kind` delight | friction | competitor, `text` verbatim from
  the thought), and `expects` (short tags for what they expected from other tools).
- `highlights`: 5 to 8 moments in story order (`run`, `step`, `caption` of 12 words at most), covering delight, the main
  hesitation, and the competitor's wall.
- `divergences`: `id`, `title`, `summary`, `groups`, `kind`, `moments` (`run`, `step`) and `variations` (ids).
- `variations`, ranked: `id`, `rank`, `title`, `change`, `for` (labels), `evidence` (for example "4 of 4 testers
  hesitated"), `effort` (for example "S · copy" or "M · behaviour"), `risk` ("none" or one short line), `lever` (what it moves: activation speed, findability, upgrade…), `conflicts` (ids
  of variations that use the same UI slot), `divergence` (id), `before` (`run`, `step`: the step whose thought is about
  the screen being changed), and `overlays`: boxes in 1280x800 screenshot coordinates (`x`, `y`, `w`, `h`, `label`,
  optional `bg` and `fg` CSS colours) that draw the change on the real screen. Rank by testers affected × severity
  (blocked > hesitated > slower > cosmetic), then effort.

The screen shown with a step's thought is the one before that step's action, so pick `before.step` and highlight steps
by the thought, not by what the action opened. To place overlays, open the screenshot URL of the step before and read
the positions off it. Do not guess.

## 5. Build and open the page

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/replay.py" .usersim/<run>
```

It writes `.usersim/<run>/replay.html`, an interactive page with:
- the verdict and the simulated-tester disclosure;
- the race chart (each tester's steps on both products, coloured by stage);
- the ranked decision list, with evidence, before/after sliders, Approve and a "why" note;
- a highlight reel, full replays, and a side by side that shows the competitor's detours;
- voices, method and raw data.

Approved items can be copied for Claude Code or as Markdown. Open the page for the user (macOS `open`, Linux `xdg-open`,
otherwise give the path). In chat give 3 lines: the verdict, the top 3 ranked changes, and the honesty note.

## 6. Apply what the user approved

The user approves on the page and pastes the "Copy for Claude Code" text back, or names the changes in chat. Apply only
those, on a new git branch if the project uses git. Offer to re-run only the affected testers once the change is on a
preview URL, so the user can see whether the split closed.

## Honesty rules

- Every number you show comes from a run file. Say "N of M runs" rather than percentages for small counts.
- The groups describe who real Product Hunt users are. They are not a validated forecast of how a given product's
  users will behave. Always show the `accuracy` note next to group results.
- A run that was blocked by a captcha or the server is a limitation of the test, not a finding about the product,
  unless the plain tester saw the same block.
