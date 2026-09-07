#!/usr/bin/env python3
"""Standing seed inbox: poll GCS for jobs, warm-CDP first frame, run worker.

No SSH per study — orchestrator only writes inbox/{seed}.json.
Uses the Python GCS client (instance SA) — plain user ``gsutil`` is broken on
these seeds (Permission denied).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HOME", "/home/shreyaspatel"))
ROOT = HOME / "usersim"
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

INBOX_PREFIX = os.environ.get(
    "MVP_SEED_INBOX_PREFIX",
    "gs://usersim-bakeoff-347838016394/mvp_seed_inbox",
)
POLL_S = float(os.environ.get("MVP_SEED_INBOX_POLL_S", "0.4"))


def _seed_name() -> str:
    if os.environ.get("MVP_SEED_NAME"):
        return os.environ["MVP_SEED_NAME"]
    try:
        return subprocess.check_output(
            [
                "curl",
                "-sf",
                "-H",
                "Metadata-Flavor: Google",
                "http://metadata.google.internal/computeMetadata/v1/instance/name",
            ],
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return "usersim-youtube-seed-0"


SEED_NAME = _seed_name()


def _claim_job() -> dict | None:
    from mvp.gcs_store import gcs_download_json, gcs_upload_json
    from google.cloud import storage

    uri = f"{INBOX_PREFIX.rstrip('/')}/{SEED_NAME}.json"
    try:
        job = gcs_download_json(uri)
    except Exception:
        return None
    if not isinstance(job, dict) or not job.get("job_uri"):
        return None
    # Delete claim object.
    try:
        assert uri.startswith("gs://")
        _, rest = uri.split("gs://", 1)
        bkt, name = rest.split("/", 1)
        storage.Client().bucket(bkt).blob(name).delete()
    except Exception as exc:  # noqa: BLE001
        print(f"claim delete failed: {exc}", flush=True)
        # Avoid re-running forever: overwrite with empty marker.
        try:
            gcs_upload_json(uri, {"claimed": True, "ts": time.time()})
        except Exception:
            pass
    return job


def _heartbeat() -> None:
    from mvp.gcs_store import gcs_upload_json

    hb = f"{INBOX_PREFIX.rstrip('/')}/{SEED_NAME}.heartbeat.json"
    gcs_upload_json(hb, {"ts": time.time(), "seed": SEED_NAME})


def _run_job(meta: dict) -> None:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(HOME),
            "JOB_URI": meta["job_uri"],
            "CODE_URI": meta["code_uri"],
            "CODE_SHA": meta.get("code_sha256") or "",
            "GOOGLE_CLOUD_PROJECT": env.get(
                "GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"
            ),
            "GCP_PROJECT": env.get("GCP_PROJECT", "project-amer-scs-sandbox"),
            "DISPLAY": ":99",
            "MVP_WARM_CDP": "http://127.0.0.1:9222",
            "MVP_SKIP_LANDING_FRAME": "1",
            "KEEP_VM": "1",
            "PYTHONPATH": f"{ROOT}/src:{ROOT}",
        }
    )
    script = ROOT / "scripts/vm/seed_hot_run.sh"
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / "inbox_worker.log"
    with log.open("a") as fh:
        fh.write(f"\n==> inbox claim {time.strftime('%FT%TZ')} job={meta.get('job_uri')}\n")
        fh.flush()
        subprocess.run(
            ["bash", str(script)],
            cwd=str(ROOT),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    ensure = ROOT / "scripts/vm/ensure_warm_chromium.sh"
    if ensure.is_file():
        subprocess.run(["bash", str(ensure)], cwd=str(ROOT), check=False)
    print(f"SEED_INBOX listening as {SEED_NAME} on {INBOX_PREFIX}", flush=True)
    while True:
        try:
            _heartbeat()
            meta = _claim_job()
            if meta:
                print(f"SEED_INBOX claimed {meta.get('job_uri')}", flush=True)
                _run_job(meta)
        except Exception as exc:  # noqa: BLE001
            print(f"SEED_INBOX error: {exc}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
