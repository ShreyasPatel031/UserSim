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

- No agent designs, approves, builds, runs or publishes a "lists-only", "light", "fast-first", "capped" or "two-pass" pull,
  whatever it is called. The only stops allowed are Product Hunt's own (recorded as such in the paging record).
- The code enforces it: the pull driver writes a person's file only when the pull is complete (full-only mode). Any build
  that can write an incomplete person fails its audit.
- The population agent scores a sample of saved people against this definition every 30 minutes and FAILs loudly on any
  incomplete saved pull.
- Progress is reported as **complete people**, read from the store. A rate of pulls, pages or lists is never reported as
  people.
- Any agent that sees this rule broken alerts Grok Bot by webhook within 1 minute, naming the agent.
