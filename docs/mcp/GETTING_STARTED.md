# UserSim MCP: getting started

UserSim lets an AI assistant (Claude, Cursor, or your own script) look at a real, public web product the way its users would, and bring back what it learned. You connect once, then ask your assistant in plain language.

No account, token or setup is needed. This guide is for people using the server. The full reference for agents and operators is [README.md](README.md).

## 1. Connect

The server address is:

```
https://35-202-98-224.sslip.io/mcp
```

**Claude Code**
```bash
claude mcp add --transport http usersim https://35-202-98-224.sslip.io/mcp
```

**Claude Desktop**: add this to `claude_desktop_config.json`, then restart the app.
```json
{
  "mcpServers": {
    "usersim": { "command": "npx", "args": ["-y", "mcp-remote", "https://35-202-98-224.sslip.io/mcp"] }
  }
}
```

**Cursor**: add this to `~/.cursor/mcp.json`.
```json
{
  "mcpServers": {
    "usersim": { "url": "https://35-202-98-224.sslip.io/mcp" }
  }
}
```

Check that it works: ask your assistant to list the `usersim` tools. You should see `usersim_predict_experience`, `usersim_start_session`, `usersim_get_report` and others.

## 2. What you can pull

### A. A quick prediction of the user experience (about 1–2 minutes, no browser)

Use this first. It reads live reviews of the product and its competitors (G2, Capterra, TrustRadius, Gartner) and predicts how a kind of user will experience it.

Ask your assistant, for example:

> Use usersim_predict_experience for Basecamp (https://basecamp.com). The user is a project manager at a 20-person agency who is on a trial. Rivals: Asana, Trello.

You get back:
- **Ratings**: overall, ease of use and likelihood to recommend, each with the evidence behind it and a "most likely score" for this kind of user.
- **Pros and cons**: what this kind of user will like and what will frustrate them.
- **Overall experience**: a short written summary.
- **Product profile**: who tends to use it, what they use it for, what they value, what frustrates them and why they switch.
- **Evidence**: how many reviews were used, and which competitors were left out and why.

Notes:
- The first call starts the review scrape and returns `pending`. Ask again after a minute with the same details.
- A new product with no reviews of its own gets a category-level prediction from its competitors. The result says so (`new_product: true`).
- Giving the product's URL is strongly recommended. Without it, the product's own reviews aren't used.

### B. A simulated user who really uses the product (a few minutes per user)

A simulated user opens the product in a recorded cloud browser, tries one task as a given person, and says what they think at each step. Then UserSim's own independent judge writes a report.

Ask your assistant, for example:

> Start a UserSim session on https://example.com. The user is Priya, a freelance designer who has never used it. Her task: find out what the site is for and sign up. Run it to the end, then get me the report.

You get back:
- a **live link** to watch the run (`watch_url`);
- a **report**: the judge's verdict, what was easy and what was hard, every step with a screenshot and the user's thought at that step.

### C. A full study (the large, expensive option)

A full study is your product plus two competitors, 6 simulated people and 6 tasks, which is 108 runs, with a comparison report at the end. It costs real money, so **ask the UserSim owner before starting one**.

## 3. Pulling a report again later

Every run is saved as a study with an id.
- Ask your assistant: *"Get the UserSim report for study `<study_id>`"* (the tool is `usersim_get_report`, in markdown or JSON).
- Or open the report page in a browser: `https://usersim.vercel.app/report?study=<study_id>`.
- A live run can be watched at `https://usersim.vercel.app/?study=<study_id>`.

If a study is still running, the report says so. Ask again in about 30 seconds.

## 4. Limits

There is no sign-up, so shared daily limits apply:

| Limit | Value now |
|---|---|
| Daily budget per person (estimated) | $5 |
| Daily budget for everyone together | $100 |
| Browser sessions open at once, per person | 5 |
| Steps per run / time per run | 200 / 30 minutes |
| Cost estimate | about $0.05 per session + $0.005 per step; about $0.60 per prediction |

The limits change from time to time. The server reports its current limits at `https://35-202-98-224.sslip.io/api/mcp/limits`. When you hit one, the tool says which, and the daily budgets reset at midnight Pacific time.

## 5. Ground rules

- **Public sites only.** Local or private addresses are rejected.
- **No personal logins.** Simulated users sign up with fresh throwaway email addresses. Google and GitHub sign-in are not used.
- **Keep your `session_id` private.** It is your key to a running session. Study ids are not secret, because they appear in report links.
- **Be considerate of the product you test.** Use your own product, or a product whose team would be fine with it, and don't run it many times in a row.
- **Treat the results as evidence, not as a verdict.** The predictions are based on reviews, and simulated users are not real people. Use them to find what to check with real users.

## 6. If something goes wrong

| What you see | What to do |
|---|---|
| `pending` from a prediction | Ask again in a minute with the same details |
| A limit message (`anon_daily_usd_per_ip` and similar) | Daily budget used up. Try after midnight Pacific |
| `UserSim is at its simulated-user limit right now` | Too many runs are open. Retry in a few minutes |
| `unknown session_id` / `unknown study_id` | Wrong id, or the server restarted and dropped a running session |
| HTTP 401 | Remove any `Authorization` header from your client. No token is needed |
| Calls time out | Raise your client's timeout. Starting a run takes up to 20 seconds |

The full list of errors and tools is in [README.md](README.md).
