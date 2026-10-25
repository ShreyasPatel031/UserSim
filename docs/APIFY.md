# Apify (review scraping): where the token is and how to use it

**Agents: read the token from the `APIFY_TOKEN` environment variable.** Never commit it, print it, or paste it in chat.

## Where the token lives

| Place | Who sets it | Who can read it |
| --- | --- | --- |
| Cloud environment variable `APIFY_TOKEN` (environment settings → Edit → environment variables / network secrets) | the account owner, in the Claude app | every new session in that cloud environment |
| GCP Secret Manager `usersim-APIFY_TOKEN` (see [mcp/OPERATIONS.md](mcp/OPERATIONS.md#secrets-gcp-secret-manager)) | anyone with `gcloud` access to the project | the live MCP server |
| `~/.config/apify/token` | one session, by hand | that container only; lost when it is reclaimed |

`mvp/review_context.apify_token()` checks `APIFY_TOKEN` first, then `~/.config/apify/token`.
If neither is set, scrapes are skipped and the result says why. Nothing is substituted.

Check it works without printing it:

```bash
curl -s -H "Authorization: Bearer $APIFY_TOKEN" https://api.apify.com/v2/users/me/limits \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['data'];print(d['current']['monthlyUsageUsd'],'/',d['limits']['maxMonthlyUsageUsd'])"
```

## Account limits (as of 25 Oct 2026)

- $105 a month, with $88.43 used. Ask the user before any run that could cost more than a few dollars.
- 16 GB of memory and 5 concurrent runs. HTTP 402 means the memory cap was hit, not that credit ran out.
  `_apify_run` caps runs at 3 at a time with explicit memory.

## Which actor to use

- **`zen-studio/software-review-scraper`** (default). One call by product name covers G2, Gartner, TrustRadius and
  Capterra in one schema.
  - Coverage: job title 84%, company size 100%, industry 72%, real pros and cons.
  - Cost: about $0.5 per 100 reviews.
  - `maxResults` must be at least 100, and a run needs at least 2 platforms.
- **`zen-studio/g2-reviews-scraper`**: adds G2 "problems solved".
- Weak, avoid:
  - `trakk/capterra-reviews-scraper` misses many products.
  - `automation-lab/g2-scraper` has no job titles and no pros/cons text.
- Details: `experiments/staged_context/SCRAPER_BAKEOFF.md`.

## Rules

- Production competitor data comes only from live scrapes of a product's real, named competitors. The FreshCrawl
  Capterra and G2 snapshots are research and eval data only.
- Check product identity. A search for "Sentry" on Capterra returned an insurance product of the same name.
  `_same_product` and agent mode's identity gate drop most of these.
- Scrapes are cached per product in `cache/apify/`. Failed scrapes are not cached.
