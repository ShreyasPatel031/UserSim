# Mini-2 harness bakeoff (gemini-3.6-flash)

## Selection
Two Online-Mind2Web tasks that:
1. Pass on ≥2 strong HAL agents (SeeAct+GPT-5 / SeeAct+Gemini-2.0-Flash / Browser-Use+Gemini)
2. Load from this cloud IP (no Akamai wall on first paint)

| task_id | site | task | HAL |
|---------|------|------|-----|
| `c698ff3fc0f6cbce39947c597ab5749b` | Eventbrite | Event planning tips page | 3/3 |
| `b320c68bffc1f3c7f2a8dc9d5478fb27` | IGN | Zelda BOTW walkthrough | 2/3 (GPT-5, BU+Gemini) |

**Attempt 1 dropped:** Apartments.com + Uniqlo — HAL-valid but Akamai Access Denied here → all `BLOCKED` (`mini2_harness_gemini-36-flash_attempt1_blocked.json`).

## Results (attempt 2)
Model: `gemini-3.6-flash` · max_actions=33 · judge: gemini-2.5-flash

| Harness | Eventbrite | IGN | Score | Cost |
|---------|------------|-----|-------|------|
| **Browser Use OSS** | SUCCESS | SUCCESS | **2/2** | ~$0.40 |
| SeeAct-lite (Playwright two-stage) | SUCCESS | FAILURE (JSON/grounding) | 1/2 | ~$0.06 |

### Notes
- Browser Use completes both in ~8 steps with vision+DOM.
- SeeAct-lite reaches Eventbrite resources/planning; on IGN it loops menu/search clicks then truncates JSON (`bad_json`) → classified `HARNESS`.
- SeeAct-lite is cheaper but not competitive on the medium task with this lite grounding.

## Verdict
For 3.6 Flash on this validated Mini-2 set: **prefer Browser Use OSS** as the capability scaffold. Do not expand to Hard-20 / Pro until a harness choice is locked; human-calibration still waits.
