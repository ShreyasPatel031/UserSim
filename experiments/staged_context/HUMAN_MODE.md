# Human mode: what the browser run adds on top of agent mode (18 Oct 2026)

Human mode = a simulated user signs up and works in the real product through the public UserSim MCP
(`https://35-202-98-224.sslip.io/mcp`, no token). The question is what to ask the run, and how much of what it saw
to add to the agent-mode prediction, so that predictions of **real reviewers** get better.

## Results first

1. **On top of the shipped agent mode, adding the run's product observations helps cons.**
   - Agent-mode words are rewritten from the same evidence plus the run's product notes.
   - Held out: 173 real reviewers of 5 products (Basecamp, Bitwarden, Brevo, ClickUp, GetResponse; 40 each, not in
     the evidence; 2 seeds).
   - Cons recall: 0.269 → 0.315, **+0.046, 95% CI +0.007 to +0.085** over people (+0.043, +0.001 to +0.083 when
     resampling the 5 products). It improved on 4 of 5 products; Basecamp,
     the only product with 2 runs, gained the most (+0.12).
   - Pros: 0.382 → 0.386 (+0.004, CI −0.02 to +0.03), so no change.
   - Changing at most one item instead of rewriting was slightly worse on this setup: cons −0.019.
   - Shipped: `mvp/human_mode.py`, `usersim_combine_human_run`. Details: `hm_agent_eval.py`,
     `out/human_mode/agent_mode_plus_run.csv`.
2. **Ratings: never from the run.**
   - Run-informed ratings were about a star below real reviewers. On Basecamp, run-only predicted 3.5 against an
     actual 4.55.
   - A first session's friction is not a long-term user's rating. Ratings stay agent mode's.
3. **What to ask the run: the core job done for real, not onboarding.**
   - From 420 Capterra reviewers (`out/human_mode/themes.csv`), the context-only agent already hits:
     - 53–56% of onboarding and pricing complaints;
     - only 17% of UI/navigation frictions and 10% of core-feature-depth frictions.
   - The task (`usersim_plan_human_run`) is therefore built from rivals' live complaints:
     - do the main job with 3+ items;
     - then two second-level features (views, custom fields, reports, automations);
     - then edit or reorganise.
   - **Correction (18 Oct, later):** an earlier version of this report said the old onboarding-style runs cut cons
     coverage and the core-job run did not. That came from a first, flawed judge (pros and cons scored in one call,
     one seed). Under the final judge, added on top of context on Basecamp, the five onboarding-style runs gave pros
     +0.17 and cons −0.03 (one seed), and the core-job run pros +0.03 and cons −0.01 (three seeds). So there is **no
     demonstrated advantage** of the core-job task when added to context.
   - What is supported: alone, the core-job run's notes match far more of what real reviewers wrote (cons 0.22, pros
     0.44) than the onboarding-style notes (cons 0.01, pros 0.12). That is Basecamp only.
4. **No own reviews (a new product), so context = competitors only:** free-form notes hurt and a bounded edit
   helped.
   - Product-level top-6 lists, 5 products (Basecamp with 2 runs, Bitwarden, Brevo, ClickUp, GetResponse) × 40
     reviewers × 3 seeds (`human_mode.py`, `out/human_mode/plist_all_deepall.csv`).
   - Free-form notes:
     - pros −0.071 (95% CI −0.105 to −0.039);
     - cons −0.050 (CI −0.094 to −0.003).
   - Edit at most 1 pro and 1 con, after dropping free-plan / setup / onboarding / pricing / billing / support notes:
     - **cons +0.033 (CI +0.001 to +0.066)**;
     - pros +0.008 (CI −0.004 to +0.021).
   - Allowing 2 edits: pros −0.026. Shipped as the no-own-reviews rule.
5. **Even true facts about the product don't raise per-person pros/cons when given to a context-only agent.**
   - Oracle test: notes from 12 other real reviewers of the same product, 120 people (`out/human_mode/oracle.csv`).
   - Cons fell 0.257 → about 0.21.
   - The "candidate list, ratings anchored" format improved ratings slightly (overall MAE 0.633 → 0.596).
   - With the product's own reviews in the evidence (point 1), the run's notes do help. So own-review evidence
     anchors the words, and run notes then add specifics.
6. **Sign-up is the bottleneck for anonymous runs.**

   | Product | Signed in | Product observations | Why it failed |
   | --- | --- | --- | --- |
   | Basecamp (2 runs) | yes | 9 + 8 | |
   | Bitwarden | yes | 8 | |
   | ClickUp | yes | 8 | |
   | GetResponse | yes | 7 | |
   | Brevo | yes | 6 | 24 steps of sign-up |
   | Zoho Desk | no | 0 | rejects `+` email aliases |
   | Wrike | no | 0 | rejects `+` email aliases |
   | Trello | no | 0 | sign-up hung, probably on the `+` alias |
   | Klaviyo | no | 0 | image reCAPTCHA at login |
   | Teamwork.com | no | 0 | "can't create an account" after the phone step |
   | Ecwid | no (account only) | 0 | no free plan, card required |

   Anonymous callers can't get no-`+` aliases (`anon_allow_shared_aliases: false` in `mvp/sim_mcp/limits.json`).
   With the anonymous cap of $6/day per IP, about 12 runs a day fit.

Agent-mode side (ratings, words, held-out tables): `experiments/human_experience/HANDOFF_agent_mode.md`.

## How solid this is

- **Effective sample is 5 products and 6 runs.** Every reviewer of a product shares that product's one run, so
  intervals over reviewers overstate precision. Resampling products, the own-reviews effect is +0.043 with a lower
  bound of +0.001, and one product (GetResponse) went down.
- **The rule for each case was chosen after seeing these same products.** With own reviews, a free rewrite helped
  (4 of 5 products up) and the one-item edit did not (2 of 5). With competitors only, the free rewrite hurt (0 of 5)
  and the one-item edit helped (5 of 5). The two settings measure different outputs (per-person words, product-level
  lists), so the flip is not a clean contrast. No fresh products have confirmed either rule.
- **Unmeasured run-to-run variance:** one run per product (two for Basecamp). A second run could give different notes.
- **The model alone is already strong on these products.** Without any data it matches 0.34 of cons and 0.38 of pros
  at product level; competitor-review context adds +0.02 and +0.05. A run's +0.03 on cons is the same size as the
  whole competitor context.
- **Known products.** All held-out products are established, and the model may have seen their reviews in training.
  Nothing here measures new startups, which have no reviews to score against.
- **Ratings:** "about a star too low" rests on Basecamp (3.5 predicted, 4.55 real).
- **Judge:** Gemini 2.5 Flash scores the match; no human has checked a sample. The agent-mode session measured
  resample noise at about ±0.02 on these scores.

## Caveats

- 5 products for the main result. The CI is over people, so products are not independent replicates; 4 of 5
  improved.
- The judge is Gemini 2.5 Flash, side-separated, with "2 = same specific point" counted as a match.
- Runs averaged 35 steps, and most finished only part of the task. Sign-up and onboarding took 10–25 steps.
- The eval's own reviews come from live scrapes, with 40 held out and 60 shown.

## Files

- `human_mode.py`: observability study, oracle study, product-level eval, task generator.
- `hm_agent_eval.py`: the shipped agent mode, with and without run notes, per person.
- `hm/`: anonymous MCP client and runner guide used for the runs; `out/human_mode/runs_deep/`: run results.
- `live.py`: all-in-one live scraper and normaliser; `out/live/live_reviews.csv.gz`: 7,451 reviews of 79 products.
