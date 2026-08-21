# Mini-2 probe (gemini-3.6-flash + Browser Use OSS)

## Selection
Two Online-Mind2Web tasks that:
1. Pass on ≥2 strong HAL agents (SeeAct+GPT-5 / SeeAct+Gemini-2.0-Flash / Browser-Use+Gemini)
2. Load from this cloud IP (no Akamai wall on first paint)

| task_id | site | task | HAL |
|---------|------|------|-----|
| `c698ff3fc0f6cbce39947c597ab5749b` | Eventbrite | Event planning tips page | 3/3 |
| `b320c68bffc1f3c7f2a8dc9d5478fb27` | IGN | Zelda BOTW walkthrough | 2/3 (GPT-5, BU+Gemini) |

**Attempt 1 dropped:** Apartments.com + Uniqlo — HAL-valid but Akamai Access Denied here → all `BLOCKED`.

## Result that counts
| Harness | Eventbrite | IGN | Score | Cost |
|---------|------------|-----|-------|------|
| **Browser Use OSS** | SUCCESS | SUCCESS | **2/2** | ~$0.40 |

## Dead end (do not revive)
A homemade “SeeAct-lite” Playwright two-stage adapter was written for a fake harness bakeoff. That is **not** SeeAct and is not a useful comparison — removed from the runner. Historical JSON still has those rows; ignore them.

## Stance
Lock **Browser Use OSS + gemini-3.6-flash** as the cheap capability scaffold on Mini-2. No more fake SeeAct. No Hard-20 / Pro expansion until the next real question is specified.
