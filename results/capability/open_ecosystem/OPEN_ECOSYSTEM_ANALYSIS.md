# Open-ecosystem capability analysis ($0 inference)

**Date:** 2026-08-21  
**Decision:** Stop reinventing the capability layer. Do **not** escalate Browser Use → Pro/Sonnet next. Steal mechanisms from open scaffolds + HAL traces first.

## Assets used (all free)

| Asset | What we pulled |
|---|---|
| **SeeAct** | `vendor/SeeAct` — two-stage generate→ground, SoM, Gemini support, Playwright |
| **Online-Mind2Web** | `vendor/Online-Mind2Web` — 300 maintained tasks, WebJudge, CAPTCHA/outdated replacements |
| **HAL traces** | Decrypted SeeAct+GPT-5 ($171, **42.3%**), SeeAct+Gemini-2.0-Flash ($5, **26.7%**), Browser-Use+Gemini-2.0-Flash (~$9–18, **29%**) |

Leaderboard signal (HAL Online-Mind2Web):

| Scaffold | Model | Acc | Cost |
|---|---|---:|---:|
| **SeeAct** (Pareto) | GPT-5 Medium | **42.3%** | **$171** |
| Browser-Use | Claude Sonnet 4 | 40.0% | $1,577 |
| Browser-Use | Gemini 2.0 Flash | 29.0% | ~$9 |
| SeeAct (Pareto cheap) | Gemini 2.0 Flash | 26.7% | **$5** |

Same-ish accuracy, **~9× cost gap** between SeeAct+GPT-5 and Browser-Use+Sonnet — scaffold/stack, not “just buy a bigger model.”

## Product architecture correction

```text
Open SOTA web-agent scaffold (SeeAct / Browser Use / …)
        ↓
reliable perception + grounding + execution
        ↓
UserSim behavioral policy   ← THIS is the research novelty
        ↓
human-calibrated action distribution (which valid action, when STOP)
```

We do **not** need a custom “website interaction graph” as the central abstraction right now.

- **Capability / execution** → established browser-agent infrastructure  
- **UserSim** → which valid action a human chooses, when they stop, distribution over those choices  

Human-calibration experiments stay blocked until the capability layer is borrowed, not until we burn Pro tokens on the same Browser Use loop.

## Benchmark correction

Blindly replaying old Mind2Web live URLs was contaminated by WAF/CAPTCHA/outdated tasks (our 27 BLOCKED + audit reclasses).

**Use Online-Mind2Web’s maintained 300-task set** going forward. They explicitly replace CAPTCHA/invalid tasks (36 updated Nov 2025; more since). That removes most of the SITE_CHANGED/BLOCKED noise we audited by hand.

## Where successful agents differ (mechanisms)

From SeeAct code (`seeact_package/seeact/agent.py`, `data_utils/prompts.py`) + HAL successful traces:

| Dimension | Our Flash + Browser Use | SeeAct (successful traces) |
|---|---|---|
| **Observation** | DOM+vision via BU agent loop; weak “is constraint actually applied?” check | Explicit **screenshot status analysis** every step (“what has been set or completed”) |
| **Grounding** | Free-form tool calls / clicks; cart/form often don’t stick | **Two-stage**: (1) textual action gen (2) **ELEMENT letter** from enumerated Playwright choices + optional **SoM** boxes |
| **Planning** | Single-shot “do the task”; burns steps thrashing | Separate **Action Generation** that restates target before grounding |
| **Remaining constraints** | Often drops filters (price, size, property type) then claims done | WebJudge **key_points** checklist; generation prompt keeps multi-constraint goals salient |
| **Recovery** | Escapes to DuckDuckGo/Bing; hallucinates | Stays on **start website**; dismiss overlays (Decline Offer / Allow All) then retry; `max_continuous_no_op` stop |
| **Action primitives** | BU high-level tools; TYPE may need prior click | Playwright CLICK/TYPE/SELECT/**PRESS ENTER**; **TYPE bypasses initial click**; Enter after TYPE |
| **Success verification** | Agent self-`done` + our LLM judge | TERMINATE only when complete; OM2W **WebJudge** key-points + screenshots |

Mechanism frequencies on 80 SeeAct+GPT-5 successes (HAL): two-stage thought pairs **80/80**, screenshot status check **79/80**, element-letter grounding **80/80**, explicit filters **46/80**, PRESS ENTER after TYPE **37/80**.

## Case study: Uniqlo (exact site overlap)

**HAL SeeAct + GPT-5 SUCCESS** — *Show me Men’s Blazers, Black, Size M* (12 steps):

1. MEN tab → Outerwear → Blazers  
2. Close dialog  
3. Category → Color → **BLACK** → Size → **M**  
4. Confirm Results: 1 item  
Thoughts follow the SeeAct template: webpage ID → previous-action analysis → screenshot details → next target → ELEMENT letter.

**Our Flash + Browser Use FAILURES on Uniqlo:**

| idx | Cause | What went wrong vs SeeAct |
|---|---|---|
| 9 | GROUNDING | Claimed add-to-cart ×2; cart empty — no discrete element binding / no post-action screenshot verify |
| 19 | PREMATURE_DONE | Baby sale without under-$10 filter; said done — missing constraint checklist |
| 94 | RECOVERY | Left site for DuckDuckGo — SeeAct would stay on Uniqlo store locator |

Same website family: SeeAct+GPT-5 **1/1** Uniqlo success on HAL; our Flash failures are **mechanism gaps**, not “Uniqlo is impossible.”

Macys multi-filter success (SeeAct+GPT-5, 25 steps: evening bags → Color Blue → Price Under $50/$50–$100) shows the same pattern our Booking/UA/Airbnb STEP_CAP failures lack: **apply one constraint per step, verify in screenshot, don’t leave the site.**

## Mapping residual Flash causes → steal, don’t retrain

| Our cause | Smallest steal from open stack |
|---|---|
| **GROUNDING** | Port SeeAct-style element enumeration + letter/SoM grounding (or run SeeAct scaffold) |
| **PREMATURE_DONE** | Require key_points / constraint checklist before TERMINATE; screenshot verify |
| **STEP_CAP** | Two-stage planning + higher `max_auto_op` (SeeAct default 50); don’t expect raw step-budget alone (our m33 rerun ~3/27) |
| **RECOVERY** | Ban off-site search; overlay dismiss + retry; continuous-no-op halt |
| **PLANNING** | Explicit action-generation stage before grounding |

## What **not** to do next

1. ~~Browser Use + Pro / Sonnet~~ as the default next spend  
2. ~~Another full-100 on old Mind2Web URLs~~  
3. ~~Human-calibration / UserSim SFT~~ until capability scaffold is fixed  
4. ~~Custom interaction-graph as the spine~~

## Smallest paid test (only after ports / or 2–3 targeted tasks)

**Preferred $0–low path:**

1. Wire **Online-Mind2Web** task loader + WebJudge (or their key_points format)  
2. Either:
   - **A.** Run **SeeAct + gemini-3.6-flash** (Vertex) on **2–3** targeted tasks mirroring our Uniqlo/Macys-style multi-filter fails, **or**
   - **B.** Port SeeAct two-stage + SoM/element-choice into our runner and smoke those same 2–3 tasks  

Only if A/B show clear lift, expand. Do **not** start with a 20- or 100-task Pro sweep.

## Local artifacts

- Clones: `vendor/SeeAct`, `vendor/Online-Mind2Web` (gitignored)  
- HAL decrypts: `vendor/hal_traces/*.json` (gitignored; large)  
- This note: `results/capability/open_ecosystem/OPEN_ECOSYSTEM_ANALYSIS.md`
