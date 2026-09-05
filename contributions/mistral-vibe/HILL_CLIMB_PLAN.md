# Hill-climbing plan — Mistral Small 4 on OM2W full10

**Goal:** find the browser-use configuration that maximizes Mistral task completion on the 10-task slice, then freeze it as the default for the Vibe adapter and for the full-300 run.

**Baseline (corrected after Stage 0):** `full10_mistral_mistral-small-2603_m33.json` — **4 SUCCESS, 5 FAILURE, 1 BLOCKED, 0 unscored**. `success_rate_scored = 44.4%` (4/9), cost $0.43, ~15–20 min per pass at `--workers 4`.

The pre-Stage-0 reading of this same run was "2 SUCCESS, 22%". That was a broken judge, not a weak model — see Stage 0. Mistral Small 4 starts *above* the Gemini 2.5 Flash reference point of 35.7% on the same harness.

**Rule for this whole plan:** full10 tells us *direction*, the 300-task run tells us *the number*. With 10 tasks one flipped task is ±10pp, so no single-seed comparison is evidence.

| idx | Site | Verdict | Steps |
|---|---|---|---:|
| 7 | JetBlue | SUCCESS | 13 |
| 25 | Under Armour | SUCCESS | 32 |
| 32 | IGN | SUCCESS | 32 |
| 33 | ESPN | SUCCESS | 26 |
| 8 | Newegg | FAILURE — premature stop | 6 |
| 12 | TicketCenter | FAILURE — premature stop | 16 |
| 22 | Megabus | FAILURE — premature stop | 30 |
| 26 | Rotten Tomatoes | FAILURE — premature stop | 18 |
| 34 | Eventbrite | FAILURE — premature stop | 17 |
| 19 | Uniqlo | BLOCKED (WAF) | 9 |

**All 5 remaining failures are `PREMATURE_STOP`.** There is exactly one failure mode left on this slice, which makes Stage 2 the whole game.

---

## Stage 0 — Fix the ruler ✅ done

We could not hill climb while 5/10 tasks had no verdict. Fixing the judge moved the measured baseline from 22% to **44.4%** without touching the agent — the single largest "improvement" in this plan was a measurement bug.

### 0.1 Judge auth is broken by design

`secrets/vertex_adc.json` does not exist, so `auth.py` falls back to `_from_gcloud()`, which returns a bare access token cached for 45 minutes:

```80:83:src/auth.py
    creds = _from_gcloud()
    _cached = creds
    _expires = now + timedelta(minutes=45)
    return _cached
```

A gcloud access token has no refresh handle. The full10 pass ran longer than the token's life, so every task judged after the token expired returned `401 UNAUTHENTICATED` → `judge_task` swallowed it into `AMBIGUOUS`:

```94:102:src/capability/judge.py
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "AMBIGUOUS",
            "reason": f"judge_error: {exc}"[:400],
```

**Fixed** by pointing `_adc_path()` at gcloud's per-account authorized-user JSON (`~/.config/gcloud/legacy_credentials/<account>/adc.json`), which carries a refresh token. That avoids copying a second credential into the repo. The no-refresh fallback now caches for 20 minutes instead of 45, and `invalidate_credentials()` lets a caller force a re-mint.

`judge_task` now retries once on an auth error with fresh credentials, and — the real bug — a judge that *could not run* returns `JUDGE_ERROR` instead of being silently folded into `AMBIGUOUS`. Unscoreable is not the same as undecidable.

### 0.2 Offline re-judge

`src/capability/rejudge.py` re-scores saved traces from `run.json` + `final.png` without touching a browser:

```bash
PYTHONPATH=src python -m capability.rejudge \
  --manifest results/capability/full10_mistral_mistral-small-2603_m33.json --dry-run
```

Recovered all 5 unscored tasks in 13 s for a few cents. Two of them were **SUCCESS**. This is now the standard tool for re-scoring history whenever the judge prompt or model changes, so old runs stay comparable to new ones.

### 0.3 Separate the metrics

`src/capability/metrics.py` is now the single source of scoreboard maths, shared by the bakeoff and the re-judge:

| Metric | Definition |
|---|---|
| `success_rate_eligible` | SUCCESS / (everything except env blocks) — pessimistic headline |
| `success_rate_scored` | SUCCESS / (SUCCESS + FAILURE) — the decision metric |
| `judge_error_rate` | unscoreable / n — must be 0 before any comparison counts |

`JUDGE_ERROR` is excluded from the eligible denominator alongside `BLOCKED` and `SITE_CHANGED`, so a broken judge can never again masquerade as model failure.

**Exit criteria met:** 10/10 tasks carry a real verdict, `judge_error_rate = 0`, baseline is 44.4% scored.

---

## Stage 1 — Free harness wins ✅ implemented

Inspecting the installed harness (`browser-use 0.13.8`) showed defaults actively costing tasks. Implemented in `src/capability/browser_use_harness.py` and wired through `mistral_browser_use_runner.py`.

| Knob | Was | Now |
|---|---|---|
| `use_judge` | `True` | **`False`** — external judge only |
| `page_extraction_llm` | agent LLM | **`ministral-8b-latest`** |
| `fallback_llm` | none | **`ministral-8b-latest`** |
| `allowed_domains` | none | **`*.registrable` + host** from start URL |
| `max_actions_per_step` | 3 | **2** |
| `max_history_items` | unlimited | **6** (stays under Mistral 8-image cap) |
| `llm_screenshot_size` | full | **960×600** |
| `max_retries` | 5 | **8** |

Disable with `BROWSER_USE_STAGE1=0`. Bakeoff manifests get `_stage1` suffix and a `harness_config` block.

**Smoke validation (Newegg idx=8):** 6 steps → **26 steps**, filters actually applied, Google escape **blocked by security policy**, **zero 429s** in trace. Still judged FAILURE (couldn't find combo under $100 on-page) — that's Stage 2 territory, not infra.

```bash
PYTHONPATH=src python -m capability.run_mistral_bakeoff \
  --stage full10 --model mistral-small-2603 --workers 3
# → results/capability/full10_mistral_mistral-small-2603_m33_stage1.json
```

**Exit criteria:** zero image-limit errors, 429-aborted steps under 5%, no off-site navigation — **met on smoke**. Run full10 for confirmation.

---

## Stage 2 — Attack PREMATURE_STOP (the whole game, ~3–4 days)

**All 5 remaining failures are `PREMATURE_STOP`.** After Stage 0 this slice has exactly one failure mode, which is a gift: there is no ambiguity about where to spend effort.

The agent reaches a plausible page and declares victory. Newegg is the cleanest example — **stopped at 6 steps** on a category page and claimed a $29.99 combo it never filtered for, where Gemini took 15 steps and succeeded.

The step counts say something important. Megabus stopped at 30, Rotten Tomatoes at 18, Eventbrite at 17 — these are not agents running out of budget, they are agents *choosing* to stop while wrong. Only Newegg (6 steps) is an obvious early bail. So a budget raise alone will not fix this; the `done` decision itself is the defect.

The harness gives us the hook to fix it properly — `register_done_callback` and `register_should_stop_callback` — so we can intercept `done` instead of only asking the prompt nicely.

| Lever | Implementation | Targets |
|---|---|---|
| **2.1 Verified `done`** | On `done`, check the final screenshot + constraints externally. If a constraint is unmet and budget remains, reject and resume with a corrective message. | All 5 |
| **2.2 Constraint checklist** | Parse the task into explicit constraints (price cap, colour, size, "follow", "add to cart") and inject them as a checklist the agent must restate. | Newegg, TicketCenter |
| **2.3 Budget raise m33 → m50** | IGN succeeded on step 32 of 33 and Under Armour on 32 — both successes sat right at the cap, so the budget is binding for the tasks that *do* work. | Long multi-filter tasks |

2.1 is the highest-value item in the plan and the thing that most separates a demo harness from a usable one. Note the ordering change from the first draft: because the failures cluster at high step counts rather than low ones, verified-`done` now leads and the budget raise is a supporting move.

**Exit criteria:** Newegg idx=8 succeeds on ≥2 of 3 seeds; `PREMATURE_STOP` drops below 3/10; `success_rate_scored` clears 55%.

---

## Stage 3 — Model and reasoning sweep (~2 days, only after Stages 1–2)

Do this last, deliberately. Swapping in a bigger model before the harness is clean just buys capability to paper over config bugs, and it inflates the cost baseline we quote for the Vibe contribution.

- **Models:** `mistral-small-2603` (baseline) vs `mistral-medium-2508` (documented as agentic) vs `pixtral-large-2411`
- **Modes:** `use_thinking` on/off, `flash_mode`, `enable_planning` on/off

Pick the Pareto point on success-per-dollar, not the top-line max. Small 4 winning after harness fixes is a much better story for an open-source CLI than Pixtral Large winning.

---

## Stage 4 — Freeze and hand off to the 300

Freeze the winning configuration as `WEB_AGENT_DEFAULTS` in one module. That frozen dict is simultaneously:

1. the config for the full-300 run, and
2. the default for the Vibe adapter — the adapter ships the config we actually measured, not guesses.

**Pre-flight for the 300:**

| Item | Note |
|---|---|
| Cost | $0.43 per 10 tasks → **~$13 for 300** at Small 4 pricing. Cost is not the constraint. |
| Time | ~15–20 min per 10 at `workers 4` → ~8–10 h serial. Shard it. |
| Concurrency | `workers 4` already produced CDP screenshot-watchdog timeouts. Cap at 3 and treat harness timeouts as a tracked category, not silent failures. |
| Judge robustness | Stage 0 fixed the expiring-token bug that cost us 5 of 10 verdicts; at 300 tasks the same bug would have cost ~150. Run a `rejudge` sweep at the end regardless and confirm `judge_error_rate = 0` before reading any result. |
| Blocked sites | Preflight already skips known WAF sites before spending tokens. Feed newly discovered blocks back into `KNOWN_BLOCKED_WEBSITES`. |
| Per-task deltas | Persist per-task verdicts so we can attribute the 300-task result back to specific levers instead of one aggregate number. |

**What the 300 gives us that the 10 cannot:** a failure taxonomy with enough samples per category to prioritize honestly. The current picture rests on 5 failures that all share one cause, which is why this plan treats full10 as a smoke test and refuses to over-tune on it. If the 300 shows `PREMATURE_STOP` is not dominant at scale, Stage 2 gets re-prioritized rather than defended.

---

## Guardrails against fooling ourselves

1. **3 seeds minimum** before accepting any lever. ESPN already flipped SUCCESS/FAILURE across identical configs, so single runs prove nothing.
2. **Accept a lever only if** it wins on ≥2 of 3 seeds *or* it fixes a specific named failure with a mechanism we can point at in the trace.
3. **One lever at a time**, then a stacked confirmation run.
4. **Never tune on BLOCKED tasks** — those are environment, and Browserbase is the fix, not prompting.
5. **Re-judge old runs** whenever the judge changes, so all numbers stay comparable.
6. Track **steps-to-success**, not just success. For Newegg-type tasks a *longer* trajectory is the improvement; a config that shortens trajectories is probably just stopping early again.

---

## Sequence

| Stage | Work | Status | Est. |
|---|---|---|---|
| **0** | Judge auth + rejudge + metric split | ✅ done — baseline 22% → **44.4%** | 0.5 d |
| **1** | Harness config (`browser_use_harness.py`) | ✅ done — smoke validated | 1 d |
| **2** | Verified `done`, constraint checklist, m50 budget | **next** | 3–4 d |
| **3** | Model + reasoning sweep | after 2 | 2 d |
| **4** | Freeze config, shard the 300, feed the Vibe adapter | after 1–2 | 1 d |

**Trajectory on full10 (`success_rate_scored`):** 44.4% measured baseline → Stage 1 removes infrastructure losses → Stage 2 targets the single remaining failure mode → Stage 3 decides whether more model is worth the money.

Mistral Small 4 already clears the Gemini 2.5 Flash reference point of 35.7% on the same harness, so the framing for the Vibe contribution changes: this is not "catch up to Gemini", it is "a small open model is already competitive once the harness stops throwing away its work." No target beyond that is quoted here — with 5 failures, any specific percentage would be invented rather than measured, and the 300-task run is what sets real targets.
