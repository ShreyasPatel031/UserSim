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

```
/usersim:test https://your-preview-url.example.com
```

Or just ask: "user-test the signup flow on our staging site against Typeform".

Claude proposes the product URL, 1–3 tasks, 1–2 competitors and the testers, and waits for your approval before any
browser starts. A run of 4 testers × 3 tasks usually takes 5–15 minutes. Results go to `.usersim/<run>/` in your
project, and `replay.html` there is the replay.

## Who the simulated users are

The user groups come from UserSim's store of about 95,000 Product Hunt users whose public profiles were read in full.
The groups are built from aggregates only: kind of user, roles, topics, how they comment, account age. Every group has
at least 20 people, and the plugin carries no names, ids or profile text. The snapshot ships in
`skills/usertest/references/groups.json`.

**How far to trust them:** the groups describe who these people are. At group level they do **not** predict which
launches people vote for better than the population average (measured on 135 launches, November 2026). A group's run
is a structured hypothesis about how such users behave. Check the divergences it finds; don't treat them as forecasts.

## What this plugin runs, sends and stores

- **Runs locally:** the skill instructions, a `sim-user` agent per test cell, and
  `skills/usertest/scripts/replay.py`. That script uses the Python standard library only, reads the run folder and
  writes `replay.html`. It makes no network calls.
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
- **In your project:** `.usersim/<run>/`, holding plan.json, one JSON per run, divergences.json and replay.html.
  Code changes are made only after you approve them, on a new git branch when the project uses git.

## Limits

- Public URLs only; Google and GitHub sign-in are blocked (email signup is used); no payments are entered.
- Up to 12 test cells per run. Capacity is shared, so a busy server queues the second wave.

## License

MIT
