# Qwen3-8B-Base floor — no-babysit ops

## Rule
If a GPU job is not **vLLM + systemd + `usersim-spot-watch=true` + local watchdog**, it is not running.

## Floor Be.FM (this job)
- VM: `fm-floor-qwen-l4` (Spot L4, us-central1-a)
- Engine: **vLLM OpenAI server**, `--max-num-seqs 64`
- Eval: BehaviorBench `--concurrency 32`
- Resume: skip any task that already has a result JSON
- Boot: `usersim-floor-befm.service` (enabled)
- Spot revive: label `usersim-spot-watch=true` + Eventarc/poller
- Laptop backup: `scripts/fm_baselines/watch_qwen_befm_floor.sh` (launchd or nohup)

Done signal: `results/qwen3_8b_base_befm/SUMMARY.json` with `complete: true`. Then **stop the VM**.

## Do not
- Serve with transformers `generate` + concurrency 1
- `nohup` without systemd
- Start a Spot GPU without the watch label
- Trust a Cursor chat to keep the job alive

## Check (one command)
```bash
gcloud compute ssh fm-floor-qwen-l4 --zone=us-central1-a --project=project-amer-scs-sandbox --tunnel-through-iap --command='systemctl is-active usersim-floor-befm; cat /opt/usersim_fm/results/qwen3_8b_base_befm/PROGRESS.json'
```
