# Hacker News daily top 100 / top 10: results so far (Oct 30, 2026, overnight run)

Target: each UTC day's top 100 / top 30 / top 10 stories by final points, all story types (~960 a day).
Score: recall@k = share of the day's real top k that the model's top k also contains, averaged over days, 95%
bootstrap interval over days. Held out: May–Sep 2026 (153 days); each test month is predicted by a model trained only
on stories before it (history from Jan 2023, BigQuery public HN dataset). Random picks: top 100 10.6%, top 30 3.2%,
top 10 1.1%.

## Scoreboard (each row adds one block of data)

| Data | top 100 | top 30 | top 10 |
|---|---|---|---|
| post only: title text, domain / author records (2+ day old stories), timing | 30.8% | 20.8% | 16.5% |
| + comments in first 30 min | 39.1% | 34.0% | 27.8% |
| + who commented in first 30 min (their past record of early comments on top stories) | 39.6% | 35.0% | 27.5% |
| + comments in first 60 min | 50.4% | 48.2% | 36.4% |
| + who commented in first 60 min | 51.2% | 48.3% | 35.2% |
| + submitter as a commenter | **51.5%** (50.7–52.3) | 48.4% | 34.1% |
| + favorites taste (partial: HN blocked most favorites fetches) | 51.4% | 48.4% | 35.2% |

Blocks that added nothing measurable: a crowd model (20,000 most active people, who would engage, tallied: +0.2),
favorites taste (+0.0), Gemini reading titles (worse than the text model; dropped).

## Prior work, reproduced on the same data

| Method | What it is | Result here |
|---|---|---|
| Michael Taylor (every.to): persona votes | 1,000 personas built from real commenters' comments vote on headlines; balanced front page vs not | 53% accuracy, AUC 0.57 (3 days: 55 / 54 / 51%; he reported 60% on one day). 100 vs 1,000 personas: no difference. $2.91 |
| Philipp Dubach: RoBERTa title model (HF, MIT) | P(>=100 points) from the title | running |
| Szabo & Huberman (2010): early votes | rank by log upvotes at 30 / 60 min (Quality News minute data) | data fetching |
| Quality News / Stoddard: upvote rate | upvotes / expected upvotes at the ranks shown | data fetching |
| OpenPipe: HN reward model | LLM on title + URL + article text | weights not released; their article text ends Nov 2024 (no overlap with test months) |

## Data per person (what we know about each HN user)
- 13.8M comments by 378k people since Jan 2023 (BigQuery), each tied to its story and time.
- For early commenters: past record of commenting early on stories that made the top 100 / top 10 (smoothed), by
  topic and recency; account age (HN API, 37k profiles); usual comment speed; record on the story's domain.
- Favorites (public "likes"): HN refuses most requests from the VM; a slow fetch is running.

## Live
- hn-sim-1 / hn-sim-2 (own VMs): live recorder of the front page (every 5 min) and every new story's points at
  15 / 30 / 60 min (tables hn_frontpage, hn_early_points). Early points are what HN ranks on; history only exists
  from Quality News (from mid-2025).
- Hourly daily forecast (forecast_live.py): being deployed.

## Spend (measured, logged to `spend`)
Gemini ~$6 (persona votes $3.0, title test $1.4, judge/pilot $2), BigQuery < $0.1, VMs ~ $1/h.
