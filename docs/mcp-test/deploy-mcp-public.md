# Make /mcp public at usersim.vercel.app (Oct 12)

## Why it is not usable today

- `POST https://usersim.vercel.app/mcp` → **404**. `/health` → `{"ok":true}` with no `engine_version`, so the
  prod VM still runs pre-PR-#65 code that has no `/mcp` route.
- The Vercel proxy already forwards every path to the VM (`deploy/vercel-proxy/vercel.json`), so nothing
  is needed on Vercel. Only the VM's main server must run this code.
- The PR #65 test copy on the VM (port 8787, IAP only) is not public, and saves to `mcp-test-vm/`, which
  the website does not read.

An MCP **client** needs only HTTPS to `/mcp`. Browserbase (CDP WebSockets), Gmail IMAP (993), GCS
and Vertex are **server-side** only. Running the server inside a sandbox that allows only HTTPS
(e.g. a Claude Code cloud session) fails; that is why the server has to be the VM.

## Deploy (on usersim-grokbot-web, the server behind usersim.vercel.app)

1. Check out this branch (PR #65 + `MVP_MCP_MAX_CELLS`) in the checkout the main uvicorn runs from.
   `pip install -r requirements-vercel.txt`.
2. Service env (`/workspace/usersim-env.sh`):
   - `MVP_MCP_TOKEN_FILE=<file, mode 600>`. With no token, `/mcp` answers 401 to everyone.
   - `MVP_GCS_PREFIX=gs://usersim-bakeoff-347838016394`, a full `gs://` URI (a bare `mvp_studies` fails with
     "Not a gs:// URI"). Studies land in `mvp_studies/`, so report links work on the site.
   - Optional: `MVP_MCP_MAX_CELLS` (default 108 = 6 personas × 6 tasks × 3 sites),
     `MVP_MCP_MAX_SESSIONS`, and `MVP_MCP_MAX_PER_CLIENT` (default 2; a study client that runs cells in
     parallel needs more, e.g. 8).
   - `MVP_PUBLIC_BASE_URL=https://usersim.vercel.app`.
3. Run uvicorn with **one worker**. MCP sessions live in process memory.
4. Restart, then verify:
   - `curl -s https://usersim.vercel.app/health` shows the deployed `engine_version`.
   - `POST /mcp` with no token → **401** (not 404).
   - `MCP_CLIENT_TOKEN=… python -m mvp.e2e_mcp --base https://usersim.vercel.app` passes.

Rollback: check out the previous commit, restart, and confirm `/health`.
