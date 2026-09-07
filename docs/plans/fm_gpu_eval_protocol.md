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
- If a concurrency-1 job is already running, **kill it**. Do not attach, resume, or “just let it finish.” Resume remaining tasks on vLLM at concurrency ≥ 32.
- L4 + vLLM 0.28 needs `ninja` on PATH (`apt-get install ninja-build`) or FlashInfer warmup dies.

## 3. Use injected GCP secrets — never ask the user
Cloud-agent boxes **already have the key**. `GOOGLE_APPLICATION_CREDENTIALS` is often a **15-char stub path that does not exist**. That is not “no creds.” The real key is `GOOGLE_APPLICATION_CREDENTIALS_B64`.

**Do not say “no GCP creds.” Do not ask anyone to paste a project id, key, or zone.**

| What | Env (already a secret) |
|---|---|
| Project | `CLOUDSDK_CORE_PROJECT` / `GOOGLE_CLOUD_PROJECT` / `GCP_PROJECT` / `GCLOUD_PROJECT` |
| Stub path (may be missing) | `GOOGLE_APPLICATION_CREDENTIALS` |
| Actual service-account JSON | `GOOGLE_APPLICATION_CREDENTIALS_B64` (or `_JSON`) → write ADC, then `gcloud auth activate-service-account` |
| GPU zone | `ZONE` / `GCP_ZONE` (fleet default if unset) |
| Watchdog VM zone | `WATCHDOG_ZONE` |

```bash
python3 scripts/fm_baselines/gcp_auth.py --status   # names only, never dumps the key
python3 scripts/fm_baselines/preflight_gpu_eval.py --vm fm-floor-qwen-l4
```

`scripts/fm_baselines/gcp_auth.py` + `protocol.require_injected_gcp()` do this.

## 4. Watchdog before any long job
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

Laptop/cloud agent preflight (reads secrets itself):
```bash
python3 scripts/fm_baselines/preflight_gpu_eval.py --vm fm-floor-qwen-l4
```

## Do not
- Skip smoke because “we already know the format”
- Run full overnight on HF generate
- Start a Spot GPU without the watch label
- Tell the user there are no GCP creds, or ask them to paste project/key/zone
- Hardcode secret values into git (use env names only)
