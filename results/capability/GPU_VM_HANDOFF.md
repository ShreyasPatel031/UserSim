# GPU VM handoff — CUA bakeoff

## Connect
```bash
export CLOUDSDK_CORE_PROJECT=project-amer-scs-sandbox
export ZONE=us-central1-a
export VM=oprior-1787208583-uscentral1a

gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap
gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --command='nvidia-smi'
```

## Layout
| Path | Owner | Notes |
|------|-------|-------|
| `~/op/` | **DO NOT TOUCH** | Existing opposite-prior / IPIP job (venv, vectors, results) |
| `~/usersim/` | CUA bakeoff | Fara / UI-TARS work lives here |

## Rules
- Don't `pkill -f python` — use PID / unique pattern
- Don't delete the VM or `allow-iap-ssh` firewall tag
- Don't set heavy batches that OOM the T4 (16GB)
- Prefer **Fara1.5-4B** on T4; 7B only with 4-bit quantization

## Verified 2026-08-21
- Tesla T4, 15360 MiB, **0 MiB used**, GPU free
- Disk: ~73G free on `/`
- IAP SSH works from cloud agent as `shreyas.patel@searce.com`
