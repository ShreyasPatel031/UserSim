# Discovery (study part 1): handover

Product URL in → competitors, real users (G2 / Capterra / Product Hunt reviewers), user segments and comparison tasks
out. Live at **https://35-202-98-224.sslip.io/discovery**. Design notes: [docs/DISCOVERY.md](../DISCOVERY.md).

## Latest (Oct 25 2026, later) — end-to-end check results

Production runs of asana.com and notion.com (before the fixes below were deployed):

- **Product Hunt:** in-house via residential proxy for all 6 products (36–50 reviews each).
- **G2:** in-house via Apify Unblocker, but **10 reviews only** (page 1); Notion, Obsidian, Coda and Monday.com were
  "still scraping after 75s". Probe of `g2.com/products/asana/reviews?page=2` through the Unblocker: five 30 s
  timeouts, then 200; another try 502. `collect` stopped at the first failed page. **Fix:** skip a failed page, stop
  after two failures in a row (`review_parsers.collect`).
- **Capterra: never in-house.** Discovery passes the product root (`/p/<id>/<name>/`), which has no review cards, so
  every Capterra scrape fell back to the Apify actor (and that result is now cached 30 days per page URL). **Fix:**
  `collect` reads `/p/<id>/<name>/reviews/` (`capterra_reviews_url`); checked live, Asana-PM: 50 reviews, 2 pages.
- **Asana-PM:** `pm` added to `_EDITION`.
- **Own unblocker (probe):** Capterra: CapSolver refused the proxy, `ERROR_INVALID_TASK_DATA ... proxy host uses
  dynamic DNS` (`gw.dataimpulse.com` resolves to 3 IPs). **Fix:** `sticky_proxy` pins the gateway to one IP; re-probe
  after deploy. G2: all 3 sticky DataImpulse US IPs answered DataDome `t=bv` (IP banned), so no captcha to solve:
  CapSolver cannot help G2 on DataImpulse IPs.
- Pre-existing failing test: `test_grounding_links_are_resolved_to_real_pages_and_failures_fall_back_to_ddg`.

## Earlier (Oct 25 2026, 06:50 UTC)

- **Reviews are scraped in-house now** (`mvp/review_parsers.py`, PR #133, live): G2 and Capterra pages are fetched
  through **Apify's Unblocker proxy** (~$0.001/page) and parsed in-house; Product Hunt through the DataImpulse
  residential proxy. The Apify scraper actors are only a fallback when nothing parses. Reviews cached 30 days.
- **Measured:** stealth browsers (headless/headed Chromium, Patchright, Camoufox) + DataImpulse or Apify residential
  IPs (US-only too) are **blocked** by G2 (DataDome) and Capterra (Cloudflare). Only Apify's Unblocker gets through.
  Capterra pages also load from a Claude cloud container's IP directly.
- **In progress when the session ended:** an end-to-end production run on asana.com (Product Hunt in-house: 50
  reviews; Capterra page match missed "Asana-PM"; G2 still scraping). Re-run asana.com / notion.com on
  `/discovery` and check each "reviews" trace line says "in-house via ...".
- **Own-unblocker prototype** (`review_fetch.own_unblock`, on branch `claude/funny-euler-li5h0f`, commit d31db63, not
  merged): sticky DataImpulse US IP (ports 10000-20000) + CapSolver (`AntiCloudflareTask` for Capterra,
  `DatadomeSliderTask` for G2), clearance cookie reused. **Untested.** Test after merging:
  `curl -XPOST https://35-202-98-224.sslip.io/api/discovery/probe -H 'content-type: application/json' -d '{"url":"https://www.capterra.com/p/160498/Shortcut/reviews/","proxy":"own_unblocker"}'`
  (also a G2 URL). Needs `CAPSOLVER_API_KEY` on the server (present). Output shows each step and whether the solve
  cleared the challenge.
- **Known gaps:** G2 paging via the Unblocker can 502 (fewer than 50 G2 reviews); Capterra name match rejects
  listings like "Asana-PM" (add `pm` to `_EDITION` in `mvp/discovery.py`).
- **Probe/sample tools:** `POST /api/discovery/probe {url, proxy: saved|apify_unblocker|apify_residential|own_unblocker,
  browsers}`; `POST /api/discovery/sample {url, proxy, current_apify_token}` returns a page's HTML (token-gated).
- **Rotate** the DataImpulse password, Apify, Product Hunt and G2 tokens (pasted in chat).

## Where things stood earlier (Oct 25 2026)

| Piece | State |
|---|---|
| Discovery agent + `/discovery` page | Live. A run takes ~1.5–2.5 min (was 5.5). |
| Search | Gemini 2.5 Flash with Google Search grounding, 2.5 Pro fallback; DuckDuckGo for `site:` queries. No Apify. |
| Competitors | Led by a Google-grounded "most compared with" list; homepages confirmed in search results, then probed live. |
| Real users | G2 / Capterra / Product Hunt review pages found by search, scraped by **Apify** (zen-studio for G2, trakk for Capterra, eiv for Product Hunt). |
| Keys on the server | Saved via the page ("Data source keys"): `APIFY_TOKEN`, `PH_TOKEN`, `PH_CLIENT_ID`, `PH_CLIENT_SECRET`, `PROXY_URL` (DataImpulse residential, 5 GB). Stored in `/var/lib/usersim/discovery_keys.json`, never returned by the API. |
| **Open: replace Apify scrapes in-house** | In progress, see below. |

The Apify account hit its $105 monthly cap on Oct 25 (raised since). Replacing the scrapes is the reason for the
in-house work.

## In-house scraping: what is known

Measured on the production VM (`POST /api/discovery/probe`), each through the DataImpulse residential proxy:

| Site | curl_cffi (Chrome fingerprint) | headless Chromium | headed Chromium / Patchright / Camoufox |
|---|---|---|---|
| Product Hunt | **200, works** (~1 MB, 3–5 s) | — | not needed |
| G2 (DataDome) | 403 | 403 (challenge never clears in 30 s) | **not measured yet** (first run crashed, fix in PR #127) |
| Capterra (Cloudflare) | 403 from the VM | 403 | **not measured yet** |

From a Claude cloud container (data-centre IP, no proxy) Capterra loads with every method; G2 and Product Hunt are
blocked. Capterra blocks some IPs and not others.

**Next step:** run the probe from your own machine (a home connection is a residential IP), with and without the
proxy, and see which method passes G2 and Capterra. Then build parsers only for the method that works.

## Run the probe locally

Needs Python 3.11+.

```bash
git clone https://github.com/ShreyasPatel031/UserSim && cd UserSim
python -m venv .venv && source .venv/bin/activate
pip install curl_cffi httpx playwright patchright "camoufox[geoip]==0.4.11"
python -m playwright install chromium
python -m patchright install chromium
python -m camoufox fetch          # Camoufox 0.4.11: newer releases have no published browser build

python scripts/review_fetch_probe.py                                   # direct, your home IP
PROXY_URL='http://USER:PASS@gw.dataimpulse.com:823' python scripts/review_fetch_probe.py   # via the proxy
python scripts/review_fetch_probe.py https://www.g2.com/products/notion/reviews            # any review URL
```

Each method prints `PASS` (200, no bot challenge) or `blocked`, with status, title, size and time. Browser windows
open briefly for the headed methods. Proxy credentials are in the DataImpulse dashboard (Proxy Access); they were
pasted into a chat, so regenerate them.

Methods, in `mvp/review_fetch.py`:

- `patchright_*`: Patchright (Chromium with automation leaks patched), headed.
- `headed_chromium_*`: Playwright Chromium, headed, no UA override or injected scripts.
- `headless_chromium_*`: Playwright Chromium headless, with `navigator.webdriver` etc. hidden.
- `camoufox_*`: anti-fingerprint Firefox, geoip locale/timezone from the proxy exit IP.
- `chrome_fingerprint_*`: curl_cffi with Chrome's TLS/HTTP2 fingerprint (no browser).
- `plain_via_proxy`: httpx, for comparison.

Browsers wait up to 30 s for a challenge page to turn into the real page; images, fonts and media are not downloaded
(proxy traffic is billed per GB, ~0.5–1 MB per review page).

## If nothing passes G2 / Capterra

Options, in increasing cost and maintenance:

1. **CapSolver** (key already on the server as `CAPSOLVER_API_KEY`): `AntiCloudflareTask` returns a `cf_clearance`
   cookie for Capterra, `DatadomeSliderTask` a `datadome` cookie for G2; both need the proxy and the cookie only works
   from the same IP, so use a sticky proxy session (check DataImpulse's sticky ports / session usernames). A few tenths
   of a cent per solve. Not built.
2. **Keep Apify for G2 and Capterra only**, cheaper: cache reviews per product for 30 days, and stop the zen-studio G2
   scrape paying for 100 results and discarding its Capterra half (`mvp/discovery.py` `scrape_review_page`).

Both sites' terms forbid automated scraping; low volume and caching keep the practical risk small.

## Run discovery itself locally

```bash
pip install -r mvp/requirements.txt google-auth
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json   # Vertex (Gemini); usersim-cloud-agent works
export APIFY_TOKEN=... PH_TOKEN=... PH_CLIENT_ID=... PH_CLIENT_SECRET=...
export MVP_MCP=0 MVP_A11Y_LOOP=0 USERSIM_SECRETS_OFF=1
PYTHONPATH=src uvicorn mvp.server:app --port 8787        # open http://localhost:8787/discovery
```

If the server's startup hooks fail on missing study dependencies (Browserbase etc.), start it from a small script that
clears `app.router.on_startup` before `uvicorn.run(app)`.

Checks without the LLM: `python scripts/discovery_sources_check.py --product Linear --competitors Jira Shortcut`.
Tests: `PYTHONPATH=src python -m pytest mvp/test_discovery.py mvp/test_review_fetch.py`.

## Files

| File | What |
|---|---|
| `mvp/discovery.py` | The agent: site read, search, competitor pick, review pages, segments and tasks, trace, saved keys |
| `mvp/review_fetch.py` | In-house fetch methods and `probe()` |
| `mvp/static/discovery.html` | The page (result, agent trace, real users, keys) |
| `mvp/server.py` | `/discovery`, `/api/discovery*` (runs, keys, probe) |
| `scripts/review_fetch_probe.py` | Local probe runner |
| `scripts/discovery_sources_check.py` | Search + review sources check, no LLM |
| `docs/DISCOVERY.md` | Design and API |
