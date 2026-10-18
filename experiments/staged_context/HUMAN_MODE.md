# Human mode: what the browser run adds on top of agent mode (18 Oct 2026)

Human mode = a simulated user signs up and works in the real product through the public UserSim MCP
(`https://35-202-98-224.sslip.io/mcp`, no token). The question is what to ask the run, and how much of what it saw
to add to the agent-mode prediction, so that predictions of **real reviewers** get better.

## Results first

1. **On top of the shipped agent mode, adding the run's product observations helps cons.**
   - Agent-mode words are rewritten from the same evidence plus the run's product notes.
   - Held out: 173 real reviewers of 5 products (Basecamp, Bitwarden, Brevo, ClickUp, GetResponse; 40 each, not in
     the evidence; 2 seeds).
   - Cons recall: 0.269 → 0.315, **+0.046, 95% CI +0.007 to +0.085**. It improved on 4 of 5 products; Basecamp,
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
   - The old onboarding-style runs (5 on Basecamp) cut product-level cons coverage from 36% of reviewers to 15%. The
     new runs did not.
4. **No own reviews (a new product), so context = competitors only:** free-form notes hurt and a bounded edit
   helped.
   - Product-level top-6 lists, 3 products × 40 reviewers × 3 seeds (`human_mode.py`, `out/human_mode/plist_*`).
   - Free-form notes: pros 0.42 → 0.36, cons 0.28 → 0.21.
   - Edit at most 1 pro and 1 con, after dropping free-plan / setup / onboarding / pricing / billing / support notes:
     cons 0.28 → 0.31, reviewers covered 42% → 44%.
   - This is small, on 3 products, and has no CI yet. Shipped as the no-own-reviews rule.
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
