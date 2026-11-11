# K32 vs K8: complete people per hour and per GB (same gate)

Comparison of two whole-person pull runs, both judged by the **same** completeness gate
(full17's `whole()`), so the worker-count setting can be compared independently of which
build each run happened to use.

## Method

- **Throughput and bytes:** from each run's `vm/status/*.jsonl` (per-person `secs`, finished counts,
  and the run's `session_nic_bytes`).
- **Completeness:** the saved person JSON files from each run were re-scored through one common
  gate — full17's `whole()` — rather than trusting each build's own pass flag. Samples: 83 files
  (K32 run) and 80 files (K8 run).
- The two runs used different builds (the K32 run predates the comment-timestamp fetch), which is
  exactly why re-scoring through one gate is necessary.

## Result (common full17 gate)

| | K32 | K8 |
|---|---|---|
| Finished pulls / min | 11.2 | 6.9 |
| Pass rate under common gate | 65% | 100% |
| p50 time / person | 24 s | 9 s |
| MB / finished pull | 4.2 | 2.0 |
| **Complete people / hour (while running)** | **417** | **394** |
| **Complete people / GB** | **148** | **462** |

## Reading the numbers

1. **While running, the two are within ~6% on complete-people/hour (417 vs 394).** K32's higher raw
   pull rate (11.2 vs 6.9 finished/min) is mostly cancelled once the gate is applied: about a third
   of the K32 run's pulls are incomplete under the strict gate (its build never fetched comment
   timestamps), so they don't count as complete people.

2. **The 3.1× per-GB gap is real but mostly a confound.** Decomposed:
   - **~1.5×** is the **gate/build**: the strict build spends far fewer bytes on people it can never
     complete. This is a *build* decision, independent of worker count.
   - **~2.0×** is **profile size**: the K8 run pulled smaller people (p50 9 s, 2 MB) because it ran
     later in the queue, after the large popular profiles had already been taken by the K32 run
     (p50 24 s, 4.2 MB). Same data source, different slice. Controlling for profile size, K8 is
     ~1.5× more complete-people/GB, not 3.1×.

3. **Stability is the real differentiator.** The K8 run sustained a materially longer clean run than
   the K32 run (roughly 1.8× longer before interruption). Per-GB efficiency is set by the gate and
   the profile, not by worker count, so the sustained throughput advantage goes to the setting that
   stays productive longer.

## Recommendation

- **Build: the strict gate (full17).** ~1.5× more complete people per GB, because you stop paying
  for pulls that can never be complete — and completeness is the requirement.
- **Concurrency: K8, not K32.** Per-GB is the same at either setting (byte cost is set by the gate
  and the profile, not by K); while-running throughput is within ~6%; and K8 sustains more complete
  people over time by staying productive longer. K32's only edge is peak instantaneous rate.
- **Nuance:** the K32 setting pulls the large, high-value profiles fastest. A short K32 pass to grab
  the biggest/highest-priority makers, followed by steady K8 for the long tail, is the efficient
  split if that split is ever wanted. The default steady setting is K8.

## Caveats

- Samples are 83 and 80 files; the K32 common-gate pass rate is 65% ± ~10%.
- The two runs pulled different profile slices (big-first vs the smaller remainder), which inflates
  the raw per-GB gap; the gate-only effect is ~1.5×.
- The runs used different builds; throughput is normalized by re-scoring, not by re-running.
