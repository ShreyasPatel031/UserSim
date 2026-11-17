# A pre-launch signal for first-time hunters

E5, Nov 17 2026. Pre-registered in `PREREG.md` (commit f6c95375) before the run.

**Result: no leak-free backward test of the requested features is possible, and the one dated signal that is possible adds nothing. Closed; no patch.**

## Dating: what the store allows

- **The strict rule leaves 9 launches.** The rule was to use a person's file only if it was pulled before the launch day. Every person file was pulled Nov 4–16 2026. Of 2,856 newcomer launches (Apr 1 – Nov 12), 9 have a hunter pulled before the launch day.
- **Upvote activity before a launch cannot be dated.** 92% of held upvotes are dated only by when they were read.
- **Follow lists are undated.** In-store followers, active-voter followers and team reach cannot be tested backward. They can only be collected forward.
- **Makers are redacted in the 00:05 reads,** so maker-based inputs could not run at 00:05 anyway. Only the hunter is usable.

## What was tested: dated history of the hunter

The store's hunted and launched events carry exact dates back to 2013. Counting only events dated before the launch day:

| Input | Description |
|---|---|
| H1 | Hunter's hunts, all time (our table's record starts Jan 2025) |
| H2 | Hunter's launches as a maker |
| H3 | Days since the hunter's last hunt or launch |
| H4 | Hunter found in the store |

**Coverage among newcomer launches:**
- 79.7% have their hunter in the store;
- 17.5% have any dated earlier hunt or launch;
- those 17.5% reach the top 10 23.8% of the time, against 19.7% for the rest.

**Arm-3 rebuild with and without H1–H4, month-forward, 195 days (Apr 1 – Nov 12), paired:**

| | Top 3 | Top 5 | Top 10 | Newcomer top-10 recall (185 days) |
|---|---|---|---|---|
| Arm 3 | 57.4 [54.4, 60.7] | 65.1 [62.6, 67.7] | 77.7 [75.9, 79.4] | 43.6 [38.7, 48.2] |
| Arm 3 + hunter history | 56.4 [53.2, 59.7] | 65.7 [63.2, 68.2] | 77.6 [75.9, 79.2] | 43.6 [38.7, 48.5] |
| Difference | −1.0 [−2.6, +0.5] | +0.6 [−0.4, +1.6] | **−0.1 [−0.7, +0.5]** | 0.0 [−1.5, +1.6] |

**Not adopted.** The top-10 interval spans 0, top 3 slips by 1.0, and newcomer recall is unchanged.

## What a real test needs: forward collection

The requested signals (in-store followers, active-voter followers, team reach) can only be dated going forward:

1. At each 00:05 run, for each launch's hunter, take the held people whose follow list was pulled before the launch day.
2. Count:
   - how many follow the hunter;
   - how many of those voted on any other launch in the last 30 days;
   - the total.
3. Freeze the counts with the run's timestamp.

With about 90,000 people now held and about 80% of newcomer hunters in the store, that would give about 15 newcomer launches a day. Thirty days would give about 450, enough to read the newcomer top-10 recall with an interval, though not yet enough to train on. This needs a nightly writer on the VM (PH agent). Nothing has been started.

Files: `feats.py`, `nc_run.py`, `score.py`, `result.json`.
