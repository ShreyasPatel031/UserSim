# HOW scorecard (trace realism) v1

Do simulated users' traces behave like real people's? Thresholds are in `docs/NORTH_STAR_CALIBRATION.md`.

- **Sim:** 50 traces from 10 Product Hunt launches on Nov 21, from Atelier Sim plugin 0.4.0 (5 users each). The traces themselves are in the private store and are not committed.
- **Human:** AgentNet/OpenCUA ubuntu (first 1,500 trajectories, MIT) and VideoCUA (140 tasks from the 8 smallest apps, MIT, ms timestamps).
- **Run:** `python experiments/calibration/how_scorecard.py <sim_runs_dir> agentnet_ubuntu_5k.jsonl <videocua_extract_dir> out.json`

| Metric | v1 value (95% CI) | Target | Pass |
|---|---|---|---|
| Action-mix JS distance | 0.403 (0.369–0.444) | ≤ 0.10 | no |
| Step-timing KS | 0.756 (0.697–0.812) | ≤ 0.15 | no |
| Give-up gap (points) | −21.0 (−41.1 to −1.2), proxy | within 5 | no |
| Human-vs-sim classifier AUC | 0.965 (0.924–0.995) | ≤ 0.65 | no |

## Reading it

- **Action mix:** the domains differ, which inflates the distance. The human sets are desktop apps; our sim is web. The sim scrolls (11% vs 2%), waits (11% vs 1%) and types URLs (7% vs 0%) far more than the humans, and clicks less (50% vs 77%). Web-native human traces (Mind2Web raw dump for evaluation, OPeRA) should be added next.
- **Timing:** sim gaps are wall-clock model latency (median 7.0 s vs 2.4 s for humans). The fix is a per-step human pacing model (read, decide, move), calibrated on VideoCUA.
- **Give-up:** there is no natural human give-up data yet. The proxy is AgentNet's feasible tasks left uncompleted by paid annotators. OPeRA/OTTO give natural session-end rates.
- **Classifier:** per-trace features are step count, repeat rate and action-type shares. Each trace is one row, and no task is shared between the human and sim sets.

v1 is the baseline. Tuning targets, in order: human pacing per step, no URL guessing, scroll and wait rates matched to web humans, give-up thresholds.

## v2 (plugin 0.5.0), paired with v1 on the same 10 Nov 21 launches

Changes in v2:
- No URL guessing.
- A per-step `human_s` estimate of human time.

Human reference for both v1 and v2: AgentNet, VideoCUA, and OPeRA (527 real web shopper sessions, CC BY 4.0).

| Metric | v1 (wall-clock timing) | v2 (human_s) | Target |
|---|---|---|---|
| Action-mix JS | 0.408 (0.380–0.449) | 0.373 (0.348–0.404) | ≤ 0.10 |
| Step-timing KS | 0.440 (0.397–0.478) | 0.322 (0.286–0.371) | ≤ 0.15 |
| Give-up gap vs OPeRA (points) | −9.5 (−28.7 to +10.8) | −18.6 (−34.4 to −1.6) | within 5 |
| Classifier AUC | 0.963 (0.919–0.995) | 0.988 (0.982–0.994) | ≤ 0.65 |

What changed:
- **Better:** timing (median 7.0 s → 6.0 s; human median 4.6 s); URL typing down (7.4% → 4.0%); action mix closer.
- **Worse:** give-up. The sim leaves less often (21% vs 40% for humans). The classifier separates the sets more easily, because the wait share rose (11% → 14%).

n = 50 traces each. Target for the next report is ≥ 100.

Next (v3):
- scroll and wait rates matched to web humans;
- give-up thresholds;
- remaining `navigate` reserved for email links.
