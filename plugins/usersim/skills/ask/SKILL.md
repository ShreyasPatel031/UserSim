---
name: ask
description: Quick answer to "how would a user use this, and what would they say about it?" for any website, web app, page or product. Use by default whenever the user points at a site, URL or product and asks how users would use it, react to it, get stuck on it, or what they would think or say about it, or asks to try, check or dogfood it as a user. Runs a plain tester and one simulated user group in real cloud browsers in parallel (about 3 minutes) and answers in chat. No plan to approve. For a full multi-group comparison against competitors, with a results page, use the usertest skill instead, and only when the user asks for that.
argument-hint: "<URL or product> [question, optional]"
---

# UserSim quick answer

Answer in chat in about 3 minutes. No plan to approve, no page to open. Do exactly these four steps.

## Step 1 - Decide target, task and testers (silently, no questions)

**Target.** A URL: use it. A product name: its public URL from your own knowledge. `localhost` or a private IP: ask
once for a preview or staging URL and stop (the cloud browsers can't reach it). Only a screenshot, mockup or
description: answer with your own read under the heading **"No browser: Claude's read, not a test run"**, and stop.

**Task.** One goal in a user's words, from the question ("can people find pricing?" -> "Find out what the paid plan
costs and what it adds"). If none is named, the product's core first job ("Make your first <thing> and <use it>").
Not a signup-only task unless asked.

**Testers. Always exactly these two:**

1. `plain-tester`, persona: "A methodical first-time visitor who tries to finish the task step by step and notes
   anything broken or confusing."
2. `group`: the one group below that best fits the product's likely users, unless the user named a kind of user
   ("a teacher"), in which case use that person and drop the group. Write a 2-sentence persona from the group's
   description, naming 1-2 tools this person already uses for this job.
   - **Product Makers** (6,500 real Product Hunt users): founders and makers who ship their own launches. Read
     products as builders: ROI, integrations, how it works under the hood; compare to SaaS they use. Leave when the
     value or stack fit isn't clear fast. Fits B2B, SaaS, dev and business tools.
   - **Tech Innovators** (12,814): developers, PMs and marketers; Mac apps, dev tools, GitHub, APIs. Go straight to
     technical details, pricing model and how it differs from what they know. Leave on vague pricing or limits, no
     integration, or a me-too. Fits developer, AI and productivity tools.
   - **Curious Observers** (33,248): newer, casual, broad interest, more students. Ask what it does and which
     features exist; first impressions positive. Leave when the first screen doesn't show what it does, or signup
     or a paywall comes before any value. Fits consumer apps, design tools, anything for a broad audience.

## Step 2 - Start both browsers yourself and post the watch links

Load the `usersim_*` tools if needed, then call `usersim_start_session` **twice in one message** (each with
`product_url`, `task`, `persona`). Do not let the agents start sessions: you start them so the user can watch at
once. Then post exactly this, nothing more:

> Running 2 simulated users on <site> (~3 min): a plain tester and a <Group> user (persona from <N> real Product
> Hunt users). Task: "<task>".
> Watch live: <watch_url plain> · <watch_url group>

If a start fails on capacity, retry it once after the other run finishes. If both fail, say so and stop. Never fake
a run.

## Step 3 - Let them play

In one message, start one `sim-user` agent per session. Give each: `session_id`, `study_id`, `watch_url`,
`product_url`, `task`, `persona`, `label` (`plain-tester` or `group`), `max_actions: 20`, and
`out_file: .usersim/quick-<YYYYMMDD-HHMM>/<label>.json`. Wait for both. Say nothing while they run.

## Step 4 - Answer, in this shape, under 220 words

```
**<Verdict in one line: did they get it done, and the one thing that mattered most>**

- **Plain tester:** <completed | gave up | blocked> in <n> actions. <the path, one line>
- **<Group> user:** <outcome> in <n> actions. <the path or where they left, one line>

**What they'd say**
- "<verbatim thought>" (<label>, step <n>)
- "<verbatim thought>" (<label>, step <n>)
- "<verbatim thought>" (<label>, step <n>)

**Where they stuck:** <1-3 places, each with the step and what was on screen>
**Try:** <1-2 concrete changes, only if the runs point at them>

Replays: <report or watch link 1> · <link 2>
_Simulated users, one run each, 1280x800 browser: a quick signal, not a validated forecast. Group personas
covered 65% of the broad points real Product Hunt commenters raised on 276 launches, but only ~9% of exact issues._

Want another kind of user, another task, or the full comparison against a competitor (`/usersim:test`)?
```

Rules: quotes are verbatim from the `thought` of the cited step and support the line they sit under. Every number
comes from the run files or the agents' replies. A captcha or server block is a limit of the test, not a finding,
unless the plain tester hit it too. If the user is in this product's repo and a fix clearly lives in its code, offer
to make it; don't make it unasked.
