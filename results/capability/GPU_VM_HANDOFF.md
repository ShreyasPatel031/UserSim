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

## Verified 2026-08-22
- Tesla T4, 15360 MiB, **0 MiB used**, GPU free
- Disk: ~67G free on `/`
- IAP SSH works from cloud agent as `shreyas.patel@searce.com`
- VM **RUNNING** (`35.194.10.67`)

## Models on VM (from GCS)
```bash
gsutil -m cp -r gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Fara1.5-4B ~/usersim/models/
gsutil -m cp -r gs://ai-studio-bucket-347838016394-us-east1/usersim-models/OpenWebRL-4B ~/usersim/models/
```

## Serve + smoke (T4-safe settings)
```bash
# Copy scripts from repo: scripts/vm/serve_fara.sh, smoke_vllm.py
bash ~/usersim/scripts/serve_fara.sh   # port 8000
python ~/usersim/scripts/smoke_vllm.py --base-url http://127.0.0.1:8000/v1
```

Colab alternative: `notebooks/colab_cua_models.ipynb`
