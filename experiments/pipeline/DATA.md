# UserSim data warehouse

Everything we have collected, cleaned, in one place, queryable by any agent. Durable: Parquet files in Cloud Storage
(`gs://usersim-bakeoff-347838016394/usersim_sim/`), plus an immutable raw backup under `raw/`.

## Query it

```bash
cd experiments
python -m pipeline.q --tables                                   # tables and row counts
python -m pipeline.q "SELECT kind, count(*) FROM events GROUP BY 1"
```

```python
from pipeline import warehouse as W
df = W.query("SELECT * FROM people WHERE person = 'some_user'")
W.write("spend", new_rows)          # append; never edit old parts
```

The first call pulls the tables into `~/.usersim_sim` (about 200 MB); later calls fetch only new parts.
Needs `gcloud` auth with read access to the bucket, plus `pip install duckdb pandas pyarrow`.

## Rules

- **Append, never rewrite.** Every write adds a part. Snapshot tables (marked *snapshot*) keep the newest row per key
  (`updated_at`); log tables keep every row.
- **Every fact is dated.** `date` is when it happened. `observed_on` / `last_fetched` is when we read it. Undated facts
  (follow lists, profiles) carry the day they were read, so a model as of day D must use only `observed_on < D`.
- **Fetch only what is new.** Before fetching anything about a person or launch, read `fetch_state` / `launch_state`
  (see `pipeline/incremental.py`). Every fetch writes its `fetch_state` row.
- **Costs are logged.** Every paid call or proxy byte goes into `spend`.

## Tables

| Table | Key | What one row is | Columns |
|---|---|---|---|
| `people` (snapshot) | person | a Product Hunt user we know about | person, headline, about, twitter, joined, ph_followers, ph_followings, is_maker, upvotes_total, li_headline, li_company, li_location, x_bio, x_followers, segments (JSON), stacks (JSON), reviews (JSON), first_seen |
| `launches` (snapshot) | id | a launch and its final outcome | id, slug, day, name, tagline, description, topics (JSON), poster, makers (JSON), daily_rank, weekly_rank, monthly_rank, votes, outcome_final |
| `events` (log) | — | a person upvoted or commented on a launch | person, launch_id, date, kind (upvote / comment), date_quality (exact / launch_day: upvote times are not public, so the launch day stands in) |
| `comments` (log) | — | a comment with its text | person, launch_id, slug, date, text |
| `follows` (log) | — | person follows followee, as read on observed_on | person, followee, observed_on |
| `fetch_state` (snapshot) | person, source | what we last fetched about a person | person, source (upvotes_page1, upvotes_scroll, follows, profile, profile_tabs, activity_tabs, linkedin, segments), last_fetched, status, items, newest_item (newest upvoted launch id seen), complete, back_to |
| `launch_state` (snapshot) | launch_id, source | what we last fetched about a launch | launch_id, slug, source (comments, site), last_fetched, items |
| `forecasts` (log) | — | a prediction made before results | forecast_date, model, predicted_rank, name, launch_id, made_on |
| `backtests` (log) | — | one held-out backtest score | run_file, run_on, variant, list (day@3 ...), recall, seeds, months |
| `persona_ratings` (log) | — | a persona's 1–5 fit rating of a launch | person, day, launch_id, design, rating |
| `spend` (log) | — | money spent on a step | step, provider, usd, note, logged_on |
| `pipeline_runs` (log) | — | one step of the daily pipeline | run_date, step, status, items, bytes, usd, seconds |

## Raw backup

`raw/ph_predict_data/` (every raw fetch: launch days, comment pages, profiles, follow lists, upvote pages and scrolls,
LinkedIn, X), `raw/simlab_cache/` (person rows, persona ratings, model inputs), `raw/simlab_data_v2/` (the store).
Never edited; new raw fetches go under `raw/<source>/<date>/`.

## Privacy

Person-level data (usernames, comments, profiles) is for research only. The bucket sits in a shared project, so keep
it out of anything public and share aggregates, not rows.
