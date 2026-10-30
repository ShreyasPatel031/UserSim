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
| + people2: early commenters' account age, new accounts, comment speed, record on this domain | 51.5% | 48.7% | 35.2% |
| + domain popularity (Tranco top-1M rank) | 51.6% | 48.6% | 34.8% |
| + submitter reach (HN profile links, account age) | 51.5% | 48.5% | 34.6% |
| + on Lobsters before HN | 51.5% | 48.5% | 33.9% |

**Forecast made later in the story's life (late bloomers):** a story scored once it is 2 / 4 / 8 hours old, with its
comments in that window:

| Forecast age | top 100 | top 30 | top 10 |
|---|---|---|---|
| 60 min | 51.2% | 48.7% | 35.9% |
| 2 h | 62.4% | 56.9% | 41.8% |
| 4 h | 69.9% | 65.8% | 51.1% |
| 8 h | **73.7%** | 71.8% | 57.3% |
| 8 h, per-day ranker | 66.0% | **75.4%** | **67.1%** |

Model variants (60 min, same data):

| Variant | top 100 | top 30 | top 10 |
|---|---|---|---|
| classifier (made the day's top 100) | **51.2%** | 48.7% | 35.9% |
| per-day ranker (graded by rank) | 48.5% | **50.5%** | **40.2%** |
| + comment acceleration (0-15 / 15-30 / 30-60 min) | +0.1 | +0.1 | -1.3 |
| + topic-specific early-commenter records | +0.0 | -0.4 | +0.0 |

Use the ranker for the top-10 / top-30 list and the classifier for the top 100. (An earlier acceleration run leaked
the outcome: stories never commented on were filled differently from stories commented on later; discarded.)

**Event level (Sep 2026, best model):** of each day's real top 10, the model's top 10 contains 36% (by event: the
same news under any submission; 35% exact), its top 30 63%, its top 100 81%.

**Where it fails:** 60 of 300 real top-10 stories in Sep 2026 had zero comments in their first hour and took off
later (".name Termination" 2,230 points, "Claude, change the 'Add to Cart' button to blue" 1,215, "Audacity 4.0"
1,163). An hourly forecast with longer windows (2 / 4 / 8 h) is being tested for these late bloomers.

Blocks that added nothing measurable: a crowd model (20,000 most active people, who would engage, tallied: +0.2),
favorites taste (+0.0), Gemini reading titles (worse than the text model; dropped).

## Prior work, reproduced on the same data

| Method | What it is | Result here |
|---|---|---|
| Michael Taylor (every.to): persona votes | 1,000 personas built from real commenters' comments vote on headlines; balanced front page vs not | 53% accuracy, AUC 0.57 (3 days: 55 / 54 / 51%; he reported 60% on one day). 100 vs 1,000 personas: no difference. $2.91. **Same ballots, our post-only model: 69% accuracy, AUC 0.76; adding the persona votes lowers it (66%, 0.72)** |
| Philipp Dubach: RoBERTa title model (HF, MIT) | P(>=100 points) from the title | running |
| Szabo & Huberman (2010): early votes | rank by upvotes at 30 / 60 min (Quality News minute data, which goes back to mid-2025) | **best single signal.** Sep 20-30 (11 days): upvotes at 60 min alone 57.2% / 51.5% / 47.3% (top 100 / 30 / 10) vs our 60-min model 51.9% / 48.5% / 36.4%. Trained combination: running |
| Quality News / Stoddard: upvote rate | upvotes / expected upvotes at the ranks shown | weak alone: 39.7% / 23.9% / 20.9% |
| Lerman & Hogg (2010): early votes + site design | adjusts early votes for where the story was shown | covered by the Quality News rank and expected-upvote inputs in the trained combination |
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

## Against HN's real daily list (news.ycombinator.com/front?day=D), Sep 2026, 30 days
The real list is ordered by HN's ranking (time decay, penalties), not by points, and 21% of its top 30 were posted
the day before. A perfect "top by final points" list matches only 47% of the real top 10 and 47% of the real top 30.

| | real top 10 in model top 10 | in top 30 | in top 100 | real top 30 in model top 30 | in top 100 |
|---|---|---|---|---|---|
| 60-min model (trained on points) | 18.7% | 39.7% | 67.0% | 23.8% | 48.8% |

Next: train on the real list itself (daily lists fetched back to Jan 2025).

## Trained on HN's real daily list (May–Sep 2026, 153 days; lists from Jan 2025)

| Model | real top 10 in model top 10 | in top 30 | in top 100 | real top 30 in model top 30 |
|---|---|---|---|---|
| 60 min, trained on points | 15.8% | 38.7% | 65.1% | 25.2% |
| **60 min, trained on the real list** | **30.3%** | **53.1%** | 68.2% | **38.1%** |
| 8 h, trained on points | 29.0% | 63.1% | 86.7% | 39.5% |
| **8 h, trained on the real list** | **50.2%** | **78.6%** | 87.2% | **62.1%** |

## Early upvotes, trained combination (Quality News data; train Aug 22–Sep 15, test Sep 16–30, 15 days)

| Method | top 100 | top 30 | top 10 |
|---|---|---|---|
| ours 60 min | 52.3% | 50.7% | 35.3% |
| upvotes at 60 min alone (Szabo & Huberman) | 57.7% | 53.3% | 46.0% |
| ours + early upvotes (trained for top 100) | **68.5%** | 55.6% | 40.0% |
| ours + early upvotes (trained for top 30) | 62.6% | 55.6% | 45.3% |

## Dubach's RoBERTa title model (test May–Sep 2026, trained from Mar 2026)

| Method | AUC (>=100 pts) | top 100 | top 30 | top 10 |
|---|---|---|---|---|
| Dubach alone | 0.67 (he reported 0.685) | 19.1% | 10.3% | 6.1% |
| ours post-only | 0.755 | 29.5% | 19.5% | 15.0% |
| ours post-only + Dubach | 0.783 | 31.8% | 22.2% | 17.1% |
| ours 60 min + Dubach | 0.878 | 51.7% | 49.2% | 34.9% |

## Operations note
hn-sim-1/2 were stopped four times (04:36, 08:43, 11:21 UTC, plus 08:16 for others) by a Cursor agent on another
machine using the shared usersim-cloud-agent service account (audit log, per the PH session). A watchdog restarts
them and requeues jobs; long jobs save every 5-15 minutes.

## Daily list v2 (current best): HN's real daily list, 153 held-out days (May–Sep 2026)
Per-day ranker on the real list; candidates posted in the 72 h before the end of the day; inputs: post block, who
commented early, submitter, the story's place on the previous day's list, and comments up to the forecast time.

| Forecast made at | real top 30 in our top 30 | real top 10 in our top 10 | real top 10 in our top 30 |
|---|---|---|---|
| 06:00 UTC | 21.2% | 16.3% | 18.9% |
| 12:00 UTC | 32.1% | 24.6% | 29.6% |
| 18:00 UTC | 54.6% | 42.2% | 65.9% |
| end of day (before the list is published) | **65.8%** | **55.1%** | **87.8%** |

For reference: knowing every story's exact final points reproduces 58% of the real top 30. Early forecasts are
capped by stories not yet posted. Next: votes over the day (Quality News hourly upvotes and rank).

## Daily list v3 = v2 + votes and HN rank over the day (Quality News hourly), Sep 23–30 (8 test days, 10 training days)

| Forecast at | v2 (comments) | v3 (+ votes and rank) | HN's live rank at that moment only |
|---|---|---|---|
| end of day: real top 30 in our top 30 | 64.6% | **77.1%** (72.9–81.7) | 55.8% |
| end of day: real top 10 in our top 10 | 53.7% | **66.2%** | 46.3% |
| end of day: real top 10 in our top 30 | 83.8% | **93.8%** | 76.2% |
| 18:00 UTC: real top 30 / top 10 | 51.7% / 36.2% | **55.8% / 50.0%** | 48.7% / 35.0% |
| 12:00 UTC: real top 30 / top 10 | **40.4% / 26.3%** | 33.3% / 23.8% | 34.2% / 18.8% |

Small sample (8 days); the 12:00 stage-2 overfits on 10 training days. Fetch continues back to Aug 29 (more training days).
