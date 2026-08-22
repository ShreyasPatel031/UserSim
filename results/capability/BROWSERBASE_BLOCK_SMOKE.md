# Browserbase smoke test vs previously blocked sites

Session (no proxies, free tier): https://www.browserbase.com/sessions/6e250fe6-bd86-4dc1-9b5f-a845d0da85ef

| Site | Our GCP Chromium (before) | Browserbase free (no proxies) | Browserbase + proxies |
|------|---------------------------|-------------------------------|------------------------|
| apartments.com | Akamai 403 | **Still 403 Access Denied** | **402** — proxies not on free plan |
| uniqlo.com/us/en | Akamai 403 | **200 OK** — real storefront | (not needed) |
| example.com | OK | OK | — |

## Verdict

- Browserbase **without** residential proxies is **partially** useful (Uniqlo cleared; Apartments did not).
- Hard Akamai targets need **paid Proxies** (Developer+). Free plan rejects `proxies: true` with Payment Required.
- Do **not** buy Browserbase assuming free tier fixes OM2W blocks — only some sites improve.
