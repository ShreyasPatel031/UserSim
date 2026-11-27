# UserSim Core — Handoff & Next-Dataset Plan (`2026-11-27`)

> **Purpose:** Complete technical handoff at the end of the `usersim_core v5 -> v9` Product Hunt + Cross-Domain sprint (`branch: usersim-core-v1`, `HEAD` pushed to `origin/usersim-core-v1`). All heavy compute VMs (`usersim-exp-2`, `gemma-persona-probe`) are `TERMINATED` and all caches, results, `why_v9` cards, and repo snapshots are backed up in `gs://usersim-trace-store-347838016394/usersim_core_v9/`.

---

## 1. Current State & Verified Results (`DEC-CORE-V9`)

### A. Product Hunt (`USERSIM-CORE-HILLCLIMB-5..9`)
All `usersim_core` models preserve the frozen `arm3` structural baseline (zero `arm2` mixing per `AGENTS.md`), lock every hyperparameter strictly on `Val Sep <= 2026-09-30`, and pass `input_order_permutation_max_abs_diff == 0.0` and `product_only_comment_isolation_max_abs_diff == 0.0`.

#### 23-Day Live Website Window (`Oct 29 – Nov 25`, `230` Top-10 slots)
| Track / Model | Top-3 | Top-5 | Top-10 | Mean (3/5/10) |
|---|---:|---:|---:|---:|
| Published Website (`00:05`) | `49.30%` (`34/69`) | `61.70%` (`71/115`) | `69.60%` (`160/230`) | `60.20%` |
| Frozen `arm3` (`00:05` strict) | `56.52%` (`39/69`) | `68.70%` (`79/115`) | `70.00%` (`161/230`) | `65.07%` |
| **Track 1: `Product only v6` (zero comments)** | `56.52%` (`39/69`) | `68.70%` (`79/115`) | **`73.04%`** (`168/230`) | `66.09%` |
| **Track 1: `Product only v9` (zero comments)** | **`59.42%`** (`41/69`) | **`68.70%`** (`79/115`) | `72.61%` (`167/230`) | **`66.91%`** |
| **Track 2: `Product + comments v7` (`<=03:45 PT`)** | `68.12%` (`47/69`) | **`77.39%`** (`89/115`) | `72.17%` (`166/230`) | `72.56%` |
| **Track 2: `Product + comments v9` (`<=03:45 PT`)** | **`71.01%`** (`49/69`) | `76.52%` (`88/115`) | **`73.48%`** (`169/230`) | **`73.67%`** |

#### 24-Day November Full Calibration (`Nov 1 – Nov 24`, `412` Reach-Matched Pairs)
| Track / Model | Top-3 | Top-5 | Top-10 | Mean | Paired Lift (95% CI) | Reach-Matched Ties |
|---|---:|---:|---:|---:|---|---:|
| Frozen `arm3` | `59.72%` | `68.33%` | `69.58%` | `65.88%` | — | `57.52%` |
| **`Product only v9`** | **`63.89%`** | **`70.00%`** | **`72.08%`** | **`68.66%`** | **`+2.78` `[+0.05, +5.74]`** | **`69.90%`** (`+12.38` pts) |
| **`Product + comments v9`** | **`68.06%`** | **`73.33%`** | **`73.33%`** | **`71.57%`** | **`+5.69` `[+1.85, +9.63]`** | **`78.88%`** (`+21.36` pts) |

#### 55-Day Locked Test (`Oct 1 – Nov 24`, `851` Reach-Matched Pairs)
- **Track 1 (`Product only v9`):** `61.82%` Top-3 / `68.73%` Top-5 / `74.00%` Top-10 (`68.18%` mean, `+1.60` pts over `arm3`), `65.69%` reach-matched ties.
- **Track 2 (`Product + comments v9`):** `63.64%` Top-3 / `70.18%` Top-5 / `74.18%` Top-10 (`69.33%` mean, `+2.75` pts `[+0.08, +5.49]`), `71.33%` ties (`v8` hit `74.36%` Top-10 & `71.45%` ties).

### B. Cross-Domain Generalizability Proofs
1. **Hacker News (`USERSIM-CORE-HN-1`, `usersim_core/hn_transfer_v7.py`):**
   - Zero-rewrite transfer of `UniversalUserSimulatorV7` + `SanitizedSurface` (`572` live URLs) + `< D` author/domain priors on `16` held-out Oct 2026 days (`937` reach-matched pairs).
   - At `t=0` (`Story Only`, zero comments/points): `+1.17` pts ties (`51.12% -> 52.29%`).
   - At `t=30m` (`Story + Early Discourse`, points stripped): within-day Spearman `0.1729 -> 0.2218` (`+28.3%`), Top-3 `8.33% -> 12.50%` (`+4.17` pts `[0.0, +10.42]`), reach-matched ties `51.12% -> 57.63%` (`+6.51` pts `[0.0, +13.50]`).
2. **Real User Product Comments (`USERSIM-CORE-COMMENTS-1`, `usersim_core/comment_ceiling_v7.py`):**
   - Equal-size (`K=6` statements/launch) split-half human ceiling (`Nov 15–24`, `6` resamples/launch, zero real comments seen by simulator):
   - Theme recall `23.38% -> 31.76%` (**`56.8%` of human ceiling `55.93%`**); precision `24.07% -> 29.17%` (**`56.4%` of human ceiling `51.71%`**); concrete complaint recall `4.51% -> 7.87%` (**`1.75x` plain prompt**).

### C. Bottleneck Diagnosis: Why PH Uncontrolled Top-10 Stalled at `~73–74%`
- Prompt/LLM/ranker iteration on current PH inputs is **exhausted**: `v4..v9` on the same PH inputs only move Top-10 by `~0.4–1.3` pts, whereas reach-matched ties already sit at **`78.9%`**.
- Per `E0` shock analysis, **90.5% of remaining PH vote error is unobserved external launch-morning mobilization** (founder email blasts, LinkedIn/X launch posts, YC/investor/WhatsApp/Slack pods, in-app banners) outside our `~36%` held PH voter pool.

---

## 2. Key Code & Artifacts Added/Updated

- **Core Universal Simulator & PH `v7–v9`:**
  - `usersim_core/universal_sim_v7.py` — Domain-agnostic 5-archetype multi-family simulator (`claude-sonnet-4-6` load-balanced `global`+`us-east5` + `gemini-2.5-pro` + `openai/gpt-oss-120b-maas`).
  - `usersim_core/sync_complete_live_data.py` — Zero-leakage pre-reveal data recovery (`1,780` `<=03:45 PT` threads/replies, `230/230` live arrivals, `7,522` media rows, `pnx_0005`, `xbuzz`).
  - `usersim_core/hillclimb_v6.py`, `hillclimb_v7.py`, `hillclimb_v8.py`, `hillclimb_v9.py` — `DualBoundaryUniversalRankerV9` (Podium Head `k=5` + Cutline/Bubble Head) + `93,618`-person archetype-coupled choice + Podium/Bubble tournaments.
  - `usersim_core/qwen_vl_unified_v5.py` — Qwen2.5-VL-7B `bf16` LoRA `r=32` multimodal CUA + choice distillation (`100%` valid JSON, `0.1237` MAE, `989` Sep–Nov scores).
- **Cross-Domain Benchmarks:**
  - `usersim_core/hn_transfer_v7.py` (`USERSIM-CORE-HN-1`)
  - `usersim_core/comment_ceiling_v7.py` (`USERSIM-CORE-COMMENTS-1`)
- **Live Pipeline, Website & Fleet Sign-In:**
  - `usersim_core/fleet/live_intraday_updater.py` — Upgraded to Dual-Boundary `v9` + `api_replies`/`comments_ts`/`pnx` ingestion (`usersim-live-pre.timer` active at `00:12, 01:10, 02:20, 03:35 PT`).
  - `usersim_core/fleet/local_signin_sync.py` — Updated to capture & report Google (`SID`), LinkedIn (`li_at`), X (`auth_token`), and GitHub (`user_session`) cookies, and tolerate missing `usersim-poolb.service`.
  - `mvp/ph_site/live.py`, `mvp/static/ph.html`, `mvp/static/ph_site.css`, `mvp/test_ph_site.py` — Privacy-audited (`WHY_MIN_GROUP = 20`) `why_cards` UI integration (`65/65` tests passing).
- **Audit Ledger:** `docs/ledger/{experiments,decisions}.jsonl` (`347` experiments, `215` decisions, `0` errors) and `docs/RESEARCH_LOG.md`.

---

## 3. Infrastructure & GCS State

- **VM States:**
  - `usersim-exp-1` (`us-central1-b`, `e2-standard-2`): `RUNNING` (shared with `tau2-bench`; `/tmp/usersim_work` = `120M`; `usersim-live-pre.timer` active).
  - `usersim-exp-2` (`us-central1-b`, `e2-highmem-16`, `128 GB RAM`): `TERMINATED` (already has `/var/tmp/usersim_core_work/{data,flywheel_v1,live_23d,complete_v7,fleet_hc3,fleet_hc4,hn_v7,comment_ceiling_v7}` populated on disk when started!).
  - `gemma-persona-probe` (`us-central1-c`, L4): `TERMINATED`.
  - Pool B Fleet (`feeder-fleet-20261108t082000z-{32,40,42,44,45}`, `us-central1-a`): `RUNNING` (never stop fleet VMs; their `/var/tmp/usersim_google_sso/gmail_*` sessions were cleared on VM refresh and await local Mac `fleet_signin.sh` re-sync if running the final all-data PH sweep).
- **GCS Backups (`gs://usersim-trace-store-347838016394/usersim_core_v9/`):**
  - `UserSim_repo_usersim_core_v1_v9.tar.gz` (plus updated repo snapshot with this handoff)
  - `usersim_core_hillclimb_9_results.json`, `why/` (`54` cards), `cache_univ_v7/`, `cache_tourn_v8/`, `u7_predicted_comments.json`, `local_signin_sync.py`
  - `usersim_core_v7/usersim_core_hn_1_results.json` & `usersim_core_comments_1_results.json`
  - `usersim_core_v5/qwen_vl_v5/runs/qwen_vl_r32_v1/` (Qwen2.5-VL-7B LoRA adapter + `sep_nov_item_scores.parquet`)

---

## 4. Next Steps When Resuming

### Option A — Final All-Data PH Salvage Test (Settle Whether External Signals Push `~74% -> 80%+`)
1. On Mac, sync `local_signin_sync.py` and run `for SLOT in 32 40 42 44 45; do usersim_core/fleet/fleet_signin.sh $SLOT; done`, signing into **Google + LinkedIn + X** (and **GitHub / Reddit** if available).
2. Run `#9–#20` 4-step Pool B CUA (`pool_b_interactive_cua.py`), intraday LinkedIn/X founder launch-post scraping (`<= 03:30 PT`), and `$0` zero-login audience footprint pulls (**Tranco Top-1M `< D` domain rank**, **YC directory**, **Chrome Web Store / npm / PyPI / GitHub stars**, **Discord invites**, **HN Algolia**).
3. Evaluate once on `Oct–Nov` / `23d Live`.

### Option B — Move Primary Iteration to Next Universal Simulator Datasets (Recommended)
1. **Real User Product Comments & Bugs (`CEILING-2` + `Client QA`, `28.5% -> 80%+` complaint recall):**
   - Use deeper multi-step Camoufox CUA traces (testing signup, pricing, core workflow, error states) feeding `UniversalUserSimulatorV7` so predicted complaints catch real bugs & pricing pushback (`comment_ceiling_v7.py`).
2. **Hacker News Full `UniversalUserPool` (`tables/hn_people`, `hn_comments`, `hn_posts`, `hn_early_points`):**
   - Replace `hn_transfer_v7.py`'s static 3-persona prompt with a full `< D` `HNUniversalUserPool` built from `hn_people` + `hn_comments` taste vectors & topic/comment-critique rates.
