# UserSim Core — VM Handoff & 4-Phase Project Plan (`2026-11-26`)

> **Purpose:** Self-contained technical handoff and execution roadmap so work continues 24/7 on a GCE VM (`usersim-exp-2` `e2-highmem-16` for 93K population & ranker hill-climb; `gemma-persona-probe` `g2-standard-4` `L4 GPU` for unified Qwen-VL JIT CUA + Preference distillation) with zero laptop dependency and zero re-computation.

---

## 1. Quick-Start on GCE VM (2 Minutes)

### Step A — Start & SSH into the Compute VM
We have two idle VMs already provisioned in `project-amer-scs-sandbox` (do **not** stop any currently running VMs):
1. **Primary Hill-Climb + Live Daemon VM (`16 vCPU, 128 GB RAM`):** `usersim-exp-2` (`us-central1-b`, `e2-highmem-16`)
2. **GPU Distillation VM (`NVIDIA L4 24GB VRAM`):** `gemma-persona-probe` (`us-central1-c`, `g2-standard-4`) — start when running Phase 4 model fine-tuning.

From any terminal (or Cloud Shell):
```bash
# 1. Start the 16-vCPU / 128GB RAM VM
gcloud compute instances start usersim-exp-2 \
  --project=project-amer-scs-sandbox --zone=us-central1-b

# 2. SSH into the VM
gcloud compute ssh usersim-exp-2 \
  --project=project-amer-scs-sandbox --zone=us-central1-b --tunnel-through-iap
```

### Step B — Run the 1-Command State Restore on the VM
Inside `usersim-exp-2`:
```bash
# Clone repo if not already present on the VM, checkout usersim-core-v1, and restore all 570MB of data/caches/CUA traces:
if [ ! -d "$HOME/UserSim/.git" ]; then
  git clone https://github.com/$(git config --get remote.origin.url 2>/dev/null || echo "atelier-sim/UserSim") "$HOME/UserSim" || true
fi
cd "$HOME/UserSim"
git fetch origin && git checkout usersim-core-v1 && git pull origin usersim-core-v1
bash usersim_core/vm_bootstrap_handoff.sh "$HOME/UserSim" /var/tmp/usersim_core_work
```
*(Note: If GitHub auth isn't configured on the VM, copy the local repo directly once from Mac: `tar -czf - -C /Users/shreyaspatel/.gemini/antigravity/scratch/UserSim --exclude='.venv' . | gcloud compute ssh usersim-exp-2 --project=project-amer-scs-sandbox --zone=us-central1-b --tunnel-through-iap --command="mkdir -p ~/UserSim && tar -xzf - -C ~/UserSim"` and then run `bash ~/UserSim/usersim_core/vm_bootstrap_handoff.sh ~/UserSim /var/tmp/usersim_core_work`.)*

### Step C — Copy-Paste Kickoff Prompt for the VM Agent
Once inside `~/UserSim` on `usersim-exp-2`, start your coding agent (`agy`, `claude`, or `codex`) and paste:

```text
Read AGENTS.md and docs/VM_HANDOFF_AND_PLAN_20261126.md first.
All local data, LLM caches ($0 re-spend), 350 Google-SSO Camoufox surfaces (HC3), 220 4-step interactive post-login CUA traces + screenshots (HC4), 93,618-person bench/follows tables, and Qwen-7B per-person P(yes) parquets (backer_pred + stack_coef.json) are restored in /var/tmp/usersim_core_work.
Execute Phase 1 (USERSIM-CORE-HILLCLIMB-5: Explicit Named Competitors + Full 93,618-Person Choice/Switching + STACK-1b Fusion + Unfrozen Joint Ranker), Phase 2 (Privacy-Safe Per-Launch Interpretability Cards matching results/web/why/ schema with min_group >= 20), and Phase 3 (systemd timer for live_intraday_updater.py dispatching to signed-in Pool B fleet VMs 32, 40, 42, 44, 45). Keep Product-only (mid, zero comments) and Product+comments (pre, <=03:45 PT order-free) strictly separate, pre-register in docs/ledger/experiments.jsonl, and validate all leak/isolation assertions.
```

---

## 2. Exact Current State Snapshot (`2026-11-26T14:55 PT`)

### Git & GCS Artifacts
- **Active Branch:** `origin/usersim-core-v1` (clean ledger: `331` validated rows, `0` errors/warnings via `python -m simharness.ledger validate`).
- **Complete Handoff Bundle in GCS:** `gs://usersim-trace-store-347838016394/vm_handoff_20261126/usersim_core_scratch_bundle.tar.gz`
  - Contains:
    - `data/{bench,sites,apify_v1,taxonomy,hn,struct_bt,daily_0005,e5_pop}`
    - `flywheel_v1/{stage_b_features.parquet,cache_surfaces,cache_cohort_sim_v2,cache_cohort_sim_v3_po,cache_mm_cua4,cache_finalist_v4_po}` (all Vertex Gemini 2.5 Pro + GPT-OSS-120B caches — `$0.00` to replay!)
    - `fleet_hc3/hillclimb3_slot*.jsonl` (`350` 1-step Google-SSO Camoufox surfaces)
    - `fleet_hc4/hillclimb4_*_slot*.jsonl` (`220` 4-step interactive post-login SaaS traces + base64 screenshots)
    - `live_23d/{forecasts,post0005,page_daily,nov25}` + `live_check/2026-11-25/usersim_core_frozen_2026-11-25.json`
    - `usersim_core_hillclimb_{2,3,4}_results.json`

### Live Infrastructure Already Running
1. **5 Signed-In Google-SSO Camoufox Fleet VMs (`Pool B`, pinned across 15m rotations):**
   - `feeder-fleet-20261108t082000z-32` (`us-central1-a`) — signed-in Google profile `/var/lib/usersim/camoufox_profile`, `usersim-poolb.service` active
   - `feeder-fleet-20261108t082000z-40` (`us-central1-a`) — signed-in Google profile, `usersim-poolb.service` active
   - `feeder-fleet-20261108t082000z-42` (`us-central1-a`) — signed-in Google profile, `usersim-poolb.service` active
   - `feeder-fleet-20261108t082000z-44` (`us-central1-a`) — signed-in Google profile, `usersim-poolb.service` active
   - `feeder-fleet-20261108t082000z-45` (`us-central1-a`) — signed-in Google profile, `usersim-poolb.service` active
   - Queue path: `gs://usersim-bakeoff-347838016394/usersim_sim/raw/fleet_external/_jobs/`
2. **Website (`atelier-sim.com`) Dual-Track Leaderboard (`main` via PRs #229 & #230):**
   - Settled `Product only` headline fixed (`69.6%` settled days; unfinished today excluded).
   - `Product + comments` wired as default tab reading `gs://usersim-bakeoff-347838016394/usersim_sim/results/web/forecast_pre/<day>.json` (strictly live pre-`03:50 PT` forecasts ONLY; historical replays live in `results/web/forecast_pre_replay/`).
3. **`fleet-cursor` Pool A Throughput Fix Published:**
   - Staged at `gs://usersim-bakeoff-347838016394/usersim_sim/mailbox/to_cursor/20261126_FLEET_FIX_DEAD_SUPERVISORS_AND_RAMP.md` (`msg 23493903189075915`): restart dead supervisors on slots `5, 9, 27, 30, 31, 33, 35, 38, 43`, stop `phsuper` on Pool B slots `42, 44, 45`, apply `--ramp 1:8,2:14` + `60m` `.purl` quarantine.

### Score Progression Through `Hill-Climb v4` (Strict Zero-Leakage)

| Track & Evaluation Window | Published Site (`00:05`) | `Hill-Climb v3` (`293d57d33`) | `Hill-Climb v4` (`59b5eaaf2`) |
|---|---|---|---|
| **Track 1: `Product only` (`mid`, ZERO comments)** — 23d Live (`Oct 29–Nov 25`) | `49.3%` Top-3 / `61.7%` Top-5 / `69.6%` Top-10 | `58.0%` Top-3 / `67.8%` Top-5 / `71.7%` Top-10 | **`59.4%` Top-3 / `68.7%` Top-5 / `72.2%` Top-10** (`166/230`) |
| **Track 1: `Product only`** — 24d Nov Full Calibration | `59.7%` Top-3 / `69.2%` Top-5 / `71.2%` Top-10 | `61.1%` Top-3 (`+1.25` lift) | **`62.5%` Top-3 / `69.2%` Top-5 / `70.8%` Top-10** (`+1.62` lift, **`66.3%` Ties**) |
| **Track 1: `Product only`** — 55d Locked Test (`Oct–Nov`) | `60.6%` Top-3 / `68.0%` Top-5 / `72.0%` Top-10 | `61.8%` Top-3 (`+0.81` lift) | **`61.8%` Top-3 / `68.0%` Top-5 / `72.6%` Top-10** (`+0.87` lift, **`64.0%` Ties**) |
| **Track 2: `Product + comments` (`pre`, `<= 03:45 PT` order-free)** — 23d Live | *(new default tab)* | **`68.1%` Top-3 (`47/69`) / `73.9%` Top-5 / `72.2%` Top-10** | `66.7%` Top-3 / `73.9%` Top-5 / `72.6%` Top-10 |
| **Track 2: `Product + comments`** — 24d Nov / 55d Locked Test | `59.7%` / `60.6%` Top-3 | **`69.4%` Nov Top-3 (`+5.19` lift)** / **`64.9%` 55d Top-3 (`+2.85` lift)** | `68.1%` Nov Top-3 (`+4.86` lift) / `64.2%` 55d Top-3 (`+2.65` lift) |

### Why `v1–v4` Plateaued at ~`72–73.5%` Top-10 (And What Unlocks the Next Step)
1. **Physical Pre-Reveal Ceiling:** Even Product Hunt's own hidden live vote counts at `03:45 PT` only reach `86.7%` Top-10 (`80.0%` Top-5) because ~`13–15%` of winners mobilize external audiences after `04:00 PT`.
2. **Forensic Breakdown of Our `61/230` Misses:** `34/61` (`56%`) were razor-thin `#11..#15` predictions (`Product Hunt MCP` `#12 -> #1`, `Notch Metrics` `#11 -> #4`, `Orphex MCP` `#11 -> #6`, `Adobe AI Assistant` `#15 -> #6`).
3. **Three Concrete Gaps in `v1–v4`:**
   - **Named Competitors Were Not Explicitly Modeled:** `v3/v4` only injected generic G2 category notes — it never matched launch $x$ against its **5 specific named competitors** (`Granola`, `Composio`, `Lyzr`, etc.) or compared launch $x$'s hands-on CUA execution against those exact competitors' user complaints and popularity.
   - **The `93,618` User Population Was Compressed to 4 Global Averages:** `UniversalUserPool.item_pool_features` collapsed all `93,618` users into 4 summary scalars without modeling **who backs the team/hunter**, **who previously upvoted the named competitors (`switcher pool`)**, **same-day voter cannibalization across day $D$'s launches**, or **E5's fine-tuned Qwen-7B per-person `P(yes)` (`STACK-1b`)**.
   - **`arm3` Was Frozen With a Hard `±0.21` Clamp:** Cold-start official brand launches (`Product Hunt MCP`, `Adobe`, `Anthropic`, `Google`) with modest hunter/maker PH history could never jump from `#12..#15` into Top-5.

---

## 3. Detailed 4-Phase Execution Plan on the VM

### Phase 1: `USERSIM-CORE-HILLCLIMB-5` — Named Competitors + 93K Voter Choice + Unfrozen Joint Ranker
**Target VM:** `usersim-exp-2` (`e2-highmem-16`, `$0` API spend)
**Files to create:** `usersim_core/population_competitors_v5.py`, `usersim_core/hillclimb_v5.py`

1. **Pre-register `USERSIM-CORE-HILLCLIMB-5`** in `docs/ledger/experiments.jsonl` before touching Oct–Nov test metrics (`python -m simharness.ledger validate`).
2. **Module 1A — Strictly Causal (`< D`) Named Competitor Graph (`CompetitorGraph`):**
   - **Leak Guard (`CATEGORY1_README.md`):** Do **not** use `similar_products` read on Nov 1 for pre-Nov-1 historical backtest rows where future products could leak! Instead:
     - Use `launch_categories.parquet` `embedding_top3` / `embedding_0005_pre_april` (100% knowable at `00:05 PT`) + `< D` launches in `bench.items` (`7,461` launches with exact `day < D`) + `g2_products_and_reviews_raw.jsonl` (reviews filtered `< D`) + `competitor_feedback_slot*.jsonl`.
     - For forward/Nov launches (`day >= 2026-11-02`), `taxonomy/competitors.parquet` (`fetched_at <= 2026-11-01T21Z`) is strictly `< D` and 100% causal!
   - For each launch $x$ on day $D$, retrieve **Top-5 Named Competitors $C_1..C_5$** and compute:
     - `comp_market_demand_z`: `< D` historical vote/review volume of $C_1..C_5$ (separates high-demand builder markets like MCP/Coding Agents from dead niches).
     - `comp_cua_advantage_z`: Launch $x$'s 4-step CUA quality (`hands_on_works`, `ui_craft_depth`, `has_free_tier`, `has_open_source`, `-hit_paywall`) minus the incumbent baseline & G2 complaint profile (e.g., if G2 complaints on $C_1..C_3$ cite pricing/lock-in and launch $x$ is open-source or verified free workspace, boost!).
     - `sameday_direct_rival_cannibalization_z`: Max semantic similarity among **stronger or equal same-day launches** on day $D$, plus relative rank within same-day category cluster.
3. **Module 1B — Full `93,618`-Person Discrete-Choice Voter & Switcher Simulator (`PopulationChoiceSim` + `STACK-1b`):**
   - Build sparse `< D` incidence matrices across all `93,618` people (`bench/people.parquet`, `bench/history.parquet`, `data/follows/*.parquet`):
     - **Past Team/Maker/Hunter Backers (`< D`):** Exact held users who previously upvoted/commented on prior launches by launch $x$'s makers or hunter, weighted by `rw30` recency.
     - **Named-Competitor Switchers (`< D`):** Exact held users who previously upvoted or critiqued launch $x$'s Top-5 named competitors $C_1..C_5$, modulated by `comp_cua_advantage`!
     - **Category Power Voters (`10–99` and `100+` 90d tiers):** Active builders whose `< D` SVD taste vector aligns with launch $x$, modulated by `mm_hands_on_works` & `v3po_net_conviction`.
     - **Fine-Tuned Qwen-7B Per-Person `P(yes)` (`STACK-1b` Fusion):** Load `/var/tmp/usersim_core_work/data/e5_pop/backer_pred/<day>.parquet` + `stack_coef.json` (`logit = -6.6634 + 0.3962*z(ln_rw) - 0.0442*z(tm) + 0.0386*z(ln_rw_x_tm) + 1.2958*z(logit_pyes)`).
   - **Same-Day Discrete-Choice Competition:** For each active person $u$ on day $D$, apply temperature-calibrated multinomial/top-$k$ choice across all launches on day $D$ (`P_day(u votes x | lineup D)`) so launches fighting for the exact same niche audience split that voter pool realistically rather than double-counting!
4. **Module 1C — Unfreeze `arm3` with Walk-Forward Joint Ranker + Cold-Start Brand Authority:**
   - Extract raw structural features from `data/struct_bt/<day>.json` & `live_23d/forecasts/<day>.json` + Cold-Start Brand/Domain Authority (`official tech domains`, `LinkedIn employeeCount/followers`, `pre-launch X author followers`, `GitHub OSS`).
   - Fit walk-forward (`< month M`, hyperparameters locked strictly on `Val Sep <= 2026-09-30`) **Joint LightGBM `lambdarank` + Pairwise Logistic Ranker** with uncapped / wide authority promotion so `#11..#15` breakouts can reach Top-3/Top-5.
   - Maintain **100% strict separation** and run automated assertions:
     - `Product only v5`: `product_only_comment_isolation_max_abs_diff == 0.0`
     - `Product + comments v5`: `input_order_permutation_max_abs_diff < 1e-9`

---

### Phase 2: Website Interpretability Cards (`results/web/why/` Schema + Competitor & Voter Breakdown)
**Target VM:** `usersim-exp-2`
**Files to create:** `usersim_core/why_cards_v5.py`

Generate per-launch structured explainability JSONs (`/var/tmp/usersim_core_work/why_v5/<day>_mid.json` and `<day>_pre.json`, staged to `gs://usersim-trace-store-347838016394/usersim_core_v5/why/` for `orchestrator` / website agent integration) that strictly enforce **`min_group = 20` (`WHY_MIN_GROUP = 20` — zero person handles or IDs ever emitted!)**:
1. **`named_competitors`:** Top-3 named competitors (`name`, `slug`, `shared_categories`, `reviews_count`, `key_user_pain_point` from G2/HN, and `hands_on_comparison` from our 4-step CUA session).
2. **`voter_population_breakdown` (`held_people = 93,618`, all reported segments `n >= 20`):**
   - `team_and_hunter_backers`: count & expected votes from prior backers (`< D`),
   - `competitor_voters_and_switchers`: count of held users who voted on named competitors $C_1..C_5$ (`< D`) and their expected vote share for launch $x$,
   - `activity_tier_mix`: share across `1-9`, `10-99`, `100+` 90-day upvoters,
   - `sameday_head_to_head_split`: which same-day rival competes for the same voter cohort (`overlap_pct`) and which launch wins each segment (`e.g., Power Builders 10-99 prefer X 62% vs Y 38% due to working post-SSO workspace`).
3. **`cua_execution_proof`:** Sanitized 4-step browser trace summary (`sso_entered`, `workflow_action`, `workflow_responded`, `hands_on_works`, `exec_digest`).

---

### Phase 3: 24/7 Live Intraday Daemon on `usersim-exp-2` (`systemd`)
**Target VM:** `usersim-exp-2`
**Files to update/install:** `usersim_core/fleet/live_intraday_updater.py`, `/etc/systemd/system/usersim-live-pre.{service,timer}`

1. Wire `population_competitors_v5` + `hillclimb_v5` + `why_cards_v5` into `usersim_core/fleet/live_intraday_updater.py`.
2. Install a `systemd` timer on `usersim-exp-2` firing at **`00:12`, `01:10`, `02:20`, and `03:35 PT`** every day:
   - Discovers post-`00:05 PT` launches (`sanitize_post_0005_record` stripping all ranks/votes/order),
   - Dispatches un-inspected URLs to the 5 signed-in Pool B Camoufox VMs (`slots 32, 40, 42, 44, 45`) for 4-step post-login Google-SSO testing,
   - Computes both **`Product only` (`mid`)** and **`Product + comments` (`pre`, `<= 03:45 PT` order-free)** forecasts + per-launch `why` cards,
   - Writes live `gs://usersim-bakeoff-347838016394/usersim_sim/results/web/forecast_pre/<day>.json` **strictly before `03:50 PT`** so `atelier-sim.com`'s default `Product + comments` leaderboard updates automatically every day!

---

### Phase 4: Unified Single-Model Distillation (`Qwen2.5-VL-7B` JIT CUA + Per-Person Preference)
**Target VM:** `gemma-persona-probe` (`us-central1-c`, `g2-standard-4`, `NVIDIA L4 24GB GPU`)

Shreyas's north-star architecture: **replace the multi-stage pipeline with ONE fine-tuned multimodal model that consumes just-in-time product evidence + named competitors + a user's `< D` history, and replicates both interactive CUA judgment and per-person vote/comment reaction.**

1. **Base Checkpoint & Existing Adapter Reference:**
   - Existing text LoRA reference: `gs://usersim-bakeoff-347838016394/usersim_sim/simharness/choice_ft1/runs/choice-ft1-b/adapters/ckpt_final_500000` (`Qwen-7B` trained on `309,399` person-launch rows).
   - Unified multimodal backbone: **`Qwen/Qwen2.5-VL-7B-Instruct`** (fits cleanly in 24GB L4 VRAM with `bf16` + QLoRA/LoRA `r=32`, FlashAttention-2).
2. **Joint Multi-Task Training Corpus (100% Strictly `< D` Split: Train `Apr–Aug`, Val `Sep`, Test `Oct–Nov`):**
   - **Head / Task 1 — JIT Browser Action & Reality Judge (`CUA_TRACE` trajectories):**
     - Input: `(product_pitch, named_competitors_top3, step_t_screenshot, sanitized_dom_tree)`
     - Target: `(next_cua_action_json, hands_on_works, ui_craft_depth, friction_finding)` distilled from `fleet_hc3` (`350` sessions) + `fleet_hc4` (`220` 4-step sessions) + nightly Pool B sessions.
   - **Head / Task 2 — Grounded Per-Person Preference & Critique (`PERSON_CHOICE` + `PERSON_REACTION`):**
     - Input: `(person_<D_compact_history, named_competitors_and_pains, jit_cua_finding_summary, same_day_lineup_context)`
     - Target: calibrated `<YES>/<NO>` token log-odds (`P(upvote | person u, launch x, lineup D)`) + conditional real user comment/complaint (`CEILING-2` / `COMPLAINT-1` split-half benchmark).
3. **Inference Loop at `00:05–03:35 PT` (Single Unified Model):**
   - Step 1: Model drives Pool B Camoufox (`<= 4` JIT clicks/inputs) on each new launch and emits structured `jit_product_state` KV summary.
   - Step 2: Batched vLLM prefix-cached inference shares the launch + competitor + screenshot KV prefix across `N = 2,000` stratified active held users per day (<25 seconds on 1 L4 GPU!), producing exact per-person `P(yes)`, segment choice shares, realistic complaints, and final leaderboard ranking from **one model**.

---

## 4. Non-Negotiable Guardrails Checklist (`AGENTS.md`)
- [ ] **Zero Rank/Vote/Order Leakage:** Strip `dailyRank`, `votesCount`, `latestScore`, and array order everywhere. Assert `input_order_permutation_max_abs_diff < 1e-9`.
- [ ] **Strict Track Isolation:** `Product only` (`mid`) never touches comments (`product_only_comment_isolation_max_abs_diff == 0.0`). `Product + comments` (`pre`) uses strictly `ts <= 03:45 PT` scrubbed comments.
- [ ] **Forecast Pre Path Hygiene:** Never write historical replays to `results/web/forecast_pre/` (only live pre-`03:50 PT` runs!). Replays go to `results/web/forecast_pre_replay/`.
- [ ] **Privacy & Minimum Group Size:** Never expose person IDs, handles, or credentials; enforce `min_group >= 20` on all `why` / interpretability segment outputs.
- [ ] **Fleet Safety:** Never stop/delete running GCE VMs; never access `producthunt.com` from Pool B signed-in Google profiles (`32, 40, 42, 44, 45`); `$0` Apify spend without explicit user approval.
