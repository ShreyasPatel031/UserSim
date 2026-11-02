# HN Caught at 15 min: direction review (2026-11-02)

Caught per post today: 1 h 47.2% [43.7, 50.6]; 15 min 24.7% [22.6, 26.9] (28.4% on Oct 2-14 with honest /newest votes +
who commented); at posting 23.2% [21.2, 25.3]. Evidence: `RESULTS.md`.

## Critique

1. **80% at 15 min is not reachable under the current per-post rule, and the data says why.** Oct 2-14 winners:
   181 fast (on the front page within 1 h), 145 late risers, 62 re-ups. Late risers and re-ups (53%) have a median of
   1 point at 15 min (12% / 4% with 3+ points vs 7% of non-winners): nobody has voted yet. Their fate is decided later,
   by who finds them on /newest page 2 or by a moderator putting them in the second-chance pool (median 23 h after
   posting). Catching every fast winner, with the rest at today's rates, gives 220/388 = 57%. Fast winners are noisy
   too (35% with 3+ points by ~11 min, but so do 763 non-winners). Realistic ceiling at 15 min: about 40-45%.
2. **Early outcome is mostly exposure luck.** 97% of winning reposts had flopped before with the identical link; the
   same-link pair model cannot tell the winning posting from the flop (51.8%).
3. **Most "did not move" verdicts are underpowered.** Oct 2-14 is 13 days, 388 winners: paired intervals of +-2-5 points,
   so a real +2 lever (the size of everything that has worked) is invisible. Read them as "not large", not "zero", and
   use within-day pairwise accuracy (more power) for lever decisions.
4. **The backtest's "15 min" is ~11 min.** Wayback captures /newest every ~10 min; the live recorder's per-minute reads
   add ~4 minutes of votes.

## Directions, most promising first

**A. Exposure-normalised votes from the per-minute recorder (fast winners; +5-10 points at 15 min).** Two posts with
2 votes at 15 min differ if one sat on /newest page 1 for 3 minutes at peak and the other for 15 minutes at 03:00 UTC.
Next experiment: in `live15.py`, exposure on /newest page 1 (minutes, position-weighted), votes per exposure-minute,
the minute of the 2nd / 3rd vote, posting volume around the post; the leave-one-day-out model switches on at 5 posting
days (~Nov 5), reported on all posts and seen-only, with and without the exposure inputs. ~2 weeks of live days gives
the October archive's power.

**B. Judge each post 15 min after each exposure event, not only after posting (re-ups and next-day late risers; raises
the ceiling from ~57% to ~74%).** Re-ups enter the pool a median 23 h after posting; 31% of pool posts win; 8 of 10
re-up winners passed through it. Under an exposure clock they become fast winners at their re-up time. Reported beside
the per-post headline. Next experiment: `live15.py` re-up clock (score 15 min after a post enters /pool or returns to
the front page; Caught for that cohort). Needs /pool read every ~5 min (asked of Grok Bot / Data Feeder).

**C. Predict the moderator's pick (re-ups at posting and at 15 min; +3-6 points).** A second-chance re-up is a human
quality call on a post that got no exposure, the one winner type that is content-driven. Next experiment: Wayback
captures of news.ycombinator.com/pool for Oct 2-16 (asked of Data Feeder); train "goes to /pool" on the page judge,
domain / author record and the at-posting odds; test as a 15-min input on Oct 9-14 with caught-by-type. If pool entry is
predictable at AUC > 0.8, it also feeds B.

**Stop:** adding more at-15-min inputs about the post itself (feeds, page content, competition, ties) on the 13-day
archive: each is a +0-2 lever the test cannot see. Accumulate live days, then test A on them.
