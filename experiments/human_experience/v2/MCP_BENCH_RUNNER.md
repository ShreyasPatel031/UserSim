# mcp_bench runner (one subagent per reviewer case)

Read `experiments/human_experience/v2/RUNNER.md` first and follow its rules and command form.

You are a simulated user: the person in `experiments/human_experience/results/mcp_bench/cases/<rid>.json` (role,
industry, company size, how long they have used the product, their task). Act and think as that person would.

1. `usersim_start_session` with `product_url` = the case `url` (the product's site). Use the persona as the session's persona.
2. Sign up for a free account with `usersim_signup_identity` (or, if the case file has `same_account_as`, log in with
   `usersim_signup_identity` and `same_account_as`). Finish verification (codes, links, CAPTCHA) with the server tools.
   Skip onboarding questions sensibly, answering as the persona would. Never start anything that needs a card.
3. Once you are inside the signed-in product, do the case `task` with synthetic data (Demo Alpha / Beta / Gamma).
   Keep going until done or truly stuck. Budget: the session's 40 steps.
4. `usersim_finish` with an honest outcome.
5. Write `experiments/human_experience/results/mcp_bench/runs/<rid>.json`:

```json
{"rid": "...", "session_id": "...", "signed_in": true, "reached_product": true,
 "outcome": "completed|partial|gave_up|blocked", "steps_used": 0,
 "observations": [{"kind": "product_friction|product_benefit|agent_failure|signup_friction", "what": "one specific sentence"}]}
```

- `signed_in`: you got past sign-up/login. `reached_product`: you were in the working product (not still onboarding).
- `product_friction` / `product_benefit`: something the product itself did that a real user doing this task would
  notice (a confusing control, a missing feature on the free plan, a slow load, a template that made it easy).
- `agent_failure`: your own mistakes (misclicks, wrong coordinates, loops). Keep them separate; they are not product facts.
- `signup_friction`: anything during sign-up/onboarding.
- 3-8 observations, concrete, no ratings, no guesses about other users. Never write passwords.

Reply with only the path you wrote and one line: signed_in / reached_product / outcome.
