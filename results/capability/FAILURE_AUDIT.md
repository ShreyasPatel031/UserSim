# Failure audit (45) + Hard-20 — capability unfrozen

**Date:** 2026-08-21  
**Source:** `full100_browser_use_gemini36flash.json` (saved traces/screenshots only — **$0 new model spend**)  
**Decision:** Keep **gemini-3.6-flash + Browser Use OSS** as the **cheap baseline**, but **unfreeze** capability. Do **not** run another 100-task sweep. Escalate on **Hard-20**.

## Why the curated-10 was misleading

| Set | Eligible success |
|---|---|
| Curated 10 | 8/8 (100%) after excluding 2 login BLOCKED |
| Full 100 (raw) | 25/73 (34%) |
| Full 100 after this audit | **25/52 (48%)** |

Raw 34% mixed model inability with WAF/CAPTCHA/outdated tasks. Human-calibration on that mix would mostly measure site walls.

## Audit of 45 FAILURES (one primary cause each)

| Primary cause | n | Next move |
|---|---:|---|
| **SITE_CHANGED/BLOCKED** | **16** | Remove from eligible denominator |
| **STEP_CAP** | **9** | Rerun with 40 steps |
| **PREMATURE_DONE** | **7** | Capability / policy |
| **GROUNDING** | **5** | Browser Use issue |
| **RECOVERY** | **5** | Planning / model |
| **HARNESS_ERROR** | **2** | Fix harness |
| **PLANNING** | **1** | Stronger model |
| PERCEPTION / JUDGE_ERROR | 0 | — |

**18/45 are not model failures** (16 site/blocked + 2 harness). Throwing Pro at those wastes money.

**27/45 are genuine model failures** → pool for Hard-20.

Artifacts: `results/capability/failure_audit_45.json`

### Notable reclassifications

- Login walls mislabeled FAILURE: ESPN Follow, Eventbrite Follow, Uniqlo wishlist, SoundCloud like/history, Ultimate Guitar playlist  
- Outdated live tasks: Megabus 2023, NYC comedy 2023, United Apr 2023, missing TicketCenter game  
- WAF/CAPTCHA: GameStop, MTA Access Denied  
- Harness: Parking.com “Update browser” + skeleton UI; RT load timeouts  
- RT Top Critics (idx 26): correct URL but blank review pane → site render, not Flash skill  

## Hard-20

Selected from **genuine** Flash failures only. **Flash baseline = 0/20 by construction** (no Flash rerun).

| Bucket | n | Examples |
|---|---:|---|
| Long multi-filter | 8 | Booking hostel, ExploreTock winery, Airbnb tiny/castles, JetBlue cruise, Amtrak, Instacart, UA filters |
| Final-action | 5 | UA/Uniqlo/Newegg/Megabus cart-basket; TicketCenter “all NFL” |
| Navigation/search | 4 | ExploreTock wrong city, Uniqlo baby<$10, TVGuide, Parking book |
| Recovery | 3 | Kohl’s→DDG/Bing, Uniqlo stores→DDG |

**14 websites.** Causes on Hard-20: STEP_CAP 8, RECOVERY 4, PREMATURE_DONE 4, GROUNDING 3, PLANNING 1.

Indices: `4,6,25,30,68,88,55,85,3,9,76,53,12,57,19,50,5,35,42,94`  
Artifact: `results/capability/hard20.json` · code: `HARD20_INDICES` in `src/capability/tasks.py`

## Capability stance (updated)

```text
BASELINE (cheap):  gemini-3.6-flash @ global + Browser Use OSS
                   max 20 actions, 1280×800
STATUS:            UNFROZEN — escalate on Hard-20, not another full-100
NEXT:              (1) optional 40-step rerun on STEP_CAP subset
                   (2) stronger Vertex model on Hard-20
                   (3) only then resume UserSim human-calibration
```

Do **not** start human-sim / SFT / STOP calibration until Hard-20 shows the stack can operate these sites.
