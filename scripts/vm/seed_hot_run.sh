#!/usr/bin/env bash
# Hot path on a standing seed: reuse warm CDP Chromium, skip code pull when hash
# matches, push first screenshot ASAP, then run the full agent worker.
set -euo pipefail
export HOME="${HOME:-/home/shreyaspatel}"
cd "$HOME/usersim"
mkdir -p "$HOME/usersim/logs"

JOB_URI="${JOB_URI:?}"
CODE_URI="${CODE_URI:?}"
CODE_SHA="${CODE_SHA:-}"

# Avoid pkill patterns that match this script's own argv.
if [[ -f "$HOME/usersim/logs/worker.pid" ]]; then
  kill "$(cat "$HOME/usersim/logs/worker.pid")" 2>/dev/null || true
fi

# User gsutil is broken on these VMs — pull via Python ADC (instance SA).
.venv/bin/python - <<PY
import json, os
from pathlib import Path
from mvp.gcs_store import gcs_download_json
from google.cloud import storage

job_uri = os.environ["JOB_URI"]
code_uri = os.environ["CODE_URI"]
code_sha = os.environ.get("CODE_SHA") or ""
job = gcs_download_json(job_uri)
job_path = Path("/tmp/usersim_inbox_job.json")
job_path.write_text(json.dumps(job, default=str))
# Keep a convenience copy when writable.
try:
    Path("job.json").write_text(job_path.read_text())
except Exception:
    pass
if not code_sha:
    code_sha = (job or {}).get("code_sha256") or ""
need = True
marker = Path(".payload.sha256")
if code_sha and marker.is_file() and marker.read_text().strip() == code_sha and Path("scripts/vm/fast_first_frame.py").is_file():
    need = False
    print(f"SKIP_PAYLOAD sha={code_sha}", flush=True)
if need:
    print("PULL_PAYLOAD", flush=True)
    assert code_uri.startswith("gs://")
    _, rest = code_uri.split("gs://", 1)
    bkt, name = rest.split("/", 1)
    storage.Client().bucket(bkt).blob(name).download_to_filename("/tmp/usersim_payload.tgz")
    import tarfile
    with tarfile.open("/tmp/usersim_payload.tgz", "r:gz") as tar:
        tar.extractall()
    if code_sha:
        try:
            marker.write_text(code_sha)
        except Exception:
            Path("/tmp/usersim_payload.sha256").write_text(code_sha)
print(f"JOB_PATH={job_path}", flush=True)
PY

export MVP_SKIP_APT=1
export MVP_BROWSER_CHANNEL=0
export MVP_CHROMIUM_NO_SANDBOX=1
export MVP_FORCE_LOCAL_BROWSER=1
export MVP_BROWSER_HEADLESS=0
export BROWSER_HEADLESS=0
export DISPLAY=:99
export KEEP_VM=1
export MVP_WARM_CDP=http://127.0.0.1:9222
export MVP_SKIP_LANDING_FRAME=1
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-project-amer-scs-sandbox}"
export GCP_PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
export PYTHONPATH="$HOME/usersim/src:$HOME/usersim"
unset CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE || true
unset GOOGLE_APPLICATION_CREDENTIALS || true

chmod +x scripts/vm/ensure_warm_chromium.sh scripts/vm/mvp_study_worker.sh 2>/dev/null || true
bash scripts/vm/ensure_warm_chromium.sh

JOB_FILE=/tmp/usersim_inbox_job.json
[[ -f job.json ]] && JOB_FILE=job.json
# Drop stale live frames so SSH relay cannot grab a prior study's PNG.
rm -f "$HOME/usersim/live"/*/step_0.png "$HOME/usersim/live"/*/step_0.ready "$HOME/usersim/live"/*/step_0.json 2>/dev/null || true
.venv/bin/python scripts/vm/fast_first_frame.py --job "$JOB_FILE"
echo FAST_FRAME_DONE

# Worker still expects job.json in cwd — symlink if needed.
if [[ ! -w job.json ]]; then
  ln -sfn /tmp/usersim_inbox_job.json job.json 2>/dev/null || cp -f /tmp/usersim_inbox_job.json /tmp/job.json
  export MVP_JOB_JSON=/tmp/usersim_inbox_job.json
fi
bash scripts/vm/mvp_study_worker.sh
