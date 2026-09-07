# Program plan: one human-cognition foundation model that beats Centaur, Socrates and Be.FM on their home benchmarks

Status: draft v1, 2026-09-04. Single goal, nothing else on the roadmap until this ships.

## 0. The goal, stated so it can fail

One set of weights (one base + one adapter, no per-benchmark fine-tune) that, on each target's own benchmark, own split and own metric, scores better than the published number:

| Target | Home benchmark | Their metric | Published number to beat | Their recipe |
|---|---|---|---|---|
| Centaur (70B) / Minitaur (8B) | Psych-101 held-out participants (10% per experiment, gated test set) + OOD sets (new cover story, modified structure, new domain) | Negative log-likelihood of human choices, loss only on response tokens | Centaur NLL per experiment, Table 1 of the paper; also CogBench alignment | Llama-3.1-70B, QLoRA all linear layers, 1 epoch, CE masked to human responses, bs 32, lr 5e-5, wd 0.01 |
| Socrates-Qwen-14B / Socrates-Llama-8B | SocSci210 unseen-study split (also unseen-condition, unseen-outcome) | Wasserstein distance to human response distribution (lower is better); individual accuracy as secondary | W = 0.151 (uniform 0.203, empirical bound 0.125); acc 73.9% with DPO | Qwen2.5-14B / Llama3-8B, SFT lr 1e-5 then DPO lr 1e-6, 4-24 h on A100-80G |
| Be.FM-1.5 (4B, 70B) | BehaviorBench, 12 tasks, 4 capabilities; live leaderboard | Pairwise win rate, separate individual and distributional boards | Distributional: Be.FM-1.5-4B 95.3% (#1). Individual: Gemini 3.1 Pro #1, Be.FM-1.5-4B 66.5% (#7) | Qwen3-4B / Llama-3.3-70B, LoRA r=8 alpha=32 all linear, ms-swift, surveys + economic games + literature |

"Beat" means: better than the published number on the published split, and reproduced by us on the public checkpoint first. If we cannot reproduce a target's number within tolerance, we cannot claim to beat it.

## 1. Why this is winnable

The three targets are siloed by training data and each fails on the others' benchmarks:

- Centaur trained only on Psych-101 (learning and decision-making trials). Scored S=8.5 on SimBench, worst tier.
- Socrates trained only on SocSci210 (TESS survey experiments). Socrates-14B-SFT scored 47.4% on BehaviorBench (rank 11).
- Be.FM trained on surveys, economic games, literature. Held-out subjects, but the same instruments as BehaviorBench. Weak on individual-level prediction (rank 7).

Nobody has trained one model on the union. That is the single largest lever, and it is exactly the "foundation model" thesis: breadth. Three further levers the targets left on the table:

1. Base model age. Centaur is on Llama-3.1 (2024), Socrates on Qwen2.5 / Llama3. Same recipe on a 2026 base is a free, legitimate gain.
2. Objective. All three use token cross-entropy on individual responses (Socrates adds DPO). None optimizes the distributional metric they are scored on. Distribution-matching objectives (soft-label CE, KL to the empirical response distribution, GRPO with a distributional reward) have beaten Centaur-style SFT on choices13k in the literature.
3. Entropy preservation. The alignment-simulation tradeoff (instruction tuning collapses response entropy) is documented on SimBench and OmniBehavior. Starting from a base checkpoint or merging the adapter back at 1:1 keeps the mass-covering behavior that distributional metrics reward.

## 2. Non-negotiable rules

- Leakage registry. Every test item from Psych-101-test, SocSci210 unseen splits and BehaviorBench is hashed (prompt text and source-dataset ID) before any training data is assembled. Training corpus is filtered against the registry, and the filter log is a deliverable. BehaviorBench is built from public source datasets (Big Five test data, published games); we train on those sources only after removing BehaviorBench subjects.
- Their metric, their split, their code where it exists. Centaur's repo, Socrates' released eval, BehaviorBench's submission harness. We do not re-implement a scorer we can run.
- Same weights for all three. Per-benchmark adapters are allowed only as an ablation to quantify negative transfer, never as the headline.
- Every number is paired with the reproduced baseline number on the same hardware and same eval code, in the same table.

## 3. Phases and gates

### Phase 0: reproduce all three baselines (weeks 1-2)

Gate 0: all three reproduced within 2% relative (or documented reason). Output: `results/fm_baselines/`.

See **§8 Phase 0 ops** below for the step-by-step and Colab vs GCP routing.

#### Phase 0 checklist (summary)

- Pull Minitaur (`marcelbinz/Llama-3.1-Minitaur-8B-adapter`) and Psych-101-test. Run NLL on held-out participants. **Centaur-70B deferred / skipped** (user: don't run; needs 80GB anyway).
- Pull Socrates weights (`socratesft/socrates-qwen2.5-14b-sft` and `-dpo`, plus the 8B pair) and SocSci210. Reproduce W = 0.151 on unseen studies. **Run on Colab L4 (4-bit).**
- Pull Be.FM-1.5-4B (`befm/BeFM1.5-4B`) and BehaviorBench harness. Reproduce 4B win rates. **Run on Colab T4.** Defer Be.FM-70B.
- Compute human noise ceilings where the data allows (split-half TVD per study on SocSci210, empirical bound already 0.125).

### Phase 1: unified corpus (weeks 2-5)

Convert everything into the Centaur transcription format (natural-language experiment description, trial-by-trial prompt, response token). Sources, in priority order:

1. Psych-101 train (160 experiments, ~10M choices).
2. SocSci210 train studies (2.9M responses).
3. BehaviorBench source datasets minus held-out subjects (Big Five test, economic games).
4. choices13k, SubPOP, OpinionQA, WVS, SocioBench, SimBench train (distributional targets with group labels).
5. OmniBehavior slices already local (`~/Centaur/colab_minitaur/`) as an extra domain and a fourth eval, not on the critical path.

Each record carries: source, domain tag, individual ID, group/condition ID, and the empirical response distribution for its (study, condition) cell when more than one human answered. Deliverable: dataset card with counts per source and per domain, and the leakage filter log.

### Phase 2: v0, Centaur recipe on the union (weeks 5-9)

- Base: newest strong open base checkpoint at 8B-class (Qwen3-8B-Base or equivalent; decide at kickoff). Base, not instruct.
- Recipe: identical to Centaur (QLoRA all linear, 1 epoch, CE masked to responses, lr 5e-5), only the data changes.
- Runs: (a) Psych-101 only, (b) SocSci210 only, (c) union. Evaluate every run on all three benchmarks.

Gate 1: union at 8B beats at least one target on its home benchmark and does not lose more than the eval noise on the other two versus single-source. If union shows negative transfer, pivot to domain-tagged prompts and data reweighting before touching architecture.

### Phase 3: objective (weeks 9-14)

Ablate on 8B, union data, each evaluated on all three:

- A. Soft-label CE: where a (study, condition) cell has n > 1 humans, target the empirical distribution over options instead of the single sampled response.
- B. KL/TVD auxiliary loss on the option-token distribution, weighted per cell by n.
- C. GRPO with reward = 1 - TVD(model distribution, human distribution) per cell, warm-started from the best SFT run.
- D. DPO contrastive on individual responses (Socrates recipe) for individual-level accuracy.
- E. Sequence: SFT (A+B) then C then D.

Gate 2: distributional metrics (Socrates W, BehaviorBench distributional board) and individual metrics (Psych-101 NLL, BehaviorBench individual board) both improve over v0. If a method trades one for the other, it is reported, not shipped.

### Phase 4: capability and entropy preservation (weeks 14-17)

- Measure response entropy vs. human entropy per cell; measure general capability (MMLU-Pro slice, metabench) and CogBench.
- Compare: base-start vs instruct-start; adapter merge at 1:1 with the instruct model (HumanLLM recipe); small replay of general instruction data.
- BehaviorBench knowledge and workflow tasks are where frontier models win; this phase is what closes the individual-level board.

### Phase 5: scale and ship (weeks 17-22)

- Final recipe at 70B-class (Llama-3.3-70B or Qwen3 large base). One run, seeds fixed, budget below.
- Submit to the BehaviorBench live leaderboard. Publish Psych-101 and SocSci210 tables side by side with reproduced baselines. Report SimBench and OmniBehavior as additional evals.
- Release: weights, dataset card, leakage log, eval scripts. Reproducibility is the credibility of the claim.

## 4. Compute

Local machine is an M4 24 GB; nothing above evaluation of 4B models runs here. Everything trains on rented GPUs.

| Item | Estimate |
|---|---|
| Phase 0 reproduction (70B eval, 3 benchmarks) | 1 x A100-80G, ~3 days |
| Each 8B ablation run (Phases 2-4, ~15 runs) | 1 x A100-80G, 6-24 h each (Socrates runs took 4-24 h at this scale) |
| GRPO runs at 8B | 2-4 x A100, 1-2 days each |
| Final 70B QLoRA on union (~4x Psych-101 tokens) | 8 x H100, 3-5 days |
| Total | roughly 600-900 GPU-hours; low five figures USD at spot pricing |

## 5. Risks and the honest answer to each

- "You just used more data and a newer base." Correct, and that is the thesis. The scientific result is the transfer matrix (Phase 2, runs a/b/c on all three benchmarks): does SocSci210 help Psych-101 OOD? Nobody has measured it.
- Be.FM weights or training data not released. We beat the published leaderboard number via submission. The individual-level board is led by Gemini 3.1 Pro, not Be.FM; beating Be.FM there is easier than beating Gemini, and we set the target as Be.FM only.
- Psych-101-test is gated and ND-licensed. We request access; we never train on it; we do not redistribute it.
- Negative transfer between trial-level cognition data and survey data. Detected at Gate 1; mitigations are domain tags and reweighting, then mixture-of-adapters as a last resort (which weakens the one-model claim and must be disclosed).
- Individual-level metrics may not move at 8B. Scale is the known lever; Phase 5 exists for this.
- Contamination of the base model with published experiment data. Report base-model zero-shot on every benchmark as the floor; if the base already scores anomalously high, say so.

## 6. What is explicitly out of scope until the goal is hit

- Persona steering vectors (Persona Selection Model). Prompting beats steering on published comparisons; park as differentiation after the win.
- OPeRA and the shopping funnel experiment. Product demo, not a cognition benchmark.
- UserSim product surface. It inherits the model once it exists.

## 7. First week, concretely

1. Request Psych-101-test access on HF (`marcelbinz/Psych-101-test`, gated CC-BY-ND). Be.FM-1.5-4B/70B are public on HF (`befm/BeFM1.5-*`); accept Llama 3.3 license for the 70B base.
2. Clone eval repos and pin commits: `marcelbinz/Llama-3.1-Centaur-70B`, `akaashkolluri/socrates`, `umich-foreseer/behaviorbench_eval`.
3. Run the cheap ladder first (§8): Minitaur → Socrates-8B → Be.FM-4B on Colab/L4, then Centaur-70B on A100-80G.
4. Start the leakage registry: hash every test item across all three benchmarks.
5. Write the unified transcription converter for SocSci210 into Centaur format and validate on 5 studies by hand.

## 8. Phase 0 ops: how to reproduce, and which machine

### 8.1 What each baseline needs

| Job | Model | VRAM floor | Est. runtime | Est. cost | Where |
|---|---|---|---|---|---|
| 0a smoke | Minitaur 8B 4-bit | 8–16 GB | 10 min | ~$0 | Colab T4 / local if metal ok |
| 0b Centaur home | Minitaur 8B NLL on Psych-101-test | 16–24 GB | 4–12 h | $5–20 | **Colab** (you already have `~/Centaur/colab_minitaur/`) |
| 0c Socrates home (cheap) | Socrates-Llama-8B-SFT W on SocSci210 unseen | 16–24 GB | 2–8 h | $5–15 | **Colab** or GCP L4 |
| 0d Socrates home (target) | Socrates-Qwen-14B-SFT W = 0.151 | 28–40 GB (4-bit) / ~30 GB bf16 | 4–12 h | $15–40 | Colab A100-40G **or** GCP `a2-highgpu-1g` |
| 0e Be.FM home (required) | Be.FM-1.5-4B on BehaviorBench | 16–24 GB | 2–8 h | $5–20 | **Colab** L4/T4 or GCP `g2-standard-4` (~$0.70/hr) |
| 0f Centaur home (headline) | Centaur-70B adapter 4-bit, Psych-101-test NLL | **80 GB single GPU** (authors' requirement) | 8–24 h | $20–120 | Colab A100-80G **or** GCP `a2-ultragpu-1g` |
| 0g Be.FM-70B (optional) | Be.FM-1.5-70B bf16 | ~140 GB → 2× A100-80G | 8–24 h | $80–250 | **GCP only** (2× `a2-ultragpu`); skip in Phase 0 |

Phase 0 total if you do 0a–0f and skip 0g: roughly **$50–200**. Stays inside the "few hundred dollars" GCP sandbox budget; Colab alone can cover most of it if A100-80G assignment cooperates.

### 8.2 Decision rule: Colab vs GCP

```
DEFAULT FOR PHASE 0 EVALS: Colab T4, 4-bit quantization.
  Be.FM-4B, Minitaur-8B, Socrates-8B/14B (4-bit) all fit T4 (16GB).
  Prefer T4 over L4/A100 to conserve compute units.
  This Colab account currently allows ~2 concurrent GPU assignments.

Centaur 70B 4-bit (needs ~80 GB)
  → Colab A100-80G or GCP a2-ultragpu-1g only. Not T4/L4.

Be.FM 70B or any multi-GPU / multi-day training (Phase 2+)
  → GCP. Keep Colab for eval smokes.
```

**Use Colab T4 as the default for Phase 0.** L4/A100 only if T4 OOMs. Use GCP as failover for Centaur-70B and for training.

### 8.3 Exact artifacts to pull

```
# Centaur / Minitaur
HF: marcelbinz/Llama-3.1-Centaur-70B-adapter   # needs unsloth, 80GB, 4-bit
HF: marcelbinz/Llama-3.1-Minitaur-8B-adapter   # or merged Llama-3.1-Minitaur-8B
HF: marcelbinz/Psych-101                       # train
HF: marcelbinz/Psych-101-test                  # GATED — request access first
Git: github.com/marcelbinz/Llama-3.1-Centaur-70B

# Socrates
HF: socratesft/SocSci210
HF: socratesft/socrates-llama3-8b-sft
HF: socratesft/socrates-llama3-8b-dpo
HF: socratesft/socrates-qwen2.5-14b-sft        # W=0.151 target
HF: socratesft/socrates-qwen2.5-14b-dpo
Git: github.com/akaashkolluri/socrates
Site: stanfordhci.github.io/socrates

# Be.FM / BehaviorBench
HF: befm/BeFM1.5-4B                            # LoRA on Qwen3-4B-Instruct-2507
HF: befm/BeFM1.5-70B                           # optional; LoRA on Llama-3.3-70B-Instruct
HF: befm/BehaviorBench
Git: github.com/umich-foreseer/behaviorbench_eval
Board: umich-foreseer.github.io/behaviorbench
```

Accept Meta Llama licenses on HF before Centaur-70B / Be.FM-70B base downloads work. Put `HF_TOKEN` in the Colab secret / GCP secret manager; never commit it.

### 8.4 Run order (do not skip steps)

**Day 0 — access and disk (laptop, $0)**
1. Request `Psych-101-test` access. Blocker for Centaur numbers.
2. `huggingface-cli login`; accept Llama 3.1 / 3.3 licenses.
3. Clone the three git repos into `~/Centaur/` (or a new `~/behavior-fm/`) and pin SHAs in a `PINS.md`.
4. Hash every test prompt into `results/fm_baselines/leakage_registry.jsonl` (Psych-101-test once approved, SocSci210 eval mappings, BehaviorBench indices). This is also Phase 1 prep; do it while GPUs are idle.

**Day 1 — prove the ladder on cheap GPUs (Colab)**
1. Reuse `~/Centaur/colab_minitaur/setup_minitaur.py`. Smoke: load Minitaur 4-bit, generate one `<<…>>` choice. Already written.
2. Wire Psych-101-test (once approved) into their eval script; compute Minitaur NLL on held-out participants. Save `results/fm_baselines/minitaur_psych101.json`.
3. Load Socrates-8B-SFT; run their unseen-study eval; save Wasserstein + accuracy.
4. Load Be.FM-1.5-4B + `behaviorbench_eval`; produce the JSON the leaderboard expects. Save alongside.

If Day 1 numbers are within ~5% of published for the 8B/4B models, the pipeline is real. Only then spend on 14B / 70B.

**Day 2–3 — Socrates-14B (Colab A100-40G or GCP A100-40G)**
1. Target: W ≈ 0.151 on unseen studies with `socrates-qwen2.5-14b-sft`.
2. Also run the DPO checkpoint; expect better individual accuracy, worse W (paper's finding). Report both.
3. Compute split-half human W as the noise ceiling (paper's empirical best = 0.125).

**Day 3–5 — Centaur-70B (Colab A100-80G preferred; GCP failover)**
1. Load via unsloth exactly as the authors prescribe (`load_in_4bit=True`, 80 GB). Do not use the merged 160 GB path.
2. Run Psych-101-test NLL with their masking (loss only on response tokens inside `<< >>`).
3. Compare per-experiment to paper Table 1. Gate: within 2% relative on the aggregate, or document any experiment that diverges.
4. Optional cheap add-on: CogBench if their script is in the repo; not a Phase 0 blocker.

**Day 5–7 — package Gate 0**
Write `results/fm_baselines/SUMMARY.md` with one table:

| Benchmark | Their published | Our reproduction | Δ | Hardware | Commit |
|---|---|---|---|---|---|

If any cell is blank because access was denied, say so explicitly. Do not invent a proxy metric.

### 8.5 GCP sandbox recipe (when Colab fails)

```bash
# Single A100 80GB for Centaur-70B failover
gcloud compute instances create fm-eval-a100 \
  --zone=us-central1-a \
  --machine-type=a2-ultragpu-1g \
  --accelerator=type=nvidia-tesla-a100,count=1 \
  --boot-disk-size=500GB \
  --boot-disk-type=pd-ssd \
  --maintenance-policy=TERMINATE \
  --provisioning-model=SPOT   # drop SPOT for non-preemptible

# Cheap L4 for Be.FM-4B / Socrates-8B if Colab is busy
gcloud compute instances create fm-eval-l4 \
  --zone=us-central1-a \
  --machine-type=g2-standard-8 \
  --boot-disk-size=200GB
```

Always: attach a persistent disk for HF cache (`~/.cache/huggingface`), so killing the VM does not re-download 140 GB. Delete the VM the moment the JSON is copied to the laptop / GCS. Spot is fine for eval if you write results incrementally every N experiments.

### 8.6 What "reproduced" means operationally

- Same weights ID + revision hash.
- Same split file (SocSci210 `metadata/*_mapping.json`, BehaviorBench `behaviorbench_indices.json`, Psych-101-test as released).
- Same metric code from their repo, not a reimplementation.
- Temperature / sampling: Centaur NLL is deterministic (logprobs). Socrates / Be.FM generation: match their paper settings (Socrates used `temperature=0.6, top_p=0.9`; Be.FM recommends `0.6 / 0.95 / top_k=20`). Seed and average if they did.
- Tolerance: aggregate within 2% relative, or per-experiment Spearman ρ > 0.95 against their Table 1 values.

### 8.7 Kill / escalate rules during Phase 0

- Psych-101-test access denied after 7 days → email Marcel Binz; proceed with Socrates + Be.FM; Centaur gate stays open.
- Colab won't give A100-80G after 48 h of trying → flip Centaur to GCP spot `a2-ultragpu-1g`. Budget ~$40–80 for a full Psych-101-test pass.
- Be.FM-4B numbers match but 70B is needed for a claim → only then spend on 2× A100-80G; otherwise cite the published 70B number and beat the 4B board first.
- Any reproduction off by >5% with no obvious bug → stop and debug before touching Phase 1 data. Wrong baseline poisons the whole program.
