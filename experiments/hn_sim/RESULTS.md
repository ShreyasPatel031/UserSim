# Hacker News daily top 100 / top 10: results so far (Oct 30, 2026, overnight run)

Target: each UTC day's top 100 / top 30 / top 10 stories by final points, all story types (~960 a day).
Score: recall@k = share of the day's real top k that the model's top k also contains, averaged over days, 95%
bootstrap interval over days. Held out: May–Sep 2026 (153 days); each test month is predicted by a model trained only
on stories before it (history from Jan 2023, BigQuery public HN dataset). Random picks: top 100 10.6%, top 30 3.2%,
top 10 1.1%.

## Current headlines: Caught per post (north star 80% at each checkpoint; updated 2026-11-04 16:30 UTC)
| checkpoint | headline | what it is |
|---|---|---|
| 1 h | **48.5% [45.0, 52.1]** (Sep 1 - Oct 14) | rank only + history score + content model (large) |
| 15 min (posting clock: judged 15 min after posting) | **29.6%** Oct 2 - 14 daily retrain = **headline for the live product** (dense early-vote coverage, as live); **28.4% [25.8, 31.3]** Sep 1 - Oct 14 = full-period backtest headline (was 24.7%; paired +3.7 [+1.2, +6.1]) | votes + who + volume + hour (Oct 2-14; the light model reaches 30.2% there, +0.5 [-2.7, +3.5], not significant); light model: all 2025 Wayback rows + content (full period) |
| at posting | **26.1% [23.9, 28.2]** (Sep 1 - Oct 14) | 3-way rank blend: Jul-Aug model + 2025+ history + content model (large) |
Secondary line, never the headline (orchestrator decision 2026-11-03 16:55 UTC): 15 min on the exposure clock (also
judged 15 min after a front-page return or /pool entry; direction B) 34.5% [31.5, 37.7], Oct 2-14. Content model at
15 min on the posting clock (Oct 2-14, vs votes + who 28.4%): 30.2%, +1.8 [-1.1, +4.8], not significant.

**Honest ceiling at 15 min (posting clock), from the miss decomposition (miss15.py):** perfect flagging of every fast
post (front page within 1 h) would give about 28.0 + 25.2 + 5.1 + 3.3 = **61.6%**. The other 38.4 pts are late risers
(25.5) and re-ups (12.9): posts with no front-page signal in their first hour. **80% needs about half of the late
risers and re-ups caught from at-posting or first-15-min off-HN signals.** Re-ups have no 15-min data source: /pool is
sampled every 5 min live, but /pool entry comes a median 23 h after posting.

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

## Daily list: more list days, three months of votes (2026-10-30)

More daily lists (2023-03..2024-12, 638 days, from news.ycombinator.com/front?day=) for the comment-only ranker, tested on
153 days from 2026-05-01 (more_days.py): no gain. End of day real top 30 in our top 30 64.6% with vs 64.5% without;
top 10 53.6% vs 53.3%; 12:00 and 18:00 UTC also within 1 point.

Votes for June-August (Quality News, stories with 30+ final points; every daily top 30 this summer had 44+): stage 2
trained on 87 days, tested on 18 fully fetched September days (daily_fast.py 2026-09-01).

| forecast | comments only: top 30 / top 10 | + votes, rank, age, previous list: top 30 / top 10 | real top 10 in our top 30 |
|---|---|---|---|
| 12:00 UTC | 37.2% / 28.3% | 40.2% / 27.8% | 33.9% |
| 18:00 UTC | 53.1% / 39.4% | 62.2% / 50.6% | 65.0% |
| end of day | 65.9% / 59.4% | 82.2% / 76.7% | 94.4% |

The 30-point cut uses final points (stories under 30 get the no-votes fill); leak_check.py measures its effect.

Leak check (leak_check.py, same stage-2 model, September tested with real votes for every story, as a live forecast
would see them): end of day unchanged (82.4% / 76.7%); 18:00 UTC top 30 59.8% (cut 62.2%); 12:00 UTC top 30 36.5%
(cut 40.2%); top 10 unchanged at both. Honest numbers are the no-cut ones.

All June-August votes fetched (5+ final points; under 5 Quality News mostly has no page): no 30-point cut, trained on
87 summer days, tested on 18 fully fetched September days. Best variant (+ votes, rank, age, previous list):

| forecast | real top 30 in our top 30 | real top 10 in our top 10 | real top 10 in our top 30 |
|---|---|---|---|
| 12:00 UTC | 38.3% [35.2, 42.0] | 27.8% [21.7, 34.4] | 32.2% |
| 18:00 UTC | 62.0% [59.4, 64.6] | 51.7% [46.7, 56.7] | 65.0% |
| end of day | 81.9% [79.8, 83.7] | 76.7% [72.2, 81.1] | 94.4% |

Where the misses come from (18 September test days, best variant, per day out of the real top 30):

| forecast | found | not posted yet at T | ranked 31-60 by us | ranked below 60 |
|---|---|---|---|---|
| 12:00 UTC | 11.5 | 13.4 | 0.6 | 2.9 |
| 18:00 UTC | 18.6 | 5.0 | 1.6 | 3.2 |
| end of day | 24.6 | 0 | 3.4 | 0.4 |

(The rest of each 30 are stories posted more than 72 h before the day ended, outside the candidate window.)
HN's ranking formula at T, real rank minus formula rank (penalties), comments per point: no gain (18:00 61.7% vs
62.0%; end of day 81.1% vs 81.9%); deeper trees: no gain.

Votes for Sep-Oct 16 added (136 fully fetched days). Stage 2 trained on 90 summer days, tested on 46 days
(2026-09-01..10-16); best variant (+ votes, rank, age, previous list), by forecast time (2023-24 lists left out: no gain,
and memory):

| forecast (UTC) | real top 30 in our top 30 | real top 10 in our top 10 | real top 10 in our top 30 |
|---|---|---|---|
| 12:00 | 35.1% | 25.7% | 28.3% |
| 15:00 | 46.5% | 33.0% | 42.0% |
| 18:00 | 59.9% | 49.8% | 64.1% |
| 20:00 | 68.0% | 60.9% | 78.7% |
| 21:00 | 73.5% | 64.3% | 85.4% |
| 22:00 | 77.2% | 70.2% | 92.2% |
| 23:00 | 78.6% | 72.4% | 93.7% |
| end of day | 80.1% | 74.1% | 95.0% |

Training on 120 days (to Sep 30) and testing October 1-16: no change (end of day 81.5%, 18:00 59.4%).

## How HN builds the daily list (2026-10-31, list_rule.py and checks)

- Every story is on exactly one day's list: 20,159 listed stories, all 120 ranks, 0 on two days.
- The day: the UTC day the story first reached the front page (rank <= 90 on Quality News), or its posting day if it
  got there within 30 min: 93.6% of list entries (posting day alone: 86.5%; shifted day boundaries are worse).
- 15-20% of a day's top 30 were posted 2+ days earlier: second-chance re-ups that return days later. HN's API, item
  page and list page all show the original time, so re-ups are seen only through rank history.
- Order within the day: not points alone (a 1,160-point story at #5 below 685). With list membership known: final
  points 79% of the top 30 (rank corr 0.89), points with a comments penalty 81%, a ranker on final points + comments
  + front-page history 90% (5-fold by day). So ~90% is the practical ceiling even at end of day.
- No simple rule from the day's front-page ranks works: exposure 55%, time in top 10 60%, points gained 56%.
- Outside feeds (Grok Bot backfill, 86,630 URLs): of the ~14 daily top-30 stories not yet posted at 12:00 UTC, 0.8/day
  had their URL in a feed before 12:00 (0.4/day at 18:00): feeds can add at most ~3 points at noon.
- Model variants on the v4 table (relative ranks, binary classifier, bigger trees, points regressor): no gain.

Early v4 with whole-life Quality News series (re-ups visible), 10 fully fetched test days (Sep 7-10, 22-27), trained
on 15 fully fetched days: real top 30 in our top 30 at 21:00 UTC 80.3% [76.3, 83.7] (was 72.7% without re-ups), end
of day 88.3% [86.3, 90.3] (was 79.6%); share of the real top 30 the model can see: 97% at 21:00, 100% at end of day
(was 87% / 90%). 18:00 UTC 59-64%. Full run pending the rest of the fetch.

### v4 full result (whole-life series, timeouts re-fetched; 57 train days Jul-Aug, 46 test days Sep 1 - Oct 16)

v4 + comments (v4_cov.py 2026-09-01 ... 0.97); "visible" = share of the real top 30 posted / back on the page by T.

| forecast (UTC) | real top 30 in our top 30 | real top 10 in top 10 | real top 10 in top 30 | visible | previous model |
|---|---|---|---|---|---|
| 12:00 | 41.4% [39.6, 43.3] | 27.0% | 30.2% | 52.4% | 35.1% |
| 15:00 | 52.0% [49.7, 54.1] | 36.1% | 44.8% | 65.4% | 46.5% |
| 18:00 | 64.1% [62.0, 66.2] | 52.2% | 65.7% | 80.5% | 59.9% |
| 20:00 | 74.0% [72.2, 75.7] | 66.1% | 81.7% | 90.6% | 68.0% |
| 21:00 | 78.5% [76.4, 80.4] | 68.7% | 88.9% | 95.3% | 73.5% |
| 22:00 | 81.5% [79.6, 83.2] | 73.0% | 94.3% | 97.6% | 77.2% |
| 23:00 | 84.9% [83.4, 86.2] | 76.5% | 97.2% | 99.0% | 78.6% |
| end of day | 86.0% [84.7, 87.2] | 77.2% | 97.8% | 99.3% | 80.1% |

Upvote-rate inputs: within noise. 18:00 is capped by the 19.5% of the real top 30 not yet posted / re-upped by then.

After the full v4 run, on the same 46 test days (top 30 found): 30 vs 57 training days 77.7% vs 78.4% at 21:00 (more
days add little); 5-seed average 78.9%; one ranker pooled over all forecast times 78.3% (64.3% at 18:00, 84.8% at end
of day); front-page rank vs HN-formula rank gap (penalty signal) 79.1% at 21:00, 64.3% at 18:00, 86.5% at end of day.
All within noise: with this data the model is saturated.

Live: forecast_daily.py runs hourly on hn-sim-1 (forecast_daily/<day>/<HHMM>.json in the bucket); listwatch.py records
each day's list every hour (listwatch/<day>.jsonl), so live forecasts can be scored against the real lists, and the
"list at a fixed hour" target can be trained once enough days are recorded. HN's second-chance pool (hn_pool, every
10 min): 35% of pool stories reached the front-page top 30, usually within minutes; ~4 per day made the daily top 30
(Oct 30-31) - an input for the live 18:00 forecast, testable only going forward.

Outside feeds as inputs for stories already posted (Grok Bot backfill; URL seen on lobste.rs / Reddit / Techmeme /
arXiv listing / RSS / X before T, count and number of sources; posting times only, counts read later are not used):
18:00 UTC 64.1% vs 63.6%, 21:00 78.8% vs 78.4% - within noise. 23% of the real top 30 had a feed hit before 18:00, but
so did 16% of all candidates.
Early velocity (points gained in the last 30 / 60 min, Quality News upvote rate) is already in v4.
Second-chance pool and hourly list snapshots start 2026-10-30 / 10-31: they can be tested only going forward
(score_live.py scores each live forecast against the list once it settles).

### 18:00 iteration (v4_t18.py, v4_cls.py; 57 train / 46 test days, real top 30 found at 18:00 UTC)

| try | 18:00 top 30 | 18:00 top 10 | 21:00 top 30 |
|---|---|---|---|
| v4 lambdarank (was current) | 63.6% | 51.5% | 78.4% |
| + post hour / weekday / title | 63.5% | 52.6% | |
| + submitter and domain history (past results only; karma read today would leak) | 64.1% | 51.3% | |
| + who commented in the first 30 / 60 min | 64.1% | 52.4% | |
| + all three | 63.7% | 52.0% | |
| rank_xendcg objective | 40.9% | 41.5% | |
| top-30 classifier | 65.8% | 40.0% | 80.2% |
| **hybrid: classifier picks the 30, ranker orders them (now live)** | **65.8%** | **51.5%** | **80.2%** |

Hybrid vs ranker, paired by day: 18:00 +2.2 points [+1.3, +3.3], better on 21 days, worse on 3; 21:00 +1.8 [+0.9,
+2.8], 22 better / 5 worse; end of day 86.8% vs 87.0% (no change). A top-40 label or rank-weighted classifier: no
better. The 18:00 ceiling stays ~81% (share of the real top 30 posted / re-upped by then).
Predicted final points (out-of-fold regressor) as a classifier input: 18:00 65.8% -> 65.8%, 21:00 80.2% -> 79.7%; no gain.

18:00 round 2 (v4_t18b.py, hybrid, paired by day vs hybrid):
- Recall among stories already posted / back on the page: 18:00 81.9% (of 80.5% visible -> 65.8% overall); 21:00
  84.2% (of 95.3% -> 80.2%).
- Title similarity to earlier daily top-30 titles (TF-IDF cosine, nearest and top-5 mean, 60 earlier days): 18:00
  -0.1 [-0.7, +0.5]; 21:00 -0.8 [-1.5, -0.1]. The title text score (TF-IDF ridge) was already an input.
- Training weight x2 on stories still rising (gaining votes in the last hour, or not yet on the page): -0.1 [-0.5, +0.4].
- Training weight x2 on stories under 6 h old: +0.1 [-0.5, +0.7].
- Author / domain priors: round 1, no gain.

18:00 round 3:
- The real top 30 not posted / back by 18:00: 5.6 per day (18.9%). Their links: github.com 0.37/day, openai.com
  0.15, anthropic.com 0.11, arxiv.org 0.11, others under 0.1; 5% Show HN. Outside feeds caught 0.4/day of them before
  18:00 (URL match). So cross-platform early signals can add at most ~1 point, and naming a not-yet-posted story means
  picking it from thousands of repos / articles. GitHub star history: no backfill (trending archive blocked, GitHub API
  blocked from this container); live only.
- LambdaRank on the top-30 cutoff (vs hybrid, paired by day): in/out-of-top-30 labels 18:00 -0.5 [-1.2, +0.1],
  21:00 +0.1; same truncated at 30: same; graded labels truncated at 30: -2.2 [-3.3, -1.2] / -1.8; truncated at 40:
  -0.9 / -0.7. The hybrid stays.

18:00 round 4:
- Still-to-come slots (real top 30 not posted / back by 18:00): 5.6 per day (sd 2.2, range 1-11), flat by weekday
  (5.2-6.2). Predicting the day's count from the field at 18:00 is worse than the mean (MAE 2.25 vs 1.76). They are
  posted 18:00-22:00 UTC (88%), from every kind of source (github.com 7%, openai.com 2%, arxiv.org 2%).
- Hybrid at 18:00: recall of the full top 30 65.8%; recall on the achievable set (posted / back by 18:00) 81.9%.
  Naming only 24 and leaving 6 "still to come" slots: precision 74.7% (vs 65.8% when naming 30); recall on the
  achievable set 74.6%.
- Ensembles of the hybrid's classifier and the lambdarank ranker (per-day percentile blend, 30/50/70% classifier):
  18:00 -1.3 / -0.5 / +0.1; 21:00 -0.8 / -0.6 / -0.3; end of day +0.3 / +0.6 / +0.1 points vs the hybrid, all within
  noise or worse. The hybrid stays.
- GitHub star velocity: ghstars.py on hn-sim-1, hourly from 2026-10-31 (github.com links in HN stories of the last
  48 h + github.com/trending; star count from the repo page) -> ghstars/<day>.jsonl. github.com is blocked from the
  dev container, so it runs only on the VM; usable once enough days are recorded.

## Scoring as probabilities (top-30 classifier, 46 test days, stories that exist at T)

| at | stories | made top 30 | AUC | avg precision | Brier (base rate) | naive "on top 30 now": precision / recall |
|---|---|---|---|---|---|---|
| 18:00 | 30,518 | 1,111 (3.6%) | 0.975 | 0.826 | 0.0129 (0.0351) | 50% / 61% |
| 21:00 | 32,560 | 1,315 (4.0%) | 0.989 | 0.895 | 0.0107 (0.0388) | 60% / 62% |

Calibration at 18:00 (forecast -> actual): 0.05 -> 0.07, 0.18 -> 0.19, 0.40 -> 0.36, 0.61 -> 0.51, 0.81 -> 0.66,
0.98 -> 0.96: slightly overconfident between 0.5 and 0.9 (fixable with isotonic calibration on held-out days).
Expected winners among existing stories per day (sum of probabilities): 22.9 vs 24.2 actual at 18:00; 27.2 vs 28.6 at
21:00.

## Per-post forecast (per_post.py): a story is posted; at a fixed age, chance it makes its day's list top 30 / top 10

Train: 61,947 stories posted Jul 1 - Aug 31; test: 44,263 posted Sep 1 - Oct 14. 3.0% of posts make a daily top 30,
1.0% a top 10. "Flagged" = the model gives 50% or more.

| age | top 30 AUC | top 30 avg precision | flagged | of flagged, made top 30 | winners flagged | top 10 AUC | top 10: of flagged, made it |
|---|---|---|---|---|---|---|---|
| at posting | 0.783 | 0.17 | 86 | 67% | 4% | 0.792 | 37% |
| 15 min | 0.820 | 0.22 | 145 | 57% | 6% | 0.817 | 53% |
| 30 min | 0.897 | 0.35 | 371 | 58% | 16% | 0.899 | 48% |
| 1 h | 0.956 | 0.45 | 616 | 59% | 28% | 0.958 | 51% |
| 2 h | 0.969 | 0.60 | 828 | 70% | 44% | 0.973 | 66% |
| 4 h | 0.976 | 0.73 | 906 | 81% | 55% | 0.979 | 72% |

Stories with no Quality News page (they end under ~5 points) get the no-votes fill after posting; at posting time no
vote data is used.

## User simulation, Step 1: individual reliability (twin_test.py, twin_llm.py)

Panel: the 3,000 most active commenters (180-day comments: median 225); twins built only from data before 2026-07-01.
Held out Jul 1 - Oct 14: per person, the listed stories (daily list, rank <= 120) of days they were active; positives =
stories they commented on, negatives = up to 20x the others. Per-person AUC, median over people:

| model | people | median AUC | share > 0.7 |
|---|---|---|---|
| vector twin (recency-weighted mean title embedding of their stories) | 2,950 | 0.583 | 7.9% |
| LLM twin (Gemini 2.5 Flash-Lite persona from their last 60 story titles; same items) | 197 | 0.540 | 13.2% |
| vector twin on the same 197 people / items | 197 | 0.570 | 14.7% |
| popularity only (story's final points; not known at posting) | 2,950 | 0.808 | 93.2% |
| twin + popularity (rank average) | 2,950 | 0.761 | 83.7% |

The twin beats popularity for 3.3% of people. Presence: 43% of held-out comments fall in the twin's 6 most active
UTC hours (uniform 25%). Gate (median > 0.7 and beats popularity): not passed. LLM pilot cost: $0.058 (217 calls).
Embeddings (embed.py, text-embedding-005, 803,523 titles): $1.371. Next: v2 shared engagement model with several
personal signals, scored within popularity bands (twin_v2.py); crowd model (audience.py).

## Crowd simulation at posting time (audience.py; train posts Jul-Aug, test Sep 1 - Oct 14, no votes)

44,082 simulated readers (10+ comments in the 18 months before Jul 1; 2,916 regular /new browsers): taste from title
embeddings, hour-of-day presence, /new-browsing share; per post at its posting hour: expected interested readers
online, interested /new browsers, close fans; plus the outcomes of the 30 most similar past titles.

| inputs | top 30 AUC | avg precision | winners in model's daily top 30 | in top 100 | top 10 AUC |
|---|---|---|---|---|---|
| post features (baseline) | 0.782 | 0.169 | 21.5% | 39.1% | 0.789 |
| + 30 nearest past titles | 0.792 | 0.174 | 20.9% | 41.2% | 0.794 |
| + title embedding | 0.796 | 0.171 | 21.5% | 41.3% | 0.797 |
| + crowd simulation | 0.793 | 0.176 | 19.9% | 40.7% | 0.803 |
| + crowd + embedding | 0.799 | 0.174 | 21.8% | 42.2% | 0.797 |
| crowd simulation alone | 0.668 | 0.069 | 10.1% | 22.4% | 0.666 |

Ceiling check - the same link posted twice (56,317 pairs, 2025-01..2026-10, >1 h apart): of 2,915 pairs where one
posting made a daily top 30, both did in 30 (1%); P(second wins | first won) 4.7% vs 4.1% if the first lost; log
points correlate 0.18. (HN discourages reposting a link that did well, which lowers "both won"; it does not explain
losing links winning on a repost.) Content explains only part of the outcome at posting time; early exposure decides
the rest.
Same-link check, continued: the first posting's points predict whether the repost makes a daily top 30 with AUC 0.567
(56,317 pairs); among first postings that flopped (< 10 points, where reposting is not discouraged; 48,912 pairs)
the repost wins 4.0%, the base rate. The at-posting model (AUC 0.78-0.80) beats knowing the content's own past result
because it also uses who posted, when, and the crowd.

Individual v2 (twin_v2.py: one shared LightGBM over (person, story) pairs; trained on Jul-Aug, tested Sep 1 - Oct 14;
2,879 people, 5.78M pairs; profiles from data before Jul 1). Median per-person AUC (share > 0.7), and the same within
popularity bands (stories of similar final points: the "beyond popularity" number):

| model | median AUC | within popularity bands |
|---|---|---|
| v1: mean taste | 0.577 (10%) | 0.579 (13%) |
| v2: personal signals (closest past stories, domain / submitter history, presence) | 0.632 (20%) | 0.628 (23%) |
| popularity only (final points) | 0.814 (92%) | 0.548 (5%) |
| v2 + popularity | 0.828 (95%) | 0.635 (25%) |

Personal signals carry real preference beyond popularity (0.63 within bands vs 0.55) and now add to popularity
(0.828 vs 0.814). Below the 0.7 gate on personal signal alone.

Crowd v2 (crowd_v2.py): the individual v2 engagement model (personal signals only, trained on Jul-Aug pairs) run for
the 6,000 most active commenters (profiles from data before Jul 1; 174 of them regular /new browsers) over every
Jul 1 - Oct 14 post at posting time (106,210 posts; 57 min). At-posting classifier, test Sep 1 - Oct 14:

| inputs | top 30 AUC | avg precision | winners in model's top 30 / day | top 100 | top 10 AUC |
|---|---|---|---|---|---|
| post features (baseline) | 0.782 | 0.169 | 21.5% | 39.1% | 0.789 |
| best so far (+ past titles + embedding + crowd v1) | 0.798 | 0.168 | 20.8% | 41.7% | 0.804 |
| + crowd v2 | 0.803 | 0.175 | 21.7% | 42.2% | 0.808 |
| crowd v2 alone | 0.623 | 0.049 | 5.7% | 18.7% | 0.611 |

Crowd v2 vs best so far, winners caught per day (paired): top 30 +0.9 points [-0.4, +2.3]; top 10 +0.1 [-1.7, +1.8].
Within noise.
/new competition at posting time (competition.py: number and at-posting strength of posts made 15 / 30 / 60 min
before, and where the post ranks among them; nothing after the post): top 30 AUC 0.795 vs 0.803; winners caught per
day +0.0 [-1.0, +1.1] points (top 30), +0.1 [-1.1, +1.5] (top 10). No gain.

## Calibrated odds per post (odds.py): P(daily top 30), fit Jul 1 - Aug 15, isotonic on Aug 16-31, test Sep 1 - Oct 14

| age | top 30 AUC | Brier (base rate 0.0290) | top 10 AUC |
|---|---|---|---|
| at posting | 0.796 | 0.0270 | 0.791 |
| 15 min | 0.824 | 0.0260 | 0.810 |
| 30 min | 0.898 | 0.0233 | 0.891 |
| 1 h | 0.956 | 0.0206 | 0.951 |
| 2 h | 0.969 | 0.0174 | 0.958 |

Calibration at posting (forecast -> happened, posts): <1%: 0.4% -> 0.5% (15,980); 1-3%: 1.7% -> 1.8% (14,066);
3-10%: 5.3% -> 5.3% (12,428); 10-30%: 16.3% -> 15.1% (1,574); 30-50%: 42.7% -> 38.8% (183). At 1 h: 3-10%: 6.1% ->
8.5%; 50-70%: 52.6% -> 49.2% (535); 70-90%: 77.1% -> 66.9% (254); 90%+: 95.9% -> 79.2% (77): slightly overconfident
at the top, well calibrated below 50%. Full table: <cache>/odds_calibration.csv.

Individual model + favorites (Grok Bot fetch; pagination bug means only each person's first 30 favorites were
collected: 40,446 unique; 21,947 of stories posted before Jul 1; 1,682 of the 3,000 panel people have some).
Median per-person AUC, Sep 1 - Oct 14 (all 2,879 people | the 487 with 10+ favorites):

| model | all | within popularity bands | 10+ favorites | 10+, within bands |
|---|---|---|---|---|
| v2 personal signals | 0.632 | 0.628 | 0.623 | 0.625 |
| v2 + favorites | 0.640 | 0.635 | 0.653 | 0.651 |
| v2 + popularity | 0.828 | 0.635 | 0.828 | 0.627 |
| v2 + favorites + popularity | 0.830 | 0.644 | 0.838 | 0.658 |

Favorites help most where there are enough of them (+3 points for people with 10+, +1 overall). Full pages 2-10
requested from the feeder.

## Tie strength (ties.py; Product Hunt finding: who you know beats content taste). Ties before Jul 1 from 2025+ comments
and 6.5M reply edges (replies_bq.py, BigQuery 2.1 GB, $0.013).

Individual (median per-person AUC | within popularity bands; 2,879 people, Sep 1 - Oct 14): content taste (+ favorites)
0.638 | 0.629; ties to the submitter (commented on their stories / replied to them / reciprocity / share of history)
0.512 | 0.517; content + ties 0.641 | 0.635; + popularity 0.830 | 0.643. 24% of (person, story) pairs have any tie
(27% of engaged pairs).
At posting (submitter's tie network: tied people, their presence at the posting hour, /new browsers among them,
reciprocal ties; 73% of posts have one): top 30 AUC 0.799 vs 0.803; winners caught per day -0.9 [-2.3, +0.5] points;
top 10 +0.2 [-1.8, +2.2]. On HN, unlike Product Hunt, ties add nothing measurable.

## Single-post odds tool (odds_live.py)
Same models as odds.py without the crowd inputs (no measurable gain, need the person panel). Test Sep 1 - Oct 14,
P(top 30): AUC 0.794 at posting, 0.827 at 15 min, 0.900 at 30 min, 0.956 at 1 h, 0.968 at 2 h; mean forecast 2.98%
vs 2.99% actual at posting. Post features use the same code as training (top10.feats on full history + new posts;
matches the training features for 99.3-100% of values).

Person-level pick accuracy (person_top3.py; research-program metric, same as Product Hunt): per person-day (60,451,
Sep 1 - Oct 14), rank that day's candidate stories for the person; hit if a top-3 pick is one they commented on.
Ties now include days since the last interaction and the tie's rank among the person's options that day.

| model | top-3 hit | 95% CI | random |
|---|---|---|---|
| content taste (+ favorites) | 29.7% | [29.3, 30.1] | 14.1% |
| ties to the submitter | 17.2% | [16.9, 17.5] | 14.1% |
| content + ties | 30.2% | [29.8, 30.6] | 14.1% |
| popularity (final points; not known at posting) | 49.8% | [49.3, 50.1] | 14.1% |
| content + ties + popularity | 55.5% | [55.1, 55.9] | 14.1% |

On HN, content taste beats ties (opposite of Product Hunt); ties add +0.5 points on top of content.

18:00 round 5 (v4_t18c.py): the per-post content signals in the daily hybrid (paired by day vs hybrid 65.8% / 80.2%):
similar past titles 18:00 -0.6 [-1.2, +0.0], 21:00 -0.7 [-1.4, +0.1]; + embedding -0.7 / -0.7; crowd v1 + v2
-0.6 / -0.1; all -0.7 / -0.6 points. No gain: by 18:00 the votes carry what the content signals know.

Live per-post odds: odds_live.py recent runs hourly at :35 on hn-sim-1 (every story of the last 3 h at the age it has
reached) -> odds_live/<day>/<HHMM>.json in the bucket; first run 2026-11-01 19:25 UTC, 155 posts, VM memory 0.9 of
7.9 GB. Scored against settled lists from Nov 3.

## North star: Caught at posting (caught.py) - set by the user 2026-11-01

Each post scored at its posting moment with only what is known then (no votes or comments of the post). For each list
day D, rank the posts posted on D; Caught = share of D's real daily top 30 in our top 30. Holdout Sep 1 - Oct 14
(44 days), fit on posts Jul 1 - Aug 31; 95% bootstrap intervals over days.

| | Caught |
|---|---|
| ceiling: share of D's real top 30 posted on D (others are earlier posts / re-ups) | 67.2% [64.2, 70.2] |
| **at posting** (post features, domain / author record, similar past titles, embedding, crowd) | **14.4% [12.5, 16.3]** |
| post features only | 14.2% [12.6, 15.9] |
| + similar past titles | 14.4% [12.6, 16.2] |
| + embedding | 14.5% [12.7, 16.3] |
| extra, includes early votes: at 15 min | 19.3% [17.3, 21.5] |
| extra, includes early votes: at 1 h | 41.0% [38.3, 43.6] |
| extra, includes early votes: at 3 h | 53.7% [50.5, 56.5] |

## North star redefined per post (user, 2026-11-01): Caught = winners flagged / winners

Every test post judged once at a fixed age; winners = posts that made any daily top 30; flags = as many posts as
winners (highest scores over Sep 1 - Oct 14); 95% interval resampling posting days. 44,263 posts, 1,323 winners,
44 days; random flags 3.0%.

**Leak found and fixed in the vote-age numbers.** Quality News series were fetched only for posts that ended with 5+
points (qn.py QN_MIN_POINTS): 23.6% of test posts, 99.5% of winners. A missing series revealed the outcome.
Honest base = rank only (a post ending < 5 points is truly off the front page); point counts dropped. Leak check =
AUC of telling real from imputed series from the vote inputs (0.5 = none; rank-only above 0.5 is real front-page
signal).

| Age | rank-only (headline) | const 1 pt | ramp to final | series-only (outcome-selected) |
|---|---|---|---|---|
| at posting | 21.4% [19.3, 23.4] | | | |
| 15 min | 24.7% [22.6, 26.9] (leak 0.521) | 28.9% (0.667) | 30.3% (0.878) | 36.2% |
| 1 h | 45.9% [42.1, 49.4] (leak 0.654) | 48.5% (0.942) | 47.9% (0.954) | 48.6% |
| 3 h | 61.0% [57.7, 64.3] (leak 0.726) | 61.2% (0.966) | 61.5% (0.853) | 62.5% |

Earlier vote-age numbers (Caught day-matched 19.3 / 41.0 / 53.7%; odds_live AUC 0.82 at 15 min, 0.96 at 1 h) used
points with the same leak; treat them as upper bounds. Clean live test: live_caught.py (hn_minute, no selection),
from Nov 4; hn_minute ran only ~10 of its first 42.5 h (feeder asked to fix).

Stage-1 levers on the const base (caught1h.py; 48.5%): curve -0.3, comments -0.2, who comments early -0.9, HN
mechanics -0.8, outside feeds in the first hour -0.6, all +0.2 [-1.3, +1.8]: none helps. Rerun on the rank-only
base queued.

### At-posting levers (caught.py levers; base 21.4% [19.3, 23.4]; paired by day)

| Lever | Caught | with vs without |
|---|---|---|
| without submitter history (b_sub_*, b_author_*) | 20.9% | -0.5 [-1.9, +0.9] |
| + submitter tie network (ties.py) | 21.0% | -0.4 [-1.8, +1.1] |
| without any domain / author record | 19.3% | **-2.0 [-3.5, -0.5]** |
| + record on the real daily list (domain, site, author) | 22.0% | +0.6 [-0.8, +2.1] |
| + outside feeds before posting (own link seen, domain buzz; 6.0% of posts, 10.4% of winners) | 21.9% | +0.5 [-0.8, +1.8] |
| + day fit (6 h comment topics, previous 2 days' top 30, nearest post) | 22.1% | +0.8 [-0.7, +2.0] |
| + all four | 21.5% | +0.1 [-1.6, +1.7] |

The existing domain/author record is the one input that matters (-2.0 without it). The new levers each add +0.5 to +0.8,
none significant, and together +0.1: at posting, the model is at its noise floor with these inputs.

### Simulated early votes at posting (caught.py simvotes)
Simulated audience (who is on /new at that hour: taste, ties; crowd v1/v2, tie network, day fit) -> predicted points /
best rank at 15 / 60 min (out-of-fold). Spearman with the real values on the test posts: points 0.050 (15 min), 0.222
(60 min); best rank 0.023 / 0.122. Added at posting: 21.2%, -0.2 [-1.4, +1.2].

### More training history (caught.py history; same test posts; vs post features trained Jul-Aug, 19.7%)
| Trained from | posts / winners | post | post + real-list record |
|---|---|---|---|
| 2026-07-01 | 61,947 / 1,860 | 19.7% [17.6, 21.7] | 21.0% (+1.4 [+0.2, +2.6]) |
| 2026-01-01 | 247,817 / 7,276 | 20.7% (+1.1 [-0.8, +2.8]) | 21.4% (+1.7 [+0.1, +3.4]) |
| 2025-01-15 | 538,880 / 17,804 | 21.6% (+2.0 [+0.0, +4.0]) | **22.6% [20.5, 24.8] (+2.9 [+1.1, +4.8])** |
More history plus the real-list record is the first at-posting gain: 22.6%, above the current 21.4% (which also uses
similar titles, embedding, crowd, trained Jul-Aug only).

### Reading the linked page (pagejudge.py; pilot Sep 15-16, 2,283 posts, 67 winners; Gemini 2.5 Flash, $1.168 logged)
Fetch (plain HTTPS from the cloud container): page read 65.5%, 403 18.8%, thin 4.7%, text post 3.7%, 429 2.3%, other
5%. Judged 100% (title-only when the page wasn't read). AUC for winners: judge's front-page probability 0.607 (base
0.792); novelty 0.571, depth 0.593, title match 0.594, HN fit 0.602. Winner rate by kind: postmortem 8.0%, tutorial
6.5%, deep dive 5.6%, research 3.4%, launch 3.2%, news 3.0%, opinion 2.4%, Show HN product 1.0%.
Caught on the pilot days: base 16.4%; judge alone 11.9%; rank blend 50/50 14.9%; weight chosen leave-one-day-out:
20.5% -> 12.8% and 14.3% -> 14.3%. As a blend, the judge does not add to the base; untested as a model input (needs
the training period judged: ~106k posts, ~$75 Flash / ~$25 Flash-Lite).

### Competition at the posting minute (caught.py comp; base 21.4%)
/new rivals in the 15 / 30 / 60 min before (count, content prior, title score) +0.2 [-0.8, +1.4]; rivals' strength
by our own at-posting score (out-of-fold) and this post's rank among them -0.1 [-1.7, +1.4]; /new traffic (site-wide
comments in the previous 60 min, vs the same hour in the previous 4 weeks) +0.1 [-1.3, +1.5]; all +0.4 [-1.3, +2.1].

### 2025+ training with title embeddings (caught.py history2)
Every 2025+ title now embedded (embed.py EMB_FILL_FROM=2025-01-01: 167,390 titles, $0.278 logged; the old 3+ points /
comment filter made a missing embedding reveal the outcome). Trained from 2025-01-15 (1,200 trees, 63 leaves): post +
real-list record 22.4% [20.4, 24.5]; + title embedding (PCA 64) 22.4% [20.2, 24.9], +0.1 [-1.3, +1.7].

### Checkpoint 3 (at posting): blend of the two models (blend_hist.py)
Rank average of the Jul-Aug model (post + similar titles + embedding + crowd; 21.4%) and the 2025+ history model
(post + real-list record + embedding; 22.4%), weight fixed at 50/50 in advance: **23.2% [21.2, 25.3], +1.8 [+0.4, +3.2]**
vs the Jul-Aug model (reference only, chosen on test: 0.3 -> 23.1%, 0.7 -> 22.9%).

## North star as of 2026-11-01 (Shreyas): per-post Caught at three checkpoints
Checkpoint 1 = 1 h after posting (focus, to 80%), 2 = 15 min, 3 = at posting. Current: 1 h 45.9% [42.1, 49.4]
(rank only), 15 min 24.7% [22.6, 26.9] (rank only), at posting 23.2% [21.2, 25.3].

### Checkpoint 1 levers on the honest (rank-only) base (RANK_ONLY=1 caught1h.py; base 45.9% [42.1, 49.4])
Leak check (real vs imputed series from the rank inputs): AUC 0.654 (front-page presence; real signal).
| Lever | Caught at 1 h | with vs without |
|---|---|---|
| + rank curve (rank every 10 min, front-page entry time, minutes on it, trend) | 46.7% | +0.8 [-0.1, +1.8] |
| + comments (count by 15 / 30 / 60 min, last 20 min, commenters, first delay) | 46.4% | +0.5 [-0.5, +1.5] |
| + who comments early (commenters' record before Jul 1; proven scouts) | 47.0% | **+1.1 [+0.2, +2.2]** |
| + HN mechanics (rank) | 46.4% | +0.5 [-0.4, +1.5] |
| + outside feeds in the first hour | 46.1% | +0.2 [-0.7, +1.3] |
| + all | 46.3% | +0.5 [-0.6, +1.7] |
| + curve, comments, who | 46.2% | +0.3 [-0.5, +1.2] |

### History score as an input (caught.py hist_prior; history model trained 2025-01-15 .. 2026-06-30 only)
At posting: history model alone 22.4% (+1.0 [-0.7, +2.9] vs the Jul-Aug model); as an input to the Jul-Aug model
21.9% (+0.5 [-0.8, +1.9]). The 50/50 blend (23.2%) stays the best at posting.
Checkpoint 1 (rank-only + history score; HIST=1 RANK_ONLY=1 caught1h.py): **47.2% [43.7, 50.6]** (was 45.9%).
Levers on top: curve +0.3, comments +0.4, who -0.2, mechanics +0.6, outside +0.8 [-0.1, +1.8], all +0.4,
curve + who +0.0 (none significant).

### What the 1 h checkpoint sees (test winners, Quality News series; 99.5% of winners have one)
Winners on the front page (top 30) by 1 h: 48.5% (non-winners: 2.95%, 1,265 posts); by 3 h 66.9% (4.22%, 1,814); by
24 h 80.5% (4.80%, 2,063). Half the winners are not yet visible on the front page at 1 h: for them the 1 h
checkpoint is the at-posting / /new problem (plus second-chance re-ups later).

### Checkpoint 1 split: where the misses are (seg1h.py; rank-only + curve + comments + who + history score, 47.6%)
| At 1 h | posts | winners | flagged | winners caught |
|---|---|---|---|---|
| on the front page | 1,907 | 642 | 1,136 | 569 (89%) |
| not yet on the front page | 42,356 | 681 | 187 | 61 (9%) |
Separate models for the two groups: 46.3%, -1.4 [-2.6, -0.1] vs one model. Checkpoint 1 is decided by the 681 winners
still on /new at 1 h; for them the honest backtest has no vote counts (QN series exist only for 5+ point posts), so
their /new votes in the first hour are the missing input (hn_minute live; a Jul-Oct /newest archive if one exists).

### Honest early votes from Wayback /newest (wb_caught.py; Grok Bot raw/hn_early_votes, partial: Oct parse 43%)
Verified: page created_at = BigQuery for 100% of rows (within 60 s); early score <= final points 99.99%. Snapshot
coverage does not depend on the outcome (test posts 64.4% vs winners 65.5% with one by 15 min).
| Checkpoint | test | without early votes | with | difference |
|---|---|---|---|---|
| 15 min | A: train Jul-Sep (4.9% with a snapshot), test Oct 2-14 (12,788 posts, 388 winners) | 25.5% | 26.0% | +0.5 [-1.6, +2.7] |
| 15 min | B: train Jul 1-Oct 8, test Oct 9-14 (5,817 / 180) | 27.2% | 29.4% | +2.2 [-2.2, +6.3] |
| 1 h | A | 45.6% | 45.6% | +0.0 [-1.8, +1.7] |
| 1 h | B | 48.9% | 48.3% | -0.6 [-2.4, +1.2] |
Base = at-posting inputs + history score + front-page rank + comments. To rerun when the October parse completes.

### Individual twins with the full favorites (pages 2-10; 146,216 unique favorites, 3,422 people; twin_v2.py)
2,879 people, Sep 1 - Oct 14, median per-person AUC | within popularity bands: v2 personal signals 0.632 | 0.628;
v2 + favorites **0.642 | 0.633** (page-1 favorites: 0.640 | 0.635); people with 10+ favorites (618): 0.658 | 0.649
(page-1: 0.653). Popularity alone 0.814; v2 + favorites + popularity 0.830 | 0.645. The full favorites add +0.002
overall, +0.005 for heavy favoriters.

## Status 2026-11-02 02:50 UTC - Caught per post (north star 80%): 1 h 47.2% [43.7, 50.6]; 15 min 24.7% [22.6, 26.9]; at posting 23.2% [21.2, 25.3]

### Page judge as an input (pagejudge.py full run: 106,210 posts, Gemini 2.5 Flash-Lite, $13.543 logged; pj_eval.py)
Judged 99.9%; page read 62.8%. At posting: Jul-Aug model 21.4% -> 22.1%, +0.8 [-0.4, +1.9]; 50/50 blend 23.2% -> 23.1%,
-0.1 [-1.1, +1.0]. 1 h (rank + history score + who): 47.0% -> 47.5%, +0.5 [-0.7, +1.6].

### Honest early votes, complete October /newest archive (wb_caught.py; Oct 2-16 coverage 93-98% except Oct 6, 13, 14, 15)
| Checkpoint | test | all days | 90%+ coverage days |
|---|---|---|---|
| 15 min | A: train Jul-Sep, test Oct 2-14 (388 winners) | 25.5 -> 28.4, +2.8 [-0.5, +6.4] | 26.1 -> 29.3, +3.1 [-0.7, +7.1] |
| 15 min | B: train <= Oct 8, test Oct 9-14 (180) | 27.2 -> 27.2, +0.0 [-2.4, +3.0] | 29.8 -> 29.8, +0.0 [-3.9, +3.2] |
| 1 h | A | 45.6 -> 45.6, +0.0 [-1.6, +1.5] | 46.3 -> 46.0, -0.3 [-2.4, +1.7] |
| 1 h | B | 48.9 -> 47.8, -1.1 [-2.5, +0.0] | 47.4 -> 46.5, -0.9 [-2.3, +0.0] |

Why /newest votes do not move 1 h: among Oct 2-14 posts not on the front page by 1 h (10,890 with a snapshot, 193
winners), the winners' latest /newest score (median age 38 min) is median 2 vs 1 for the rest; AUC 0.615 (score),
0.608 (votes per minute), 0.505 (comments). Where the 681 test winners not on the front page at 1 h land: on the list of
their posting day 42%, the next day 25%, 2+ days later (re-ups) 32%. Winners on the front page by 1 h: 93% / 7% / 0%.
Half the winners look like flops in their first hour; they are late risers and second-chance re-ups.

### Winner types at posting (wintypes.py; test 641 fast / 461 late risers / 221 second-chance re-ups)
| At posting | Caught | vs |
|---|---|---|
| a current Jul-Aug model | 21.4% [19.3, 23.4] | |
| b a + type record (domain / site / author: same-day, next-day, re-up wins) | 22.3% | +0.9 [-0.4, +2.4] vs a |
| c one model per type, summed | 19.8% | -1.6 [-3.2, +0.2] vs a |
| b blended with the 2025+ model | 23.0% | -0.2 [-1.5, +1.1] vs best (23.2%) |
| c blended with the 2025+ model | 22.4% | -0.8 [-1.9, +0.4] vs best |
Caught by type (a): fast 140/641 (22%), late 100/461 (22%), re-up 43/221 (19%); c + history: 147 / 110 / 40. The
at-posting model already catches each kind at about the same rate; separating them does not help.

### Same link, posted again (2025-01-15 .. 2026-10-14; URLs normalised; postings 1+ day apart)
55,575 URLs posted 2+ times (136,498 posts). Win rate (any daily top 30): all posts 3.28%, reposted URLs 3.03%.
57,243 consecutive pairs: P(second wins | first won) 10.3% (n 611; HN blocks many recent dupes); P(second wins |
first lost) 3.9%; P(first won | second wins) 2.8% (n 2,273): of the repostings that won, 97% had flopped before
with the same link. At posting the link's content is the same both times; what differed was the moment and who posted.

### Same link posted before, as an at-posting input (caught.py urlhist)
15.6% of test posts (21.0% of test winners) had their link posted before. Jul-Aug model 21.4% -> 22.0%, +0.6 [-0.5, +1.7];
blend 23.2% -> 22.9%, -0.3 [-1.4, +0.7].

### Same-link pair model (pairs.py)
Informative pairs (same URL, 1+ day apart, exactly one posting won): 2,189 to train (to Jun 30), 569 held out (Jul-Oct).
LambdaRank on the moment (hour, weekday, volume, same host / words in 6 h), title (text score, length, words, question,
Show / Ask HN) and submitter (HN record, comments before, account age, real-list record).
Held-out pairs: the winning posting scored higher in **51.8%** (chance 50%). As an input at posting: Jul-Aug model
-0.1 [-1.4, +1.3]; blend -0.4 [-1.5, +0.7]; the context score alone catches 2.8%.
Given the link, nothing known at posting (moment, title wording, submitter) separates the posting that won from the
one that flopped.

## Direction (Shreyas, 2026-11-02): push checkpoint 2 (15 min) with honest early votes; at posting = calibrated probability (odds tool)

### Predicted 15-min state chained in (wb_chain.py; train <= Oct 8, test Oct 9-14)
Predicting the 15-min /newest score from at-posting inputs: Spearman 0.220 (4,437 test posts); on /news by 15 min: -0.019.
| Checkpoint | days | without | with predicted 15-min state | difference |
|---|---|---|---|---|
| at posting | all 6 (180 winners) | 18.3% | 22.2% | +3.9 [-1.5, +9.4] |
| at posting | 4 days 90%+ coverage (114) | 18.4% | 25.4% | **+7.0 [+1.7, +12.2]** |
| 1 h (with early votes) | all 6 | 48.9% | 48.9% | +0.0 [-1.6, +1.6] |
| 1 h | 4 days 90%+ | 47.4% | 48.2% | +0.9 [+0.0, +2.3] |
Small test (4-6 days); being confirmed on Oct 2-14 with a forward daily retrain (wb15.py).

### Odds tool, honest (odds_live.py: after posting, front-page rank only; retrained, deployed as oddsloop2)
Test Sep 1 - Oct 14, P(top 30): AUC at posting 0.79, 15 min 0.803, 3 h 0.926; calibration at 15 min: forecast 3.00%
vs actual 2.99%. At posting is reported as this calibrated probability (Shreyas).

### Person-level top-3 with the full favorites (decision tool only)
Content taste + favorites: top-3 hit 29.7% [29.3, 30.1] (random 14.1%), unchanged by pages 2-10; the rest of the run was
killed by the container restart.

### Checkpoint 2 (15 min) on the October archive, forward daily retrain (wb15.py)
For each posting day Oct 2-14: train Jul 1 .. d-2, score day d at 15 min. 12,788 posts, 388 winners; 85.6% with a
/newest snapshot by 15 min. Base = at-posting inputs (incl. history score, page judge) + front rank + comments by 15 min.
| Caught at 15 min | all 13 days (388 winners) | 10 days with 90%+ coverage (287) |
|---|---|---|
| base | 25.5% [20.6, 30.3] | 26.1% [20.3, 31.5] |
| + /newest votes (trajectory, push-down rate, /news rank) | 27.1%, +1.5 [-0.3, +3.3] | 28.2%, +2.1 [+0.6, +3.5] |
| **+ votes + who commented in the first 15 min** | **28.4% [23.6, 33.0], +2.8 [+0.3, +5.3]** | **29.3%, +3.1 [+1.3, +5.3]** |
| + votes + who + predicted 15-min score | 26.8%, +1.3 [-1.7, +4.2] | 27.9%, +1.7 [-1.1, +5.3] |
Early votes plus who commented early is the first significant gain at 15 min. The chained prediction does not add on
top (its +7.0 at posting on Oct 9-14 was a 4-day result).
Early commenters' ties to the submitter / activity / newcomers on top of votes + who: 28.4% (+2.8 [+0.5, +5.2] vs base;
+0.0 vs votes + who). No extra gain.

### Live, PROVISIONAL: Caught at 15 min (live15.py, run 2026-11-02 ~09:30 UTC)
Posts Oct 31 02:13 - Nov 1 (1,388; Algolia), labels = any daily top 30 so far (latest complete top-30 read per list day;
no list day settled yet): 40 winners (Oct 31: 25, Nov 1: 15). Seen by the recorder within 15 min: 47.8% (Oct 31 41.7%,
Nov 1 53.2%; /newest read about every other minute before the always-on VM).
| Score at 15 min (flags = 40) | Caught |
|---|---|
| votes at 15 min (recorder) | 15.0% [8.0, 26.7] (6/40) |
| odds tool at posting | 10.0% [0.0, 16.0] (4/40) |
| blend 50/50 | 10.0% [6.7, 12.0] (4/40) |
Two days, 40 winners: far too few to read; re-scored daily as lists settle (daily task 00:47 UTC).
Fixes found on the way: listwatch reads were missing pages (HN refusals) and never re-read a day after the next, so no
list could settle; listwatch2 retries pages and re-reads the 3 previous days (deployed; history backed up and kept).
Seen-within-15-min subset (orchestrator's request; flags = winners in the subset; 15 winners seen: Oct 31 11, Nov 1 4):
votes at 15 min 26.7% (4/15); odds at posting 6.7%; blend 6.7%. Coverage per day: Oct 31 41.7% of posts seen,
Nov 1 53.2%; recorder minutes front / newest / pool: Oct 31 930 / 306 / 307, Nov 1 1,445 / 606 / 321.

### Where the 15-min misses are (wb15.py diagnose; Oct 2-14, + votes + who, 28.4%)
| Winner type | caught at 15 min | with a /newest snapshot by 15 min | latest score median | >= 3 points | >= 5 points | on the front page by 15 min |
|---|---|---|---|---|---|---|
| fast (front page by 1 h, listed that day / next) | 71/181 (39%) | 156 | 2 | 34.6% | 17.9% | 14.7% |
| late riser | 25/145 (17%) | 132 | 1 | 12.1% | 2.3% | 0% |
| re-up (2+ days later) | 14/62 (23%) | 55 | 1 | 3.6% | 0% | 0% |
| non-winners | - | 10,607 | 1 | 7.2% | 1.2% | 0.4% |
Snapshot age median 10-11 min (Wayback captures every ~10 min), so the votes seen are ~4 min short of 15.
Late risers and re-ups (53% of winners) look like non-winners on /newest at 15 min (median 1 point; 12% / 4% with
3+ vs 7% of non-winners). Fast winners do separate (35% with 3+), but 763 non-winners also have 3+ points by then.

### Live pipeline with per-minute vote features (live15.py; PROVISIONAL, posts Oct 31 02:13 - Nov 1, 40 winners so far)
Per-minute features at 15 min and 1 h: points, comments, minute of the 2nd / 3rd / 5th vote, votes per minute, front-page
entry time / best position / minutes on it, last /newest position and push-down rate. Saved each run
(out/live_minute_feats.parquet); a leave-one-day-out model on them + the at-posting odds switches on at 5 posting days.
| Live, provisional | all posts | seen by the recorder only |
|---|---|---|
| 1 h, votes + front page | 32.5% [24.0, 46.7] (13/40) | 39.4% (13/33 seen) |
| 1 h, odds at posting | 10.0% | 9.1% |
| 1 h, blend 50/50 | 27.5% | 30.3% |
| 15 min, votes + front page | 15.0% [8.0, 26.7] (6/40) | 20.0% (3/15 seen) |
| 15 min, odds at posting | 10.0% | 6.7% |
Coverage: seen within 1 h 77.4% of posts (Oct 31 80.6%, Nov 1 74.6%), 33/40 winners; within 15 min 47.8%, 15/40.
Recorder minutes Nov 2: front 1,807 / newest 830 (always-on VM). Two days, 40 winners: too few to read.

### Re-ups and the second-chance pool (live recorder, Oct 31 - Nov 2; provisional labels)
52 posts seen in /pool: 30.8% made a daily top 30 (vs ~3% of all posts). Re-up winners in reach: 8 of 10 passed through
/pool. First seen in /pool a median 22.9 h after posting (10th-90th percentile 2.9-32.6 h): not a 15-min input; the
re-up-clock view (re-ups judged 15 min after entering /pool) goes into the live readout once enough days settle.

### Late-riser model at 15 min (wb_late.py; Oct 2-14 forward daily retrain)
Slow starts (<= 2 points at the latest /newest snapshot by 15 min, off the front page): 11,934 of 12,788 posts; 129 of
the 145 late risers, and 119 of the 181 fast winners. Among slow starts, flags = 129: general 15-min model catches 15
late risers, the late-riser model 14. Blended in for slow starts: Caught at 15 min 28.1% (weight 0.25), -0.3
[-2.7, +1.9]; 27.8% (0.5), -0.5 [-3.9, +2.3] vs 28.4%. A dedicated model does not find late risers any better.

### Outside traction by posting + 15 min (wb_outside.py; feeds backfill; Oct 2-14 forward retrain)
Own link seen outside HN before posting + 15 min: fast winners 27/181 (15%), late risers 15/145 (10%), re-ups 10/62 (16%),
non-winners 756/12,400 (6%). Mentions by source on Oct 2-14 posts: Reddit 343, lobste.rs 285, Techmeme 113, arXiv 64,
RSS 33, X 13, GitHub trending 8. Caught at 15 min: 28.4% -> 28.4%, +0.0 [-2.2, +2.3] (90%+ days -0.3 [-2.8, +2.1]);
caught by type fast 71 -> 70, late 25 -> 29, re-ups 14 -> 11. GitHub stargazer timing not run: api.github.com
returns 403 from the dev container and no token is available here (needs hn-sim-1 + a token).

### Re-up clock (direction B; live15.py; PROVISIONAL, posts Oct 31 - Nov 1, 38 winners so far)
Exposure event = first /pool sighting, or a front-page return 3+ h after posting after 3+ h off it; median 4.8 h after
posting. 41 posts had one; 12 of the 38 winners are among them. Judged 15 min after the event (points gained, front
page): 5/12 of the cohort's winners flagged (flags = 12). 15-min Caught, all posts: posting clock only 15.8% (6/38);
posting clock + re-up clock (each post at its stronger clock; being in /pool itself ranks the post high) 28.9% (11/38).
Two days; /pool read every 5 min only since Nov 2 12:43 UTC (recorder v6). Wayback has no /pool history for October
(one capture, an HN block page), so B and C are live-only.

### At-posting ensemble of the small levers (ens_post.py; equal rank weights fixed in advance)
Members: Jul-Aug 21.4%, 2025+ history 22.4%, + page judge 22.1%, + type record 22.3%, one model with every input 22.4%.
vs the current best (Jul-Aug + history, 23.2%): Jul-Aug + history + judge + type 23.1% (-0.2 [-1.1, +0.9]);
history + judge + type 23.8% (+0.6 [-0.4, +1.7]); all + history 22.8% (-0.5); all five 23.3% (+0.1). No ensemble beats
the current best significantly; at posting stays 23.2% (reported as the odds tool's calibrated probability).

### Direction A on the October archive (wb15.py; exposure on /newest page 1 from Wayback captures; forward daily retrain)
Exposure inputs at 15 min: share of /newest captures in the first 15 min that showed the post (and position-weighted,
1/sqrt(rank)), estimated minutes on page 1, votes per exposure-minute (plain, weighted), posts submitted in the 30 min
before, posting hour.
| Caught at 15 min | all 13 days (388 winners) | 10 days 90%+ coverage (287) |
|---|---|---|
| + votes + who | 28.4% [23.6, 33.0] | 29.3% |
| **+ votes + who + exposure** | **29.6% [25.4, 33.4]** (+4.1 [+1.1, +7.4] vs base) | 30.0% (+3.8 [+1.3, +7.0]) |
| exposure vs votes + who, paired | +1.3 [-1.0, +3.7] | +0.7 [-1.9, +3.1] |
Direction A adds about +1 point on the archive, not significant on its own (Wayback captures every ~10 min give a coarse
exposure; the live recorder reads /newest every minute). Live test from Nov 5.

### Directions B and C on the October backtest (wb_reup.py; Oct 2-14 forward daily retrain, 388 winners)
Exposure event = front-page arrival or return (Quality News rank <= 90) 3+ h after posting after 3+ h off it, from the
10-minute rank series (series exist for 5+ point posts only: a few non-winning events are missing, small optimistic bias
for B). Jul-Oct: 2,552 posts (2.4%) had one, 19.4% of them won; median 5.7 h after posting. Oct 2-14 winners with an
event: late risers 69/145, re-ups 10/62 (the series cover ~36 h, so most re-ups return after it ends), fast 13/181.
| Caught at 15 min, Oct 2-14 | Caught | vs posting clock | fast / late / re-up caught |
|---|---|---|---|
| posting clock (votes + who + exposure) | 29.6% [25.6, 33.5] | | 74 / 30 / 11 |
| **B: exposure clock** (also judged 15 min after the event; beside the headline) | **35.6% [33.0, 38.3]** | **+5.9 [+2.3, +10.1]** | 71 / 57 / 10 |
| C: + predicted second-chance return (per-post rule) | 26.8% | -2.8 [-4.8, -0.8] | 69 / 26 / 9 |
B nearly doubles the late risers caught (30 -> 57): judged 15 min after they reach the front page. C as built hurts.
Next for B: extend events past 36 h with Quality News late samples (re-ups), and the live /pool events.

### 15-min model variance (wb15_seeds.py; votes + who + exposure, Oct 2-14 forward retrain)
Single model 29.6% [25.6, 33.5]; 5-seed average 29.1% (-0.5 [-2.6, +1.3]); 5 seeds slower + regularised 28.1%
(-1.5 [-4.5, +1.6]). The model is not limited by its own variance.

### GitHub (in progress)
starred_at is admin-only on GitHub since July 2026, so Data Feeder pulls daily new-star counts per repo
(raw/github_stargazers/star_history_*.jsonl; 9,662 repos). wb_gh.py uses the days before the posting day only (1 / 7 /
30 days, acceleration, repo age); to run when the pull lands.

### Why 15 min is 24.7% over Sep 1 - Oct 14 but 29.6% on Oct 2-14 (gap15.py), and the fix
Not the dates: the headline model catches Sep 1-30 25.5% (228/895) and Oct 1-14 23.1% (99/428). The gap is inputs and
setup: the Oct 2-14 tests add Wayback /newest votes (a snapshot by 15 min for 5.4% of Sep posts vs 79.2% of Oct 1-14),
who commented, exposure, history score and page judge, retrain daily on the newest days, and flag within Oct only.
Fix = give the full-period model every 15-min input that exists for the period (train Jul-Aug, test Sep 1 - Oct 14):
| 15-min model, Sep 1 - Oct 14 | Caught | vs headline | Sep / Oct 1-14 | fast / late / re-up |
|---|---|---|---|---|
| headline (at posting + front rank) | 24.7% [22.6, 26.9] | | 25.5% / 23.1% | 194 / 93 / 40 |
| + comments + who by 15 min | 24.9% | +0.2 [-1.3, +1.6] | 24.8% / 25.0% | 193 / 92 / 44 |
| + history score + page judge | 25.3% | +0.6 [-1.5, +2.7] | 24.0% / 28.0% | 195 / 101 / 39 |
| **+ Wayback votes + exposure (where captured)** | **26.5% [24.4, 28.7]** | **+1.8 [+0.0, +3.6]** | 26.8% / 25.9% | 216 / 90 / 45 |
New full-period 15-min headline: 26.5%. The rest of the gap to 29.6% is daily retraining on the newest days and
within-October flagging; with dense early votes for every day (live recorder) the full model applies everywhere.

### GitHub star history as a 15-min input (wb_gh.py; PARTIAL pull: 8,229 / 9,662 repos, smallest repos first)
Daily new-star counts (GitHub made starred_at admin-only in July 2026); days before the posting day only. With star
data on Oct 2-14: winners fast 2/181, late 3/145, re-up 1/62; non-winners 1,126. Caught at 15 min 29.6% -> 28.4%,
-1.3 [-2.9, +0.5]; GitHub-linked posts only (1,132, 6 winners): 1/6 -> 2/6. Rerun when the pull completes (the big
repos come last).

### CORRECTION (2026-11-02 ~23:00 UTC): exposure inputs were empty (pandas 3 timestamp bug; found by E5)
wb15.expo15 converted capture times with astype("int64") // 10**9, which under pandas 3 gives microseconds / 1e9, so no
capture fell in any post's window: x_caps = 0 and every exposure input was NaN except posts-in-the-30-min-before and
hour. Fixed (pushed). Rerun, Oct 2-14, 388 winners:
| Caught at 15 min | all days | 90%+ coverage days |
|---|---|---|
| + votes + who | 28.4% [23.6, 33.0] | 29.3% |
| + votes + who + exposure (fixed) | 28.1% [24.1, 32.5], -0.3 [-1.7, +1.3] vs votes + who | 29.3%, +0.0 [-1.4, +1.5] |
| + votes + who + posts in the 30 min before + hour (what the earlier "29.6%" actually used) | 29.6% [25.4, 33.4], +1.3 [-1.0, +3.7] | 30.0% |
Exposure from Wayback captures (~10 min apart) adds nothing; the earlier gain was posting volume and hour. Results that
used expo15 are being rerun: gap15 (26.5%), wb_reup (35.6% exposure clock), wb_gh, wb15_seeds; live_oct had the
same bug (no result had been reported). Live per-minute exposure (direction A) is still tested from Nov 5.
Reruns after the fix:
- gap15 (full period, Sep 1 - Oct 14): + Wayback votes + exposure 25.4% [23.2, 27.7], +0.7 [-1.2, +2.5] vs the 24.7%
  headline (was 26.5%, +1.8 with empty exposure). No step is significant: **the full-period 15-min headline stays 24.7%**.
- wb_reup (Oct 2-14): posting clock (votes + who + exposure) 28.1%; **B, exposure clock 34.5% [31.5, 37.7], +6.4
  [+2.2, +10.5]** (late risers 27 -> 53 of 145); C -0.5 [-3.3, +1.9].

### Live 15 min with an October-trained model (live_oct.py; PROVISIONAL labels; run 2026-11-03 ~02:00 UTC)
Model trained on Oct 2-14 (Wayback /newest archive) with live-available inputs only: odds tool at posting, /newest votes
by 15 min, best /news position, exposure (fixed), volume, hour. Flags = winners per posting day.
| posting day | posts | winners so far | list days read | seen by 15 min | model, all | model, seen only | votes only | odds only |
|---|---|---|---|---|---|---|---|---|
| Oct 31 | 648 | 25 | 3 | 41.7% | 16.0% (4/25) | 8.3% (1/12) | 12.0% | 16.0% |
| Nov 1 | 740 | 16 | 2 | 53.2% | 6.2% (1/16) | 16.7% (1/6) | 25.0% | 0.0% |
| **Nov 2** (first full always-on day) | 1,083 | 25 | 1 | **99.7%** | **24.0% (6/25)** | 24.0% | 16.0% | 28.0% |
Nov 2 is the first day with near-full per-minute coverage; 25 winners so far and one list day read, so these are far
too few to read. Re-scored daily.

### GitHub star history, final (wb_gh.py on Data Feeder's dedup file; run 2026-11-03 ~02:45 UTC)
Caught at 15 min, Oct 2-14 (388 winners): votes + who 28.4% [23.8, 32.9]; + GitHub stars 28.6% [23.7, 33.4],
**+0.3 [-1.1, +1.6]**. Star data reaches few winners: fast 16/181, late 15/145, re-up 1/62. GitHub-linked posts only
(1,348 posts, 32 winners): 18.8% -> 21.9%. GitHub stars stay out of the model.

### Wayback outage (2026-11-03)
web.archive.org (CDX and the home page) times out from hn-sim-1 and from this container since ~23:59 UTC Nov 2;
HN's API answers from the VM. wb25h2 (Jul-Dec 2025 /newest) has fetched nothing. Replacement job wb25h2b waits for
the old job to end, probes Wayback every 10 min for 24 h, and resumes the same fetch when it answers.
Update 03:55 UTC: Wayback answers from Data Feeder's box (no 429s) but not from GCP: hn-sim-1 sees TCP timeouts only
(no 403/429), so GCP source IPs are being dropped. Both jobs stopped (nothing fetched); Data Feeder takes Jul-Dec 2025
onto its box, same output path. GitHub stars: closed lever.

### Live provisional readout (live15.py, run 2026-11-03 ~05:15 UTC; labels PROVISIONAL: Nov 2 has 1 list day read)
Oct 31 - Nov 2 posting days, 2,471 posts, 66 winners so far. Flags = winners. Nov 2 is the first full always-on day
(99.7% of posts seen by 15 min).
| Checkpoint | score | all 3 days | Nov 2 |
|---|---|---|---|
| 1 h | votes + front page | 37.9% [20.0, 50.0] | 13/26 (50.0%) |
| 1 h | blend with at-posting odds | 31.8% | 11/26 |
| 15 min | votes + front page | 18.2% [4.0, 34.6] | **9/26 (34.6%)** |
| 15 min | posting clock + re-up clock (direction B) | 24.2% [16.0, 33.3] | 7/26 |
| 15 min | at-posting odds alone | 15.2% | 6/26 (23.1%) |
| at posting | odds tool | 15.2% [0.0, 23.1] | 6/26 (23.1%) |
Re-up clock: 84 posts with an exposure event (median 6.5 h after posting), 16 of 66 winners among them; 31.2% of
those caught 15 min after the event. Per-minute model (direction A) switches on at 5 posting days (Nov 5).
E5: atposting_hist.parquet (44,263 Sep 1 - Oct 14 posts, out of sample: odds tool fit Jul 1 - Aug 15, calibrated
Aug 16-31) and live_atposting/ (Oct 31 - Nov 3) uploaded.

### Content model at posting (content_ft.py; orchestrator's bet; run 2026-11-03)
ModernBERT-base fine-tuned on title + domain + Show/Ask text (known at posting), label = ever in a daily top 30, every
winner + 4 sampled non-winners per epoch, 2 epochs, one T4 (L4 stocked out). Trained only on days <= the cut; scored
only later posts. Cost ~$1.75 GCE (~3.2 VM-hours incl. three failed starts).
| model | train | test | AUC |
|---|---|---|---|
| cut Jun 30 | 489k posts (15,944 winners) | Jul 1 - Oct 14 | 0.813 |
| cut Aug 30 | 552k | Sep 1 - Oct 14 | 0.816 |
| cut Sep 30 | 584k | Oct 1 - 14 | 0.817 |
| page text (title + domain + page), Jul-Aug only | 40k | Sep-Oct posts with a page | 0.717 vs 0.736 title-only, same rows |

**Caught at posting (Sep 1 - Oct 14, 1,323 winners), paired vs the current 23.2% blend:**
| score | Caught | vs 23.2% | late risers | re-ups | fast |
|---|---|---|---|---|---|
| current blend (Jul-Aug model + 2025+ history) | 23.2% [21.2, 25.3] | | 110/461 | 43/221 | 154/641 |
| content model alone (cut Aug 30) | 23.9% [21.9, 26.0] | | 111/461 | 51/221 | 154/641 |
| content (cut Jun 30) as an input to the Jul-Aug model, same 50/50 blend | 24.7% [22.2, 27.2] | +1.5 [+0.2, +2.9] | 121/461 | 43/221 | 163/641 |
| **3-way rank blend, equal weights set in advance** | **25.4% [23.2, 27.6]** | **+2.2 [+0.4, +4.0]** | 116/461 | 52/221 | 168/641 |
Content alone has pairwise accuracy 0.810 [0.797, 0.823] and matches the whole current blend on its own; it adds most on
re-ups (43 -> 51-52) and late risers (110 -> 116-121). **New at-posting headline: 25.4%.** Page text does not help
(trained on Jul-Aug only: 40k posts).

**Caught at 15 min (Oct 2-14, 388 winners), content (cut Jun 30) as an input to votes + who:** 28.4% -> 29.1%,
+0.8 [-2.7, +3.9]; late risers 25 -> 33, re-ups 14 -> 13, fast 71 -> 67. Not significant.

**Caught at 1 h (Sep 1 - Oct 14, 1,323 winners), content (cut Jun 30) as an input to the 47.2% model (post + history
score + rank only; cont1h.py):** **48.4% [45.0, 51.8], +1.1 [+0.0, +2.3]**, pairwise +0.012 [+0.009, +0.016]; late
risers 45 -> 60 of 461, re-ups 17 -> 20 of 221, fast 563 -> 560 of 641.

**Reach table (E5 handoff) at 15 min: not run.** It was fitted on Oct 2-9 outcomes, which are test days of the 15-min
backtest (Oct 2-14), so as an input it would leak; an honest version (fitted on training days) is a step function of the
15-min /newest score, which wb15 already gives the model directly.

**Odds tool with the content score (odds_live.py, ODDS_CONTENT=1; same protocol: fit Jul 1 - Aug 15, isotonic Aug 16-31,
test Sep 1 - Oct 14; content input = cut-Jun-30 score as a percentile, out of sample for every row):**
| age | AUC top 30, current -> + content | Brier top 30 | AUC top 10 |
|---|---|---|---|
| at posting | 0.794 -> **0.831** | 0.0271 -> 0.0263 (base 0.0290) | 0.789 -> 0.844 |
| 15 min | 0.803 -> 0.840 | 0.0267 -> 0.0259 | 0.805 -> 0.850 |
| 30 min | 0.842 -> 0.869 | 0.0247 -> 0.0243 | 0.849 -> 0.886 |
| 1 h | 0.882 -> 0.903 | 0.0223 -> 0.0217 | 0.896 -> 0.919 |
| 2 h | 0.914 -> 0.932 | 0.0188 -> 0.0183 | 0.932 -> 0.946 |
| 3 h | 0.926 -> 0.940 | 0.0168 -> 0.0165 | 0.936 -> 0.948 |
Live: the content version runs on hn-sim-1 alongside the current tool (oddsloop3, :50 past each hour, writes
odds_live_content/; the current tool keeps odds_live/ at :35), so live scoring compares the two on the same posts. Live
content scores come from a ModernBERT-base trained on every post up to Oct 14 (CPU), as a percentile against its own
scores on Sep 1 - Oct 14 posts.

**Reach table at 15 min, September refit (E5 handoff `reach_table_by_15min_score_sep`, fitted Sep 1-30 only; reach15.py):**
votes + who 28.4% -> 27.6% [24.3, 31.1], **-0.8 [-3.1, +1.5]**; fast 71 -> 67, late 25 -> 28, re-ups 14 -> 12. No gain
(the model already has the 15-min /newest score itself). Closed.

### showdead check (dead15.py; orchestrator question, 2026-11-03)
15-min backtest Oct 2-14 (votes + who): 388 flags, 110 winners caught, 278 flagged non-winners. HN item API today: 0 of
278 are dead, 0 deleted (today's state is an upper bound on what a 15-min recorder could see). A signed-in showdead
recorder would remove no false flags. Closed.

### Content model, ModernBERT-large (content_ft.py plan "large"; T4, ~4.5 VM-hours incl. the deploy model, ~$2.5)
Up to 3 epochs, early stopping on the last month inside each cut (both stopped after epoch 2, keeping epoch 1's
weights). Test AUC: cut Jun 30 0.815 (base 0.813), cut Aug 30 **0.825** (base 0.816). Gates rerun with CONTENT_PREFIX=large_
(same protocol and baselines as the base model):
| checkpoint | baseline | + base content model | **+ large content model** |
|---|---|---|---|
| at posting, 3-way blend (Sep 1 - Oct 14) | 23.2% | 25.4%, +2.2 [+0.4, +4.0] | **26.1% [23.9, 28.2], +2.9 [+1.4, +4.3]** |
| at posting, content as an input | 23.2% | 24.7%, +1.5 [+0.2, +2.9] | 25.2%, +2.0 [+0.6, +3.6] |
| 15 min, Oct 2-14 (votes + who + content) | 28.4% | 29.1%, +0.8 [-2.7, +3.9] | 30.2% [25.6, 34.7], +1.8 [-1.1, +4.8] |
| 1 h (rank-only + history + content) | 47.2% | 48.4%, +1.1 [+0.0, +2.3] | **48.5% [45.0, 52.1], +1.3 [+0.4, +2.2]** |
By type, large model: at posting (3-way) late risers 110 -> 122 of 461, re-ups 43 -> 50 of 221, fast 154 -> 173 of 641;
15 min late 25 -> 33, re-ups 14 -> 15, fast 71 -> 69; 1 h late 45 -> 53, re-ups 17 -> 22, fast 563 -> 567.
**Headlines: at posting 26.1%, 1 h 48.5%; 15 min stays on the posting clock (24.7% Sep 1 - Oct 14, 29.6% Oct 2-14), content +1.8 n.s.**

**Odds tool with the large content model** (odds_live.py, ODDS_CONTENT=1 CONTENT_MODEL=large; input = cut-Jun-30 large
score as a percentile, out of sample; same protocol): AUC top 30 at posting 0.794 (no content) -> 0.831 (base) ->
**0.836 (large)**, Brier 0.0263; 15 min 0.844; 1 h 0.905; 2 h 0.933; 3 h 0.940. CPU check on hn-sim-1 (2 vCPU):
ModernBERT-large scores 160 posts in 84 s (an hourly run is 100-160 posts). Deploy model: ModernBERT-large on every post
up to Oct 14 (2 epochs, as early stopping chose), reference = its scores on 5,000 Sep 1 - Oct 14 posts (GPU); live job
oddsloop3d swaps in after a verified first run (odds_live_content/ switches from base to large at that run).
P(top 10) is capped at P(top 30) in every version from 2026-11-03 13:09 UTC.
Live swap done 2026-11-03 16:56 UTC (oddsloop3e): the large content model now feeds odds_live_content/ (base before);
first run 301 posts, VM-wide peak memory 7.1 of 7.95 GB after scoring content first and freeing the model (the first
attempt, content scored last, was killed for memory). Thin margin: if a run is killed, that hour has no content scores.
Content-score cache (orchestrator's option b): each live post scored once (content_live.cached_logits); second hourly run
179 cached / 96 computed, but VM-wide peak still 6.75 GB of 7.95 (> 6.5 GB threshold), so per the orchestrator's
fallback hn-sim-1 was resized e2-standard-2 -> e2-standard-4 (16 GB, +$0.067/h) at 19:12 UTC Nov 3 (37 s down); the six
running jobs (fdloop3, ghstars1, listwatch2, live5, oddsloop2, oddsloop3f) were requeued and verified running.

### Content model + author history as text ((c); content_ft.py plan "next", base size, 256 tokens; T4 ~$1.2)
Input: title + domain + Show/Ask text + the author's last 5 titles from posts >= 2 days earlier, with their points
(82.9% of posts, 90.7% of winners have some). Same rows and cuts as the base content model.
Test AUC: cut Jun 30 0.818 (base 0.813), cut Aug 30 0.824 (base 0.816).
| checkpoint | base content | + author history | author vs base content, paired |
|---|---|---|---|
| at posting, 3-way blend | 25.4% | 25.8% [23.5, 28.1] | **+0.4 [-1.0, +1.7]**, pairwise +0.000 [-0.002, +0.002] |
| at posting, as an input | 24.7% | 24.0% | |
| 15 min (posting clock, Oct 2-14, vs votes + who 28.4%) | 29.1% | 28.4%, +0.0 [-2.8, +2.6] | |
| 1 h | 48.4% | 48.5%, +1.3 [+0.2, +2.4] vs 47.2% | |
Higher AUC, no Caught gain: the author's track record is already in the at-posting blend (real-list record, history
score). Per the orchestrator's rule (run large only if it clears at posting) no large author run. For reference, large
vs base content at posting is +0.7 [-0.6, +1.9] paired (both clear the 23.2% baseline; auth_vs_base.py).
(b) 2025 out-of-fold content scores done: quarters q1-q4 AUC 0.789 / 0.783 / 0.818 / 0.824 (each scored by a model never trained
on its own quarter); used when the 2025 Wayback votes land. The T4 deleted itself after the run.

### Live check 2026-11-04 00:31 UTC (score_live.py, live_caught.py)
Settled list days: Oct 30, Oct 31, Nov 1. **Live hourly daily-list forecast, settled days** (share of the real daily
top 30 / top 10 found): Oct 31 at 21:00 47% / 40%, last forecast (23:00) 53% / 60%; Nov 1 at 21:00 60% / 40%, 23:00 67% /
40%. Backtest reference: top 30 at 21:00 80.2%, end of day 86.0%. Two days only, but live is well below the backtest.
Provisional (not settled): Nov 2 57% at 21:00, Nov 3 80%.
Per-post odds: 6,372 live forecasts, none scorable yet (each post needs its 4 list days settled; first ~Nov 7).
Live Caught (hn_minute): no posting day has its 4 list days settled yet (first ~Nov 6). hn_minute minutes read per day
(front / newest / pool): Oct 31 930 / 306 / 307; Nov 1 1,445 / 606 / 321; Nov 2 3,290 / 1,611 / 152; Nov 3 2,769 /
1,538 / 194 (two recorders unioned; Nov 3 includes the 19:11-19:14 resize gap).

### Live daily-list forecast vs backtest: diagnosis (diag_live21.py; orchestrator, 2026-11-04)
Live hourly forecast at 21:05 found 14/30 (Oct 31) and 18/30 (Nov 1) of the settled top 30 (backtest at 21:00: 80.2%).
Replaying the backtest code path at the same forecast time (daily_v4 series/candidates/features cut at T, same fd_v4
models, Quality News series fetched now) finds **24/30 and 27/30**: the backtest path is not leaking; live got different
inputs. The 28 real top-30 posts live missed, by cause:
| cause | count |
|---|---|
| **live input differed** (replay has it in its top 30): slots taken by posts already on the previous day's list | **20** |
| model miss (replay misses it too) | 4 |
| posted after the forecast time | 2 |
| under 5 points at the forecast time (live candidate filter) | 2 |
Root cause: every wrong live pick sat on the previous day's settled list (Oct 31: 16 of 16 wrong picks on the Oct 30
list, incl. its #1-#9; Nov 1: 12 of 12 on the Oct 31 list). They should be excluded (`on_earlier_list`), but the live
exclusion comes from scraping news.ycombinator.com/front?day= for the last 7 days at forecast time with no check for
empty pages; at :05 the pages evidently came back empty (HN refuses some requests; listwatch reads the same pages on the
same IP). Live points of the live top 30 equal the replay's at T (no Quality News lag). Fix (forecast_daily.py, live
from fdloop4): exclusion = listwatch's own reads from the bucket + the scrape with retries on empty pages; the count of
excluded stories is written into each forecast. Caught headlines do not use the earlier-list input (no change there).

### Daily live readout 2026-11-04 ~01:30 UTC (live15.py; PROVISIONAL, labels = daily top 30 so far)
Backtest headlines (unchanged): 1 h 48.5%; 15 min (posting clock) 24.7% Sep 1 - Oct 14, 29.6% Oct 2-14; at posting 26.1%.
Live, Oct 31 - Nov 3 posting days (3,697 posts, 97 winners so far; list days settled: Oct 31 2, Nov 1 1, Nov 2-3 0):
| checkpoint | votes + front page | at-posting odds | blend 50/50 | by day (votes; blend) |
|---|---|---|---|---|
| 1 h | 34.0% [18.6, 50.0] | 15.5% | 30.9% | Oct 31 3/26, Nov 1 8/19, Nov 2 12/35, Nov 3 10/17 |
| 15 min (posting clock) | 13.4% [5.2, 20.0] | 15.5% | **18.6% [6.7, 28.8]** | blend: 2/26, 1/19, 10/35, 5/17 |
| at posting (odds tool) | | 15.5% [4.8, 23.7] | | 4/26, 0/19, 9/35, 2/17 |
Secondary (exposure clock, direction B): 105 posts with an exposure event (median 6.8 h after posting), 29 of 97 winners;
posting + re-up clock 21.6% [16.3, 27.0]. Seen by the recorder within 15 min: Oct 31 41.7%, Nov 1 53.2%, Nov 2 99.7%,
Nov 3 99.7%. Recorder minutes read (front / newest / pool): Nov 2 3,290 / 1,611 / 152; Nov 3 2,769 / 1,538 / 194.
Per-minute model (direction A) switches on at 5 posting days (tomorrow's run).
**Live headline from now on = full-coverage days** (recorder saw >= 95% of posts within 15 min; orchestrator,
2026-11-04), flags = winners on those days only. Full-coverage days so far: Nov 2, Nov 3 (provisional labels):
| checkpoint | votes + front page | at-posting odds | blend 50/50 |
|---|---|---|---|
| 1 h | 34.6% [28.6, 47.1] | 26.9% | 32.7% |
| 15 min (posting clock) | 11.5% | 26.9% | **21.2% [17.6, 22.9]** |
| at posting (odds tool) | | **26.9% [23.5, 28.6]** | |
All days (Oct 31 - Nov 3) alongside: 1 h 34.0%, 15 min 18.6%, at posting 15.5%. Note: the per-day counts printed by an
all-days run (e.g. Nov 2 10/35) use flags spread over all days, so they are not a valid full-coverage number.

### 15 min with 2025 Jan-Jun Wayback rows (+ content) (wb25_train.py; run 2026-11-04 ~02:30 UTC)
Data check (Data Feeder's final Jan-Jun pull): 674,460 rows, 0 duplicates, 0 failed captures; 67.8% of Jan-Jun posts have
a /newest snapshot by 15 min (Jan 55%, Feb 47%, Mar 68%, Apr-Jun 77-81%). **Outcome-independent**: snapshot-by-15-min
rate 66.1-69.1% across every final-points band (1 point ... 200+), winners 67.3% vs all 67.8% (as October's archive).
Model inputs (all known at 15 min, no "who"/history/QN rank: those would leak into 2025 rows): post features, title score,
real-list record, title embedding (PCA 32), comments by 15 min, Wayback votes by 15 min, volume, hour; + content =
content-model score as a percentile (2025 rows: out-of-fold quarter models; 2026: cut-Jun-30). Paired vs "2026 rows".
| test | 2026 rows | + content | + 2025 rows | + 2025 rows + content |
|---|---|---|---|---|
| Oct 2-14 daily retrain (388 winners) | 23.5% [20.1, 26.9] | 27.6%, +4.1 [+0.5, +7.7] | **27.8%, +4.4 [+2.7, +6.1]** | 27.1%, +3.6 [+0.5, +6.8] |
| Sep 1 - Oct 14, fit <= Aug 31 (1,323 winners) | 23.7% [21.6, 25.4] | 26.2%, +2.6 [+1.2, +3.9] | 24.9%, +1.3 [-0.5, +3.2] | **28.0% [25.5, 30.5], +4.4 [+2.3, +6.6]** |
By type (Sep 1 - Oct 14, 2025 + content vs 2026 rows): fast 173 -> 198 of 641, late 97 -> 122 of 455, re-ups 43 -> 50 of
221. 2025 rows on top of content: Oct +-0.5 [-3.6, +2.6], Sep-Oct +1.8 [-0.1, +3.9].
Reading: 2025 rows and content each lift this model by ~4 points on Oct 2-14 but do not stack there; on the longer
Sep 1 - Oct 14 test they stack (28.0%). This model has no who/history/QN-rank inputs, so it is not yet the headline
model: the posting-clock headlines stay 24.7% (Sep 1 - Oct 14) and 29.6% (Oct 2-14) until the 2025 rows are combined
with those inputs (needs who/history measured before each 2025 row). Jul-Dec 2025 lands in ~1 day; rerun then.

### Paired headline test at 15 min (paired15.py; posting clock; identical posts and flag counts)
| test | headline | light (2025 Jan-Jun rows + content) | 50/50 blend (fixed in advance) |
|---|---|---|---|
| Sep 1 - Oct 14 (1,323 winners) | 24.7% [22.6, 26.9] | **28.0% [25.7, 30.7], +3.3 [+1.1, +5.5]** | 26.1%, +1.4 [-0.2, +2.8] |
| Oct 2 - 14 (388 winners) | 29.6% [25.6, 33.3] | 27.1%, -2.6 [-5.7, +0.2] | 28.1%, -1.5 [-4.2, +1.3] |
By type, Sep 1 - Oct 14: late risers 93 -> 123 of 461, re-ups 40 -> 50 of 221, fast 194 -> 198 of 641.
**New full-period 15-min headline: 28.0%** (Sep 1 - Oct 14). Oct 2-14 headline stays 29.6% (who + Wayback-dense days).
Leak checks: (1) 2025 snapshots outcome-independent (snapshot-by-15-min rate 66-69% in every final-points band; winners
67.3% vs all 67.8%); (2) on the Sep 1 - Oct 14 test posts, the light model's only vote input (Wayback /newest by 15 min)
is present at 27-30% in every final-points band, winners vs non-winners Sep 4.1% vs 5.5%, Oct 81.5% vs 79.2%: no
outcome signal; (3) content scores out of sample by construction (2025 rows: quarter models never trained on their
quarter; 2026: trained <= Jun 30); (4) no QN series, who or history inputs (the leak-prone ones).

### Predict every minute (Shreyas via the orchestrator, 2026-11-04)
**Per-minute odds live** (job oddsmin1 on hn-sim-1, from 02:04 UTC Nov 4): every 60 s (each run ~3 s), every post of the
last 3 h: P(top 30) / P(top 10) at posting, 15 min, 1 h and now -> odds_minute/<day>/<HHMM>.parquet. Inputs: the odds
tool's models (large content model) with front-page rank now / best rank from hn_minute (both recorders) instead of
Quality News 10-min slots; at-posting feature rows from a cache job (~10 min per pass: author/domain history over all
posts), so a new post's first prediction comes 10-20 min after posting, then every minute. Bug fixed on the way:
hn_minute's rank is already the absolute position (page 2 = 31-60); live_caught.load_minute added (page-1)*30 again,
inflating page 2-3 positions in the live readouts.
**Per-minute model (direction A) on from 2 posting days** (leave one day out), live table per posting day:
| day | seen by 15 min | lists settled | winners | 15 min (gap vs 29.6%) | 1 h (gap vs 48.5%) | top miss reasons at 15 min |
|---|---|---|---|---|---|---|
| Oct 31 | 41.7% | 2 of 4 | 26 | 2/26 7.7% (-21.9) | 5/26 19.2% (-29.3) | not seen 13; late riser 6; ranked below cut 3 |
| Nov 1 | 53.2% | 1 of 4 | 19 | 0/19 0.0% (-29.6) | 2/19 10.5% (-38.0) | not seen 14; ranked below cut 4; late riser 1 |
| Nov 2 | 99.7% | 0 of 4 | 35 | 7/35 20.0% (-9.6) | 11/35 31.4% (-17.1) | late riser 16; ranked below cut 12 |
| Nov 3 | 99.7% | 0 of 4 | 17 | 2/17 11.8% (-17.8) | 8/17 47.1% (-1.4) | ranked below cut 12; late riser 3 |
Full-coverage days (Nov 2-3), 15 min: per-minute model 17.3%, blend 21.2%, at-posting odds alone 26.9%: with 4 days
(two with poor coverage) the per-minute model is still weaker than the odds; it retrains daily as days settle.
**Position bug audit (orchestrator, 2026-11-04).** Both sources give the absolute position already (hn_minute rank: page
2 = 31-60; Wayback rank: news_p2 = 31-60), but four places added (page-1)*30: live_caught.load_minute (live readouts),
wb15.votes15 (v_front), wb_caught (ev_front_best) and live_oct (archive features). All fixed (offset 0).
- Full-coverage live numbers (15 min 21.2%, 1 h 34.6%, at posting 26.9%): unchanged by the fix; the votes / odds /
  blend scores use front-page presence only, never the position (the 02:10 rerun's small moves, votes 11.5 -> 13.5% at
  15 min and 34.6 -> 36.5% at 1 h, are refreshed labels: Nov 3 winners caught at 1 h 8 -> 9 of 17).
- Backtests: none used load_minute. The Wayback inflation reached v_front / ev_front_best only as tree-model inputs, a
  strictly increasing transform, so no backtest number moves: rerun of votes + who with corrected positions 28.4%
  [23.8, 32.9] (identical). live_oct was consistent before (train and live both inflated) and is consistent again.

### Miss decomposition of the 15-min headline (miss15.py; Sep 1 - Oct 14, light model 28.0% = 371 / 1,323)
Every winner not flagged, by bucket; oracle gain = points of Caught if every winner in the bucket were flagged.
| bucket | winners | caught | missed | oracle gain |
|---|---|---|---|---|
| late riser (not on the front page within 1 h) | 461 | 123 | 338 | **25.5 pts** |
| fast, no recorder data by 15 min (no /newest snapshot) | 466 | 133 | 333 | **25.2 pts** (302 of the 333 in September) |
| re-up (first listed 2+ days after posting) | 221 | 50 | 171 | 12.9 pts |
| fast, snapshot but no early signal (<= 2 pts, 0 comments) | 88 | 21 | 67 | 5.1 pts |
| fast, early signal but scored below the flag | 87 | 44 | 43 | 3.3 pts |
Reading: (1) model error on posts with a visible early signal is only 3.3 pts; (2) 25.2 pts is a backtest data gap:
September has a /newest snapshot by 15 min for 4.1% of winners (October 81.5%); live, the per-minute recorder sees ~100%,
so this bucket is a coverage artifact of the backtest, not of the live product (the Oct 2-14 headline, 29.6%, is the
dense-coverage read); (3) 38.4 pts sit in late risers + re-ups, posts with no front-page signal in their first hour:
at the posting clock only at-posting inputs (content moved late risers 97 -> 123) reach them.

### 15 min with all of 2025 (Jan-Dec Wayback rows + content; wb25_train.py, paired15.py; 2026-11-04)
Jul-Dec check (verify25.py, Data Feeder's final pull): 822,840 rows, 0 duplicates; 74.5% of Jul-Dec posts have a
/newest snapshot by 15 min (Sep 2025 47%, other months 77-84%); **outcome-independent**: 73.7-75.2% in every
final-points band, winners 74.6% vs all 74.5%.
| test | 2026 rows | + content | + 2025 rows | + 2025 rows + content |
|---|---|---|---|---|
| Oct 2-14 daily retrain | 22.4% | 27.6%, +5.2 | 26.0%, +3.6 | **30.2%, +7.7 [+4.3, +11.7]** |
| Sep 1 - Oct 14 (fit <= Aug 31) | 22.8% | 25.8%, +2.9 | 25.6%, +2.8 | **28.4%, +5.6 [+3.4, +8.0]** |
With the full year, 2025 rows add on top of content in both tests (+2.6 [-0.5, +5.8] Oct; +2.6 [+0.5, +5.1] Sep-Oct).
Paired vs the headlines (identical posts and flags): Sep 1 - Oct 14 **28.4% vs 24.7%, +3.7 [+1.2, +6.1]** (Jan-Jun
only: 28.0%); Oct 2-14 30.2% vs 29.6%, +0.5 [-2.7, +3.5] (late risers 30 -> 38, re-ups 11 -> 15, fast 74 -> 64).
Headlines: full period 28.4%; Oct 2-14 stays 29.6% (live product). Next: the two models are complementary on Oct 2-14
(light catches late risers and re-ups, the headline catches fast posts) but the pre-set 50/50 blend gave 28.9%, -0.8.
