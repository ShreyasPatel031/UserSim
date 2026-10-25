# Product Hunt top-list predictor

Predicts which launches end up on Product Hunt's front-page lists (**Yesterday's / Last Week's / Last Month's Top
Products**, and the same lists per topic) **without using any launch's own votes, comments or ranks**. Results:
[`results/REPORT.md`](results/REPORT.md).

## Pipeline

| Step | Script | Where it runs | Source |
|---|---|---|---|
| Featured launches per Pacific day (labels + metadata) | `collect_ph.py` | container | Product Hunt API v2 (`PH_TOKEN`), 6,250 complexity / 15 min |
| Today's launches (forward test) | `today.py` | container | same |
| Launch website (no producthunt.com fetches) | `resolve_sites.py` | VM (direct, no proxy) | maker `websiteUrl`, links in the description, `<slug>.{com,ai,app,io,so,dev,co}`; a guessed domain must mention the product and share ≥3 pitch words |
| X followers (hunter, makers, company) | `external.py x`, `sitex` | container | fxtwitter |
| Domain registration date | `external.py rdap` | container | rdap.org |
| Hacker News before launch | `external.py hn` | container | Algolia HN, `created_at < launch day` |
| Archived before launch? | `external.py wb` | container | archive.org availability API (closest snapshot ≤ day before launch) |
| LLM judgements (pitch / pitch+homepage / brand) | `llm.py` | container | Claude Sonnet 4.5 on Vertex (training data predates every launch) |
| Features | `features.py` | | |
| Backtest, ablations, importance | `run.py`, `model.py` | | |
| Factor table | `factors.py` | | |
| Report / dashboard data | `report.py`, `export_dash.py` | | |
| Forecast for a live day | `forecast.py <date>` | | |

`sync.sh` and `ext_loop.sh` keep the VM resolver, the outside-signal lookups and the LLM scoring caught up while
collection runs. Data lives in `data/` (not committed: homepage HTML is large).

## Daily use

```bash
./forecast_today.sh 2026-10-26        # today's launches -> results/forecast_2026-10-26.md
python3 forecast_week.py 2026-W44     # this week's list, from a model trained before the week
```

New finished days come in with `python3 collect_ph.py <from> <to>`; then rerun `run.py` to refresh the backtest.

## Backtest design

- **Rolling origin by month.** Test month M is predicted by models trained only on launches before M.
- **Labels never used as inputs.** History features (`hist_*`: how the hunter's and makers' *other, earlier*
  launches did) use only days strictly before the launch, as a live predictor would.
- **Lists scored against PH's own rank fields** (`dailyRank`, `weeklyRank`, `monthlyRank`), which are not pure
  vote order. Weeks are ISO weeks (they match `weeklyRank`); only weeks fully inside the test span count.
- **Topic lists**: top k by votes among launches carrying the topic, per day / week / month.
- **Recall@k** = |predicted top k ∩ actual top k| / k, averaged over lists; 95% bootstrap CI over lists.
- **Random tie-break.** The API returns launches in rank order, so ties must never fall back to row order.

## Known limits

- **Follower counts are today's**, not launch-day. A top launch earns its makers followers, so maker PH
  followers are excluded from the headline model (`LEAKY` in `model.py`) and reported separately. Hunter PH
  followers and X followers are kept; they are mostly built up before any one launch, but they are not
  launch-day snapshots either.
- **Featured set and its size** (`ph_day_n_launches`, within-day ranks) are known only once the day's featuring
  is done (early in the day).
- **Weekly / monthly list models** compare a launch with the rest of its week / month, so they assume the period's
  launches are known (their votes are not used).
- **Homepages are mostly the live site.** The Wayback Machine banned the VM's IP for a while after a burst of
  requests, and web.archive.org is unreachable from the container. A slow pass (`wayback_snap.py`, ~1 request/s)
  later fetched pre-launch snapshots for 693 September–October launches; 186 had one. On those, homepage features
  predict about equally weakly from the snapshot and from the live site (`snapshot_vs_live.py`), so using the live
  site does not change the finding that the homepage adds little.
- **Not used:** GitHub stars (the container's GitHub token only reaches this repo), LinkedIn (999), Reddit
  (blocked; its API keys are not readable by this service account), Google/DataForSEO search (secrets not
  readable), producthunt.com pages (403; scraping them through proxies was ruled out).
