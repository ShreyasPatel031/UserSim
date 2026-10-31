# Fetch ladder → Prediction agent: handover to Grok Bot

Read-only write-up (Oct 31 2026, main at `9804217`). Nothing here was run for this document: every number is copied
from the repo docs and code named beside it, and each is marked **measured** (a doc reports a run), **code**
(read from source) or **derived** (my arithmetic from those). Where the repo has no answer, this says so.

**Naming corrections to the brief.** The file is `mvp/review_fetch.py` (there is no `fetch.py`). "Route 4" in
`review_fetch.TIERS` is `residential_camoufox`. PR #140 only adds `x.com` to `ALLOWED_HOSTS`
(plus a test); it adds no x.com parser, route or output format. The "Product Hunt study" that motivates it is not
described anywhere in the repo, and `docs/producthunt/` and `scripts/ph_crawl.py`, which `docs/DISCOVERY.md` cites,
do not exist on main.

Deeper detail: [discovery/FETCH_LADDER.md](discovery/FETCH_LADDER.md) (routes, per-site results),
[discovery/HANDOVER.md](discovery/HANDOVER.md), [DISCOVERY.md](DISCOVERY.md),
[experiments/human_experience/HANDOFF_agent_mode.md](../experiments/human_experience/HANDOFF_agent_mode.md).

---

## 1. What the ladder extracts, and from where

The ladder only **fetches HTML**. `mvp/review_parsers.py` turns it into review rows. Only 3 of the 10 allowed
sites have a parser.

| Site | Parser | Rows per page | Fields extracted |
|---|---|---|---|
| G2 | `parse_g2` | 10 | source, product, name (None for "Verified User"), role, size, industry, rating, title, date, pros, cons, problems |
| Capterra | `parse_capterra` (reads `/p/<id>/<Name>/reviews/`) | 25 | name, role, size, industry, time used, rating, title, date, pros, cons, text, switched-from / reasons |
| Product Hunt | `parse_producthunt` (JSON embedded in the page) | varies | name, role (user headline), rating, text, pros, cons, date, review_type, id |
| GetApp, TrustRadius, Trustpilot, Gartner, AlternativeTo, Slashdot, SourceForge | **none** | – | fetch works, nothing is parsed |
| x.com | **none** | – | allowed host only (PR #140); no code reads it, and I found no evidence the page is fetchable logged out |

Up to `PER_PRODUCT = 50` reviews per product per site, at most 6 pages. Paging stops at 50 reviews, a page with
nothing new, or two failed pages in a row (**code**: `review_parsers.collect`).

Callers: `discovery.scrape_review_page` → `scrape_inhouse` → `review_parsers.collect` → `review_fetch.ladder_fetch`.
Fallback when nothing parses: the Apify actors, G2/Capterra/Product Hunt only.

## 2. The ladder (**code**: `review_fetch.TIERS`, `ladder_fetch`)

Per page, try in order and return the first real page (HTTP 200, not a bot challenge):

| # | Route | What | Cost (measured, FETCH_LADDER.md) |
|---|---|---|---|
| 1 | `vm` | curl_cffi, Chrome TLS fingerprint, VM IP | free |
| 2 | `vm_camoufox` | Camoufox (anti-fingerprint Firefox), VM IP | free, 15-150 s |
| 3 | `residential` | curl_cffi via DataImpulse US exit | ~$0.00006/page (55-85 KB at ~$1/GB) |
| **4** | **`residential_camoufox`** | Camoufox via DataImpulse US exit | $0.0005-0.0019/load (0.4-1.8 MB), 20-140 s |
| 5 | `apify_unblocker` | curl_cffi via Apify Proxy group `UNBLOCKER`, 3 tries | $0.0015 per successful request, failures free |

A route that hits a bot wall on a site is skipped for that site for 6 h (`MVP_FETCH_BLOCK_TTL_S`). Timeouts and
errors do not mark a route blocked. At most 2 Camoufox browsers run at once. Reviews are cached per page URL for 30 days.

## 3. How to run it

There is **no batch CLI for the ladder**. Three ways in, from least to most work:

**A. Probe one URL on the production VM (all routes, nothing parsed or stored).**
```bash
curl -XPOST https://35-202-98-224.sslip.io/api/discovery/probe -H 'content-type: application/json' \
  -d '{"url":"https://www.g2.com/products/asana/reviews","proxy":"ladder"}'
```
Takes 2-8 min. Run at most 2-3 at once (10 in parallel dropped connections). Only https URLs on `ALLOWED_HOSTS`.
Returns per route: pass, status, title, ms, wire KB, $/page, and `cheapest_pass`. Never returns page content.

**B. Full discovery run (competitors + users + review scrape), on the VM.**
```bash
curl -XPOST https://35-202-98-224.sslip.io/api/discovery -H 'content-type: application/json' \
  -d '{"url":"https://asana.com","max_competitors":2,"task_count":6,"scrape_reviews":true}'   # -> {"id"}
curl https://35-202-98-224.sslip.io/api/discovery/<id>                                         # poll until status != running
```
A run takes about 1.5-2.5 min (**measured**, HANDOVER.md). The review step waits at most `MVP_DISCOVERY_REVIEW_WAIT_S`
(default 75 s in code; DISCOVERY.md says 240, which is stale). A slower scrape keeps going and is cached for the next run.

**C. Locally, in Python, for one page (what a bulk job would call).**
```bash
pip install curl_cffi httpx playwright "camoufox[geoip]==0.4.11" requests
python -m playwright install chromium && python -m camoufox fetch   # Camoufox 0.4.11: newer has no browser build
```
```python
from mvp import review_fetch as F, review_parsers as P
status, html, route, tried = F.ladder_fetch(url, residential_proxy_url_or_None)   # tried[] has per-route usd
rows, info = P.collect("g2", url, "Asana", lambda u: F.ladder_fetch(u, proxy)[:2])  # or via discovery.scrape_inhouse
```
Local probe of every raw method: `PROXY_URL=... python scripts/review_fetch_probe.py <url>`.
Tests: `PYTHONPATH=src python -m pytest mvp/test_review_fetch.py mvp/test_review_parsers.py`.

### Env vars and secrets

| Name | Used by | Notes |
|---|---|---|
| `PROXY_URL` | routes 3 and 4 | DataImpulse, e.g. `http://USER:PASS@gw.dataimpulse.com:823`; `us_exit()` appends `__cr.us`. Without it, routes 3-4 are silently skipped |
| `APIFY_TOKEN` | route 5, Apify fallback, `apify_proxy()` | discovery raises `APIFY_TOKEN missing` if absent, even when in-house would succeed (**code**: `scrape_review_page`) |
| `PH_TOKEN`, or `PH_CLIENT_ID` + `PH_CLIENT_SECRET` | Product Hunt API in discovery | not used by the ladder |
| `CAPSOLVER_API_KEY` | `own_unblock` prototype only | not on the ladder |
| `MVP_FETCH_BLOCK_TTL_S` (21600), `MVP_RESIDENTIAL_USD_PER_GB` (1.0), `MVP_UNBLOCKER_USD_PER_PAGE` (0.0015) | ladder | cost figures are config, not billed amounts |
| `MVP_DISCOVERY_REVIEW_CACHE_DAYS` (30), `MVP_DISCOVERY_REVIEW_WAIT_S` (75), `MVP_APIFY_CACHE_DIR` | discovery | cache location, see §4 |

On the VM these come from Secret Manager (`usersim-<NAME>`, project `project-amer-scs-sandbox`, refreshed within ~5 min,
no redeploy) or `/var/lib/usersim/discovery_keys.json` (saved via `/discovery`). Cloud-session env settings do **not**
reach the VM. The DataImpulse password and the Apify, Product Hunt and G2 tokens were pasted in chat and are listed as
**not yet rotated** (FETCH_LADDER.md open item 5). Do not paste them again.

## 4. Inputs and outputs

**Input:** a review-page URL per site, e.g. `https://www.g2.com/products/<slug>/reviews`,
`https://www.capterra.com/p/<id>/<Name>/reviews/`, `https://www.producthunt.com/products/<slug>/reviews`.
Discovery finds them with Google-grounded search; for your own batch you must supply them.

**Output of `collect`:** `list[dict]` per product, each row the keys in §1, plus `via` (e.g. `"in-house via VM"`) when it
came from `scrape_inhouse`. Rows are not normalised across sites (Capterra has `time_used`; G2 has `problems`; Product
Hunt has neither role family nor size).

**Where it lands (all on the VM disk, none in GCS):**

| What | Path | Format |
|---|---|---|
| Per-page review cache | `<MVP_APIFY_CACHE_DIR or repo>/cache/apify/page2-<slug(url)>.json` | JSON list of rows, 30-day TTL |
| Per-product all-in-one Apify scrape (agent mode input) | `cache/apify/aio-<slug(product)>.json` | `{"product", "reviews":[...], "errors":[...]}` |
| Discovery run | `MVP_RUNS_DIR/discovery/<id>.json` (`/tmp/usersim-runs` or `mvp/runs`) | `{status, steps[], result:{product, competitors[], similar_products[], users[], segments[], tasks[], source_gaps[], counts}}` |

`gs://usersim-bakeoff-347838016394` (`mvp/gcs_store.py`) holds **study results**, not review data. I found no code that
uploads the review caches or discovery runs to GCS. If Grok Bot needs them durable, that is new work: copy
`cache/apify/` and `runs/discovery/` out of the VM, or add an upload. The VM disk is the only copy today.

**Research snapshots in git** (`experiments/staged_context/out/live/`, read these before scraping again):
`live_reviews.csv.gz` (12,996 rows, 79 products; columns `query,site,rid,found_as,title,role_family,size3,industry,time_used,overall_rating,recommendation_score,date,headline,pros,cons,review_text`),
`scrapes.json` (per-product count, `by_site`, `run_id`, `usd`, `ts`), `live_cache.tar.gz`. These came from the Apify
all-in-one scraper on Oct 18, not from the ladder.

## 5. Coverage and failure modes

Per-site results are in the table in FETCH_LADDER.md (Asana's page on each site, **measured** Oct 25 on the VM, 1-3
runs). Summary of what works:

| Site | Cheapest passing route | Notes |
|---|---|---|
| GetApp, TrustRadius | 1 (free) | no parser; TrustRadius flips to CF on route 4 in 1 of 2 runs |
| Trustpilot | 2 (free, 17 s) | no parser |
| Product Hunt, AlternativeTo | 3 ($0.00006) | PH has a parser |
| Gartner | 4 or 5 | route 3 passed 1 of 3 runs; flips between runs |
| Capterra | 5 ($0.0015, 27-57 s) | route 4 passes but costs $0.0019 (known gap) |
| Slashdot, SourceForge | 5 only (4-51 s) | no parser |
| **G2** | 5 only, unreliable | DataDome bans every DataImpulse IP tried (`t=bv`), so CapSolver cannot help. The Unblocker passed 2 of 3 runs, 502 on the third; `?page=N` times out 30 s repeatedly. **Expect fewer than 50 G2 reviews on some runs** |

**Cloudflare 403s.** Routes 1-3 get 403 or a "Just a moment" page on Capterra, Slashdot, SourceForge, Product Hunt
(route 1-2), AlternativeTo (route 1-2), Gartner (intermittent). Blocks are judged per IP, so one run says little.
Cloudflare localises its challenge to the exit IP's language ("Трохи зачекайте…"). `_CHALLENGE_RE` lists the ones seen;
**an unseen language can pass as a ~28 KB "success"**. Real pages are 300 KB+, so treat any small 200 with an odd title as
a failure. Non-US exits produced these; `us_exit()` only pins the country when the proxy host contains `dataimpulse`,
and one run still produced an Italian page.

**The 30 s wait.** Browser routes (2 and 4) call `_load(page, url, wait_s=30)`: they poll every 1.5 s for 30 s for the
challenge to clear, then return whatever is there (status as served, e.g. 403). A challenge that needs longer fails the
route, and because it then reads as a bot wall that route is blocked for that site for 6 h. Camoufox as a whole has a
180 s thread timeout per page. The Unblocker is a separate clock: 3 tries at 90 s each. Practical effect: browser
routes are slow (20-150 s) and a slow-but-eventually-passing page is recorded as blocked.

**Other limits.**
- 7 of 10 sites have no parser. Route 5 is billed per request regardless of size, so unparsed pages cost money for nothing.
- The ladder has no concurrency control beyond 2 browsers; discovery scrapes ~9 pages at once.
- Block memory (`_BLOCKED`) is in-process: a server restart forgets it and re-spends on dead routes.
- A cached empty result is possible for 30 days after a bad run (cache writes happen for whatever `rows` were returned, including the actor fallback's output).
- Capterra/G2/Product Hunt terms forbid automated scraping; low volume and caching are the only mitigation noted.
- No x.com support exists beyond the allowlist.

## 6. Costs

Per page (**measured**, §2). Per product at the 50-review target (**derived**, assuming the route in the table):

| Site | Pages | Route | ≈ $ per product |
|---|---|---|---|
| Product Hunt | 1-2 | 3 | $0.0001-0.0002 |
| Capterra | 2 | 5 (or 4) | $0.003 ($0.004) |
| G2 | 5 | 5 | $0.0075, if all five pages pass |

So a discovery run over the target plus 2 competitors, three sites each, is on the order of **$0.04** (3 × ~$0.012) in
proxy fees, plus Gemini calls (not costed here). For comparison, the Apify all-in-one scraper used for the research
data was **measured at $0.54 per 98 reviews** (SCRAPER_BAKEOFF.md; `scrapes.json` `usd` field per product). The
Apify account has a **$105/month cap**; about $45 was used by Oct 18, and the cap was hit on Oct 25 before being raised.
DataImpulse is billed per byte, blocked or not (a 403 is ~$0.000006); the plan noted is 5 GB. I have no billing
records, so these are rates, not spend.

## 7. What the Prediction agent consumes (`mvp/agent_mode.py`, MCP tool `usersim_predict_experience`)

It does **not** read the ladder's output today. It reads `mvp/review_context.live_reviews()`, which calls the Apify
all-in-one actor `zen-studio~software-review-scraper` (G2, Capterra, TrustRadius, Gartner; `maxResults` min 100) and
caches `aio-<slug>.json`. The ladder feeds only the discovery flow (competitors, users, segments, tasks). Wiring ladder
rows into agent mode is not done, and the two schemas differ.

**Schema agent mode expects** (per review, **code**: `review_context._all_in_one_item`):
`source, product, role, size, industry, time_used, rating, nps, pros, cons, text, date, ease, functionality, value,
support`. Ratings: 1-5, `nps` 0-10, G2 `ease_1_7` rescaled. Capterra supplies `ease/functionality/value/support`;
the other sites don't. A product's scrape must be `{"product", "reviews", "errors"}`.

**Gaps between ladder rows and that schema:** the ladder's G2 rows have no `time_used`, `nps`, `ease`; Product Hunt rows have
no `size`, `industry`, `time_used`; neither parser fills `nps`/sub-ratings. Agent mode's persona offsets lean on
`time_used` ("tenure dominates"), which only Capterra provides, so ladder-only data would weaken that.

### What it still needs (from the repo's own open items)

1. **Own and rival reviews for net-new products**, in the schema above, last ~100 recent reviews per product
   (`LAST = 100`) and ~50 per rival, for G2 and Capterra at least. Own-reviews are the biggest rating lever
   (RMSE −11% on G2 test); rivals-only data for net-new products is the weaker fallback.
2. **Live eval sets from TrustRadius and Gartner**, which are currently only reachable by Apify. Parsers for both
   (and GetApp/Trustpilot, free via routes 1-2) are open item 3 in FETCH_LADDER.md.
3. **YC Fall 2026 B2B test (20 startups)**: `experiments/human_experience/yc_fall20.py` has `plan` (done, `results/yc_fall20/plan.json`),
   `scrape-list` (every product name needing a scrape) and `run --cache DIR`. The live scrape and full run were never done; they need `APIFY_TOKEN`
   (HANDOFF_agent_mode.md, "Open"). DIR must hold `aio-<slug>.json` files in the format above.
4. **Job titles and company size** are what make segment averages work. Rows missing `role`/`size` don't contribute to people-like-them.
5. **Problems solved / use cases** (G2 `problems`, TrustRadius use cases) feed tasks; G2 `problems` is parsed by the ladder,
   which is the one field the ladder has that Capterra rows lack.
6. **Recency**: the model uses *recent* reviews (all-history was worse on G2). Keep `date` and sort descending.
7. **Identity**: the same-name problem ("Dock" returned Dock Health) is handled by `agent_mode.check_identity`; keep `product`
   exactly as the site names it.
8. **Rating labels**: a person's rating is predicted from level and offsets, not the model's own guess. Don't expect more precision from more words.

### What the training agents need

The "training" thread in the repo is the foundation-model plan (`docs/plans/beat_behavior_fms.md`, `scripts/fm_train/`,
`scripts/fm_baselines/`). It trains on Psych-101, SocSci210, BehaviorBench sources and survey sets, **not on review
data**; nothing in it consumes ladder output. The nearest overlap is the OPeRA funnel experiment
(`docs/experiments/opera_coldstart_prior.md`), which also does not use reviews. I did not find a spec asking the
ladder to feed training. If one exists outside the repo, I could not see it, so the format below is a proposal, not an agreed contract.

Proposed hand-off format if review rows are to be used as persona-conditioned labels: one JSONL row per review,
`{"source","product","product_url","role","role_family","size","industry","time_used","date","rating","nps","pros","cons","text","fetched_at","via"}`,
partitioned `product/site/date.jsonl`, with `via` recording the ladder route so a bad route can be filtered later. Keep a
registry of products and review IDs so held-out sets can be excluded, which the plan requires for its other data.

## 8. Recommended next steps for Grok Bot (in order)

1. Run route probes for the product and rival URLs you plan to scrape (§3A), 2-3 at once, before bulk jobs.
2. Put Capterra on route 5 first, or reuse `cf_clearance` after one browser solve (open item 1).
3. Write parsers for Trustpilot, GetApp, TrustRadius (all free via routes 1-2), then Gartner.
4. Write an exporter: ladder rows → `aio-<slug>.json` shape, so `agent_mode` and `yc_fall20.py run --cache` can use them.
5. Persist caches and discovery runs to GCS; today they live only on the VM.
6. Retry failed G2 pages later in the background; log fewer-than-50 results as a gap, never fill them.
7. Rotate the leaked credentials before anything else.
8. Respect the repo rule: no silent fallbacks. If a source returns nothing, report the gap.
