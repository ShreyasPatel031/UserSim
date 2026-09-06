# Browserbase smoke test vs previously blocked sites

Run:

```bash
set -a && source secrets/env && set +a   # needs BROWSERBASE_API_KEY in secrets/env
PYTHONPATH=src .venv/bin/python -m capability.run_browserbase_smoke
# paid proxies: add --proxies (Developer+ plan)
```

Output: `results/capability/browserbase_block_smoke.json`

## Prior manual run (free tier, no proxies)

Session: https://www.browserbase.com/sessions/6e250fe6-bd86-4dc1-9b5f-a845d0da85ef

| Site | Local Chromium | Browserbase (no proxies) | Browserbase + proxies |
|------|----------------|--------------------------|------------------------|
| apartments.com | Akamai 403 | **Still 403** | **402** — proxies not on free plan |
| uniqlo.com/us/en | Akamai 403 | **200 OK** — real storefront | (not needed) |
| example.com | OK | OK | — |

## Verdict

- Browserbase **without** residential proxies is **partially** useful (Uniqlo cleared; Apartments did not).
- Hard Akamai targets need **paid Proxies** (Developer+). Free plan rejects `proxies: true` with Payment Required.
- Do **not** buy Browserbase assuming free tier fixes all OM2W blocks — only some sites improve.

## Harness integration

Set in `secrets/env`:

```bash
BROWSERBASE_API_KEY=bb_live_...
BROWSERBASE_PROJECT_ID=...   # optional; inferred from API key if omitted
USE_BROWSERBASE=1          # Mistral/Gemini bakeoffs use Browserbase CDP
# BROWSERBASE_PROXIES=1    # paid residential proxies
```

Then run bakeoff as usual (`run_mistral_bakeoff`, etc.).
