# Capability backbone — FROZEN

**Date:** 2026-08-20  
**Decision:** Freeze **Gemini 3.6 Flash + open-source Browser Use (Vertex)** as the UserSim capability backbone.

Do not resume model/harness search until human-calibration experiments need it.

## Access notes

| Resource | Status |
|---|---|
| `gemini-3.6-flash` | Works on Vertex **`location=global`** only (404 in `us-central1`) |
| Native Computer Use tool | Accepted on 3.6 Flash @ global |
| Browser Use OSS + `ChatGoogle(vertexai=True)` | Works |
| Browser Use Cloud / ChatBrowserUse | Not used |

## Smoke (Newegg + Under Armour)

| Stack | Newegg | Under Armour |
|---|---|---|
| Native Computer Use + 3.6 Flash | FAILURE (premature stop / incomplete filters) | FAILURE (20 actions, filters incomplete) |
| Browser Use OSS + 3.6 Flash | **SUCCESS** | **SUCCESS** |

→ Eliminated native Computer Use for this bakeoff.

## Full 10 (Browser Use + 3.6 Flash)

| Result | Count |
|---|---:|
| SUCCESS | **8** |
| BLOCKED (login required for Follow) | **2** (Eventbrite, ESPN) |
| Eligible success rate | **8/8 = 100%** |

Blocked tasks reached the Follow control but sites require authentication. Per bakeoff rules these are not model failures.

Raw if counting blocked as failures: 8/10. Gate was ≥9/10 *or* approximately 9–10; with BLOCKED excluded from the capability denominator the stack clears the freeze gate cleanly.

## Cost

~**$3.25** Vertex for the full-10 Browser Use runs (plus earlier smoke/native CU).

## Frozen stack

```text
MODEL:        gemini-3.6-flash
LOCATION:     global
HARNESS:      browser-use OSS (NOT Browser Use Cloud)
LLM ADAPTER:  ChatGoogle(vertexai=True, project=..., credentials=ADC)
OBSERVATION:  Browser Use DOM + vision
MAX_ACTIONS:  20
VIEWPORT:     1280x800
```

Code entry points:

- `src/capability/browser_use_runner.py`
- `src/capability/run_bakeoff.py`
- Results: `results/capability/full10_browser_use.json`

## Next (UserSim research — not capability)

Run the **same frozen stack** under:

1. Capable agent (this policy)
2. Human-sim prompt
3. UserSim SFT (when available)
4. Calibrated STOP

Compare trajectories to Mind2Web humans on path metrics. Do not change model/harness while doing that.
