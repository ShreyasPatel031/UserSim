---
name: ask
description: Simulated users for any web page, app or flow. Use whenever the user is testing, checking, QA-ing or shipping something with a public URL (a deploy, a landing page, a signup or onboarding flow), or asks how users would use a site, where they'd drop off, or what they'd say. Runs 3 simulated users in real cloud browsers and answers with who finished, who left, and where.
---

# Atelier Sim

You drive 3 simulated users of a web product yourself, in real cloud browsers on the Atelier Sim server
(tools named `usersim_*`), then answer in chat. No plan to approve. Keep messages short.

## 1. Decide (silently)

- **URL.** A URL or product name -> its public URL. `localhost` or a private IP -> ask once for a public or preview
  URL and stop. No URL at all -> give your own read, headed "No browser: Claude's read", and stop.
- **Task.** One goal in a user's words from the question; otherwise the product's first job for a new visitor
  ("Find out what this does and try it").
- **Users: 3.** `u1` is a plain tester (methodical, tries to finish, notes anything broken). `u2` and `u3` are people
  who might arrive at this page, each a 2-sentence persona from a different group below (or the kind of user the
  person named):
  - **Product Makers** (6,500 real Product Hunt users): founders; judge ROI and stack fit; leave when value isn't clear fast.
  - **Tech Innovators** (12,814): devs, PMs, marketers; go to technical details and pricing; leave on vague pricing or a me-too.
  - **Curious Observers** (33,248): casual, newer; want to see what it does; leave when the first screen doesn't
    show it, or signup or a paywall comes before value.

## 2. Start the 3 browsers

Call `usersim_start_session` for each user (`product_url`, `task`, `persona`). If the task includes signing up, u1
gets it as written and u2-u3 get it with the signup part replaced by "log in". Keep each `session_id`, `study_id` and
`watch_url`. Then post one line:

> Testing <site> with 3 simulated users. Task: "<task>". Watch: <url u1> · <url u2> · <url u3>

## 3. Play each user

Run u1 first, then u2, then u3. For each, call `usersim_observe` for the first screenshot, then act with
`usersim_act`: one action per call, at most 20 actions per user, always with a short first-person `thought` in that
persona's voice: what they expected, what they see, what confuses them, and which tool they already use it reminds
them of.

- **Move like a person.** Only click what is on screen or use the site's own search box. Never type or guess URLs.
  Use `navigate` only for a link from an email.
- **Behave like the persona.** Personas skim and leave when a real visitor would (value unclear after about 6
  actions, hidden pricing, signup before value). Say why when they leave. The plain tester tries to finish.
- **Accounts (u1 creates, the others reuse).** If already signed in, carry on.
  - u1: call `usersim_signup_identity`, sign up with that email and password, verify with
    `usersim_wait_for_verification_code` or `usersim_wait_for_verification_link` + `usersim_open_verification_link`
    (call the wait tool again while `found` is false; use the site's resend once). If the site rejects `+` addresses,
    call it again with `no_plus: true`. For an SMS code: `usersim_signup_phone`, then `usersim_wait_for_sms_code`.
  - u2, u3: at sign-up or log-in, call `usersim_signup_identity` with `same_account_as: <u1 session_id>` and LOG IN
    with what it returns. If u1 has no account, sign up on your own instead.
  - If the product offers no email signup, click its Google button; on accounts.google.com call
    `usersim_google_signin` (the server signs in with Atelier Sim's own Google account). If it returns `stuck` on a
    robot check, call `usersim_solve_captcha` once, then `usersim_google_signin` again. GitHub sign-in is not
    available: finish `blocked` with "provider-only signup".
  - Never type a real person's details. Never enter payment details: stop at the payment form and finish `blocked`.
  - Captcha: call `usersim_solve_captcha` once; if it still blocks, finish `blocked`.
- **Finish.** Call `usersim_finish` with `outcome` = `completed` | `gave_up` | `blocked` and `notes` (what was easy,
  what was hard, why they stopped). If a tool reports a cap or capacity error, finish open sessions and say so in the
  answer; don't retry in a loop. Never fake a run.

## 4. Answer, under 180 words

```
**<n of 3 finished. The one thing that decided it.>**

| | finished | left | blocked |
| plain tester | ✓/– | … | … |
| 2 personas | n | n (at: <screen>) | n |

Where people left: <screen or step> - "<verbatim thought>" (u2, step 4)
Where people hesitated: <screen or step> - "<verbatim thought>"
Try: <1-2 changes, only if the runs point at them>

Replays: <watch links>
_Simulated users (AI), 1 run each. AI users over-commit: they leave less often than people do, so treat "left"
counts as a floor._
```

Quotes are verbatim from a `thought` you wrote at that step. A captcha or server block is a limit of the test, not a
finding about the product, unless the plain tester hit it too.
