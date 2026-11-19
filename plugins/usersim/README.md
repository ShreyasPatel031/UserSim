# UserSim user testing for Claude Code

Test your web product with simulated users, without leaving your Claude Code session. UserSim opens real cloud
browsers on your site. A **plain tester** (the usual end-to-end check) and **2–3 user groups** drawn from UserSim's
bank of real Product Hunt users each try your key tasks, in parallel. Claude then:

- **replays** every run step by step, with screenshots and each simulated user's thoughts;
- finds where the groups **diverge** from the plain run: they gave up, took another path, expected something a
  competitor has, or needed far more steps;
- proposes concrete **variations** (changes to your code) for each divergence, and applies only the ones you approve.

It works for public websites and web apps, including preview and staging deploys. Localhost is not reachable.

## Install

```
/plugin marketplace add ShreyasPatel031/UserSim@claude/usersim-plugin
/plugin install usersim@usersim
```

No account, API key or token is needed.

## Use

Point at anything and ask:

```
/usersim:ask https://excalidraw.com
```

or just say "how would a user use cal.com, and what would they say about it?" Claude starts two simulated users in
real cloud browsers at once, a plain tester and the user group that fits the product, and posts links so you can
watch them live. In about 3 minutes it answers in chat: what each did, where they got stuck, what they said in their
own words, and what to try. There is no plan to approve.

For the full study, ask for it or run:

```
/usersim:test https://your-preview-url.example.com
```

Claude proposes 1–3 tasks, a competitor and 2–3 user groups, and waits for your approval. It then runs every tester
on your product and the competitor in parallel, builds `replay.html` (race chart, ranked changes with before/after,
highlights, side by side) and applies only the changes you approve. This takes 10–20 minutes.

Results go to `.usersim/<run>/` in your project. Localhost is not reachable; use a preview or staging URL.

### From Claude chat (claude.ai or the desktop app)

Plugins run in Claude Code. In Claude chat, add the server as a custom connector (Settings → Connectors → Add
custom connector, URL `https://35-202-98-224.sslip.io/mcp`, no sign-in) and ask the same question.

## Who the simulated users are

The user groups come from UserSim's store of about 95,000 Product Hunt users whose public profiles were read in full.
The groups are built from aggregates only: kind of user, roles, topics, how they comment, account age. Every group has
at least 20 people, and the plugin carries no names, ids or profile text. The snapshot ships in
`skills/usertest/references/groups.json`.

**How far to trust them:** group reactions are simulated. On 276 past Product Hunt launches, group panels covered 65% of the
broad points real commenters raised, but only about 9% of the exact issues, below a plain prompt with no personas
(13.5%). How these groups behave inside a product has not been validated yet. Treat each divergence as a hypothesis
with a step you can watch, not as a forecast.

## What this plugin runs, sends and stores

- **Runs locally:** the skill instructions, a `sim-user` agent per test cell, and
  `skills/usertest/scripts/replay.py`. That script uses the Python standard library only, reads the run folder and
  writes `replay.html` from `skills/usertest/assets/report.html`. It makes no network calls. When you open
  `replay.html` in a browser, the page loads its fonts from Google Fonts and its screenshots from UserSim's report
  links. Approvals and notes are kept in that browser's local storage.
- **Connects to:** the UserSim MCP server at `https://35-202-98-224.sslip.io/mcp`. It runs on Google Cloud in the US
  and has no other declared connectors.
- **Sends to the UserSim server:**
  - the product URL, the task text and persona text you approved;
  - each browser action and the simulated user's short "thought" for it.

  Your source code is **not** sent. Claude reads your repository locally to choose tasks and to propose and apply
  changes.
- **What the server does:**
  - opens the product URL in a browser on UserSim's own machines, and records screenshots, steps and thoughts;
  - runs an independent judge (Gemini) over the run;
  - for signups, uses UserSim-owned email aliases and a UserSim phone number. No personal details of yours are typed
    into your product.
  - If a captcha blocks a run, the server may send that page's captcha to a captcha-solving service.
- **Stored:** run reports, screenshots and steps are kept by UserSim (Google Cloud Storage). Anyone who has a run's
  watch or report link can open it, so don't test pages that show private data. To have a run deleted, open an issue
  in this repository with its study id.
- **In your project:** `.usersim/<run>/`, holding one JSON per run; for a full study also plan.json, session.json
  and replay.html.
  Code changes are made only after you approve them, on a new git branch when the project uses git.

## Limits

- Public URLs only; Google and GitHub sign-in are blocked (email signup is used); no payments are entered.
- A quick answer uses 2 browsers. A full study uses up to 24 (4 testers × 3 tasks × 2 products). Capacity is
  shared, so a busy server queues the rest.

## License

MIT
