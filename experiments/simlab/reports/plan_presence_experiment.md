# Plan: hour-of-day presence and vector twins in the Product Hunt person model (for the agent carrying it out)

## Goal
Test two ideas from the HN simulation on Product Hunt, with the same honest scoring as everything else:
1. **Presence:** each person has active hours. A launch that gets its votes early is seen by early people. Does
   knowing when a person is usually active, and when a launch's votes arrive, improve who-picks-what and the launch
   score?
2. **Vector twins:** a free per-person embedding from the person's own comments and picks (we have 68,823 comments and
   full upvote histories), used as a direct taste match to each launch, instead of only aggregated taste traits.

Read `experiments/simlab/reports/overnight_1030.md` first: it has every result so far and the scoring conventions.

## Data you have
- `simlab` store (`SIMLAB_DATA=data_v2` on usersim-exp-1): people, launches, events (upvote/comment, dated).
  Event dates are days, not times, so **presence by hour needs the comment timestamps**: `comments` table in the
  warehouse has `created` to the second (via `ph_comments.parse`) for 68k comments by 20k people.
- Hourly vote snapshots per launch start Oct 31 (`vote_snapshots` table, `raw/vote_snapshots/`). Only a few days
  exist at first; the presence test of launches' vote timing needs ~14 days. Start with the people side.
- Embeddings: `ph_predict/data/emb.npz` has `person` vectors (bge-small over profile text) and `launch` vectors.
- Person model: `simlab/popscore.py` (TASTE=1 is the current best); within-person test harness `simlab/pick_boost.py`
  (ABLATE=1 shows how to add an input group); launch-level test `ph_predict/newsim_eval.py` (STAGE=2 STAGE3=1).

## Step 1: presence profile per person (1 day)
For each person: distribution of their comment hours (Pacific), from the `comments` table; share of activity in the
first 2 hours of a Product Hunt day (00:00–02:00 PT), first 6 hours, and the evening. Fall back to "unknown" for people
with fewer than 5 timed comments and report coverage.
- Add to `popscore.py` behind `PRESENCE=1`: `pres_early2`, `pres_early6`, `pres_n`.
- A launch-side counterpart comes later from `vote_snapshots`: share of its votes by hour 2 and hour 6 (NOT available
  before launch; use it only in the launch-day forecast, never in the pre-launch model).

## Step 2: vector twins (1 day)
For each person, a taste vector = mean of the launch embeddings of their past picks, recency-weighted (half-life 60
days), computed before each day (no leakage). Add `twin_cos` (cosine to the launch) and `twin_rank` (standing of that
cosine within the day's line-up) behind `TWIN=1`. Compare with the existing `meaning` and `taste_*` inputs; the
question is whether a direct twin beats aggregated taste traits.

## Step 3: tests (1 day of compute on usersim-exp-1, e2-standard-32)
Always run `ph_predict/coverage_check.py` first; it must print COVERAGE OK.
1. Within-person: `SIMLAB_DATA=data_v2 PRESENCE=1 TWIN=1 ABLATE=1 OMP_NUM_THREADS=2 python3 -m simlab.pick_boost 6`.
   Report top-3 hit and AUC with and without each group, and months better than base (6 months). Current base:
   top-3 hit ≈ 49–50, AUC ≈ 0.70. **Beware the tie-break artifact:** "only X" top-3 hits with few inputs are inflated
   (line-up order breaks ties); trust AUC for small groups or add a random tie-break.
2. Launch level: `TASTE=1 PRESENCE=1 TWIN=1 python3 -m simlab.popscore 16` writes a new features file (give it its own
   prefix, e.g. `psq_`, and add the file name to `ph_predict/features.py`'s extras list), then
   `python3 robust_src.py +pst +psq =pst =psq` (Jun–Oct) and `STAGE=2 STAGE3=1 python3 newsim_eval.py` with the new
   source added to `base`. Current simulation-only: 61.5 / 71.0 / 80.2 daily top 3/5/10 (Jul–Oct); launch model 65.8 /
   72.9 / 80.8.
3. Report every number with a 95% interval (bootstrap over days, as `ctrl.py` does) and the per-month win count.
   A change under ±3.5 points on daily top 3 is noise.

## Step 4: launch-day forecast (after ~14 days of snapshots, about Nov 14)
Train on `vote_snapshots`: votes at hour 1, 2, 4 (+ the pre-launch simulation score as a prior) → final daily rank.
Rolling by day. Report top 3/5/10 at each hour against the pre-launch forecast. This is a different claim (made during
launch day); label it so.

## Cost and rules
- Compute: usersim-exp-1 only (start/stop it; ~$1.5/h). No Claude calls; Gemini only if needed (not expected here).
- Don't touch usersim-pipeline except through the skip-run procedure described in `run_daily.sh`.
- Commit to `claude/cool-volta-l5nuo4` with results appended to `overnight_1030.md`; do not commit files that list
  Product Hunt usernames (reports with per-person rows stay on the VM).

## Expected outcome, honestly
Presence on the people side alone: small (knowing who shows up added ~1.5 points in the oracle test). Twins: likely
within noise of the existing taste inputs. The launch-day forecast in step 4 is where the large gain is expected
(75–85% top 3 at hour 2, to be measured).
