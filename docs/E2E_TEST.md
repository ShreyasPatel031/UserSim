# UserSim end-to-end (e2e) test definition

This is the **only** definition of an e2e test in UserSim. Agents, the website, and the MCP server must follow it.

## For client agents

Connect to **`https://35-202-98-224.sslip.io/mcp`** with **no token** and **no env vars**.

Do **not** set `MVP_OWNER_PHONE`, `MVP_NTFY_SMS_TOPIC`, `GMAIL_USER`, `MVP_CAPTCHA_API_KEY`, `APIFY_TOKEN`, or `credentials.json`, and do **not** run the UserSim engine locally. The server provides SMS (`usersim_signup_phone` / `usersim_wait_for_sms_code`), the signup inbox (`usersim_signup_identity` and verification wait tools), competitor discovery when rivals are omitted, and captcha handling (stop and report; no paid solver without founder approval).

Use **fresh** `usersim.signups+<tag>` signups only; reuse a prior MCP session’s account with `same_account_as`. Never use personal logins.

## What counts as an e2e test

An e2e test is a **full UserSim comparison study**:

| Dimension | Requirement |
|-----------|-------------|
| **Products** | Exactly **3 sites**: your **target product** plus **2 competitors** (public URLs). |
| **Personas** | Exactly **6** buyer personas (simulated users). |
| **Tasks** | Exactly **6** tasks (goals). Every persona attempts every task on every site. |
| **Matrix** | **108 runs** (6 × 6 × 3). Every cell must execute and be scored. |
| **Signup** | Account creation and email verification is **one of the six tasks**, or signup + verification is completed as a **prerequisite** on each product before other tasks that need an account. |
| **Output** | The **website comparison report**: where you win, where you lose, head-to-head vs each competitor. |

## What is **not** an e2e test

- A single-product run (target only, no competitors).
- A “quick”, “smoke”, or `test_mode` run with one persona or one task.
- A partial matrix (fewer than 2 competitors, fewer than 6 personas, or fewer than 6 tasks).
- A single MCP `usersim_start_session` without a full `usersim_start_study` matrix (useful for debugging, but not an e2e test).

The API and MCP server **reject** requests that try to start a reduced study. If competitors, personas, or tasks are omitted, UserSim **fills** them using the same competitor-finding and persona/task planning code as the website (never a separate shortcut).

## For implementers

- Enforcement: `mvp/e2e_study.py`
- Website entry: `POST /api/studies` in `mvp/server.py`
- MCP entry: `usersim_start_study` in `mvp/sim_mcp/server.py`
- Planning defaults: `mvp/fast_plan.py` (`MVP_STUDY_MODE=compare`, 6 personas, 6 tasks, 2 rivals)
