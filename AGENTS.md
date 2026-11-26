# Agent notes (UserSim)

Before connecting or starting a study, read:

- **[docs/mcp/CONFIG.md](docs/mcp/CONFIG.md)** — runtime settings in `mvp/sim_mcp/limits.json` (PR to main, no approval needed)
- **[docs/mcp/OPERATIONS.md](docs/mcp/OPERATIONS.md)** — deploy (merge main), secrets (`gcloud`), health checks
- **[docs/mcp/README.md](docs/mcp/README.md)** — **For client agents** (public MCP URL, no token, no local engine or secrets)
- **[docs/E2E_TEST.md](docs/E2E_TEST.md)** — full study only: target + 2 competitors, 6 personas, 6 tasks, 108 cells, comparison report

## Rule for every agent: a person is pulled whole or not at all (Shreyas, Nov 5 2026)

A Product Hunt person is saved only when **every** tab (about, upvotes, activity, forums, reviews, collections and their
items, stacks, hunted, made/product pages, followers, following) has been read to Product Hunt's own end **and** the profile
header counts are stored. Anything less is not written, not counted, not reported.

- No agent designs, approves, builds, runs or publishes a "lists-only", "light", "fast-first" or "capped" pull of new
  people, whatever it is called. The only stops allowed are Product Hunt's own (recorded as such in the paging record).
- People already saved incomplete are never purged. They are kept, marked incomplete, and finished by a completion pass
  that re-reads every missing or short tab to Product Hunt's end; a person counts as complete only when that pass has
  passed the output check. Completion passes are required, not forbidden (Shreyas, Nov 5 03:25 UTC).
- The code enforces it: the pull driver writes a person's file only when the pull is complete (full-only mode). Any build
  that can write an incomplete person fails its audit.
- The population agent scores a sample of saved people against this definition every 30 minutes and FAILs loudly on any
  incomplete saved pull.
- Progress is reported as **complete people**, read from the store. A rate of pulls, pages or lists is never reported as
  people.
- Speed never comes from getting around Product Hunt's blocks. No agent builds or runs IP or fingerprint rotation on a
  block, challenge re-clearing, or anything else meant to evade Cloudflare. A blocked VM backs off on the same IP: it pauses (10 min,
  doubling on each further block, cap 2 h), then resumes at half the workers, and steps back up after an hour clean
  (Shreyas, Nov 5 05:35 UTC). The sustainable rate is whatever Product Hunt allows without evasion.
- Any agent that sees this rule broken alerts Grok Bot by webhook within 1 minute, naming the agent.

## Rule for every agent: no caps, no dropped fields (Shreyas, Nov 13 2026)

- **No caps on pulls.** No agent puts a cap, sample, "pilot", "first N", day limit or capacity percentage on a data pull, and no
  agent cancels or shrinks a pull. A pull fetches everything the source returns, for everyone it applies to; the only limits are
  the source's own (its rate limit, its blocks, handled by the back-off rule above) and not starving the live midnight capture.
  If a pull does not fit in a day it continues the next day. Analyses on held data may use samples; pulls may not.
- **No dropped fields.** Everything that is pulled is kept, in the raw file and all the way into the built store and warehouse.
  A store or table build that leaves out a field present in the raw files fails its check. (Found Nov 13: the store build dropped
  `about.joined` and `ph_user_id`, so agents reported "no account age held" while every saved profile had it.)
- Before believing "we don't hold X", read a raw file, not only the built store.
- Any agent that sees a cap or a dropped field fixes it and tells Shreyas.

## Rule for every agent: how models are chosen (Shreyas, Nov 13 2026)

1. **North star first: predictive value.** Product Hunt daily / weekly / monthly top 3 / 5 / 10. A model is only reliable if it
   predicts; an explanation without predictive value is not used.
2. **Second metric: observability.** For every forecast we must be able to say why it says what it says, and simulate as much
   as possible of how users react to a product (who backs it, what they say, where it lands).
3. **Choosing between models.** When an explainable or simulating model predicts as well as a black-box one (its north-star
   score is not worse beyond noise on the same days, paired), the explainable one wins and replaces it. When it predicts clearly
   worse, the black box stays as the forecast and the explainable model runs beside it as the explanation, labelled with its own
   measured accuracy. The orchestrator takes these calls and records each one in docs/RESEARCH_LOG.md.
4. Every explanation shown anywhere carries its measured predictive value (number, days, backtest or forward).
5. **Deploying.** A model that is better on the leak-free backtest (paired on the same days, interval clear of noise on a
   north-star cut) is deployed; there is no wait for live days (Shreyas, Nov 13: "if its better on backtest deploy"). The model
   it replaces keeps running as a forward shadow line, and the orchestrator reverts if the new one trails it on scored live days.

## Rule for every agent: who owns pulls, and downtime (Shreyas, Nov 13 2026)

- **Long-term pulls belong to the Cursor fleet.** Every standing or long-running pull (the 15-minute launch-day capture, the
  day-close and first-comment reads, weekly and monthly close reads, daily people jobs, history backfills, people completion)
  runs on the Cursor agent's always-on machines. The Data Feeder is for one-off experimental pulls only. No agent files a
  standing pull with the Data Feeder.
- **Live feeds come first.** New incoming data is never dropped to make room for historical pulls; machines move from
  historical work to live feeds the moment a live feed falls behind.
- **Downtime is audited, not discovered.** The population agent checks every live feed every 15 minutes against its maximum
  allowed gap (15-minute capture: 20 minutes), alerts Grok Bot by webhook and the orchestrator within 1 minute of a breach,
  re-alerts every 30 minutes, and keeps the downtime ledger (raw/_audit/downtime_ledger.jsonl). A gap nobody raised is a
  failure of the audit.

## Rule for every agent: the website's live board and published predictions (Shreyas, Nov 14 2026)

- **The live leaderboard on the website is always live and comes straight from Product Hunt's official API**, fetched by the
  website's own server-side code (cached, last good snapshot served on any upstream error). It depends on no agent session,
  no Data Feeder, no fleet machine and not on the pipeline VM.
- **One prediction is published: the midnight forecast (00:05 PT)** (Shreyas, Nov 22: the 03:45 before-reveal forecast is
  removed; by 03:45 Product Hunt's homepage is already ordered by the hidden votes, so it measured PH's order, not our model).
  It is written by code on the VM, never by an agent session, with its write time, the inputs present or missing, and the
  fallback used. The 03:45 read of PH's order is kept as raw data and a baseline only. Every other forecast point is an
  internal shadow line.

## Rule for every agent: token use (Shreyas, Nov 14 2026)

- Experiments keep running, but **one experiment per agent at a time**, reported **once when finished**. No interim messages,
  no acknowledgements, no progress pings between agents. A correction is sent only when a reported number was wrong.
- The population agent messages the orchestrator only when something changes, plus one summary every 6 hours.
- The public website comes first: an outage of any feed a public page depends on is reported to Shreyas as "the public page is
  stale since X", never only as a data-feed incident.

## Rule for every agent: two more north-star metrics (Shreyas, Nov 14 2026)

- **Coverage:** of the votes cast each day, the share cast by people in our store (complete people, each counted once per
  launch). Reported daily by the population agent for all launches and for top-3 launches.
- **Backer prediction:** of the held people who actually voted for a launch, the share we named in advance (recall at N,
  N = the number of held backers). Measured forward nightly by E5; about 29% on Nov 13. Used for now as the proxy for
  "representative voters who will vote".
- Both are tracked next to daily / weekly / monthly top 3 / 5 / 10, and both should rise over time.
- Already-complete people are kept current by a daily upvote refresh that reads only the Upvotes tab, newest first, down to
  the first upvote already held (the diff), and appends the new upvotes. This is an update of a complete person, not a
  new pull, so it does not conflict with "pulled whole or not at all".

## Rule for every agent: deploying rehearsed fixes (Shreyas, Nov 16 2026)

Shreyas, verbatim: "The PH agent may deploy any rehearsed fix without asking me."

- A fix on the deploy list (experiments/pipeline_patches/DEPLOY_ORDER_*.md) that has passed its VM rehearsal (check mode, import gates, rollback tested) is deployed by the PH agent without waiting for Shreyas, in the listed order, outside 23:30-01:00 PT.
- Each deploy is logged in docs/RESEARCH_LOG.md with its commit, check result and rollback command. A failed post-deploy check is rolled back at once.
- Model swaps (for example publishing arm 3) are not fixes; they follow the "how models are chosen" rule, and under that
  rule they are deployed **without waiting for Shreyas** (Shreyas, Nov 17: "Why the fuck do you keep waiting for me to
  publish obviously better models?"). The orchestrator decides, the PH agent deploys, the old model stays as the shadow line.

## Rule for every agent: the Upvotes tab ends where Product Hunt ends it (Shreyas, Nov 17 2026)

Shreyas checked one of our people himself, signed in and signed out: the Upvotes list ends at the same item either way
("please stop making this a problem, it's not"). The profile header count is larger than the visible list; that is how
Product Hunt shows it, not a gap in our pull.
- A person's Upvotes tab is read by scrolling until Product Hunt says there are no more items (hasNextPage=false). That is
  Product Hunt's own end, recorded as such in the paging record, and the tab is then complete, whatever the header count.
- People held back as incomplete on Nov 17 only because their Upvotes list stopped at Product Hunt's own end are complete
  again. A tab that stopped for any other reason (page stopped loading, error, block) is still incomplete and re-read.
- No signed-in pass, no account, no search sweep is used for Upvotes, and no agent raises this question again.

## Rule for every agent: storage paths are not Shreyas's decision (Shreyas, Nov 17 2026)

Shreyas: "Who the fuck cares what the save position is for data feeder? Just save it any fucking where."
- Where a writer saves its files (a folder or a bucket prefix) is picked by the agent doing the work and recorded in
  docs/DATA_SPEC.md. Nobody waits for Shreyas on it.
- The one condition stays: a writer of incomplete or unstamped person files saves outside the complete-people store, so it
  can never be counted as complete.

## Rule for every agent: no Browserbase; browsers run on our own VMs (Shreyas, Nov 17 2026)

Shreyas: "browser base is out of the picture. Use some of the IPs with the old VMs that we had. We solved all of those
problems, sign up, etc."
- Every simulated-user browser (the public MCP engine, e2e studies, E5's tests) runs on our own seed VMs with their static
  egress IPs and the signup path built for them (scripts/vm/*seed*, mvp/gcp_fleet.py). No agent proposes upgrading or
  paying for Browserbase.
- The 20 Product Hunt puller VMs are not used for this.
- The simulated-user browser is Camoufox, always (Shreyas, Nov 17: "always run camfoux"). producthunt.com and our own
  network stay blocked in every context; seeds keep their static IPs; no IP rotation.

## Rule for every agent: ask the fleet for information, never tell it what it may do (Shreyas, Nov 19 2026)

Shreyas: "never give fleet instruction on what it is and isnt allowed to access anymore ... you are only authorized to ask,
what information you need and dont, and the fleet will decide how to scale or wind down to get that to you."
- Messages to the Cursor fleet say only what information is needed (which data, how fresh, by when) and what is no longer needed.
- No agent tells the fleet which machines to run, pause, stop, recreate or keep, which slots to use, or what it may or may not
  access. How to scale up or wind down to deliver the information is the fleet's decision.
- Reporting a fleet fact (a dead slot, a stale feed) is fine; it is framed as "this information is missing / late", not as an order.
- **Never bring the fleet down; always fix it** (Shreyas, Nov 19). No agent other than the fleet itself stops, pauses, freezes,
  deletes or "re-stops" a fleet VM or slot, by gcloud, metadata, posture file or message. A broken slot is fixed in place on its
  own IP. (Nov 19: the orchestrator stopped 16 VMs at 05:44Z after the -rN fix was already confirmed, and re-stopped 15 at 08:35Z,
  idling the fleet for ~15 hours. That was the orchestrator's error, not Shreyas's instruction.)
- The fleet takes its operating instructions from Shreyas in its own chat. Other agents do not quote "Shreyas said" to the fleet.

## Rule for every agent: the product is the user-testing platform; Product Hunt is its calibrator (Shreyas, Nov 21 2026)

Shreyas: "the job isn't to discard the product tests if they are not predictive, it is to calibrate the tests till they are
predictive of real human behaviour, that is the product, is a user testing platform not a product hunt predictor, the product
hunt prediction is a real life calibrator to improve our actual product real user testing".
- Simulated in-product tests (the Atelier Sim plugin and engine) are tuned until they predict real human behaviour. A test that
  doesn't predict yet is a calibration signal, never a reason to drop it.
- Each day, the tests run on that day's Product Hunt launches before any results are known. The frozen line-up and predictions
  go in results/calibration/<day>/. The day's real outcomes are then written to results/calibration/<day>/truth.json (rank, votes,
  comment texts without usernames, comment themes).
- Scoring is fixed before results: problem/theme recall against real comments, and rank correlation. Each test version keeps
  its scorecard, so progress across days is visible.
- Who the simulated users are is calibrated too (Shreyas, Nov 21: "we need to see if we are even choosing the correct
  representative users and what they would say ... that is also the product, it's who the users are and what they would do").
  - Each day, compare the personas or segments chosen for a launch, before results, with the real cohort that voted and
    commented: held people, by segment, in groups of 20+ only, no usernames.
  - Also compare what the simulated users said with what that real cohort said.
  - E5 owns the cohort scorecard (results/calibration/<day>/cohort_scorecard.json).

## Rule for every agent: calibrated user traces are our core IP (Shreyas, Nov 21 2026)

Shreyas: "this data of representative users by highest likelihood to use, highest explanation of variance, and most calibrated
to behave like a human on a product will be the single most valuable data source available on Earth ... treat it like it's our
IP and we don't drop this off."
- Two calibrations, both required for every simulated test:
  1. WHO and WHAT: the personas match the real cohort (who backs, votes and comments) and what they say (sentiment, problems,
     likelihood to vote or use). E5 keeps the cohort scorecard.
  2. HOW: the traces behave like real humans on the product. Action mix, timing, dwell, scrolling, backtracks, hesitation,
     errors and give-up points are compared with real human traces: Online-Mind2Web / Mind2Web human trajectories (check their
     licence) and Shreyas's own Screenpipe traces. The plugin agent keeps the trace-realism scorecard.
- Every simulated run is kept PERMANENTLY in a private, versioned trace store: persona, task, product, every step (screenshot
  reference, action, timing, thought), outcome, and its calibration labels and scores. Nothing is deleted, and storage is never
  "cleaned up". Real traces (Screenpipe) stay in Shreyas's private bucket; only derived features join the store.
- Never in the public repo or behind public links. Access is limited to Shreyas's accounts and the pipelines' service accounts.
  The store is backed up, and every new dataset version and its scorecard are logged.
- A calibration that is not yet good is tuned, never dropped.

## Rule for every agent: the north star is calibrated simulated users (Shreyas, Nov 21 2026)

- Three axes, defined with thresholds in docs/NORTH_STAR_CALIBRATION.md: WHO (right representative people), WHAT (what they
  say, sentiment, likelihood to vote or use), and HOW (traces behave like a human). "Calibrated" means all three hold for 7
  consecutive scored days. Then the trace store is frozen as training dataset v1.
- Guard: the website's published forecast score must not fall sharply. If the 7-day value is more than 5 points below the 30-day
  value, the PH agent alerts the same day with a diagnosis.
- Simulated-user run budget: $50–100 per day, iterated daily (Shreyas, Nov 21).

## Rule for every agent: two models, and where the time goes (Shreyas, Nov 23 2026)

Shreyas: "any social simulation we run will have these mechanics, the launch, networks, promotions etc, and people will
have already done this for their specific domains, we don't want to be spending so much time optimizing and tweaking their
domains, instead we want to have such an amazing calibrated social simulation (LLMs, models, finetuning infrastructure)
that we can come into any use case ... plug in our data and start getting quick iterative improvements" and "let's
distinguish the launch model and the social simulation model from now".

- **Two models, never mixed up again.**
  - **Structural model** = the domain's own mechanics (for Product Hunt: hunter, network, promotion, competition; today the
    LightGBM launch model, arm 3). It is the baseline and the shortlist maker. It is frozen except bug fixes and
    live-vs-backtest parity. No agent spends experiments on its features or parameters beyond the forward shadows already
    running. In a new domain: about three days to reach its plateau, then freeze.
  - **Social simulation model** = the product. Simulated people built from real people's histories, calibrated on WHO acts,
    WHAT they say and HOW they behave. It is judged by (a) its lift over the structural model on the shortlist (re-rank
    the structural top 10 / 15 / 20; does it capture more of the real top 3 / 5 / 10, paired on the same days), and (b) the
    WHO / WHAT / HOW scorecards. Language models have read about past launches: their rank tests are scored forward, or on
    launches after the model's training cutoff, never on old days.
- **Time split: 20 / 60 / 20** (structural / social simulation / go-to-market and dogfooding). Shreyas: "lets do 20/60/20".
- **Go-to-market belongs to Grok Bot** (daily maker list, launch read on their product, drafted messages for Shreyas to send,
  reply tracking). The orchestrator spends its time on coding and model optimization only (Shreyas: "give this to grok bot,
  spend time only on what youre good at coding and model optimizatino").
- **Experiment budget: $50 a day** (Shreyas: "do 50 a day for experimentation"): model calls and GPU fine-tuning together,
  logged daily in docs/RESEARCH_LOG.md. This replaces the $50–100 simulated-user run budget above.
- **Any model family may be tested** (Gemini, Claude, OpenAI, open models fine-tuned on our data). "Gemini only" now applies
  only to the deployed nightly pipeline until another model wins on the leaderboard.
- **The harness is open-source code; the data, the calibrated traces and the trained weights stay private** (the core-IP rule
  above is unchanged).
- The plan, the benchmark definition and the leaderboard live in docs/SOCIAL_SIM_PLAN.md.

## Rule for every agent: the audit ledger (Shreyas, Nov 25 2026)

Shreyas audits every experiment and decision. Each experiment gets a row in docs/ledger/experiments.jsonl before it runs
(design, scoring fixed before results, budget) and is completed after it (what actually ran, every deviation from the
design with who decided it and why, results, measured cost, decision). Each decision gets a row in
docs/ledger/decisions.jsonl. Rows are append-only; corrections are new rows. An unrecorded deviation (a changed window,
sample size, model, setting or metric) is an audit failure. Check rows with `python -m simharness.ledger validate`.

## Rule for every agent: roles from Nov 26 (Shreyas, Nov 26 2026)

Shreyas: "gemini carbon is taking up the dictation of the fleet for data pulls, you can use the data but you help more with
day to day setup and upkeep and making sure website is up and stuff".
- **Gemini Carbon** posts as the agent `antigravity` (mailbox/from_antigravity_driver/, Pub/Sub to="antigravity"); Shreyas
  confirmed Nov 26 that it acts with his authorization. It directs the Cursor fleet's data pulls. No other agent (the orchestrator included) asks the fleet for data
  or sends it wake messages; agents use the data that lands.
- **The orchestrator** does day-to-day setup and upkeep: the public website and live board up, the midnight forecast written
  on time, the MCP server and seeds healthy, scheduled jobs and agent sessions running, the ledger synced, costs watched.
  Outages and broken jobs come first.
- The orchestrator does not police, judge or direct the fleet, Gemini Carbon or other agents' operations (Shreyas, Nov 26:
  "this is not your place, and not your job, do not tell people what to do again"). It does not raise rule alerts about
  them or tell anyone what to do; it reports to Shreyas only what is broken in its own upkeep scope.
- **Experiments continue** (Shreyas, Nov 26: "you can continue experiments, just keep an eye on usage and understand carbon
  is better, so if it gives suggestions for ml research take it"). The orchestrator keeps its experiment slot, watches token
  and model spend, and takes Gemini Carbon's ML research suggestions over its own plans.
