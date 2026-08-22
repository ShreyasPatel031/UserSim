# UserSim MVP

Local web UI for synthetic user research: URL + segment → generated tasks → parallel persona agents → executive summary.

## Run

From the repo root:

```bash
pip install -r mvp/requirements.txt
PYTHONPATH=src uvicorn mvp.server:app --reload --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

Requires `MISTRAL_API_KEY` and `BROWSERBASE_API_KEY` in `secrets/env`.

Blocked sites (403, WAF, empty JS shells) are retried via Browserbase. If still blocked, the study stops — no inferred fallback.

## Flow

1. User enters a public URL and customer segment.
2. Mistral generates 4 personas and 4 on-site tasks.
3. Four agents run in parallel (page snapshot + persona simulation).
4. Mistral synthesizes friction themes, strengths, and recommendations.

This MVP uses HTTP page snapshots, not live browser agents. Swap in `mistral_browser_use_runner` later for full browsing traces.
