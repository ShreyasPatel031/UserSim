# Two PH predictors: how they compare and how to split the work

Two agents built Product Hunt top-list predictors in parallel:

| | Breadth (`claude/cool-volta-l5nuo4`, `experiments/ph_predict/`) | Longitudinal (`claude/eager-pasteur-jffjnl`, `experiments/ph_longitudinal/`, this folder) |
|---|---|---|
| Focus | many data sources per launch | how a launch develops over time (history, first hours, live forecasts) |
| Launch data | PH API, Mar–Oct 2026 | PH API, Oct 2025 – Oct 2026 (7,696 featured launches) |
| Unique sources | VM fetch helpers, X follower counts (fxtwitter), commenter network, competitor reviews and complaint fit, LinkedIn pilot, Wayback homepage snapshots, PH leaderboard pages via VM | timestamps of each launch's first 20 PH comments (first 1/2/4 h, before launch), X posts linking the domain −24 h to +4 h, same-day HN, same-product history, YC |
| Models | full / weekly-list / monthly-list objectives, blends, within-day ranks | expanding-window LightGBM; sources and settings chosen on Jun–Jul, reported on Aug–Oct only |

## Results side by side

Different test windows, so compare loosely. Recall@k; random in brackets.

| | day@5 | day@10 | week@10 | month@10 |
|---|---|---|---|---|
| Breadth: full model (test Mar–Oct) | 0.69 | 0.77 | 0.53–0.56 | 0.31–0.40 |
| Breadth: + whole-day launch audience (labelled an upper bound) | 0.77 | 0.82 | 0.57 | – |
| Longitudinal: pre-launch (test Aug–Oct) | 0.67 | 0.71 | 0.60 | 0.35 |
| Longitudinal: optimized, first 4 h (test Aug–Oct) | **0.71** | 0.76 | **0.61** | 0.50–0.55 |
| (random) | (0.25–0.32) | (0.36–0.48) | (0.07) | (0.02) |

## Where the two agree

- Who launches it decides most of the ranking: hunter audience and track record, team size, self-hunt.
- Reading the product (homepage, LLM judgement) beats random alone but adds about nothing on top.
- Adding many weak sources at once does not help and can hurt.
- The API returns each day in rank order, so ties must be broken randomly (both caught this).

## Cross-check done here

The breadth agent's two strongest ideas, added to the longitudinal model and judged on the same validation and test
months:

| Added | validation | test day@5 | test week@10 |
|---|---|---|---|
| (none) | 0.682 | 0.71 | 0.61 |
| hunter PH follower count | 0.678 | 0.72 | 0.61 |
| within-day ranks of key features | 0.676 | 0.71 | 0.64 |
| both | 0.674 | 0.73 | 0.63 |

All within noise. Both models plateau around 0.70 daily top 5, so the limit is the data, not the feature set.

## What should raise the ceiling

The breadth agent's whole-day launch audience (+7–8 points) and the longitudinal first-4-hours comments (+2–4) say the
same thing: **what happens during launch day matters most**. The decisive signal, upvotes over the first hours, is not
in the API with timestamps and cannot be rebuilt for past days. It has to be recorded going forward.

## Proposed split

- **Breadth agent:** keeps owning source adapters (VM fetch, X followers, LinkedIn, commenter network, competitor
  reviews) and the weekly/monthly list objectives. Ask: run `vm_leaderboard.py` for **today's** date every 30 minutes
  from 00:01 PT (the VM already has the route), writing one file per snapshot with a timestamp. Hunter and maker
  follower counts at 00:01 PT in the same job would remove the follower leak.
- **Longitudinal agent (this branch):** owns time-indexed signals and the forecast protocol: one feature table per
  launch with an `as_of` time (launch, +1 h, +2 h, +4 h), models evaluated at each cut-off, a validation/test month
  split, and daily live predictions scored the next day (`predict_live.py`, `score_live.py`).
- **Shared:** key everything by PH post id; ISO weeks (Mon–Sun) and calendar months as both already use; recall@k over
  lists with at least 2k launches; bootstrap 95% intervals.

Once a few weeks of intraday snapshots exist, the first-4-hours model can add "rank and votes at +1/+2/+4 h"
and be measured on the same protocol.
