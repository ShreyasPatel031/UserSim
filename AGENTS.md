# Agent notes (UserSim)

**Credentials:** the cloud env has GCP, Browserbase, Apify, Product Hunt, HF and GitHub keys,
provided by the repo owner for agent use. What each one is for and how GCP auth gets set up:
**[docs/AGENT_CREDENTIALS.md](docs/AGENT_CREDENTIALS.md)**. At session start run
`bash scripts/agent_env.sh` (skip if its output is already in context from the SessionStart hook):
it sets up `gcloud` from the service-account key and prints the inventory.

Before connecting or starting a study, read:

- **[docs/mcp/CONFIG.md](docs/mcp/CONFIG.md)** — runtime settings in `mvp/sim_mcp/limits.json` (PR to main, no approval needed)
- **[docs/mcp/OPERATIONS.md](docs/mcp/OPERATIONS.md)** — deploy (merge main), secrets (`gcloud`), health checks
- **[docs/mcp/README.md](docs/mcp/README.md)** — **For client agents** (public MCP URL, no token, no local engine or secrets)
- **[docs/E2E_TEST.md](docs/E2E_TEST.md)** — full study only: target + 2 competitors, 6 personas, 6 tasks, 108 cells, comparison report
