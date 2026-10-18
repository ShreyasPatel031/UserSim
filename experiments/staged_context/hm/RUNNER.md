# Human-mode run guide (one subagent per run)

You are a simulated user doing one realistic working session in a real product, through the public UserSim MCP
server (real cloud browser; the server records everything). Work from `/home/user/UserSim/experiments/staged_context`.

Call the MCP only with this command form:

```
python3 hm/mcp_client.py call <tool> '<json args>' --brief
```

`--brief` prints `[session_id] step N left M | url | title` plus the visible fields and their x,y. Screenshots are
saved under `hm/shots/` and the path is printed: **Read the screenshot after every action** (the field list alone
misses most of the page). Errors come back as `{"error": ...}` text.

## Steps
1. `usersim_start_session` with `product_url`, `persona` and `task` from your brief (copy them verbatim).
2. Sign up for a free account or free trial (no card) with `usersim_signup_identity` (call it to get the email and
   password to type). Finish verification with `usersim_wait_for_verification_code` /
   `usersim_wait_for_verification_link` + `usersim_open_verification_link` (mail can take 1-3 minutes; call again),
   and CAPTCHAs with the checkbox first, then `usersim_solve_captcha`. If the site insists on a phone,
   `usersim_signup_phone` / `usersim_wait_for_sms_code`. Skip onboarding questions quickly, answering as the persona.
   Spend as few steps as possible here: the session is about the product, not sign-up.
3. Inside the product, do the task: the main job end to end with 3+ realistic demo items (Demo Alpha / Beta / Gamma,
   made-up data), then the two second-level features named in the task, then edit / reorganise / filter / report.
   If something is blocked by the free plan, note it and move to the next part.
4. Stop at about 3 steps left and call `usersim_finish` with an honest outcome (`completed`, `gave_up`, `blocked`)
   and notes.
5. Write your result file (path in your brief):

```json
{"product": "...", "run_id": "...", "session_id": "...", "task": "...", "signed_in": true, "reached_product": true,
 "outcome": "completed|partial|gave_up|blocked", "steps_used": 0,
 "observations": [{"kind": "product_friction|product_benefit|agent_failure|signup_friction",
                   "feature": "which part of the product", "what": "one specific sentence"}]}
```

## What to observe (this is the point of the run)
- 6-12 `product_friction` / `product_benefit` observations about **using the product for the work**: how many clicks
  the core job took, controls that were hard to find, editing that was clumsy, views / filters / reports /
  automations / custom fields that were missing, shallow, locked behind a paid plan, or unusually good.
- Name the feature and say concretely what happened. Include what worked well, not only problems.
- Do **not** report onboarding tours, empty states, sign-up or pricing pages as product observations: those go
  under `signup_friction` or nowhere.
- `agent_failure` = your own mistakes (misclicks, wrong coordinates). They are not product facts.
- No ratings, no guesses about other users.

## Rules
- One action per `usersim_act`, each with an honest first-person `thought`. Coordinates are pixels in the 1280x800
  screenshot; prefer the x,y printed for fields. Wait out spinners with `{"type": "wait", "ms": 4000}`.
- Email sign-up only: never Google, GitHub, Microsoft or Apple sign-in. Only type the email the server gives you.
- Never invite real people, email anyone, pay, upgrade, or start anything that needs a card.
- Never print passwords. Keep any helper files in your own folder `<scratchpad>/<run_id>/` (parallel runs share the
  scratchpad), and delete any file holding the account password before you reply.
- If sign-up is truly blocked after two honest attempts, finish with `blocked`, write the file with
  `signed_in: false`, and stop.

Reply with only the result path and one line: signed_in / reached_product / outcome / steps_used.
