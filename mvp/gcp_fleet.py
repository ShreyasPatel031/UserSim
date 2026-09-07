"""GCP Spot fleet from seed image — production path for live MVP studies.

Creates Spot copies from ``usersim-mvp-seed`` image family, writes the job to
GCS, lets each copy self-bootstrap (pull code + job, run headed Chromium under
Xvfb, stream frames, self-delete). Works from Vercel via client libraries
(no ``gcloud`` binary, no long-lived SSH).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import re

from mvp.gcs_store import (
    DEFAULT_GCS,
    gcs_download_bytes,
    gcs_download_json,
    gcs_upload_file,
    gcs_upload_json,
    screenshot_gcs_uri,
    study_gcs_root,
    write_study_state,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = (
    os.environ.get("GCP_PROJECT")
    or os.environ.get("GOOGLE_CLOUD_PROJECT")
    or "project-amer-scs-sandbox"
)
DEFAULT_ZONE = os.environ.get("GCP_ZONE", "us-central1-b")
DEFAULT_ZONES = [
    z.strip()
    for z in os.environ.get(
        "MVP_GCP_ZONES",
        "us-central1-a,us-central1-b,us-central1-c,us-central1-f",
    ).split(",")
    if z.strip()
]
DEFAULT_MACHINE = os.environ.get("MVP_GCP_MACHINE", "e2-standard-8")
IMAGE_FAMILY = os.environ.get("MVP_GCP_IMAGE_FAMILY", "usersim-mvp-seed")
IMAGE_PROJECT = os.environ.get("MVP_GCP_IMAGE_PROJECT") or DEFAULT_PROJECT
WORKERS_DEFAULT = int(os.environ.get("MVP_GCP_WORKERS", "8"))
PER_STUDY_VM_CAP = int(os.environ.get("MVP_GCP_MAX_VMS_PER_STUDY", "12"))
GLOBAL_VM_CAP = int(os.environ.get("MVP_GCP_MAX_VMS_GLOBAL", "40"))
FLEET_TTL_MIN = int(os.environ.get("MVP_GCP_FLEET_TTL_MIN", "25"))
INSTANCE_PREFIX = "usersim-mvp-"
SEED_PREFIX = os.environ.get("MVP_GCP_SEED_PREFIX", "usersim-youtube-seed-")
USE_WARM_SEEDS = os.environ.get("MVP_GCP_USE_SEEDS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
# Pack the full study onto standing seeds (warm CDP) before creating Spot copies.
# Local default: seed-only so we never cold-boot Chromium when a seed is up.
# Set MVP_GCP_ALLOW_SPOT=1 to spill overflow shards onto Spot copies.
def _allow_spot_copies() -> bool:
    raw = os.environ.get("MVP_GCP_ALLOW_SPOT", "").strip().lower()
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    # Vercel: Spot OK for parallel. Local laptop: stay on warm seed.
    return bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))


# Concurrent Browser-use agents per warm seed. CDP Chromium is one process —
# keep this at 1 unless you know the seed can host multiple contexts.
SEED_WORKERS = max(1, int(os.environ.get("MVP_GCP_SEED_WORKERS", "1")))
NETWORK = os.environ.get("MVP_GCP_NETWORK", "main-vpc")
SUBNET = os.environ.get("MVP_GCP_SUBNET", "primary-subnet")
# Copies carry no key file, so Vertex + GCS access comes entirely from the
# attached service account via the metadata server.
SERVICE_ACCOUNT = os.environ.get(
    "MVP_GCP_SERVICE_ACCOUNT",
    "usersim-cloud-agent@project-amer-scs-sandbox.iam.gserviceaccount.com",
).strip()


def _pack_tasks_onto_seeds(
    tasks: list[dict[str, Any]], n_seeds: int
) -> list[list[dict[str, Any]]]:
    """Round-robin tasks across standing seeds (all on warm CDP, no Spot)."""
    n = max(1, min(n_seeds, len(tasks) or 1))
    shards: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    for i, task in enumerate(tasks):
        shards[i % n].append(task)
    return [s for s in shards if s]


def gcp_fleet_enabled() -> bool:
    raw = os.environ.get("MVP_GCP_FLEET", "").strip().lower()
    if raw in {"0", "false", "no"}:
        return False
    if os.environ.get("MVP_SNAPSHOT_ONLY", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True
    # Prefer fleet whenever the seed image family is configured and we have creds.
    if not IMAGE_FAMILY:
        return False
    sa = ROOT / "secrets" / "sa.json"
    if sa.is_file() or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
        "VERTEX_ADC_JSON"
    ):
        return True
    # Local with gcloud still OK as last resort.
    import shutil

    return shutil.which("gcloud") is not None


def _adc_env() -> None:
    sa = ROOT / "secrets" / "sa.json"
    if sa.is_file() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
    try:
        from auth import _materialize_adc_from_env

        _materialize_adc_from_env()
    except Exception:
        pass


def _instances_client():
    from google.cloud import compute_v1

    _adc_env()
    return compute_v1.InstancesClient()


def _images_client():
    from google.cloud import compute_v1

    _adc_env()
    return compute_v1.ImagesClient()


def _pack_payload(dest: Path) -> Path:
    """Code-only tarball — no SA keys / identity vault (injected via instance SA + Secret Manager)."""
    tar_path = dest / "usersim-mvp-fleet.tgz"
    include_files = [
        "pyproject.toml",
        "scripts/vm/mvp_study_worker.sh",
        "scripts/vm/mvp_study_worker.py",
        "scripts/vm/ensure_warm_chromium.sh",
        "scripts/vm/fast_first_frame.py",
        "scripts/vm/seed_hot_run.sh",
        "scripts/vm/seed_inbox_daemon.py",
    ]
    # Minimal env stub (no secrets). Full Vertex ADC comes from instance metadata SA.
    secrets_env = ROOT / "secrets" / "env"
    include_dirs = ["src", "mvp"]
    exclude_dir_parts = {
        "runs",
        "__pycache__",
        ".venv",
        "bakeoff_data",
        "video_data",
        "node_modules",
        "product_profiles",
        "youtube_browser_profile",
    }
    secret_basenames = {
        "sa.json",
        "credentials.json",
        "identities.json",
        "vertex_adc.json",
        "youtube_storage_state.json",
        "youtube_storage_state.json.signed",
    }

    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(tarinfo.name).parts
        if any(p in exclude_dir_parts for p in parts):
            return None
        if Path(tarinfo.name).name in secret_basenames:
            return None
        if tarinfo.name.endswith((".pyc", ".png", ".jpg", ".jpeg", ".webp", ".mp4")):
            if "static" not in parts:
                return None
        return tarinfo

    with tarfile.open(tar_path, "w:gz") as tar:
        for rel in include_files:
            path = ROOT / rel
            if path.exists():
                tar.add(path, arcname=rel)
        if secrets_env.is_file():
            # Filter out lines that look like passwords / API keys — keep project ids.
            safe_lines = []
            for line in secrets_env.read_text().splitlines():
                low = line.lower()
                if any(k in low for k in ("password", "secret", "api_key", "token=", "private")):
                    continue
                safe_lines.append(line)
            stub = dest / "secrets_env"
            stub.write_text("\n".join(safe_lines) + "\n")
            tar.add(stub, arcname="secrets/env")
        for rel in include_dirs:
            path = ROOT / rel
            if path.exists():
                tar.add(path, arcname=rel, filter=_filter)
    return tar_path


def _startup_script(
    *,
    gcs_root: str,
    code_uri: str,
    job_uri: str,
    ttl_min: int,
    keep_vm: bool = False,
) -> str:
    seed_profile = "1" if os.environ.get("MVP_SEED_PROFILE", "").lower() in {"1", "true", "yes"} else "0"
    keep = "1" if keep_vm else "0"
    # Warm seeds stay up for the next run; Spot copies still get a hard TTL.
    ttl_line = (
        "echo 'KEEP_VM seed — skipping absolute TTL poweroff'"
        if keep_vm
        else f"shutdown -h +{ttl_min} || true"
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail
exec > >(tee -a /var/log/usersim-mvp-worker.log) 2>&1
echo "==> usersim MVP fleet startup $(date -u +%FT%TZ) keep_vm={keep}"
{ttl_line}
export DEBIAN_FRONTEND=noninteractive
export HOME=/home/$(id -un 2>/dev/null || echo shreyaspatel)
# Prefer the first non-root login home if present.
if [[ -d /home/shreyaspatel ]]; then export HOME=/home/shreyaspatel; fi
mkdir -p "$HOME/usersim"
cd "$HOME/usersim"
# Pull current code + job from GCS (image never goes stale).
if command -v gsutil >/dev/null 2>&1; then
  gsutil -q cp "{code_uri}" payload.tgz
  gsutil -q cp "{job_uri}" job.json
else
  python3 - <<'PY'
from google.cloud import storage
import os
client = storage.Client()
def pull(uri, dest):
    assert uri.startswith("gs://")
    _, rest = uri.split("gs://", 1)
    bkt, name = rest.split("/", 1)
    client.bucket(bkt).blob(name).download_to_filename(dest)
pull("{code_uri}", "payload.tgz")
pull("{job_uri}", "job.json")
PY
fi
tar xzf payload.tgz
export MVP_SKIP_APT=1
export MVP_BROWSER_CHANNEL=0
export MVP_CHROMIUM_NO_SANDBOX=1
export MVP_FORCE_LOCAL_BROWSER=1
export MVP_BROWSER_HEADLESS=0
export BROWSER_HEADLESS=0
export DISPLAY=:99
export MVP_SEED_PROFILE={seed_profile}
export KEEP_VM={keep}
export GOOGLE_CLOUD_PROJECT={DEFAULT_PROJECT}
export GCP_PROJECT={DEFAULT_PROJECT}
export PYTHONPATH="$HOME/usersim/src:$HOME/usersim"
# Auth: instance service account ADC — do not expect secrets/sa.json on disk.
unset CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE || true
chmod +x scripts/vm/mvp_study_worker.sh
bash scripts/vm/mvp_study_worker.sh
"""


def _list_seed_instances(project: str) -> list[tuple[Any, str]]:
    """Standing youtube/signup seeds — never deleted by the fleet reaper."""
    from google.cloud import compute_v1

    client = _instances_client()
    out: list[tuple[Any, str]] = []
    for zone_path, scoped in client.aggregated_list(project=project):
        for inst in scoped.instances or []:
            name = inst.name or ""
            if not name.startswith(SEED_PREFIX):
                continue
            zone = zone_path.split("/")[-1] if zone_path else ""
            out.append((inst, zone))
    # Prefer already-RUNNING (warm), then TERMINATED (cheap start).
    order = {"RUNNING": 0, "STAGING": 1, "PROVISIONING": 2, "TERMINATED": 3, "STOPPED": 3}
    out.sort(key=lambda pair: (order.get((pair[0].status or "").upper(), 9), pair[0].name or ""))
    return out


def _seed_has_usable_sa(inst: Any) -> bool:
    """True if the seed can auth to GCS/Vertex via the metadata server."""
    accounts = list(getattr(inst, "service_accounts", None) or [])
    if not accounts:
        return False
    email = (getattr(accounts[0], "email", None) or "").strip().lower()
    # Empty / missing email means no usable identity.
    return bool(email)


def _ensure_seed_service_account(
    *,
    client: Any,
    name: str,
    zone: str,
    project: str,
    inst: Any,
) -> Any:
    """Attach cloud-platform SA so seeds can pull payload + write frames.

    GCE only allows changing the service account while the VM is stopped.
    """
    from google.cloud import compute_v1

    if _seed_has_usable_sa(inst):
        return inst

    status = (inst.status or "").upper()
    if status in {"RUNNING", "STAGING", "PROVISIONING"}:
        op = client.stop(project=project, zone=zone, instance=name)
        op.result(timeout=300)
        inst = client.get(project=project, zone=zone, instance=name)

    sa_email = SERVICE_ACCOUNT or "default"
    req = compute_v1.InstancesSetServiceAccountRequest(
        email=sa_email,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    try:
        op = client.set_service_account(
            project=project,
            zone=zone,
            instance=name,
            instances_set_service_account_request_resource=req,
        )
        op.result(timeout=180)
    except Exception as exc:  # noqa: BLE001
        # Fall back to project default compute SA if actAs is denied.
        if sa_email != "default" and "actAs" in str(exc):
            req = compute_v1.InstancesSetServiceAccountRequest(
                email="default",
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            op = client.set_service_account(
                project=project,
                zone=zone,
                instance=name,
                instances_set_service_account_request_resource=req,
            )
            op.result(timeout=180)
        else:
            raise
    return client.get(project=project, zone=zone, instance=name)


def _gcloud_bin() -> str | None:
    import shutil

    return shutil.which("gcloud")


def _ssh_wait_first_frame(
    *,
    name: str,
    zone: str,
    project: str,
    study_id: str,
    agent_id: str,
    gcs_root: str,
    timeout_s: float = 45.0,
) -> dict[str, Any] | None:
    """Poll tiny GCS ready marker, then one IAP SCP of the PNG — no SSH probe storm.

    Seeds write step_0.ready.json immediately after the local PNG; we SCP once.
    """
    gcloud = _gcloud_bin()
    if not gcloud:
        return None

    ready_uri = f"{gcs_root.rstrip('/')}/live/{agent_id}/step_0.ready.json"
    deadline = time.time() + timeout_s
    meta: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            data = gcs_download_json(ready_uri)
        except Exception:
            data = None
        if isinstance(data, dict) and str(data.get("study_id") or "") == study_id:
            meta = data
            break
        time.sleep(0.35)
    else:
        print(f"gcs live-ready timeout ({timeout_s}s) {ready_uri}", flush=True)
        return None

    remote_png = f"/home/shreyaspatel/usersim/live/{agent_id}/step_0.png"
    env = os.environ.copy()
    sa = ROOT / "secrets" / "sa.json"
    if sa.is_file():
        env.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", str(sa))
        env.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

    with tempfile.TemporaryDirectory(prefix="usersim-live-") as td:
        local_png = Path(td) / "step_0.png"
        try:
            scp = subprocess.run(
                [
                    gcloud,
                    "compute",
                    "scp",
                    f"{name}:{remote_png}",
                    str(local_png),
                    f"--zone={zone}",
                    f"--project={project}",
                    "--tunnel-through-iap",
                    "--quiet",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"scp live-frame failed: {exc}", flush=True)
            return None
        if scp.returncode != 0 or not local_png.is_file():
            print(f"scp live-frame miss: {(scp.stderr or scp.stdout or '')[-300:]}", flush=True)
            return None
        png = local_png.read_bytes()
        # Prefer richer local companion JSON when present.
        remote_json = f"/home/shreyaspatel/usersim/live/{agent_id}/step_0.json"
        local_json = Path(td) / "step_0.json"
        try:
            scp_json = subprocess.run(
                [
                    gcloud,
                    "compute",
                    "scp",
                    f"{name}:{remote_json}",
                    str(local_json),
                    f"--zone={zone}",
                    f"--project={project}",
                    "--tunnel-through-iap",
                    "--quiet",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if scp_json.returncode == 0 and local_json.is_file():
                meta = {**meta, **json.loads(local_json.read_text())}
        except Exception:  # noqa: BLE001
            pass
    if len(png) < 100:
        return None
    from mvp.live_frames import publish_live_frame

    step = {
        "step": 0,
        "action": meta.get("action")
        or "Landed on page — live relay first frame",
        "observation": meta.get("observation") or "Live frame via SSH relay",
        "url": meta.get("url") or "",
        "screenshot_url": f"/api/studies/{study_id}/agents/{agent_id}/screenshots/step_0.png",
        "boxes": meta.get("boxes") or [],
        "outcome": meta.get("outcome") or "easy",
        "evidence_label": meta.get("evidence_label")
        or "Landing frame · live SSH relay",
    }
    return publish_live_frame(
        study_id=study_id, agent_id=agent_id, step=step, png=png
    )



def _dispatch_seed_inbox(
    *,
    name: str,
    code_uri: str,
    job_uri: str,
    code_sha256: str = "",
) -> bool:
    """Enqueue job for a standing seed inbox daemon (no SSH). Returns False if unavailable."""
    inbox = (
        os.environ.get("MVP_SEED_INBOX_PREFIX")
        or "gs://usersim-bakeoff-347838016394/mvp_seed_inbox"
    )
    uri = f"{inbox.rstrip('/')}/{name}.json"
    payload = {
        "job_uri": job_uri,
        "code_uri": code_uri,
        "code_sha256": code_sha256,
        "enqueued_at": time.time(),
    }
    try:
        gcs_upload_json(uri, payload)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"seed inbox enqueue failed ({exc})", flush=True)
        return False


def _seed_inbox_alive(name: str) -> bool:
    """True if the seed recently heartbeated (optional; best-effort)."""
    inbox = (
        os.environ.get("MVP_SEED_INBOX_PREFIX")
        or "gs://usersim-bakeoff-347838016394/mvp_seed_inbox"
    )
    hb = f"{inbox.rstrip('/')}/{name}.heartbeat.json"
    try:
        data = gcs_download_json(hb)
        if not isinstance(data, dict):
            return False
        ts = float(data.get("ts") or 0)
        return (time.time() - ts) < 30
    except Exception:
        return False


def _dispatch_seed_hot(
    *,
    name: str,
    zone: str,
    project: str,
    code_uri: str,
    job_uri: str,
    code_sha256: str = "",
) -> None:
    """Fire-and-forget hot job on a RUNNING seed (IAP SSH).

    SSH returns as soon as the remote runner is spawned so the orchestrator can
    poll GCS while warm-CDP first-frame uploads. Standing Chromium is reused.
    """
    import base64
    import textwrap

    gcloud = _gcloud_bin()
    if not gcloud:
        raise RuntimeError("gcloud not available for hot seed dispatch")

    assert job_uri.startswith("gs://")
    sha = code_sha256 or ""
    bootstrap = textwrap.dedent(
        f"""\
        set -euo pipefail
        export HOME=/home/shreyaspatel
        mkdir -p "$HOME/usersim/scripts/vm"
        cd "$HOME/usersim"
        if [[ ! -f scripts/vm/seed_hot_run.sh ]]; then
          gsutil -q cp '{code_uri}' payload.tgz
          tar xzf payload.tgz
          [[ -n '{sha}' ]] && echo '{sha}' > .payload.sha256
        fi
        chmod +x scripts/vm/seed_hot_run.sh scripts/vm/ensure_warm_chromium.sh 2>/dev/null || true
        nohup env JOB_URI='{job_uri}' CODE_URI='{code_uri}' CODE_SHA='{sha}' \\
          GOOGLE_CLOUD_PROJECT='{DEFAULT_PROJECT}' GCP_PROJECT='{DEFAULT_PROJECT}' \\
          bash scripts/vm/seed_hot_run.sh >> "$HOME/usersim/worker.log" 2>&1 &
        echo HOT_DISPATCH_PID=$!
        """
    )
    b64 = base64.b64encode(bootstrap.encode()).decode()
    ssh_cmd = f"sudo bash -c 'echo {b64} | base64 -d | bash'"
    env = os.environ.copy()
    sa = ROOT / "secrets" / "sa.json"
    if sa.is_file():
        env.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", str(sa))
        env.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
    proc = subprocess.run(
        [
            gcloud,
            "compute",
            "ssh",
            name,
            f"--zone={zone}",
            f"--project={project}",
            "--tunnel-through-iap",
            "--quiet",
            f"--command={ssh_cmd}",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or "HOT_DISPATCH_PID=" not in out:
        raise RuntimeError(
            f"hot seed dispatch failed rc={proc.returncode}: {out[-1200:]}"
        )


def _boot_seed_with_startup(
    *,
    name: str,
    zone: str,
    project: str,
    startup_script: str,
    code_uri: str = "",
    job_uri: str = "",
    code_sha256: str = "",
) -> None:
    """Attach startup-script (+ SA if missing) and start/reset a standing seed.

    If the seed is already RUNNING and ``code_uri``/``job_uri`` are set, prefer
    hot IAP-SSH dispatch (no reboot). Fall back to reset only if hot fails.
    """
    from google.cloud import compute_v1

    client = _instances_client()
    inst = client.get(project=project, zone=zone, instance=name)
    # Seeds baked without an SA cannot pull GCS payload (401 anonymous).
    inst = _ensure_seed_service_account(
        client=client, name=name, zone=zone, project=project, inst=inst
    )

    status = (inst.status or "").upper()
    if status == "RUNNING" and code_uri and job_uri:
        # Prefer inbox daemon (no SSH) when it is heartbeating.
        if _seed_inbox_alive(name) and _dispatch_seed_inbox(
            name=name,
            code_uri=code_uri,
            job_uri=job_uri,
            code_sha256=code_sha256,
        ):
            return
        try:
            _dispatch_seed_hot(
                name=name,
                zone=zone,
                project=project,
                code_uri=code_uri,
                job_uri=job_uri,
                code_sha256=code_sha256,
            )
            return
        except Exception as exc:  # noqa: BLE001
            # Never reset a RUNNING seed — that kills warm Chromium and forces a
            # cold browser start (the bug local smoke avoided / full runs hit).
            print(
                f"hot seed dispatch failed ({exc}); NOT resetting (preserve warm CDP)",
                flush=True,
            )
            raise RuntimeError(
                f"Warm seed {name} is RUNNING but hot dispatch failed; "
                "refusing to reset so Chromium stays warm. Fix SSH/inbox and retry."
            ) from exc

    items = [
        compute_v1.Items(key=it.key, value=it.value)
        for it in (inst.metadata.items or [])
        if it.key not in {"startup-script", "usersim-role"}
    ]
    items.append(compute_v1.Items(key="startup-script", value=startup_script))
    items.append(compute_v1.Items(key="usersim-role", value="mvp-fleet-seed"))
    # Refresh fingerprint after possible SA stop/start.
    inst = client.get(project=project, zone=zone, instance=name)
    meta = compute_v1.Metadata(fingerprint=inst.metadata.fingerprint, items=items)
    op = client.set_metadata(
        project=project,
        zone=zone,
        instance=name,
        metadata_resource=meta,
    )
    op.result(timeout=120)

    status = (inst.status or "").upper()
    if status in {"TERMINATED", "STOPPED"}:
        op = client.start(project=project, zone=zone, instance=name)
        op.result(timeout=300)
    elif status == "RUNNING":
        # Should be unreachable — hot path above raises instead of resetting.
        raise RuntimeError(f"Refusing to reset RUNNING warm seed {name}")
    else:
        time.sleep(5)
        op = client.start(project=project, zone=zone, instance=name)
        op.result(timeout=300)


def _image_self_link(project: str, family: str) -> str:
    images = _images_client()
    img = images.get_from_family(project=project, family=family)
    return img.self_link


def _list_mvp_instances(project: str) -> list[Any]:
    from google.cloud import compute_v1

    client = _instances_client()
    agg = client.aggregated_list(project=project)
    out = []
    for zone_path, scoped in agg:
        for inst in scoped.instances or []:
            if (inst.name or "").startswith(INSTANCE_PREFIX):
                zone = zone_path.split("/")[-1] if zone_path else ""
                out.append((inst, zone))
    return out


def reap_orphan_mvp_vms(project: str = DEFAULT_PROJECT, *, max_age_min: int | None = None) -> int:
    """Delete usersim-mvp-* older than TTL. Never touches youtube-seed / bakeoff VMs."""
    from google.cloud import compute_v1
    from datetime import datetime, timezone

    max_age = max_age_min if max_age_min is not None else FLEET_TTL_MIN
    client = _instances_client()
    deleted = 0
    now = datetime.now(timezone.utc)
    for inst, zone in _list_mvp_instances(project):
        created = getattr(inst, "creation_timestamp", None)
        if not created:
            continue
        try:
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_min = (now - ts).total_seconds() / 60.0
        if age_min < max_age:
            continue
        try:
            op = client.delete(project=project, zone=zone, instance=inst.name)
            op.result(timeout=180)
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            print(f"reaper: failed to delete {inst.name}: {exc}", flush=True)
    return deleted


def _count_running_mvp(project: str) -> int:
    n = 0
    for inst, _zone in _list_mvp_instances(project):
        if (inst.status or "").upper() in {"RUNNING", "STAGING", "PROVISIONING"}:
            n += 1
    return n


def _create_spot_instance(
    *,
    name: str,
    zone: str,
    project: str,
    machine: str,
    image_link: str,
    startup_script: str,
) -> None:
    from google.cloud import compute_v1

    client = _instances_client()
    disk = compute_v1.AttachedDisk(
        auto_delete=True,
        boot=True,
        initialize_params=compute_v1.AttachedDiskInitializeParams(
            source_image=image_link,
            disk_size_gb=40,
            disk_type=f"zones/{zone}/diskTypes/pd-balanced",
        ),
    )
    network_iface = compute_v1.NetworkInterface(
        network=f"projects/{project}/global/networks/{NETWORK}",
        subnetwork=f"projects/{project}/regions/{zone.rsplit('-', 1)[0]}/subnetworks/{SUBNET}",
        access_configs=[compute_v1.AccessConfig(name="External NAT", type_="ONE_TO_ONE_NAT")],
    )
    metadata = compute_v1.Metadata(
        items=[
            compute_v1.Items(key="startup-script", value=startup_script),
            compute_v1.Items(key="usersim-role", value="mvp-fleet-copy"),
        ]
    )
    scheduling = compute_v1.Scheduling(
        provisioning_model="SPOT",
        instance_termination_action="DELETE",
        automatic_restart=False,
        on_host_maintenance="TERMINATE",
    )
    sa_email = SERVICE_ACCOUNT
    service_accounts = [
        compute_v1.ServiceAccount(
            email=sa_email if sa_email else "default",
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    ]
    instance = compute_v1.Instance(
        name=name,
        machine_type=f"zones/{zone}/machineTypes/{machine}",
        disks=[disk],
        network_interfaces=[network_iface],
        metadata=metadata,
        scheduling=scheduling,
        service_accounts=service_accounts,
        tags=compute_v1.Tags(items=["allow-iap-ssh", "usersim-mvp"]),
    )
    try:
        op = client.insert(project=project, zone=zone, instance_resource=instance)
        op.result(timeout=300)
        return
    except Exception as first_exc:
        errors = [first_exc]

    # Without actAs on the configured SA, fall back to the project default one.
    if sa_email and "actAs" in str(errors[0]):
        instance.service_accounts = [
            compute_v1.ServiceAccount(
                email="default",
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        ]
        try:
            op = client.insert(project=project, zone=zone, instance_resource=instance)
            op.result(timeout=300)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    # Retry on-demand if Spot rejected.
    instance.scheduling = compute_v1.Scheduling(
        automatic_restart=False,
        on_host_maintenance="TERMINATE",
    )
    try:
        op = client.insert(project=project, zone=zone, instance_resource=instance)
        op.result(timeout=300)
    except Exception as last_exc:
        detail = " / ".join(str(e) for e in [*errors, last_exc])
        raise RuntimeError(f"instance create failed: {detail}") from last_exc


def _delete_instance(name: str, zone: str, project: str) -> None:
    client = _instances_client()
    try:
        op = client.delete(project=project, zone=zone, instance=name)
        op.result(timeout=180)
    except Exception as exc:  # noqa: BLE001
        print(f"delete {name}: {exc}", flush=True)


def _shard_tasks(tasks: list[dict[str, Any]], workers: int) -> list[list[dict[str, Any]]]:
    workers = max(1, workers)
    shards: list[list[dict[str, Any]]] = []
    for i in range(0, len(tasks), workers):
        shards.append(tasks[i : i + workers])
    return shards or [[]]


async def run_study_on_gcp_fleet(
    *,
    study_id: str,
    url: str,
    segment: str,
    personas: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    live_sessions: dict[str, Any],
    on_frame: Callable[[str, dict[str, Any]], Any] | None = None,
    on_status: Callable[[str], Any] | None = None,
    workers: int | None = None,
    keep_vm: bool = False,
    study_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Spawn Spot copies from the seed image, poll GCS for frames, return results.

    The copies self-delete. ``keep_vm`` is ignored for copies (always delete);
    template seed VMs / images are never touched.
    """
    del keep_vm  # copies always self-delete
    project = DEFAULT_PROJECT
    machine = DEFAULT_MACHINE
    workers = max(1, min(workers or WORKERS_DEFAULT, 8, len(tasks) or 1))
    gcs_root = study_gcs_root(study_id)
    ttl_min = FLEET_TTL_MIN

    async def _status(msg: str) -> None:
        if on_status:
            maybe = on_status(msg)
            if maybe is not None and hasattr(maybe, "__await__"):
                await maybe

    await asyncio.to_thread(reap_orphan_mvp_vms, project)

    running = await asyncio.to_thread(_count_running_mvp, project)

    # List warm seeds early — packing depends on how many are available.
    seed_pool: list[tuple[Any, str]] = []
    if USE_WARM_SEEDS:
        seed_pool = await asyncio.to_thread(_list_seed_instances, project)

    allow_spot = _allow_spot_copies()
    if seed_pool and not allow_spot:
        # Local / seed-prefer path: entire study on standing warm CDP Chromium.
        shards = _pack_tasks_onto_seeds(tasks, len(seed_pool))
        workers = SEED_WORKERS
        await _status(
            f"Packing {len(tasks)} tasks onto {len(shards)} warm seed(s) "
            f"(reuse CDP Chromium, no Spot copies)"
        )
    else:
        workers = max(1, min(workers or WORKERS_DEFAULT, 8, len(tasks) or 1))
        shards = _shard_tasks(tasks, workers)
        if len(shards) > PER_STUDY_VM_CAP:
            flat = [t for s in shards for t in s]
            chunk = max(workers, (len(flat) + PER_STUDY_VM_CAP - 1) // PER_STUDY_VM_CAP)
            shards = _shard_tasks(flat, chunk)[:PER_STUDY_VM_CAP]
        if seed_pool:
            # Fill seeds first; remaining shards become Spot.
            overflow = max(0, len(shards) - len(seed_pool))
            if overflow and not allow_spot:
                # Coalesce overflow back onto seeds instead of Spot.
                shards = _pack_tasks_onto_seeds(tasks, len(seed_pool))
                workers = SEED_WORKERS
                await _status(
                    f"Coalesced onto {len(shards)} warm seed(s) — Spot disabled"
                )

    if running + len(shards) > GLOBAL_VM_CAP:
        raise RuntimeError(
            f"GCP fleet at capacity ({running} running, need {len(shards)}, cap {GLOBAL_VM_CAP})"
        )

    await _status(f"Uploading fleet job for {len(tasks)} tasks → {len(shards)} workers")

    with tempfile.TemporaryDirectory(prefix="usersim-fleet-") as tmp:
        tmp_path = Path(tmp)
        tar_path = await asyncio.to_thread(_pack_payload, tmp_path)
        import hashlib

        code_sha256 = hashlib.sha256(tar_path.read_bytes()).hexdigest()
        # Content-addressed code blob — skip re-upload when unchanged.
        bucket = (
            os.environ.get("MVP_GCS_BUCKET")
            or "usersim-bakeoff-347838016394"
        )
        code_uri = f"gs://{bucket}/mvp_fleet_code/{code_sha256}.tgz"
        existing = await asyncio.to_thread(gcs_download_json, f"{code_uri}.ok.json")
        if not (isinstance(existing, dict) and existing.get("sha") == code_sha256):
            await asyncio.to_thread(gcs_upload_file, tar_path, code_uri)
            await asyncio.to_thread(
                gcs_upload_json, f"{code_uri}.ok.json", {"sha": code_sha256}
            )
        else:
            await _status(f"Reusing cached fleet code {code_sha256[:12]}…")

        if study_snapshot:
            await asyncio.to_thread(write_study_state, study_id, study_snapshot)

        from mvp.live_frames import issue_live_token, live_push_url_for_job

        live_token = issue_live_token(study_id)
        live_push_url = live_push_url_for_job(study_id)

        shard_metas: list[dict[str, Any]] = []
        for idx, shard_tasks in enumerate(shards):
            job = {
                "study_id": study_id,
                "url": url,
                "segment": segment,
                "personas": personas,
                "tasks": shard_tasks,
                "all_task_ids": [t.get("id") for t in tasks],
                "gcs_root": gcs_root,
                "workers": SEED_WORKERS if (seed_pool and not allow_spot) else workers,
                "keep_vm": False,
                "max_steps": int(os.environ.get("MVP_MAX_STEPS", "8")),
                "shard_index": idx,
                "shard_count": len(shards),
                "finish_study": True,
                "study_snapshot": study_snapshot,
                "code_sha256": code_sha256,
                "live_token": live_token,
                "live_push_url": live_push_url or "",
                "on_seed": bool(seed_pool and (not allow_spot or idx < len(seed_pool))),
            }
            job_uri = f"{gcs_root}/job_shard_{idx}.json"
            await asyncio.to_thread(gcs_upload_json, job_uri, job)
            shard_metas.append({"index": idx, "job_uri": job_uri, "tasks": shard_tasks})

    # Warm path: start standing youtube-seed-* first (disk already exists).
    # Overflow shards become Spot copies from the image (only when allowed).
    seed_assignments: dict[int, tuple[str, str]] = {}
    for meta, (inst, zone) in zip(shard_metas, seed_pool):
        seed_assignments[int(meta["index"])] = (inst.name or "", zone)

    n_seed = len(seed_assignments)
    n_spot = len(shard_metas) - n_seed
    if n_seed:
        await _status(
            f"Using {n_seed} warm seed(s) with standing Chromium"
            + (f", then {n_spot} Spot copies" if n_spot else " (full study on warm CDP)")
        )
    if n_spot and not allow_spot:
        raise RuntimeError(
            f"Need {n_spot} Spot copies but MVP_GCP_ALLOW_SPOT is off and only "
            f"{n_seed} warm seed(s) available. Start more seeds or set ALLOW_SPOT=1."
        )
    image_link = ""
    if n_spot:
        try:
            image_link = await asyncio.to_thread(_image_self_link, IMAGE_PROJECT, IMAGE_FAMILY)
        except Exception as exc:
            raise RuntimeError(
                f"Seed image family {IMAGE_FAMILY!r} not found in {IMAGE_PROJECT}: {exc}. "
                "Run scripts/vm/bake_mvp_seed_image.sh first."
            ) from exc
        await _status(
            f"Creating {n_spot} Spot copies from {IMAGE_FAMILY} ({machine}, {workers} workers each)"
        )

    created: list[tuple[str, str]] = []  # Spot copies only (safe to delete)
    zone_cycle = list(DEFAULT_ZONES) or [DEFAULT_ZONE]

    async def _launch_shard(meta: dict[str, Any]) -> tuple[str, str, str]:
        idx = int(meta["index"])
        if idx in seed_assignments:
            name, zone = seed_assignments[idx]
            job = await asyncio.to_thread(gcs_download_json, meta["job_uri"])
            if isinstance(job, dict):
                job["keep_vm"] = True
                job["on_seed"] = True
                await asyncio.to_thread(gcs_upload_json, meta["job_uri"], job)
            startup = _startup_script(
                gcs_root=gcs_root,
                code_uri=code_uri,
                job_uri=meta["job_uri"],
                ttl_min=ttl_min,
                keep_vm=True,
            )
            await asyncio.to_thread(
                _boot_seed_with_startup,
                name=name,
                zone=zone,
                project=project,
                startup_script=startup,
                code_uri=code_uri,
                job_uri=meta["job_uri"],
                code_sha256=code_sha256,
            )
            meta["vm"] = name
            meta["zone"] = zone
            meta["kind"] = "seed"
            await _status(f"Shard {idx} on warm CDP ({name} in {zone})")
            return name, zone, "seed"

        name = f"{INSTANCE_PREFIX}{study_id[:8]}-s{idx}-{uuid.uuid4().hex[:5]}"
        startup = _startup_script(
            gcs_root=gcs_root,
            code_uri=code_uri,
            job_uri=meta["job_uri"],
            ttl_min=ttl_min,
            keep_vm=False,
        )
        last_err: Exception | None = None
        for zone in zone_cycle:
            try:
                await asyncio.to_thread(
                    _create_spot_instance,
                    name=name,
                    zone=zone,
                    project=project,
                    machine=machine,
                    image_link=image_link,
                    startup_script=startup,
                )
                meta["vm"] = name
                meta["zone"] = zone
                meta["kind"] = "spot"
                await _status(f"Shard {idx} Spot copy up ({name} in {zone})")
                return name, zone, "spot"
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await _status(f"Create failed in {zone}: {exc!s:.120} — trying next zone")
        raise RuntimeError(f"Failed to create fleet VM for shard {idx}: {last_err}")

    # Seeds start immediately in parallel with any Spot creates.
    # Kick live relays as soon as seed VMs are known so probes overlap payload pull.
    for meta in shard_metas:
        idx = int(meta["index"])
        if idx in seed_assignments:
            name, zone = seed_assignments[idx]
            meta["vm"] = name
            meta["zone"] = zone
            meta["kind"] = "seed"

    create_tasks = [asyncio.create_task(_launch_shard(m)) for m in shard_metas]
    await _status("Fleet booting — live relay + GCS poll…")

    seen_steps: dict[str, set[int]] = {t.get("id") or "": set() for t in tasks}
    deadline = time.monotonic() + float(os.environ.get("MVP_GCP_FLEET_TIMEOUT_S", "900"))
    shard_done: set[int] = set()
    results_by_agent: dict[str, dict[str, Any]] = {}
    retried: set[int] = set()
    creates_settled = False
    relay_started: set[int] = set()
    relay_tasks: list[asyncio.Task[Any]] = []

    def _hydrate_frame_png(agent_id: str, fr: dict[str, Any]) -> dict[str, Any]:
        """Pull screenshot bytes from GCS into local mvp/runs so the UI img src works."""
        out = dict(fr)
        step_no = int(out.get("step") or 0)
        url = str(out.get("screenshot_url") or "")
        name = Path(url.split("?", 1)[0]).name if url else ""
        if not re.fullmatch(r"(?:step|bbox)_\d+\.png", name or ""):
            name = "step_0.png" if step_no == 0 else f"bbox_{step_no}.png"
        from mvp.paths import MVP_RUNS_DIR

        dest = MVP_RUNS_DIR / study_id / agent_id / "screenshots" / name
        out["screenshot_url"] = (
            f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{name}"
        )
        if dest.is_file() and dest.stat().st_size > 100:
            return out
        try:
            raw = gcs_download_bytes(screenshot_gcs_uri(study_id, agent_id, name))
            if raw and len(raw) > 100:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
        except Exception:  # noqa: BLE001
            pass
        return out

    async def _emit_frame(agent_id: str, fr: dict[str, Any]) -> None:
        step_no = int(fr.get("step") or 0)
        if step_no in seen_steps.setdefault(agent_id, set()):
            return
        seen_steps[agent_id].add(step_no)
        fr = await asyncio.to_thread(_hydrate_frame_png, agent_id, fr)
        if on_frame:
            maybe = on_frame(agent_id, fr)
            if maybe is not None and hasattr(maybe, "__await__"):
                await maybe

    async def _seed_live_relay(meta: dict[str, Any]) -> None:
        name = str(meta.get("vm") or "")
        zone = str(meta.get("zone") or "")
        shard_tasks = list(meta.get("tasks") or [])
        if not name or not zone or not shard_tasks:
            return
        agent_id = str(shard_tasks[0].get("id") or "")
        if not agent_id:
            return
        await _status(f"Live relay waiting on {name} for {agent_id}…")
        try:
            fr = await asyncio.to_thread(
                _ssh_wait_first_frame,
                name=name,
                zone=zone,
                project=project,
                study_id=study_id,
                agent_id=agent_id,
                gcs_root=gcs_root,
                timeout_s=float(os.environ.get("MVP_LIVE_RELAY_TIMEOUT_S", "90")),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"live relay exception: {exc}", flush=True)
            await _status(f"Live relay error: {exc!s:.120}")
            return
        if fr:
            await _emit_frame(agent_id, fr)
            await _status(f"Live first frame via SSH relay ({agent_id})")
        else:
            await _status(f"Live relay miss for {agent_id} — falling back to GCS")

    for meta in shard_metas:
        idx = int(meta["index"])
        if meta.get("kind") == "seed" and meta.get("vm") and idx not in relay_started:
            relay_started.add(idx)
            relay_tasks.append(asyncio.create_task(_seed_live_relay(meta)))

    while time.monotonic() < deadline:
        # Kick SSH live relays for any late seed assignment (shouldn't happen).
        for meta in shard_metas:
            idx = int(meta["index"])
            if idx in relay_started:
                continue
            if meta.get("kind") == "seed" and meta.get("vm") and meta.get("zone"):
                relay_started.add(idx)
                relay_tasks.append(asyncio.create_task(_seed_live_relay(meta)))

        if not creates_settled and all(t.done() for t in create_tasks):
            creates_settled = True
            errors = [t.exception() for t in create_tasks if t.done() and t.exception()]
            for t in create_tasks:
                if t.cancelled() or t.exception():
                    continue
                name, zone, kind = t.result()
                if kind == "spot":
                    created.append((name, zone))
            await asyncio.to_thread(
                gcs_upload_json,
                f"{gcs_root}/fleet.json",
                {"study_id": study_id, "shards": shard_metas, "created": created},
            )
            if errors and not any(m.get("vm") for m in shard_metas):
                raise RuntimeError(f"Failed to launch any fleet VMs: {errors[0]}")
            if errors:
                await _status(
                    f"WARN: {len(errors)} shard launch(es) failed; continuing with "
                    f"{sum(1 for m in shard_metas if m.get('vm'))}"
                )

        # Prefer in-memory live bus (HTTP push or SSH relay) over GCS.
        from mvp.live_frames import drain_live_frames

        for item in drain_live_frames(study_id):
            aid = str(item.get("agent_id") or "")
            fr = item.get("step") if isinstance(item.get("step"), dict) else None
            if aid and fr:
                await _emit_frame(aid, fr)

        # GCS archival path (Spot copies / late steps / replay).
        for task in tasks:
            agent_id = task.get("id") or ""
            if not agent_id:
                continue
            manifest = await asyncio.to_thread(
                gcs_download_json, f"{gcs_root}/live/{agent_id}/manifest.json"
            )
            frames: list[dict[str, Any]] = []
            if isinstance(manifest, dict):
                frames = list(manifest.get("steps") or [])
            else:
                # Fallback: try sequential steps until miss.
                for step_no in range(0, 32):
                    fr = await asyncio.to_thread(
                        gcs_download_json,
                        f"{gcs_root}/live/{agent_id}/step_{step_no:03d}.json",
                    )
                    if not isinstance(fr, dict):
                        break
                    frames.append(fr)
            for fr in frames:
                await _emit_frame(agent_id, fr)

        # Per-shard done markers.
        for meta in shard_metas:
            idx = int(meta["index"])
            if idx in shard_done:
                continue
            done = await asyncio.to_thread(
                gcs_download_json, f"{gcs_root}/shard_{idx}_done.json"
            )
            if isinstance(done, dict):
                shard_done.add(idx)
                for r in done.get("results") or []:
                    aid = r.get("agent_id") or r.get("task_id") or ""
                    if aid:
                        results_by_agent[aid] = r
                await _status(f"Shard {idx + 1}/{len(shard_metas)} finished")

        # Aggregate done.json (finisher writes this).
        aggregate = await asyncio.to_thread(gcs_download_json, f"{gcs_root}/done.json")
        if isinstance(aggregate, dict) and aggregate.get("results") is not None:
            results = list(aggregate.get("results") or [])
            await _status("Fleet agents finished — pulling results")
            return results

        if len(shard_done) == len(shard_metas) and results_by_agent:
            # Finisher may still be writing; give it a moment, else assemble.
            await asyncio.sleep(3)
            aggregate = await asyncio.to_thread(gcs_download_json, f"{gcs_root}/done.json")
            if isinstance(aggregate, dict) and aggregate.get("results") is not None:
                return list(aggregate.get("results") or [])
            ordered = []
            for t in tasks:
                aid = t.get("id") or ""
                if aid in results_by_agent:
                    ordered.append(results_by_agent[aid])
            if ordered:
                await _status("Assembling results from shard markers")
                return ordered

        # Preemption retry: shard VM gone and no done marker.
        for meta in shard_metas:
            idx = int(meta["index"])
            if idx in shard_done or idx in retried:
                continue
            if meta.get("kind") == "seed":
                # Never recreate/delete standing seeds — just wait or fail the shard.
                continue
            vm = meta.get("vm")
            zone = meta.get("zone")
            if not vm or not zone or not image_link:
                continue
            try:
                client = _instances_client()
                inst = await asyncio.to_thread(
                    client.get, project=project, zone=zone, instance=vm
                )
                status = (inst.status or "").upper()
            except Exception:
                status = "MISSING"
            if status in {"RUNNING", "STAGING", "PROVISIONING", "STOPPING"}:
                continue
            # Retry once.
            retried.add(idx)
            await _status(f"Shard {idx} preempted/missing — recreating once")
            name = f"{INSTANCE_PREFIX}{study_id[:8]}-r{idx}-{uuid.uuid4().hex[:5]}"
            startup = _startup_script(
                gcs_root=gcs_root,
                code_uri=f"{gcs_root}/payload.tgz",
                job_uri=meta["job_uri"],
                ttl_min=ttl_min,
            )
            for zone_try in zone_cycle:
                try:
                    await asyncio.to_thread(
                        _create_spot_instance,
                        name=name,
                        zone=zone_try,
                        project=project,
                        machine=machine,
                        image_link=image_link,
                        startup_script=startup,
                    )
                    meta["vm"] = name
                    meta["zone"] = zone_try
                    created.append((name, zone_try))
                    break
                except Exception:
                    continue

        status = await asyncio.to_thread(gcs_download_json, f"{gcs_root}/status.json")
        if isinstance(status, dict) and on_status:
            maybe = on_status(str(status.get("message") or "Agents running on GCP…"))
            if maybe is not None and hasattr(maybe, "__await__"):
                await maybe

        await asyncio.sleep(0.5)

    # Timeout: force-delete leftover copies.
    for name, zone in created:
        await asyncio.to_thread(_delete_instance, name, zone, project)
    raise TimeoutError(f"GCP fleet study timed out for {study_id}")
