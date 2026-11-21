---
name: ask
description: Simulated users for any web page, app or flow. Use automatically, without being asked, whenever the user is testing, checking, QA-ing, verifying, dogfooding or shipping something with a public or preview URL (a deploy, a landing page, a signup or onboarding flow, a new feature), and whenever they ask how users would use a site or product, where they'd drop off, or what they'd say. Runs 5 simulated users in real cloud browsers in parallel (about 3 minutes) and answers in chat with the spread of outcomes - who finished, who left, and where. For a full comparison against competitors with a results page, use the usertest skill, only when asked.
argument-hint: "<URL or product> [question, optional]"
---

# Atelier Sim

Run it, then answer in chat. No plan to approve. Keep everything short.

## 1. Decide (silently)

- **URL.** A URL or product name -> its public URL. `localhost` or a private IP -> ask once for a preview URL and stop.
  No URL at all (a screenshot, a description) -> give your own read, headed "No browser: Claude's read", and stop.
- **Task.** One goal in a user's words from the question or the change being tested; otherwise the product's first
  job for a new visitor ("Find out what this does and try it").
- **Users: 5.** `u1` is a plain tester (methodical, tries to finish, notes anything broken). `u2`-`u5` are people
  who might arrive at this page, written as 2-sentence personas, spread across these groups by fit (at least 2
  groups), or across the kind of user the person named:
  - **Product Makers** (6,500 real Product Hunt users): founders; judge ROI and stack fit; leave when value isn't clear fast.
  - **Tech Innovators** (12,814): devs, PMs, marketers; go to technical details and pricing; leave on vague pricing or a me-too.
  - **Curious Observers** (33,248): casual, newer; want to see what it does; leave when the first screen doesn't
    show it, or signup or a paywall comes before value.

## 2. Start all 5 browsers yourself, in one message

Call `usersim_start_session` 5 times in one message (`product_url`, `task`, `persona`). Then, in one message, write

> Testing <site> with 5 simulated users (~3 min). Task: "<task>". Watch: <url u1> · <url u2> · … · <url u5>

followed by 5 `sim-user` agents (one per session) with `session_id`, `study_id`, `watch_url`, `product_url`,
`task`, `persona`, `label`, `max_actions: 25`, `out_file: .atelier-sim/<YYYYMMDD-HHMM>/<label>.json` (relative path, as
written), and for u2-u5 `account_from: <u1's session_id>`. Only u1 signs up; the others log in with u1's account when
they reach sign-up (one account per site per test). A start that fails on capacity is retried once when another
finishes. Never fake a run.

If u1 ends `blocked` with "provider-only signup" (the product only allows Google/GitHub for new accounts), lead the
answer with that as a limit of the test, not as users dropping off, and report only what users saw before sign-up.

## 3. Answer, under 180 words

```
**<n of 5 finished. The one thing that decided it.>**

| | finished | left | blocked |
| plain tester | ✓/– | … | … |
| 4 personas | n | n (at: <screen>, <screen>) | n |

Where people left: <screen or step> - <n> users - "<verbatim thought>" (u3, step 4)
Where people hesitated: <screen or step> - "<verbatim thought>"
Try: <1-2 changes, only if the runs point at them>

Replays: <links>
_Simulated users (Claude), 1 run each. Claude users over-commit: on real traces they leave less often than people do,
so treat "left" counts as a floor._
```

Quotes are verbatim from the cited step's `thought`. Numbers come from the run files. A captcha or server block is a
limit of the test, not a finding, unless the plain tester hit it too.
