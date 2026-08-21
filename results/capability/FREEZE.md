# Capability backbone — UNFROZEN (cheap baseline retained)

**Date:** 2026-08-21 (updated)  
**Prior freeze:** 2026-08-20 on curated-10 (8/8 eligible) — **superseded** by full-100 evidence.

## Decision

| Role | Stack |
|---|---|
| **Cheap baseline** | `gemini-3.6-flash` @ Vertex `global` + Browser Use OSS |
| **Capability status** | **UNFROZEN** — do not treat curated-10 as sufficiency |
| **Do not** | Another 100-task sweep; human-calibration until Hard-20 moves |

Curated-10 was misleading. Full-100 raw eligible success was **25/73 ≈ 34%**. After auditing the 45 FAILURES ($0 model spend), **18/45** are site/harness — corrected eligible ≈ **25/52 ≈ 48%**. Still too weak for UserSim human-calibration (would mostly measure inability to operate sites).

## Access notes

| Resource | Status |
|---|---|
| `gemini-3.6-flash` | Works on Vertex **`location=global`** only |
| Browser Use OSS + `ChatGoogle(vertexai=True)` | Works |
| Browser Use Cloud | Not used |
| Cheaper models (2.5 Flash, 3 Flash preview) | Full-10 only; **worse** than 3.6 (3/10 and 4/10) |

## Baseline stack (unchanged harness)

```text
MODEL:        gemini-3.6-flash
LOCATION:     global
HARNESS:      browser-use OSS (NOT Browser Use Cloud)
LLM ADAPTER:  ChatGoogle(vertexai=True, project=..., credentials=ADC)
MAX_ACTIONS:  20  (try 40 on STEP_CAP Hard-20 subset)
VIEWPORT:     1280x800
```

## Evidence ladder

1. Curated-10 freeze candidate → 8/8 eligible (~$3.25)  
2. Full-100 live → 25 SUCCESS / 27 BLOCKED / 3 SITE_CHANGED / 45 FAILURE (~$41)  
3. Failure audit → `results/capability/FAILURE_AUDIT.md`  
4. **Hard-20** → `results/capability/hard20.json` — Flash **0/20** by construction  

## Next (capability, not UserSim yet) — UPDATED 2026-08-21

**Do not** escalate Browser Use → Pro/Sonnet as the default path.

1. **$0:** Exploit open ecosystem — SeeAct code, Online-Mind2Web tasks/WebJudge, HAL leaderboard traces  
   → see `results/capability/open_ecosystem/OPEN_ECOSYSTEM_ANALYSIS.md`  
2. Smallest test: SeeAct + 3.6 Flash (or ported two-stage/SoM grounding) on **2–3** multi-filter tasks  
3. Switch eval set to **Online-Mind2Web** (maintained; CAPTCHA/outdated tasks replaced)  
4. Resume UserSim human-calibration **only after** the borrowed capability layer works  

See also: `results/capability/failure_audit_45.json`, `hard20.json`
