# PH throughput bake-off (4 × e2-standard-2, 1 browser each)

**Goal:** maximize **people/min** (and **req/min**) per VM with **minimal blocks** over a **4 h** window — not sweep `pdeep-tabs` metadata.

Literature ([Novada](https://www.novada.com/blog-ordinary/parallel-concurrent-processing-at-scale-5-production-patterns-that-actually-work/), [Crawlex AIMD](https://blog.crawlex.net/blog/rate-limiting-yourself/), [Proxora session budgets](https://proxora.io/blog/proxy-concurrency-rate-limit-playbook), [Shifter retry classes](https://shifter.io/blog/residential-proxy-retry-logic)) converges on:

1. **Two limiters:** in-flight work (tabs / semaphores) **and** request start rate (token bucket).
2. **AIMD:** slow climb while healthy; **×0.5–0.7** on 403/429; jitter on retries.
3. **One sticky session** per browser; **one active profile extract**; identity change **between** people, not per request.
4. **Circuit breaker** after repeated blocks (your `pace-state` cooldown).
5. **Measure** req/min, people/min, 403 rate — tune from feedback, not static metadata.

**Your ceiling:** ~**64** in-flight tabs possible; exploration often uses **32** as a high but sub-max setting inside strategies that adapt.

---

## Four strategies (policy, not metadata ramps)

Configs live in `scripts/vm/ph_strategies/*.env`, injected as metadata key **`ph-strategy-env`** at VM create. `pace_startup.sh` installs GCS overlays (`_code/overlays/`) so `supervisor_strat.sh` exports `PH_*` into `ph_batch.py` as `--tabs` / `--ramp` / `--person-interval`, and expands `portscreen` to sticky ports **10000–20000**.

| ID | Name | Idea | Primary levers |
|----|------|------|----------------|
| **A** | `serial_polite` | Longevity baseline | ≤4 tabs, ~36 req/min, heavy jitter, coast between profiles |
| **B** | `aimd_adaptive` | Max people/min adaptively | Start 4 tabs / 45 rpm → climb toward 64 tabs / 150 rpm while clean |
| **C** | `burst_coast` | Duty cycle | ~24 tabs × 90 s burst, 75 s coast @ 25 rpm (avoid sitting on cliff) |
| **D** | `req_budget` | Optimize req efficiency | ≤48 tabs, hard **140 rpm** cap, skip redundant cursor work |

Shared VM shape: **e2-standard-2**, **`k-levels=1,1`**, one Camoufox, own sticky port, warm profile dir.

**403 vs 429** ([KindProxy](https://www.kindproxy.com/blog/en/blog/puppeteer-proxy-rotation-sticky-sessions-retries/)): 429 → slow down same session; 403 → deep pause + circuit, do not rotate to “evade”.

---

## Metrics (4 h, sample every 15 min)

- **people/min** — completed profile JSONs / wall time  
- **req/min** — from supervisor or extract logs (if instrumented)  
- **uptime** — VM + `phsuper`  
- **403/challenge count** — leading indicator before hard death  

Winner: highest **mean people/min** with acceptable block rate (document if one arm trades blocks for speed).

---

## Run

```bash
export GCP_PROJECT=...
export PACE_ZONE=...
export MVP_GCS_BUCKET=...
export PACE_EXPERIMENT_RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)

./scripts/vm/ph_tab_strategy_experiment.sh up --use-template --fetch-proxy-from feeder-phpeople-1
./scripts/vm/ph_tab_strategy_experiment.sh monitor --loop
./scripts/vm/ph_tab_strategy_experiment.sh summary
./scripts/vm/ph_tab_strategy_experiment.sh down
```

**Wiring:** overlays map `PH_*` → `ph_batch` CLI; home sticky ports stay in-pool (no silent remap into 10002–10018). Monitor counts `/opt/ph/reuse/out/*.json`.
