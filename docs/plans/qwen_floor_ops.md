# Qwen floor ops — do not babysit

Canonical protocol: `docs/plans/fm_gpu_eval_protocol.md` (smoke → vLLM max concurrency → watchdog → **use injected GCP secrets**).
This file is the VM-specific notes.

GCP is already on the cloud box (`GOOGLE_APPLICATION_CREDENTIALS_B64` + project env). Never ask for a paste.

Colab Pro (remaining Qwen Be.FM floor — more conservative than GCP):
```bash
# one L4, smoke then vLLM 32, supervisor watchdog. Resume completed tasks.
python3 scripts/fm_baselines/launch_colab_qwen_befm.py
python3 -u scripts/fm_baselines/resilient_fm_supervisor.py --floor-befm
```
Do not run this in parallel with the GCP L4 on the same remaining tasks.

```bash
python3 scripts/fm_baselines/gcp_auth.py --status
python3 scripts/fm_baselines/preflight_gpu_eval.py --vm fm-floor-qwen-l4
python3 scripts/fm_baselines/deploy_qwen_befm_floor.py
```

## Machine
- VM: `fm-floor-qwen-l4` (`g2-standard-8` + L4, Spot)
- Label **required**: `usersim-spot-watch=true` or Eventarc/poller ignore it
- Job: `usersim-floor-befm.service` → `scripts/fm_baselines/colab_qwen3_8b_floor_befm.py`

## Engine
- Server: `vllm.entrypoints.openai.api_server` (`--max-num-seqs 64`)
- Client: BehaviorBench `--concurrency 32`
- Resume: skip any task that already wrote metrics JSON
- `pers_score_pred` already done; do not wipe `results/qwen3_8b_base_befm/full/`

## After preempt (automatic)
1. Eventarc `usersim-spot-preempted` + Cloud Tasks retry start the VM
2. systemd starts the eval; it boots vLLM then continues remaining tasks
3. Laptop/cloud watchdog (`watch_qwen_befm_floor.sh`) is backup: start VM if down, restart unit if dead
4. When `SUMMARY.json` has `complete: true`, watchdog **stops the VM** and drops the label

## You should not
- SSH to check every 20 minutes
- Restart the job by hand unless `PROGRESS.json` is stale >30 min **and** the VM is RUNNING
- Run `qwen_openai_server.py` (transformers) ever again

## Check once
```bash
gcloud compute ssh fm-floor-qwen-l4 --zone="$ZONE" --tunnel-through-iap \
  --command='cat /opt/usersim_fm/results/qwen3_8b_base_befm/PROGRESS.json; tail -5 /opt/usersim_fm/results/qwen_befm_full.log'
```
Expect `engine: vllm` and `Completed N/M` moving in bursts, not 3–4s per call.
