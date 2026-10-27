# Agent notes (UserSim)

Before connecting or starting a study, read:

- **[docs/mcp/CONFIG.md](docs/mcp/CONFIG.md)** — runtime settings in `mvp/sim_mcp/limits.json` (PR to main, no approval needed)
- **[docs/mcp/OPERATIONS.md](docs/mcp/OPERATIONS.md)** — deploy (merge main), secrets (`gcloud`), health checks
- **[docs/mcp/README.md](docs/mcp/README.md)** — **For client agents** (public MCP URL, no token, no local engine or secrets)
- **[docs/E2E_TEST.md](docs/E2E_TEST.md)** — full study only: target + 2 competitors, 6 personas, 6 tasks, 108 cells, comparison report

## Web fetching and paid proxies (read before fetching anything)

- **All fetching goes through the fetch gateway**: `fetchgate.fetch(url)` (page), `fetchgate.fetch(url, scroll=True)`
  (browser, scrolled, XHR/JSON recorded), `fetchgate.run_actor(...)` (Apify actors), or on the command line
  `python -m fetchgate fetch < urls.txt` (stdin URLs → JSON lines `{url, status, route, final_url, html}`). It tries
  the routes cheapest first (VM IP free → VM + Camoufox free → DataImpulse residential ~$1/GB → residential + Camoufox
  → Apify last) and logs every attempt's route, bytes and $. Routes, prices, per-site results:
  **[docs/discovery/FETCH_LADDER.md](docs/discovery/FETCH_LADDER.md)**.
- **Never bypass the gateway.** Do not read, copy or build proxy URLs or tokens (DataImpulse, Apify proxy,
  `APIFY_TOKEN`, `~/php/proxy.txt`, the app's saved keys), do not call `api.apify.com` or pass a proxy to curl,
  requests, curl_cffi, Playwright or Camoufox yourself, and do not use `sudo` to reach credentials. The repo scan
  (`python -m fetchgate scan`, in pytest, CI and `.githooks/pre-commit`) fails any such code outside `src/fetchgate/`.
  On the VM, scripts call the gateway service (`FETCHGATE_URL=http://127.0.0.1:8765`, set for every login); only the
  `fetchgate` user can read the credentials.
- **Apify is off unless you set `ALLOW_APIFY=1`**, and even then it runs only for a URL after every cheaper route failed.
  Apify proxy traffic is ~$8/GB: one agent spent ~$60 sending page fetches and browser scrolling through it.
- **Budget:** each job (`FETCH_JOB=<name>`; unnamed jobs share one bucket per day) stops with `BudgetExceeded` at
  **$5**. Raising it needs `FETCH_BUDGET_USD`, and **any job estimated over $5 needs the founder's OK first**. All jobs
  together also stop at the gateway's daily cap.
- **Pilot first:** run ~20 items, then report the route mix and $ per item (`python -m fetchgate job <FETCH_JOB>`)
  before scaling up.
