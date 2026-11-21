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
