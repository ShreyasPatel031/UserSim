# Mini-2 harness bakeoff — gemini-3.6-flash

Question: **does a different open harness beat plain Browser Use on the same model?**

Three real upstream agents, one model (`gemini-3.6-flash` on Vertex), the same two
tasks, the same judge (`gemini-2.5-flash` on final state).

## Harnesses

| Harness | Source | Observation | Vertex wiring |
|---------|--------|-------------|---------------|
| Browser Use OSS | `browser-use==0.13.8` | DOM + vision | `ChatGoogle(vertexai=True)` |
| SeeAct | upstream `OSU-NLP-Group/SeeAct` | SoM screenshot + text choices | litellm `vertex_ai/` |
| WebVoyager | upstream `MinorJerry/WebVoyager` | SoM screenshot | litellm proxy on OpenAI `/v1` |

Each runs in its own venv (`.venv`, `.venv-seeact`, `.venv-webvoyager`). SeeAct pins
`openai==1.24.0` / `litellm==1.35.32` and WebVoyager pins `openai==1.1.1`, all of which
conflict with browser-use — isolation is what makes the comparison possible at all.

## Tasks
Online-Mind2Web items passing ≥2 strong HAL agents *and* reachable from this cloud IP.

| task_id | site | task | HAL |
|---------|------|------|-----|
| `c698ff3fc0f6cbce39947c597ab5749b` | Eventbrite | Event planning tips page | 3/3 |
| `b320c68bffc1f3c7f2a8dc9d5478fb27` | IGN | Zelda BOTW walkthrough | 2/3 |

## Results

| Harness | Eventbrite | IGN | Score | Cost |
|---------|-----------|-----|-------|------|
| **Browser Use OSS** | SUCCESS (8 steps) | SUCCESS (8 steps) | **2/2** | $0.40 |
| SeeAct (upstream) | FAILURE (33 steps, step cap) | SUCCESS (12 steps) | 1/2 | $1.23 |
| WebVoyager (upstream) | FAILURE (11 steps, crash) | SUCCESS (21 steps) | 1/2 | $0.27 |

### What the failures were
- **SeeAct / Eventbrite:** reached the blog but burned the budget emitting `NONE`
  actions; hit `max_op=33` without landing on the planning-tips page. Also by far the
  most expensive — SoM prompts carry the full element list plus a screenshot every step.
- **WebVoyager / Eventbrite:** died at iteration 11 with
  `StaleElementReferenceException` out of `get_web_element_rect`. Upstream lets that
  escape the task loop, so the process aborts. Each task therefore runs in its own
  process here, or one crash would take out the whole run.
- Both alternatives solved IGN, and so did Browser Use — no task was solved *only* by
  an alternative harness.

## Verdict
On this set, **no harness beat Browser Use**. Browser Use was the only one to go 2/2,
did it in the fewest steps, and cost 3× less than SeeAct. The two published harnesses
each lost the same task, for different reasons — one to planning, one to a Selenium
crash on a 2026 live site (both predate it).

Caveat worth stating plainly: n=2. This rules out "an off-the-shelf harness swap is an
easy win"; it does not rank the harnesses. The signal is that the remaining failures
look like model/planning limits rather than scaffold limits, so scaffold-swapping is
not where the next gain is.

## Reproduce
```bash
src/capability/harnesses/setup_seeact.sh
src/capability/harnesses/setup_webvoyager.sh

# Browser Use
python src/capability/run_harness_bakeoff.py --max-actions 33

# SeeAct
.venv-seeact/bin/python src/capability/harnesses/run_seeact_mini2.py --max-ops 33
python src/capability/harnesses/judge_seeact_mini2.py

# WebVoyager (needs the litellm proxy on :4000)
.venv-proxy/bin/litellm --config src/capability/harnesses/litellm_vertex_proxy.yaml --port 4000
python src/capability/harnesses/run_webvoyager_mini2.py --max-iter 33
python src/capability/harnesses/judge_webvoyager_mini2.py
```

Earlier attempt on Apartments.com + Uniqlo is kept as
`mini2_harness_gemini-36-flash_attempt1_blocked.json`: HAL-valid tasks, but both sites
return Akamai Access Denied from this IP, so every harness scored BLOCKED.
