# Request for Grok Bot: read Product Hunt's daily leaderboard page (Nov 1, 2026)

## Why
The pipeline gets each day's launches from the Product Hunt API. On Oct 31 the API's paging repeated SKI and
Specsight and left out Godwit (79 votes) and AwaitIO (65), so the forecast never covered them. The daily
leaderboard page lists every featured launch of the day, so reading that page directly is the simplest check.

Read-only. Please don't upvote, comment, follow or post.

## What to read
Page: `https://www.producthunt.com/leaderboard/daily/<YYYY>/<M>/<D>` (for example `.../daily/2026/11/1`), the
"all" tab, scrolled to the end so every launch is loaded.

## When
1. **Today, as soon as you can:** Nov 1 (the launch list is what matters; votes are early).
2. **Every day at 00:20 PT:** that day's page (launch list for the forecast).
3. **Every day at 23:50 PT:** that day's page again (near-final ranks and votes, to score the forecast).
4. **Once:** Oct 31 (final), to check yesterday's score.

## Output
One JSON file per read, to `gs://usersim-bakeoff-347838016394/usersim_sim/raw/leaderboard/<YYYY-MM-DD>_<HHMM>PT.json`:
```
{"day": "2026-11-01", "read_at": "2026-11-01T00:20:00-07:00", "url": "...", "complete": true,
 "launches": [{"rank": 1, "name": "...", "tagline": "...", "slug": "...", "url": "https://www.producthunt.com/products/...",
               "votes": 123, "comments": 20}]}
```
Set `complete` to false if the page didn't finish loading or showed a bot check. Please don't retry past a bot
check; write the file with what loaded and an `"error"` field.

## What happens with it
`pipeline/list_check.py` compares the API list with the page: any launch missing from the API list or repeated in it
is flagged in the run log and added before the forecast.

## Separate, if you can (needs the GCP account)
The pipeline machine `usersim-pipeline` (us-central1-a) stayed on after Oct 31, so the 07:05 UTC schedule didn't
start today's run. Stop and start it once (`gcloud compute instances stop usersim-pipeline --zone us-central1-a`,
then `start`); on boot it runs the day's pipeline and powers itself off after the hourly recorder ends.
