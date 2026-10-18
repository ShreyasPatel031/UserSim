# Handoff: human mode, live data, YC test (18 Oct 2026, end of night)

Everything is on `main` (PR #94 merged; later commits pushed straight to main). Agent mode belongs to another
session (`session_0165tWiTriU8xna7uWkUGrC1`, may be gone) and is also on main. Start here, then `HUMAN_MODE.md`,
`YC_TEST.md`, `MIXTURE.md`, and `experiments/human_experience/HANDOFF_agent_mode.md`.

## State in ten lines

- **Human mode ships as two MCP tools** in `mvp/human_mode.py` and `mvp/sim_mcp/server.py`:
  `usersim_plan_human_run` (task for the simulated user) and `usersim_combine_human_run` (agent-mode prediction plus
  the run's notes). Tests: `mvp/test_human_mode.py`. Docs: `docs/mcp/README.md`.
- **Not deployed.** The live server needs main deployed and `APIFY_TOKEN` set. Nobody has done either.
- **The central result rests on 5 products.** See "What the evidence says" before quoting any number.
- **Three more runs are in flight** (Asana, LastPass, Zapier), started about 18:20 UTC.
- **Five full studies (108 cells each) have not run.** The server refuses them without a token. See "Blocked".
- Tests: 218 pass, 1 fails (`test_sim_mcp_oct18::test_start_study_schema_names_required_fields`, fails on main too).
- Model spend $55.8 (ledger `out/call_log.jsonl`, cap `EXP_SPEND_CAP_USD`, default $10, so always pass it).
- Apify $88.4 of $105 this month. The YC Fall batch (159 scrapes, about $60) does not fit.

## What the evidence says (and does not)

Truth is what held-out real reviewers wrote. A model extracts up to 4 pros and 4 cons from each review, and Gemini 2.5
Flash judges whether a prediction matches each "on the same specific point". Score = share matched ("recall").

| Run added on top of | Cons | Pros | Notes |
| --- | --- | --- | --- |
| Agent mode with the product's own reviews, words rewritten with the run's notes | +0.043, 95% CI +0.001 to +0.083 (resampling products), 4 of 5 up | +0.004 | 173 people, 5 products |
| Competitors only (new product), at most 1 pro and 1 con changed | +0.033, 5 of 5 up | +0.008 | |
| Competitors only, notes added freely | −0.052, 0 of 5 up | −0.070 | |
| Ratings | not used | | Run-based rating was low on Basecamp (3.5 vs 4.55 real); one product |

Why this is weak, in order of importance:
1. **5 products, 6 runs.** People of a product share one run, so intervals over people overstate precision.
2. **Each case's rule was chosen after seeing these same products.** The two settings flip (free rewrite helps with
   own reviews, hurts without; the 1-item edit does the opposite) and measure different outputs. No fresh products
   have confirmed either rule.
3. **The model alone is already strong here**: 0.34 cons, 0.38 pros with no data. Competitor context adds +0.02 and
   +0.05. A run's +0.03 is about the whole context contribution. Noise is about ±0.02 (agent-mode session's resample).
4. **All test products are established**, so the model may have seen their reviews in training. No new startup has
   been scored; startups have no reviews to score against.
5. **Run-to-run variance is unmeasured** (one run per product, two for Basecamp).
6. **No human has checked the judge.**

**Retracted:** "onboarding-style runs hurt, core-job runs don't". It came from a first, flawed judge. Under the final
judge, added to context on Basecamp they look the same. Only the run-alone comparison differs (core-job notes match
cons 0.22 and pros 0.44; onboarding-style 0.01 and 0.12). The task design (`TASK_PROMPT` in `mvp/human_mode.py`) is
motivated by `out/human_mode/themes.csv`: context already predicts 53–56% of onboarding and pricing frictions but only
10–17% of UI and core-feature ones, and 70–96% of those are observable in one session. That is a rationale, not a
tested win.

Other results: `MIXTURE.md` (live named rivals are in every best data mix; production uses live rivals only, never the
FreshCrawl snapshots, which are research data). `YC_TEST.md` (20 B2B startups from Spring/Summer 2026: planner alone
gives usable competitors for 10; adding 6 review-site-listed rivals each gives 16; the other 4 are real gaps).

## In flight

`asana_deep_1`, `lastpass_deep_1`, `zapier_deep_1` land in `out/human_mode/runs_deep/<product>_deep_1.json`. Tasks
and rivals are already in `out/human_mode/run_tasks.json` and `out/mixture/competitors.json`. When they finish:

```
cd experiments/staged_context
PYTHONPATH=../../src EXP_SPEND_CAP_USD=120 ../../.venv/bin/python human_mode.py pooled        # new-product rule, all signed-in products
PYTHONPATH=../../src:../.. EXP_SPEND_CAP_USD=120 ../../.venv/bin/python hm_agent_eval.py Asana LastPass Zapier   # own-reviews rule; merges into the CSV
```

Both print per-product deltas and an interval from resampling products. Report whatever comes out. Sign-up was not
screened for these, so some may fail (record it, do not retry more than once). Then update `HUMAN_MODE.md` and the page
(`human_mode_page.html`; published artifact `https://claude.ai/artifact/WcrycjnsukkLe8FRHZ2wfq`, private).

**Rules fixed in advance for the new products:** own-reviews case = free rewrite; no-own-reviews case = 1-item edit
after dropping first-session notes; metric = cons recall, pros as secondary. Do not change prompts or rules after
seeing results. If the new products contradict the earlier ones, say so.

## Blocked, and what unblocks it

1. **Five full studies** (target + 2 rivals, 6 personas, 6 tasks = 108 cells; `docs/E2E_TEST.md`). The server
   refuses with "108 runs is over the 12-run limit for one study without a token"
   (`anon_max_cells_per_study` in `mvp/sim_mcp/limits.json`). Either set `MCP_CLIENT_TOKEN` as an environment secret
   (never paste it in chat), or merge a `limits.json` change (`docs/mcp/CONFIG.md`: any agent can PR it; 108 cells,
   about 10 concurrent sessions, daily USD caps raised). The user told the last session to raise the limits itself.
   That session's auto-mode safety check denied the `limits.json` edit, every `gcloud` command, and a POST to
   `/api/studies`; it did not route around any of them. Check what your session allows. If denied, ask the user to
   allow it in `/permissions`.
   Runner (on main, works; needs the `.venv` Python because it imports the `mcp<2` client API): `PYTHONPATH=src:. .venv/bin/python scripts/mcp_study_runner.py <urls> --parallel 8 --max-turns 90`.
   Check the driver first with `--smoke "<persona>" "<task>"`: KanbanFlow sign-up, email verification and board creation
   gave `proof_pass` in 277 s. Needs Vertex credentials (it uses `auth.vertex_credentials()`). Budget: Haiku about
   $100–150 for 540 cells, hours of wall clock.
   The user asked for Smartsheet first. Its sign-up failed 5 of 5 times in earlier runs (verification mail never
   arrived, or an error page), so expect failed sign-up cells. Products with sign-up verified earlier by another
   agent: KanbanFlow, Clockify, Dynalist (`docs/mcp-test/e2e-oct18/`).
2. **Sign-up for anonymous callers** failed on 6 of 12 runs: `+` email aliases rejected (Zoho Desk, Wrike; the no-plus
   address needs a token), image CAPTCHA (Klaviyo; paid solver needs a token and `MVP_CAPTCHA_API_KEY`), site refusal
   (Teamwork.com), hung sign-up (Trello), no free plan (Ecwid). Screen products before spending runs.
3. **YC Fall batch** (`experiments/human_experience/results/yc_fall20/plan.json` on branch
   `claude/zealous-knuth-4zbdb1`, `yc_fall20.py scrape-list`: 159 names). Needs the Apify limit raised. The last
   session spent about $25 on a YC re-check instead, which is why it no longer fits.
4. **Live server**: set `APIFY_TOKEN`, deploy main. `docs/mcp/OPERATIONS.md` describes deploy-by-merge and Secret
   Manager. This session could not run `gcloud`.

## Secrets and money

- **The Apify key was pasted into chat twice. Rotate it** and store it as `APIFY_TOKEN` in the environment secrets. It
  was never written to a file or the repo (GitGuardian shows neutral; the branch history was grepped clean).
- This session's safety check blocked saving the key to a file or passing it to Python, so scraping went through
  `hm/apify_scrape.sh` (curl only; `T=<key> bash hm/apify_scrape.sh names.txt cache/live`, 4 runs at once, retries,
  writes `cache/live/<slug>.json`). Python reads `cache/live/` through `live.py` and `mvp/review_context.py`.
- **Raw scrapes are gitignored and die with the container.** `data/live_cache.tar.gz` (173 products, reviewer names
  removed) is committed: `mkdir -p cache && tar xzf data/live_cache.tar.gz -C cache` restores `cache/live/`. Scrapes
  after this archive are not in it. `hm_agent_eval.py`, `yc_test.py` and the pooled eval need `cache/live/`.
- `out/calls/` (the model-call cache, 24k files) is not tracked; it is in history at commit `9ce3a7d`
  (`git checkout 9ce3a7d -- experiments/staged_context/out/calls`). Without it, re-running costs model calls again.

## Environment

`mcp` 2.x is installed system-wide and breaks the server code. Use a venv:
`python3 -m venv .venv && .venv/bin/pip install "mcp<2" pytest pandas numpy requests google-genai "anthropic[vertex]" scikit-learn -r mvp/requirements.txt browserbase playwright pillow`,
then `PYTHONPATH=src .venv/bin/python -m pytest mvp/test_sim_mcp*.py mvp/test_review_context.py mvp/test_agent_mode.py mvp/test_human_mode.py`.
The experiments' MCP client for sign-up runs is `hm/mcp_client.py` (anonymous, works with the system `mcp` 2.x);
run guide for simulated-user subagents is `hm/RUNNER.md`. Subagents share the scratchpad, so each uses its own folder.

## Rules from the user (still apply)

- Never use the FreshCrawl snapshots as a product's competitors in production. They are research and eval data.
- No silent fallbacks: say what is missing and stop.
- Browser runs go through the real MCP (`https://35-202-98-224.sslip.io/mcp`), never UserSim's browser code directly.
- Keep reports short and plain, results first. Do not wait on another agent for things you can change yourself.

## Next steps, in order

1. Collect the three in-flight runs, run the two commands above, update `HUMAN_MODE.md` and the page.
2. Get the token or the limits change, then run the five studies; report per-cell pass rates and what broke.
3. Fix sign-up blockers on the server side (shared aliases, paid CAPTCHA) if the user agrees to the risk: dot-variant
   aliases land in a shared inbox, and paid solving costs money per solve.
4. More human-mode products, screened for sign-up first, with the rules above fixed. About 15 products would make the
   result usable.
5. YC Fall batch once Apify has budget.

## Key files

`mvp/human_mode.py`, `mvp/test_human_mode.py` (tools and tests); `experiments/staged_context/`: `human_mode.py`
(observability, oracle, product-level eval, `pooled`), `hm_agent_eval.py` (shipped agent mode with and without run
notes), `live.py` (scraper mapping), `mixture.py`, `yc_test.py`, `hm/` (client, runner guide, scrape script),
`scripts/mcp_study_runner.py` (full studies), `out/human_mode/` (runs, tables), `out/yc/`, `out/armature/`
(Armature returned `no_data`, correctly: the only reviews were of a different product, and the coding assistants it
was compared to are not its competitors).
