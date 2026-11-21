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
- **Exactly two predictions are published:** the midnight forecast (00:05 PT) and one before-reveal forecast (03:45 PT, the
  last point before votes appear at 04:00 PT). Both are written by code on the VM, never by an agent session, each with its
  write time, the inputs present or missing, and the fallback used. Every other forecast point is an internal shadow line.

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
