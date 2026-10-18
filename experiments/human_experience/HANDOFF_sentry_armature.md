# Handoff: Sentry / Armature pitch demo, plus where agent mode stands (18 Oct 2026)

## What the user wants next

**Goal:** for the Armature pitch, show UserSim on a product Armature's site features. That product is **Sentry**: in
armature.tech's demo flow, a coding agent asked to "add error tracking" picks Sentry.

Steps:
1. **Who uses Sentry**, as segment percentages from real reviews. Done; see below.
2. **Real reviewers as simulated users.** Pick real Sentry reviewers, in proportion to the segments, as personas: their
   role, company size and time using the product. Their written review stays hidden.
3. **Run them through the live MCP** on the Armature-style task (human mode).
4. **Compare user types.** Check whether the types act differently, and score each simulated user against what that
   real reviewer actually wrote (their pros and cons).
5. **Publish an artifact** in Armature's style showing it. The current page is
   https://claude.ai/artifact/KQ38kBE5fRNZZiJuSaA8oW (`results/sentry/pitch_page_v2.html`). Its numbers came from the
   first 97-review pull and from held-out evals. **No simulated user runs are on it yet.**

The user is frustrated by made-up personas, arbitrary caps and fake progress. Use real data, run real runs, and say
plainly what ran.

## Data (done)

`results/sentry/sentry_reviews_317.json` holds every review the Apify actor `zen-studio~software-review-scraper` returned
for "Sentry":
- **Sites:** G2 225, Gartner 54, Capterra 23, TrustRadius 15.
- **Run:** one run over all 4 platforms, `maxResults` 5000, `most_recent`, $0.51. The actor needs at least 2 platforms per run.
- **Format:** the schema of `mvp/review_context._all_in_one_item`. No reviewer names.
- **Missing fields:** 78 of the 317 have no job title.
- **Earlier pull:** a first pull capped at 100 returned 97 reviews. Don't use it.

Segments: role is the 217 reviewers whose title maps to a family; size is the 312 with a size.

| Role | Share | Avg rating |
| --- | --- | --- |
| Software / IT engineers | 63% (137) | 4.49 |
| Founders / CTOs / execs | 17% (36) | 4.61 |
| Team / eng managers | 7% (15) | 4.47 |
| Consultants / freelance | 3% (7) | 4.21 |
| Research / analysts | 2% (5) | 4.90 |

- **Company size:** small (≤ 50) 58%, mid-market 29%, enterprise 13%.
- **Average rating:** 4.51.
- **Top complaints** (265 cons): learning curve/UI 20%, pricing 17%, integrations 10%, reporting 10%.

## How to run the simulated users (step 3)

- Use `scripts/mcp_study_runner.py --smoke "<persona>" "<task>" --max-turns 70 --out <dir>`. It runs one session on the
  live MCP (`https://35-202-98-224.sslip.io/mcp`), driven by Claude Haiku on Vertex.
- Launch it with `PYTHONPATH=src:.`. Vertex credentials worked in this container.
- **Anonymous cap:** 3 concurrent sessions per IP, so run batches of 3. Each takes about 10–30 minutes.
- **Task used** (Armature-style): "Sign up for Sentry and set up error tracking for your team's JavaScript web app: create
  the project and get to the step where you have the SDK install snippet and DSN to add to the code."
- **Persona** = a real reviewer's role, company size and time used (Capterra only), plus "trying Sentry for the first
  time". Don't include their review text.
- **Score each run:** did it reach the snippet/DSN (judge verdict), steps taken, where it got stuck, and its friction
  notes against that reviewer's cons. Example real cons:
  - #79 Product Execution Lead: "UI was intimidating for beginners… didn't know what to do".
  - #39 Co-founder/CTO: "web app UI a bit too busy".
  - #55 Software Engineer, enterprise: "initial setup and alert tuning take time".
- **Clean up first:** two earlier batches (made-up personas, then real ones) were started and killed with no results.
  Their server sessions should have timed out.
- **Killing runs:** never `pkill -f mcp_study_runner`; it kills your own shell. Use
  `ps -eo pid,args | grep "[p]ython scripts/mcp_study_runner"`.

## Agent mode: the context side (merged to main)

- **What it is:** MCP tool `usersim_predict_experience`, code in `mvp/agent_mode.py`. Full results:
  `experiments/human_experience/HANDOFF_agent_mode.md`.
- **Ratings:**
  - The level comes from the product's own recent reviews, shrunk toward a prior. The prior is the average of the
    competitors' mean and the people-like-them estimate.
  - Within-product persona offsets are added on top (`for_this_persona`); tenure matters most.
  - `most_likely` gives a whole-star score.
- **Words:** the validated predictor prompt plus people-like-them, competitors and the most similar own reviews.
- **New products:** `product_profile` gives competitor-based likely users, use cases, values/frustrations and competitor
  ratings. `discover_rivals` merges the planner's picks with up to 6 model-named rivals.
- **Identity gate:** a model checks that own reviews are of the product at `product_url`, using its homepage text
  (`page_about`), and that each rival is a real competitor. The Armature run correctly rejected Armature Fabric's
  reviews (#107).
- **Held out vs the plain context agent:**
  - Capterra overall MAE .631 → .562 with own reviews, .586 without (.44 as `most_likely`).
  - Words: overall-experience +0.02–0.05, cons +0.02–0.05.
  - G2 ratings without own reviews are worse (.845 vs .760). That G2 sample is unusually low-rated.
- **Human mode:** `mvp/human_mode.py`, built by session usersim-9c, merged in #94. Run notes add cons +0.03–0.05; ratings
  are never taken from runs.

## Not done / blocked

- **Not deployed.** The live server hasn't been redeployed with agent mode and has no `APIFY_TOKEN`. Per
  `docs/mcp/OPERATIONS.md`, deploy = merge to main and secrets go through `gcloud`. This container has no gcloud login.
- **YC Fall 2026 (20 startups):**
  - `yc_fall20.py plan` is done: 6–8 candidate rivals each.
  - The scrape-and-run step is not done. It was held for Apify budget, at about $80 of $105/month at last check.
- **5 full 108-cell MCP studies:** blocked by the anonymous cap of 12 cells per study.
  - The user hasn't approved raising it, nor provided `MCP_CLIENT_TOKEN`.
  - Don't loosen the public limits without the user's explicit OK.
- **Apify key:** the user pasted it in chat. Don't commit it, and suggest rotating it. Pass it as an environment
  variable only.
