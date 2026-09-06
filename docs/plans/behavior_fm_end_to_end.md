# Behavior FM: end-to-end plan for one model that beats Centaur, Socrates and Be.FM on their own benchmarks

Status: v2, 2026-09-06. Supersedes the strategy sections of `beat_behavior_fms.md` (v1, 2026-09-04); v1 §8 remains the operational reference for Phase 0 reproduction. This document is the full program: goal, evidence, base model, infrastructure, data, evaluation, training, objectives, stage gates, scaling, risks, budget, release.

Sequencing in this document is by dependency and gate, not by calendar. Each phase lists what must be true to enter it and what must be true to leave it.

---

## 0. How to read this document

| Section | Answers |
|---|---|
| 1 | What exactly counts as winning |
| 2 | Where we are today (Gate 0 state) |
| 3 | Why we believe it is winnable, and the honest odds |
| 4 | Which base model and why |
| 5 | Rules that are never relaxed |
| 6 | Compute, storage, orchestration, secrets |
| 7 | Data: sources, schema, transcription, leakage registry, mixture |
| 8 | Evaluation harness: home benchmarks, auxiliary evals, noise, reporting |
| 9 | Training recipe v0 and the hyperparameter table |
| 10 | Objectives beyond token cross-entropy |
| 11 | Stage-gate ladder with early kill/continue markers |
| 12 | Scaling path 8B → 14B/32B → 70B |
| 13 | Risk register |
| 14 | Budget |
| 15 | Deliverables, release, leaderboard submission |
| 16 | Decision log and open questions |
| A–D | Appendices: artifact IDs, repo layout, commands, mixture defaults |

---

## 1. Goal and success criteria

### 1.1 The claim

One set of weights (one base checkpoint + one adapter, or one merged checkpoint), with no per-benchmark fine-tuning and no per-benchmark prompt engineering beyond each benchmark's own published template, that on each target's own benchmark, own split and own metric scores better than the published number, where we have first reproduced that published number ourselves.

### 1.2 Targets

| Target | Home benchmark and split | Metric (direction) | Number to beat | Their recipe |
|---|---|---|---|---|
| Minitaur-8B (Centaur family) | Psych-101-test: held-out participants (10% per experiment, gated) + OOD sets (new cover story, modified structure, new domain) | Negative log-likelihood of human choices, loss on response tokens only (lower) | Minitaur-8B per-experiment NLL, Centaur paper tables; Centaur-70B is the stretch target | Llama-3.1-8B/70B, QLoRA all linear, 1 epoch, CE masked to responses, lr 5e-5, wd 0.01 |
| Socrates-Qwen-14B-SFT | SocSci210 unseen-study split (40 studies); also unseen-condition and unseen-outcome | Wasserstein distance to human response distribution per cell (lower); individual accuracy secondary | W = 0.151 (uniform 0.203, empirical split-half floor 0.125); DPO acc 73.9% | Qwen2.5-14B, SFT lr 1e-5 then DPO lr 1e-6 |
| Be.FM-1.5-4B | BehaviorBench, live leaderboard, 12 task families (39 eval tasks in the released harness), 4 capabilities | Pairwise win rate; separate distributional and individual boards (higher) | Distributional 95.3% (#1); Individual 66.5% (#7; Gemini 3.1 Pro is #1) | Qwen3-4B-Instruct-2507, LoRA r=8 α=32 all linear, ms-swift; surveys + economic games + literature |

Primary gates: Minitaur-8B, Socrates-14B-SFT, Be.FM-4B distributional and individual boards. Stretch: Centaur-70B NLL, Be.FM-70B.

### 1.3 Definitions

- Beat: strictly better than the published number on the published split, and better than our reproduction of that number, with a paired bootstrap 95% CI that excludes zero where a paired comparison exists (Socrates cells, Psych-101 experiments, BehaviorBench items).
- Same weights: identical checkpoint hash across all three evaluations. A mixture-of-adapters or router is a different claim and must be labelled as such.
- Reproduced: v1 §8.6. Same weight revision, same split file, same metric code, same sampling settings; aggregate within 2% relative or per-experiment Spearman ρ > 0.95.
- Floor: the base model's zero-shot score on each benchmark, reported in every table. If the base already beats a target zero-shot, that target is contaminated or trivial and we say so.

### 1.4 Secondary evaluations (reported, not gated)

SimBench (S, mean TVD), OmniBehavior, CogBench, response-entropy ratio vs humans, and a general-capability slice (MMLU-Pro subset) to document what the adapter costs.

---

## 2. Current state (Gate 0, 2026-09-06)

All three baselines are running on GCP Spot GPU VMs with two independent recovery layers: an always-on polling watchdog (`scripts/fm_baselines/spot_watchdog.py`, installed by `install_spot_watchdog.sh` as a 60 s systemd timer on a non-preemptible VM) and an Eventarc → Cloud Function → Cloud Tasks preemption handler (`scripts/fm_baselines/gcp_spot_restart/`). Runs resume from on-disk state on restart.

| Baseline | State | Notes |
|---|---|---|
| Minitaur-8B NLL | Running, full Psych-101-test | Earlier T4 attempt OOMed at max_seq 8192 (`results/fm_baselines/minitaur/oom_tail.txt`); rerun on larger GPU |
| Socrates-14B-SFT W | Running, full 40 unseen studies | Smoke on 2 studies gave W = 0.184 (`results/fm_baselines/socrates/SUMMARY_smoke.json`); n too small to compare to 0.151 |
| Be.FM-1.5-4B BehaviorBench | 34/39 tasks done; 5 `workflow_*` tasks rerunning as a bundle | BLEURT segfault (`libtriton.so` in a process that had touched CUDA) fixed by scoring BLEURT in a CPU-only subprocess (`patch_befm_bleurt_subprocess.py`, `colab_befm4b_serve_and_eval.py`). Partial results: strategic_gameplay_guessing 0.485 vs paper ~0.48 |

Our only training-adjacent evidence so far is a prompting ablation on SimBench (`results/simbench_ablate/`, 981 items, paired): persona conditioning is worth +18 S points, few-shot +13, chain-of-thought −3.5, ensembling +2. The benchmarks are dominated by conditioning and calibration, not reasoning. See §3.

Gate 0 exit: `results/fm_baselines/SUMMARY.md` with the table in v1 §8.4 filled for all three, reproductions within tolerance, and the leakage registry (§7.5) populated from the test splits.

---

## 3. Why it is winnable, and the odds

### 3.1 Structural argument

The three targets are siloed by training data and each fails on the others' benchmarks: Centaur scores S = 8.5 on SimBench (worst tier); Socrates-14B scores 47.4% on BehaviorBench (rank 11); Be.FM is weak on individual-level prediction (rank 7). No one has trained one model on the union. Four levers the targets leave on the table:

1. Breadth. Union of Psych-101 + SocSci210 + BehaviorBench sources + distributional survey corpora.
2. Base model recency. Centaur is on Llama-3.1, Socrates on Qwen2.5/Llama-3. Same recipe on a 2026 base is a legitimate gain.
3. Objective. All three train token CE on individual responses; two of three are scored on distributional metrics. Distribution-matching losses beat SFT on choices13k in the literature.
4. Entropy preservation. Instruction tuning collapses response entropy (documented on SimBench, OmniBehavior). Starting from a base checkpoint and controlling merge ratio keeps the mass-covering behavior distributional metrics reward.

### 3.2 Odds (prior, first serious cycle, 8B, union data, Centaur recipe)

| Outcome | P |
|---|---|
| Beat Minitaur-8B NLL | 0.70 |
| Beat Centaur-70B NLL (at 8B) | 0.35 |
| Beat Socrates-14B W = 0.151 | 0.55–0.60 |
| Beat Be.FM-4B distributional board | 0.40 |
| Beat Be.FM-4B individual board | 0.60 |
| All three primary targets, first cycle | 0.25–0.30 (outcomes are positively correlated) |
| All three after 3–5 gated iterations | 0.50–0.55 |
| Beat one or two, not all three (modal) | 0.55–0.65 |
| Worse than all three on all three (dilution) | 0.05–0.08; if it happens, it is almost certainly a recipe or format bug, which the ladder in §11 catches before the union run |

Where the mass moves: mixture weighting (§7.6), prompt-format fidelity (§7.3), objective (§10), leakage hygiene (§7.5). Not model size at first; size is Phase 5.

---

## 4. Base model decision

### 4.1 Choice: Qwen3-8B-Base for the ablation ladder

Reasons, in order of weight:

1. Base checkpoint available. The entropy-preservation lever requires a base, not an instruct model; Qwen3 ships `-Base` weights at 0.6B/1.7B/4B/8B/14B/32B, which also gives us a clean scaling ladder within one family (§12).
2. Recipe transfer. Be.FM-1.5-4B is a LoRA on Qwen3-4B; Socrates-14B is on Qwen2.5-14B. Two of three targets already validated Qwen tokenization and formatting on this kind of data, so tokenizer-level surprises (option tokens, numeric responses, `<< >>` markers) are lower risk than switching families.
3. Context. Psych-101 transcripts run to tens of thousands of tokens; Centaur trained at 32k. Qwen3-8B supports 32k natively (128k with YaRN).
4. License. Apache-2.0. No redistribution constraint on a released adapter or merged checkpoint.
5. Pretraining breadth. Qwen3 pretraining (~36T tokens, 119 languages) covers survey and social-science text well; SocSci210 and OpinionQA-style items benefit.

Alternatives considered: Llama-3.1-8B (Minitaur's base; keeps that comparison apples-to-apples but is older and its base is weaker on multilingual survey text), Gemma 3 12B (strong, but no clean base ladder and a more restrictive license), Qwen3-30B-A3B MoE (attractive inference cost, but QLoRA on MoE experts is less mature; keep as a Phase 5 candidate).

Control run: one v0 union run on Llama-3.1-8B to isolate "better base" from "more data" in the Minitaur comparison (§11, run 2d).

### 4.2 Scale path

Qwen3-8B-Base → Qwen3-14B-Base → Qwen3-32B-Base for the ablation-to-candidate path; final 70B-class run on Llama-3.3-70B (Be.FM-70B's base; the only dense 70B base with a matching target) or Qwen3-235B-A22B if MoE QLoRA is validated. Detail in §12.

---

## 5. Non-negotiable rules

1. Leakage registry first. No training record is assembled before every test item from all three benchmarks is hashed (§7.5). The filter log is a deliverable.
2. Their metric, their split, their code. Centaur's NLL script, Socrates' eval, `behaviorbench_eval`. We never re-implement a scorer we can run.
3. Same weights for all three. Per-benchmark adapters exist only as the negative-transfer ablation.
4. Every number is paired with the reproduced baseline and the base-model zero-shot floor, same hardware, same eval code, same table.
5. Every run is evaluated on all three home benchmarks plus the auxiliary set, no exceptions, so the transfer matrix is always complete.
6. Base checkpoints, dataset revisions, eval-repo SHAs and seeds are pinned in `PINS.md` and in every result JSON.
7. Secrets (`HF_TOKEN`, GCP credentials, W&B keys) live in GCP Secret Manager or Colab secrets; never in the repo. Region and project IDs are read from environment or `gcloud config`, never hardcoded.

---

## 6. Infrastructure

### 6.1 Compute tiers

| Tier | Use | Machine | Provisioning |
|---|---|---|---|
| T0 laptop (M4 24 GB) | Data pipeline, registry, 4B evals in 4-bit, analysis | local | — |
| T1 Colab T4/L4 | Smokes, 4B/8B evals in 4-bit | Colab | as available |
| T2 GCP single A100-80G | 8B/14B QLoRA runs, 14B/70B 4-bit evals | `a2-ultragpu-1g` | Spot, watchdog-protected |
| T3 GCP 2–4× A100-80G | GRPO at 8B, 32B QLoRA | `a2-ultragpu-2g/4g` | Spot if checkpoint cadence < 15 min, else on-demand |
| T4 GCP 8× H100 | Final 70B QLoRA | `a3-highgpu-8g` | On-demand or committed; Spot only with tested resume |

### 6.2 Preemption resilience (already built)

- `spot_watchdog.py` on a small non-preemptible VM polls labelled instances every 60 s and restarts `TERMINATED`/`STOPPED` ones; per-instance session files avoid restart storms.
- Eventarc `compute.instances.preempted` → Cloud Function (512 MiB) → `instances.start`, with Cloud Tasks retries when capacity is unavailable. Deployed via `gcp_spot_restart/deploy.sh`; region and project read from environment.
- Every training and eval job must be idempotent on restart: checkpoints and partial results written to the persistent disk and mirrored to GCS; a systemd unit relaunches the job on boot and the job resumes from the last checkpoint.

### 6.3 Storage layout

```
gs://<bucket>/behavior-fm/
  raw/            source datasets as downloaded, with revision hashes
  registry/       leakage_registry.jsonl, filter logs
  corpus/<ver>/   unified JSONL shards + dataset card
  runs/<run_id>/  config.yaml, checkpoints/, eval/*.json, logs/
  evals/baselines/ reproduced baseline outputs
```

HF cache on a persistent disk attached to whichever VM is active, so 140 GB of 70B weights is downloaded once.

### 6.4 Orchestration and tracking

- One `run_id` per training run; one YAML config per run, committed under `configs/runs/`.
- Metrics logged to W&B (or a local JSONL mirrored to GCS if W&B is unavailable): per-domain training loss, per-domain eval loss, entropy ratio, throughput.
- A `run_all_evals.py` entry point evaluates a checkpoint on all three home benchmarks plus auxiliaries and writes `evals/summary.json` with baseline and floor columns filled from `evals/baselines/`.
- Eval jobs are queued behind training jobs on the same VM when GPU memory allows; otherwise on a T1/T2 eval VM.

### 6.5 Software stack

- Training: Unsloth or PEFT + bitsandbytes for QLoRA at 8B/14B (Centaur's stack; keeps recipe parity), ms-swift as an alternative for parity with Be.FM. TRL for DPO/GRPO. FlashAttention-2 and sequence packing.
- Serving for generation evals: vLLM (already used for Be.FM), with LoRA loaded or merged.
- Scoring: each benchmark's own repo pinned; BLEURT runs in a CPU-only subprocess (already fixed).

---

## 7. Data

### 7.1 Sources

| # | Source | Content | Size | Role | License / access |
|---|---|---|---|---|---|
| 1 | Psych-101 (train) | 160 experiments, ~60k participants, ~10M trial-level choices; natural-language transcripts | ~250M tokens | Home data for Minitaur target | Public on HF |
| 2 | SocSci210 (train studies) | 210 survey experiments, ~400k participants, 2.9M responses, condition-level groupings | ~100M tokens | Home data for Socrates target | Public on HF |
| 3 | BehaviorBench source datasets minus held-out subjects | Big Five/IPIP items, economic games (dictator, ultimatum, trust, PGG), demographic prediction sources, literature QA | est. 20–50M tokens | Home data for Be.FM target; rebuilt from public sources since Be.FM training data is unreleased | Mixed; check per source |
| 4 | Distributional survey corpora: choices13k, SubPOP, OpinionQA, WVS, GlobalOpinionQA, SocioBench, SimBench-train, ESS, Afrobarometer, LatinoBarómetro, ISSP | Group-labelled response distributions | est. 50–100M tokens | Distributional targets for §10 objectives; SimBench aux eval | Public; SimBench test excluded |
| 5 | OmniBehavior slices (local) | Additional behavioral domains | small | Extra domain, fourth eval | already local |
| 6 | General instruction replay (small) | e.g. 1–3% of tokens from an open instruction set | small | Capability preservation (§11 Phase 4) | Apache/CC |

Excluded from training, always: Psych-101-test (gated, ND, never downloaded onto a training VM), SocSci210 unseen splits, BehaviorBench eval items and their held-out subjects, SimBench test.

### 7.2 Unified record schema

Every record is one JSONL line:

```json
{
  "id": "socsci210/study_0123/cond_2/participant_45/q_7",
  "source": "socsci210",
  "domain": "survey_experiment",          // psych101_trial | survey_experiment | econ_game | personality | demographics | literature | opinion_poll
  "template": "socrates_v1",              // which published prompt template this record renders with
  "individual_id": "socsci210/p_45",
  "cell_id": "socsci210/study_0123/cond_2/q_7",
  "prompt": "...full rendered prompt in the home template...",
  "response": "3",
  "response_tokens_span": [1023, 1024],   // loss mask
  "options": ["1","2","3","4","5"],       // null for free numeric / free text
  "cell_distribution": {"1":0.05,"2":0.12,"3":0.41,"4":0.30,"5":0.12},  // null if n_cell == 1
  "n_cell": 213,
  "persona": {...},                        // demographics / condition text if the source has it
  "license": "cc-by-4.0",
  "hash": "sha256 of (template, prompt, response)"
}
```

`cell_distribution` is what the distributional objectives in §10 consume; `response_tokens_span` is what CE masking consumes; `template` is what evaluation consumes to guarantee format fidelity.

### 7.3 Transcription and format fidelity

Each source is rendered in the template its home benchmark scores with:

- Psych-101 records keep the Centaur transcription verbatim: experiment description, trial-by-trial text, response inside `<< >>`, loss on the response tokens only. Long transcripts are chunked at 32k with participant history preserved in the chunk prefix, exactly as Centaur did.
- SocSci210 records use the Socrates prompt (participant demographics block, condition stimulus, question, response format) so that eval-time and train-time formats match and W is computed on the same option surface.
- BehaviorBench sources use the Be.FM/BehaviorBench prompt formats task by task.
- Sources with no home benchmark (group 4) are rendered in the Socrates survey template, with the group label in the demographics block.

A `domain` tag is prepended as a short system-style line only in the reweighting ablation (§11, 2f); the default is no tag, so evaluation prompts remain exactly the published ones.

Validation: 5 studies per source hand-checked against the source paper; a round-trip test that re-derives the published eval prompt from our record for a sample of eval items (which we then discard, since eval items never enter the corpus).

### 7.4 Cleaning and deduplication

- Exact-hash dedup on `(template, prompt, response)`.
- Near-dup on prompt text (MinHash, Jaccard > 0.9) within source, kept if `individual_id` differs (same item, different person is signal, not duplication).
- Drop records with non-parsable responses, out-of-option responses, or prompts > 32k tokens after chunking.
- Numeric free responses bucketed into the option grid the home benchmark uses for W (Socrates' bucketing), stored alongside the raw value.

### 7.5 Leakage registry

Built before any corpus assembly and re-run before every corpus version:

1. Hash every test item from Psych-101-test (hash computed on the gated VM and only the hash leaves), SocSci210 unseen-study/condition/outcome splits (`metadata/*_mapping.json`), BehaviorBench (`behaviorbench_indices.json` and the held-out subject IDs), SimBench test. Hash on normalized prompt text and on `(source, item_id)`.
2. Also register study-level and subject-level IDs, not just items: an unseen SocSci210 study is excluded entirely, not item by item; BehaviorBench held-out subjects are excluded across all their items.
3. Filter the corpus; write `registry/filter_log_<corpus_ver>.json` with counts removed per source per rule.
4. Contamination probe on the base model: zero-shot score on each benchmark (the floor) and a canary test on a handful of verbatim test prompts (completion likelihood vs paraphrase). Report both.

### 7.6 Mixture

Token counts are lopsided (Psych-101 ≈ 250M tokens vs SocSci210 ≈ 100M vs BehaviorBench sources ≈ 30M). Default mixture for the union runs uses temperature sampling over sources with τ = 0.5 on token share, then a floor so that each home source is ≥ 20% of tokens seen in one epoch. Appendix D gives the default table. Mixture weight is the first knob turned at Gate 1 if any home benchmark regresses relative to its single-source adapter.

### 7.7 Dataset card

`corpus/<ver>/DATASET_CARD.md`: counts per source, domain, template; token totals; `n_cell` histogram; licenses; registry version; filter log summary; known gaps (e.g. BehaviorBench sources we could not reconstruct).

---

## 8. Evaluation harness

### 8.1 Home benchmarks

| Benchmark | Runner | Inputs | Output | Cost per 8B eval |
|---|---|---|---|---|
| Psych-101-test NLL | Centaur repo script (`colab_minitaur_psych101_nll.py` wraps it) | adapter or merged ckpt, Psych-101-test on the gated VM | per-experiment NLL JSON, aggregate, OOD splits | 4–12 h on A100-80G at 32k; deterministic |
| SocSci210 unseen W | Socrates eval (`colab_socrates_wass.py` wraps it) | ckpt served by vLLM; temperature 0.6, top_p 0.9; n samples per cell as in paper | per-cell W, aggregate W, individual acc | 4–12 h on L4/A100 |
| BehaviorBench | `behaviorbench_eval` (`colab_befm4b_serve_and_eval.py` wraps it, workflow tasks as a bundle, BLEURT in CPU subprocess) | vLLM, temperature 0.6 / top_p 0.95 / top_k 20 | per-task metrics, leaderboard JSON | 2–8 h on L4 |

### 8.2 Auxiliary evaluations

- SimBench (S, mean TVD, per-dataset) using the existing `simbench_ablate` harness; SimBench test never trained on.
- OmniBehavior slices; CogBench if the Centaur repo script runs.
- Entropy ratio: per cell, model response entropy / human response entropy; report mean and distribution. Target ≈ 1.0.
- Calibration: ECE on option-token probabilities against `cell_distribution` on held-out cells of the training sources.
- General capability: fixed 1k-item MMLU-Pro slice; report base vs adapter delta.

### 8.3 Noise and statistics

- Bootstrap 95% CIs on the aggregate for every benchmark (resample experiments for Psych-101, studies for Socrates, items for BehaviorBench).
- Paired comparisons against the baseline reproduction and against the previous best run; report the paired delta and CI, not just point estimates.
- Human noise ceilings where data allows: split-half W per SocSci210 study (empirical floor 0.125), split-half TVD on SimBench cells.
- Generation evals: fixed seeds; where the paper averages seeds, we average the same number.

### 8.4 Reporting

Every run produces `runs/<run_id>/evals/summary.json` and one row in `results/behavior_fm/LEADERBOARD.md`:

| run_id | base | data | objective | Psych-101 NLL (Minitaur / floor) | Socrates W (0.151 / floor) | BB dist (95.3 / floor) | BB indiv (66.5 / floor) | SimBench S | entropy ratio | MMLU-Pro Δ |

---

## 9. Training recipe v0

Identical to Centaur except for the data, so the first result isolates the data lever.

| Setting | v0 value | Notes |
|---|---|---|
| Base | Qwen3-8B-Base | §4 |
| Method | QLoRA, 4-bit NF4 base, bf16 compute | Centaur parity; fits A100-80G at 32k with gradient checkpointing |
| LoRA | r = 8, α = 32, dropout 0, all linear layers (q,k,v,o,gate,up,down) | Centaur and Be.FM both used r=8 α=32 |
| Sequence length | 32,768 | Psych-101 transcripts; packing on for short survey records |
| Loss | Token CE masked to `response_tokens_span` | |
| Epochs | 1 | Centaur; Be.FM used more; ablate 1 vs 2 in Phase 3 |
| Batch | 32 sequences effective (grad accumulation) | |
| LR | 5e-5, cosine, 3% warmup | Centaur |
| Weight decay | 0.01 | |
| Optimizer | AdamW 8-bit (paged) | |
| Precision | bf16 | |
| Checkpoint cadence | every 500 steps and every 15 min, to disk and GCS | Spot survival |
| Seeds | 3 for headline runs, 1 for ladder ablations | |

Runs at 14B/32B keep the recipe; 70B follows Centaur-70B exactly (§12).

Option-token distribution extraction (used by §8 calibration and §10 objectives): for multiple-choice records, the model's distribution over options is the softmax over the first-token logits of each option string (with a check that option strings are single-token or share no prefix; otherwise full-sequence log-probs are used). For numeric responses, the distribution over the bucket grid is computed the same way.

---

## 10. Objectives beyond token cross-entropy

All ablated at 8B on the union corpus, each evaluated on everything.

| ID | Objective | Where it applies | Expected effect | Implementation |
|---|---|---|---|---|
| A | Soft-label CE: target = `cell_distribution` over option tokens when `n_cell > 1`, else hard label | Groups 2–4, BehaviorBench distributional | Lower W, higher BB-dist; neutral on NLL | Replace one-hot with the cell vector on the option-token positions; standard CE elsewhere |
| B | Auxiliary KL/TVD on option-token distribution, weight ∝ log(n_cell) | Same | Same as A, more stable when cells are small | Add λ·KL(p_cell ‖ p_model) at the response position |
| C | GRPO, reward = 1 − TVD(model sample distribution, human cell distribution), group of G samples per cell | Distributional cells | Directly optimizes the scored quantity; risk of mode collapse controlled by KL penalty to SFT | TRL GRPO, warm start from best SFT; G = 16; β = 0.04 |
| D | DPO on individual responses (Socrates recipe): chosen = actual response, rejected = sampled wrong option | Individual-level accuracy, BB-indiv | Higher acc, worse W (Socrates' own finding) | TRL DPO, lr 1e-6, β = 0.1 |
| E | Sequence: SFT(A+B) → C → D with entropy-ratio monitoring | All | Best of both if D is short and monitored | Stop D when entropy ratio drops below 0.9 |
| F | Entropy regularizer: penalty on (H_model − H_human)² per cell | Distributional | Keeps mass-covering behavior | Cheap add-on to A/B |

Gate 2 rule: an objective ships only if it improves the distributional metrics (Socrates W, BB-dist) and does not degrade individual metrics (Psych-101 NLL, BB-indiv) beyond CI, or vice versa. Trades are reported, not shipped.

---

## 11. Stage-gate ladder and early markers

Each rung is cheap relative to the next and has a numeric continue/kill marker. Run order is fixed; nothing later starts until the marker is read.

### Phase 0: reproduce baselines (in progress)

Exit: three reproductions within tolerance; registry populated; `SUMMARY.md` written. Kill rule: a reproduction off by > 5% with no bug found stops everything until resolved.

### Phase 1: corpus v1

Enter: Phase 0 exit. Deliverables: `corpus/v1/` shards, dataset card, filter log, round-trip validation report, base-model floors and canary results on all three benchmarks.

Markers:
- Round-trip test passes on 100% of sampled eval items per template.
- Registry removes a plausible count (non-zero for SocSci210 unseen studies and BehaviorBench subjects; zero for Psych-101-test, since it is never in scope).
- Base floors are well below targets on all three. If the base floor beats any target, stop and investigate contamination.

### Phase 2: v0 runs, 8B, Centaur recipe

| Run | Data | Purpose | Marker to continue |
|---|---|---|---|
| 2a | Psych-101 only | Recover Minitaur | NLL within 5% of Minitaur at 1/10 data; at full data, beats or matches Minitaur. If it cannot match at full data, the recipe or format is broken; fix before 2c |
| 2b | SocSci210 only | Recover Socrates-SFT | W ≤ 0.165 at 1/10 data; ≤ 0.155 at full |
| 2b' | BehaviorBench sources only | Approach Be.FM | BB-dist ≥ 85% at full (Be.FM has data we cannot fully rebuild; this is a floor check) |
| 2c-small | Union, 1/10 of each source | Cheapest negative-transfer test | On every home benchmark, 2c-small is within CI of the corresponding 1/10 single-source run. Any regression beyond CI → go to 2f before scaling data |
| 2c | Union, full | The v0 result | Beats ≥ 1 target; within CI of 2a/2b/2b' on the other two |
| 2d | Union, full, Llama-3.1-8B | Isolate base-model effect vs Minitaur | Reported, not gated |
| 2e | Union, 2 epochs | Epoch ablation | Reported |
| 2f (conditional) | Union with domain tags and mixture reweighting (Appendix D alternatives) | Fix negative transfer | Restores 2c to within CI of single-source on the regressed benchmark |

Per-run diagnostics read at 10%, 25%, 50% of training: per-domain eval loss curves (a domain whose eval loss rises while others fall is being diluted; reweight), entropy ratio (should stay 0.9–1.1 from a base start), and option-token calibration ECE.

Gate 1 exit: 2c or 2f beats ≥ 1 target and shows no negative transfer beyond CI.

### Phase 3: objectives, 8B

Runs A, B, A+B, C (from best SFT), D (from best SFT), E, F, each 1 seed then 3 seeds for the top two.

Markers: after 25% of steps, the trained-on distributional proxy (mean TVD on held-out training cells) must be below the SFT value; if not, kill that arm. GRPO arms are killed if entropy ratio < 0.8 or KL to SFT > threshold at any checkpoint.

Gate 2 exit: an objective improves both distributional and individual metric families over 2c/2f, or the best trade is documented and the SFT recipe proceeds.

### Phase 4: entropy and capability preservation, 8B

Runs: base-start (current) vs instruct-start; adapter merge into the instruct model at ratios {0.5, 1.0}; 1–3% instruction replay. Measure entropy ratio, MMLU-Pro Δ, BB knowledge/workflow tasks (where frontier models win the individual board).

Markers: replay or merge that recovers ≥ 50% of the MMLU-Pro Δ without moving Socrates W or Psych-101 NLL beyond CI is adopted.

Gate 3 exit: final 8B recipe fixed (data mixture, objective, start point, replay).

### Phase 5: scale

See §12. Gate 4 exit: 70B-class run evaluated on everything, BehaviorBench submitted, tables published.

### Cross-phase kill rule

If after Phase 3 the best 8B run beats none of the three targets, we do not scale. We publish the transfer matrix and the negative result, and revisit the data (most likely the BehaviorBench source reconstruction) before spending on 70B.

---

## 12. Scaling plan

### 12.1 Ladder

Before the 70B run, fit a small scaling curve inside Qwen3-Base on the fixed final recipe: 1.7B, 4B, 8B, 14B (all QLoRA, same data, same steps in tokens). Plot each home metric vs log(params). Markers:

- Monotone improvement on all three with no plateau by 14B → proceed to 32B and 70B-class with confidence.
- A benchmark flat from 8B to 14B → scale will not fix it; return to data/objective for that benchmark before 70B.
- Extrapolation of the 4-point fit must predict beating the target at 70B; if it does not, do not run 70B.

### 12.2 Candidate and final

- Candidate: Qwen3-32B-Base, QLoRA, single A100-80G at reduced sequence length or 2× A100 at 32k. Likely enough to clear Socrates and Be.FM-4B; Minitaur is cleared earlier.
- Final: Llama-3.3-70B QLoRA on 8× H100 (Centaur-70B parity, Be.FM-70B parity), 1 epoch on the final mixture, ~4× Psych-101 tokens, 3–5 days. Alternative if MoE QLoRA is validated at 30B-A3B during Phase 3: Qwen3-235B-A22B.

### 12.3 What scale is expected to move

Individual-level metrics (Psych-101 NLL, BB-indiv, BB knowledge/workflow). Distributional metrics moved mostly by data and objective; scale should not hurt them if the entropy controls from Phase 4 are kept.

---

## 13. Risk register

| Risk | Likelihood | Impact | Detection | Mitigation |
|---|---|---|---|---|
| Negative transfer between trial-level and survey data | Medium | Blocks the one-model claim | 2c-small vs single-source, per-domain eval loss curves | Mixture reweighting, domain tags (2f); mixture-of-adapters only as a disclosed fallback |
| Prompt-format drift hurts NLL/W | Medium | Large on Psych-101 NLL | Round-trip test; 2a failing to match Minitaur | Templates pinned per source; eval uses the same renderer |
| BehaviorBench source data cannot be fully reconstructed | High | Be.FM-dist may stay out of reach | 2b' floor check | Prioritize Big Five and games sources; accept BB-indiv first; document the gap |
| Psych-101-test access delayed or denied | Medium | Cannot gate Minitaur | Access status | Escalate to authors; proceed on other two; Centaur gate stays open |
| Eval noise larger than effect (Socrates headroom 0.026 W) | Medium | False positives/negatives | Bootstrap CIs, 3 seeds | Paired tests; report CIs; more samples per cell |
| Leakage through public sources (BehaviorBench built from public data) | Medium | Invalidates claim | Registry filter counts; canary probe | Subject-level and study-level exclusion, not item-level only |
| Base model contaminated with published experiments | Low–Medium | Inflated floor | Zero-shot floor, canary | Report; choose a different base if floor is anomalous |
| Spot preemption mid-run | High | Lost time | Watchdog logs | Two-layer restart (built), 15-min checkpoints, idempotent resume |
| GRPO mode collapse | Medium | Kills distributional metrics | Entropy ratio, KL to SFT | KL penalty, early stop, F regularizer |
| Instruction-tuning entropy collapse (if instruct start chosen) | Medium | Worse W and BB-dist | Entropy ratio | Base start default; merge ratio ablation |
| Cost overrun | Medium | Program stalls | Per-run cost logged | Ladder is cheap-first; 70B only after Gate 3 and §12.1 extrapolation |
| Dilution (worse everywhere) | 0.05–0.08 | Program failure | 2c-small | Ladder catches it before full-data spend; almost always a bug |

---

## 14. Budget

| Item | Hardware | Hours | Est. USD (Spot) |
|---|---|---|---|
| Phase 0 (in progress) | mixed T4/L4/A100 | — | 50–200 |
| Phase 1 corpus build | CPU VMs + laptop | — | < 50 |
| Phase 2: 2a, 2b, 2b', 2c-small, 2c, 2d, 2e, 2f (8 runs) + evals | 1× A100-80G | 8 × (6–24 h) + evals ~8 × 12 h | 400–900 |
| Phase 3: 7 arms, 1 seed + 2 arms × 3 seeds; GRPO on 2–4× A100 | 1–4× A100-80G | ~250 GPU-h | 500–900 |
| Phase 4: 5 runs + evals | 1× A100-80G | ~100 GPU-h | 150–300 |
| Scaling ladder: 1.7B, 4B, 14B, 32B | 1–2× A100-80G | ~120 GPU-h | 250–500 |
| Final 70B run + evals | 8× H100 | 3–5 days | 3,000–6,000 (on-demand higher) |
| Total | | ~800–1,100 GPU-h | roughly 5k–9k USD |

Evaluation is ~40% of GPU hours because every run is evaluated on everything; this is deliberate.

---

## 15. Deliverables and release

1. `results/fm_baselines/SUMMARY.md`: reproductions (Gate 0).
2. `corpus/v*/DATASET_CARD.md` and `registry/filter_log_*.json`.
3. `results/behavior_fm/LEADERBOARD.md`: every run, every benchmark, with baseline and floor columns; the transfer matrix from Phase 2 as its own table.
4. Final weights: adapter on HF plus merged checkpoint; model card with the full table, seeds, pins, and the negative-transfer ablation.
5. BehaviorBench leaderboard submission (the only way to claim the Be.FM number); Psych-101 and SocSci210 tables published side by side with reproductions.
6. Eval scripts and configs for every reported number; `PINS.md`.
7. A short write-up: the transfer matrix (does SocSci210 help Psych-101 OOD? does Psych-101 help BehaviorBench?) is the scientific contribution regardless of whether all three targets fall.

---

## 16. Decision log and open questions

Decided:
- Base: Qwen3-8B-Base for the ladder; Llama-3.3-70B for the final unless MoE QLoRA is validated (§4).
- Centaur-70B reproduction skipped in Phase 0 (user decision); Minitaur-8B is the primary Centaur-family gate.
- Same-weights claim; adapters-per-benchmark only as ablation.
- BLEURT runs in a CPU-only subprocess; vLLM is not killed during metrics.

Open:
- Exact reconstructable subset of BehaviorBench sources; decides whether BB-dist is a realistic Phase 2 target or a Phase 5 target.
- Whether to include a small general-instruction replay from the start (Phase 4 decides).
- Whether GRPO at 8B is worth its cost relative to A+B; Phase 3 decides.
- W&B vs local tracking (depends on sandbox egress policy).

---

## Appendix A. Artifact IDs

```
# Centaur / Minitaur
HF: marcelbinz/Llama-3.1-Minitaur-8B-adapter
HF: marcelbinz/Llama-3.1-Centaur-70B-adapter   # stretch
HF: marcelbinz/Psych-101                       # train
HF: marcelbinz/Psych-101-test                  # gated, ND; never on a training VM
Git: github.com/marcelbinz/Llama-3.1-Centaur-70B

# Socrates
HF: socratesft/SocSci210
HF: socratesft/socrates-qwen2.5-14b-sft        # W = 0.151 target
HF: socratesft/socrates-qwen2.5-14b-dpo
HF: socratesft/socrates-llama3-8b-sft, -dpo
Git: github.com/akaashkolluri/socrates

# Be.FM / BehaviorBench
HF: befm/BeFM1.5-4B                            # LoRA on Qwen3-4B-Instruct-2507
HF: befm/BeFM1.5-70B                           # stretch
HF: befm/BehaviorBench
Git: github.com/umich-foreseer/behaviorbench_eval

# Bases
HF: Qwen/Qwen3-1.7B-Base, Qwen3-4B-Base, Qwen3-8B-Base, Qwen3-14B-Base, Qwen3-32B-Base
HF: meta-llama/Llama-3.1-8B                    # control run 2d
HF: meta-llama/Llama-3.3-70B                   # final

# Distributional corpora
choices13k, SubPOP, OpinionQA, WVS, GlobalOpinionQA, SocioBench, SimBench (train only), ESS, Afrobarometer, LatinoBarómetro, ISSP
```

## Appendix B. Proposed repository layout

```
fm/
  data/        loaders per source, renderers per template, dedup, mixture sampler
  registry/    hashing, filter, canary probe
  train/       sft.py (v0), objectives/{soft_ce,kl_aux,grpo,dpo,entropy_reg}.py, configs/
  eval/        run_all_evals.py, wrappers for the three home harnesses, aux evals, stats (bootstrap, paired)
  infra/       VM templates, systemd units, GCS sync, watchdog (existing scripts/fm_baselines/*)
configs/runs/<run_id>.yaml
results/behavior_fm/LEADERBOARD.md
results/fm_baselines/                existing Gate 0 outputs
docs/plans/                          this document, v1
PINS.md
```

## Appendix C. Run lifecycle

```
1. Write configs/runs/<run_id>.yaml (base, corpus version, mixture, objective, seed, hardware).
2. Launch on a Spot VM with a systemd unit that: syncs corpus from GCS, resumes from latest checkpoint if present,
   trains, checkpoints every 500 steps / 15 min to disk and GCS, then runs run_all_evals.py.
3. Watchdog + Eventarc restart the VM on preemption; the unit resumes.
4. run_all_evals.py writes runs/<run_id>/evals/summary.json with baseline and floor columns and appends a row
   to results/behavior_fm/LEADERBOARD.md.
5. Read markers for the current rung (§11) before launching the next run.
```

## Appendix D. Default mixture (union runs)

Token shares before reweighting are estimates; replace with dataset-card values at Phase 1.

| Source group | Raw token share | τ = 0.5 sampled share | Floor applied | Final share (v0) |
|---|---|---|---|---|
| Psych-101 | 0.55 | 0.42 | — | 0.35 |
| SocSci210 | 0.22 | 0.27 | ≥ 0.20 | 0.25 |
| BehaviorBench sources | 0.07 | 0.15 | ≥ 0.20 | 0.20 |
| Distributional survey corpora | 0.14 | 0.21 | — | 0.17 |
| OmniBehavior | 0.02 | 0.08 | — | 0.03 |

Alternatives for run 2f: (i) equal shares across the three home sources (0.30/0.30/0.30, rest 0.10); (ii) home-source floor raised to 0.25; (iii) curriculum: home sources only for the first 30% of steps, full mixture thereafter.
