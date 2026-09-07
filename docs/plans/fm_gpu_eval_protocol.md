# FM GPU eval protocol (mandatory)

Every agent, every GPU job (floor, baseline, finetune eval). No exceptions.

## 1. Smoke first
Run a **small representative slice** of the **same harness, same parse, same output JSON**.
Do not start the full job until smoke writes `SMOKE_OK.json` with:
- valid schema (harness keys present)
- at least one non-null parsed score
- `engine: vllm`

If parse/format is wrong, **stop**. Do not burn a full run.

## 2. vLLM only, max concurrency
- Serve with `vllm.entrypoints.openai.api_server` (or in-process `vllm.LLM` for NLL).
- Client `--concurrency` **≥ 32**.
- vLLM `--max-num-seqs` **≥ 64**.
- **Forbidden:** transformers `generate` loops, FastAPI toy servers, `--concurrency 1`.

## 3. Watchdog before any long job
- VM label `usersim-spot-watch=true` (Eventarc + poller ignore unlabeled VMs).
- systemd unit enabled so boot after preempt resumes the job.
- Confirm `fm-gate0-spot-watchdog` is RUNNING, or start `watch_qwen_befm_floor.sh`.
- Full run **refuses** if watchdog is not armed.

## Agent command
```bash
# on the GPU VM
MODE=smoke python3 -u scripts/fm_baselines/colab_qwen3_8b_floor_befm.py
# only after SMOKE_PASSED:
MODE=full  python3 -u scripts/fm_baselines/colab_qwen3_8b_floor_befm.py
```

Laptop/cloud agent preflight (labels + watchdog):
```bash
python3 scripts/fm_baselines/preflight_gpu_eval.py --vm fm-floor-qwen-l4
```

## Do not
- Skip smoke because “we already know the format”
- Run full overnight on HF generate
- Start a Spot GPU without the watch label
