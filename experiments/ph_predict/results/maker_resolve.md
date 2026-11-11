# Placeholder makers resolved to identities, maker history recomputed (Nov 11)

**Placeholders.** On the VM's data/days files (Mar–Oct), 5,616 of 11,676 maker slots on 1,901 of 5,711 launches are
placeholders (id "0", username "[REDACTED]"; the follower count is kept). The warehouse shows the same: 5,478 of
11,411 slots on 1,850 of 5,566 launches.

**Resolution from held data only.** store_v3 "launched" events (10,566, salted person id → launch id) give a launch's
makers. Placeholder slots are filled by launched people who are not among the named makers, whose usernames I matched
through the same salted hash. No usernames are stored or committed.

| | resolved |
|---|---|
| placeholder slots, all launches | 889 / 5,478 (16%) |
| placeholder launches, all | 571 / 1,850 (31%) |
| placeholder slots, actual top-3 launches | 300 / 1,330 (23%) |
| placeholder launches, actual top 3 | 172 / 338 (51%) |

Other sources: the comment dumps carry no maker flag, people_ts only exists from Nov, and hunted tabs cover hunters,
not makers.

**Current features pool every placeholder into one maker.** features.add_history keys makers by id, so all "0"
makers merge into a single maker with the pooled history of every placeholder launch. Among placeholder launches the
mean hist_maker_n is 3,698. Placeholders treated as missing give 0.3; with resolved identities, 0.6.

**Honest LM month-forward** (maker_resolve.py on the VM): E5's ctrl.fit, honest_cols, 5 seeds, the same folds; hist_maker
recomputed with only earlier days; 245 days.

| variant | top 3 | top 5 | top 10 |
|---|---|---|---|
| (i) current | 59.9 | 67.7 | 75.4 |
| (ii) placeholders missing | 60.2 | 68.6 | 75.7 |
| (iii) resolved identities | 60.2 | 68.7 | 75.8 |

Paired differences with 95% day bootstrap:
- (ii) − (i): +0.3 [−1.2, +1.8] / +0.9 [−0.1, +1.9] / +0.2 [−0.4, +0.9]
- (iii) − (i): +0.3 [−1.2, +1.8] / +1.0 [0.0, +2.0] / +0.3 [−0.3, +1.0]
- (iii) − (ii): 0.0 / +0.1 / +0.1

Hit rate (predicted top 3) among the actual top-3 launches:

| launches | n | i | ii | iii |
|---|---|---|---|---|
| with a placeholder | 348 | 53.4 | 52.6 | 52.6 |
| without | 385 | 66.0 | 67.0 | 67.0 |
| with a resolved placeholder | 177 | 62.7 | 61.6 | 61.6 |

**Verdict: no gain on top 3.**
- The pooled "0" maker hurts less than expected, because LightGBM mostly learned to ignore the huge counts.
- Resolved makers add almost no history: 0.6 earlier launches on average. Teams that hide their makers are mostly new to PH, so their real history is thin.
- The placeholder hit-rate gap (53 vs 66) stays even after resolution, so it is not about maker identity. Placeholder launches are a different population, e.g. company accounts.
- Live step 4 is not triggered.
- The maker-fix shadow and the ready patch stay as they are, since they are the same as (ii): +0.3 top 3, +0.9 top 5, scored forward.
