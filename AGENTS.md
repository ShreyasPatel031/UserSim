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
