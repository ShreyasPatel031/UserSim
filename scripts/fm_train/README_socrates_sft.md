# Socrates QLoRA SFT — how the run is wired

Goal: fine-tune `Qwen/Qwen3-8B-Base` on the 170 *seen* SocSci210 studies and
beat the paper's mean Wasserstein of 0.151 on the 40 unseen studies, measured
by the same runner that produced our base floor.

## Pieces

| File | Role |
|---|---|
| `socrates_format.py` | The only definition of the prompt format: system string, message list, prompt rendering, target rendering |
| `build_socrates_sft_corpus.py` | Streams the HF dataset, keeps seen studies, caps participants per (study, condition, task), asserts zero unseen rows |
| `sft_socrates_qlora.py` | 4-bit QLoRA trainer; labels masked to the response; heartbeat file; aborts on non-finite loss |
| `smoke_socrates_sft.py` | Format gate — parses `SYSTEM` out of the eval runner and checks the training tensors against the eval prompt |
| `boot_socrates_sft.py` | Staged driver with stamps: install, train venv, smoke corpus, format gate, 20-step train, 1-study eval, full corpus, full epoch, full eval |
| `sft_watchdog.py` | One poll per systemd timer tick; writes `WATCHDOG.json`, and `ALERT.json` on divergence, OOM, restart loops or a stalled stage |

`../fm_baselines/colab_qwen3_8b_floor_socrates_vllm.py` scores both the base
floor and the adapter: set `LORA_PATH` to serve the adapter through vLLM and
`RESULTS_DIR` to keep predictions separate.

## Why train and eval formats cannot drift

`smoke_socrates_sft.py` reads the eval runner's source, extracts its `SYSTEM`
literal, and fails if it differs from `socrates_format.SYSTEM` or if the runner
stops building `[system, user]` messages with `add_generation_prompt=True`. It
then asserts, on real corpus rows, that prompt tokens are fully masked, that
every response token is supervised, and that decoding the unmasked positions
returns the human response.

## Running it

```bash
# One VM, staged, resumable. Stop early with STOP_AFTER=<stage>.
ROOT=/opt/usersim_fm PYTHONPATH=$ROOT/scripts/fm_train \
  MAX_PER_CELL=32 MICRO_BATCH=2 GRAD_ACCUM=32 MAX_SEQ=1536 \
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  python3 -u scripts/fm_train/boot_socrates_sft.py
```

On GCP this runs as `usersim-sft-socrates.service` with
`usersim-sft-watchdog.timer` polling every 5 minutes. Preemption is handled by
three independent layers: the spot watchdog VM restarts the instance, the
instance's startup script re-enables both units, and the driver skips stamped
stages while the Trainer resumes from its newest checkpoint.

## Environment notes (learned the hard way)

- Use the DLVM `pytorch-*-nvidia-580` image; the plain Ubuntu image fails to
  build the NVIDIA kernel module.
- Install `ninja`, or flashinfer cannot JIT its sampling kernels and vLLM dies
  during engine init.
- Installing vLLM upgrades torch past the image's torchaudio and pulls
  transformers 5.x, which current peft cannot import. Hence the separate
  training venv and the torchaudio removal in the install stage.
- Colab is not an option from a cloud agent with service-account credentials:
  only T4 is entitled, and L4/A100/G4 requests are rejected.
