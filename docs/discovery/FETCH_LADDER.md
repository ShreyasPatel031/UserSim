# Review data retrieval: fetch methods and the ladder

How discovery gets review pages from the 10 review sites, cheapest route first. Code: `mvp/review_fetch.py`
(routes, ladder, probe), `mvp/review_parsers.py` (parsers, paging), `mvp/discovery.py` (`scrape_inhouse`,
`scrape_review_page`). Measured on the production VM, Oct 25 2026, Asana's page on each site.

## The routes (methods)

| # | Route (`review_fetch.TIERS`) | What it is | Cost | Speed |
|---|---|---|---|---|
| 1 | `vm` | curl_cffi with Chrome's TLS fingerprint, from the VM's own IP | free | <2 s |
| 2 | `vm_camoufox` | Camoufox (anti-fingerprint Firefox), VM IP, images/fonts/media blocked | free | 15-150 s |
| 3 | `residential` | curl_cffi through the DataImpulse residential proxy, US exits (`us_exit`) | ~$1/GB; a page is 55-85 KB brotli: **~$0.00006** | 1-3 s |
| 4 | `residential_camoufox` | Camoufox through DataImpulse, US exits | 0.4-1.8 MB per load: **~$0.0005-0.0019** | 20-140 s |
| 5 | `apify_unblocker` | curl_cffi through Apify Proxy group `UNBLOCKER` (Apify solves the bot check), 3 tries | **$0.0015** per successful request; failures free | 2-150 s |

Residential is billed per byte, blocked or not; a 403 costs ~$0.000006. The Unblocker is billed per successful request,
whatever the size. A browser costs more than curl on the same proxy because it also downloads the page's JavaScript,
CSS and XHRs (~40 requests to 90+).

## The ladder (`review_fetch.ladder_fetch`)

For each page: try routes 1 → 5 in order, return the first that gets the real page (HTTP 200, not a bot challenge).

- A route that hit a **bot wall** on a site is skipped for that site for 6 h (`MVP_FETCH_BLOCK_TTL_S`), so later pages
  and runs go straight to the route that worked. Timeouts and errors don't mark a route blocked.
- Residential routes are skipped when no `PROXY_URL` is saved; the Unblocker needs `APIFY_TOKEN`.
- At most 2 Camoufox browsers at once (`_BROWSERS`), each in its own thread (a crashed browser poisons its thread).
- The trace's "reviews" line says `in-house via <route(s)>` and the run's cost.
- Reviews are cached per page URL for 30 days (`MVP_DISCOVERY_REVIEW_CACHE_DAYS`); a cached product costs nothing.
- When nothing parses, discovery falls back to the Apify scraper actors (G2, Capterra, Product Hunt only).

**Known ladder gap:** for Capterra, route 4 passes but costs more per page ($0.0019) than route 5 ($0.0015). Fix
options: put the Unblocker first for Capterra, or solve once in the browser and reuse the `cf_clearance` cookie
over curl on the same sticky IP (`sticky_proxy`) for the next pages (~$0.00006 each).

## Per site: which route works

`pass` = real page; `403` / `CF` / `DD` = blocked (Cloudflare / DataDome); runs 1-3 on Oct 25 2026.

| Site | Example URL | 1 vm | 2 vm_camoufox | 3 residential | 4 residential_camoufox | 5 unblocker | Use |
|---|---|---|---|---|---|---|---|
| GetApp | `getapp.com/<category>/a/<product>/reviews/` | pass | pass | pass | pass | pass | **1** free |
| TrustRadius | `trustradius.com/products/<product>/reviews` | pass | pass | pass | CF (1 of 2 runs) | pass | **1** free |
| Trustpilot | `trustpilot.com/review/<domain>` | 403 | pass (17 s) | 403 | pass / timeout | pass | **2** free |
| Product Hunt | `producthunt.com/products/<slug>/reviews` | CF | CF | pass | pass | pass | **3** $0.00006 |
| AlternativeTo | `alternativeto.net/software/<slug>/about/` | CF | CF | pass | pass | pass | **3** $0.00006 |
| Gartner Peer Insights | `gartner.com/reviews/market/<market>/vendor/<v>/product/<p>` | CF | CF | pass run 1, CF runs 2-3 | pass ($0.0011) | pass (2-4 s) | **4** or **5** |
| Capterra | `capterra.com/p/<id>/<Name>/reviews/` | CF | CF | CF | pass ($0.0019, US exit) | pass (27-57 s) | **5** (see gap above) |
| Slashdot | `slashdot.org/software/p/<Name>/` | CF | CF | CF | CF | pass (24-51 s) | **5** |
| SourceForge | `sourceforge.net/software/product/<Name>/` | CF | CF | CF | CF / error | pass (4-42 s) | **5** |
| G2 | `g2.com/products/<slug>/reviews` | DD | DD | DD (IPs banned, `t=bv`) | DD | pass runs 1-2, **502 run 3** | **5**, unreliable |

Notes:
- From a Claude cloud container's IP (not the VM), plain curl passes Capterra and GetApp only.
- G2: DataDome bans every DataImpulse IP tried outright (no captcha), so CapSolver can't help; the Unblocker times out
  or 502s now and then, especially on `?page=N`. Expect fewer than 50 G2 reviews on some runs.
- Gartner and TrustRadius flip between runs: rely on the ladder, not a fixed route.

## Parsers and paging (`review_parsers.py`)

| Site | Parser | Reviews per page | Next page |
|---|---|---|---|
| G2 | `parse_g2` | 10 | `?page=N` |
| Capterra | `parse_capterra` | 25 | `/reviews/?page=N` (the product root has no review cards: `capterra_reviews_url`) |
| Product Hunt | `parse_producthunt` | varies (JSON in the page) | `?page=N` |
| Gartner, TrustRadius, SourceForge, Trustpilot, GetApp, AlternativeTo, Slashdot | **none yet** | | |

`collect()` pages until 50 reviews, a page that loads but adds nothing new, or two failed pages in a row.
GetApp and Capterra are the same company (G2 Digital Markets) and share review content; Slashdot and SourceForge also
share listings, so a parser for one may cover the other.

To write a parser: get the real HTML with `POST /api/discovery/sample {url, proxy, current_apify_token}`, save it to
`mvp/fixtures/reviews/`, and test against the fixture (see `mvp/test_review_parsers.py`).

## Checking a site yourself

```bash
# every route for one URL: pass, status, title, ms, wire KB, $/page, and the cheapest route that passed
curl -XPOST https://35-202-98-224.sslip.io/api/discovery/probe -H 'content-type: application/json' \
  -d '{"url":"https://www.trustpilot.com/review/asana.com","proxy":"ladder"}'
```

Allowed hosts are the 10 sites above (`ALLOWED_HOSTS`). A ladder probe takes 2-8 min (two browser routes).
**Run at most 2-3 at once**: 10 in parallel dropped 2 connections (curl 56).

Other probe modes: `proxy: "saved" | "apify_unblocker" | "apify_residential"` (older per-method probe),
`"own_unblocker"` (sticky DataImpulse IP + CapSolver prototype).

## Challenge detection gotchas

- Cloudflare localises its challenge title to the exit IP's language ("Трохи зачекайте…", "Один момент…",
  "Ci siamo quasi…"). `_CHALLENGE_RE` lists the ones seen; a new language can still slip through as a 28 KB "pass".
  Real review pages are 300 KB+, so treat any small 200 with an unfamiliar title as suspect.
- A non-US title means the residential exit wasn't US. `us_exit` adds `__cr.us` only when the proxy host contains
  `dataimpulse`; one run still produced an Italian challenge, so check the saved `PROXY_URL` form.

## Open items

1. Capterra: cookie reuse after one browser solve, or Unblocker first.
2. G2: retry failed pages later in the background; or test another unblocker / residential provider for G2.
3. Parsers for the 7 sites without one (start with Trustpilot, free via route 2, and GetApp / TrustRadius, free via
   route 1).
4. Product Hunt's GraphQL API (we hold `PH_TOKEN`) might return reviews for free; unchecked.
5. Rotate the DataImpulse password and the Apify, Product Hunt and G2 tokens (pasted in chat).
