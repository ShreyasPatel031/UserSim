# Product Hunt data: start here

Agents working on Product Hunt launch data should read this first, then
[HANDOFF.md](HANDOFF.md) for results, API facts and next steps.

## Credentials (not stored in the repo)

The crawler reads these environment variables, first match wins:

| Variable | What it is |
|---|---|
| `PH_TOKEN` | Developer token (acts as its owner, includes `private` scope, never expires) |
| `PH_CLIENT_ID` + `PH_CLIENT_SECRET` | Application "Atelier" credentials; the script mints a `public`-scope token from them |

They live in the cloud environment's settings, not in git:
**cloud environment menu in the session title bar → Edit → Network secrets (or Environment
variables)**. A new session picks them up. If a variable is missing, ask the owner to add it
there. Do not paste tokens into chat, commit them, or write them to files in the repo.

Rotate them at https://api.producthunt.com/v2/oauth/applications.

## Quick start

```
python scripts/ph_crawl.py --topic developer-tools --month 2026-03 --no-resolve
python scripts/ph_baseline_eval.py
```

Output goes to `data/producthunt/<topic>_<YYYY-MM>.jsonl` (gitignored; rebuild with the crawler).

## Files

- `scripts/ph_crawl.py`: crawl featured launches for one topic and month
- `scripts/ph_baseline_eval.py`: temporal-holdout baseline
- `docs/producthunt/HANDOFF.md`: API facts, results, caveats, next steps
