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
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from mvp.gcs_store import (
    DEFAULT_GCS,
    gcs_download_json,
    gcs_upload_file,
    gcs_upload_json,
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
NETWORK = os.environ.get("MVP_GCP_NETWORK", "main-vpc")
SUBNET = os.environ.get("MVP_GCP_SUBNET", "primary-subnet")
# Copies carry no key file, so Vertex + GCS access comes entirely from the
# attached service account via the metadata server.
SERVICE_ACCOUNT = os.environ.get(
    "MVP_GCP_SERVICE_ACCOUNT",
    "usersim-cloud-agent@project-amer-scs-sandbox.iam.gserviceaccount.com",
).strip()


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


def _startup_script(*, gcs_root: str, code_uri: str, job_uri: str, ttl_min: int) -> str:
    seed_profile = "1" if os.environ.get("MVP_SEED_PROFILE", "").lower() in {"1", "true", "yes"} else "0"
    return f"""#!/usr/bin/env bash
set -euo pipefail
exec > >(tee -a /var/log/usersim-mvp-worker.log) 2>&1
echo "==> usersim MVP fleet startup $(date -u +%FT%TZ)"
# Absolute TTL so hung shards cannot bill forever.
shutdown -h +{ttl_min} || true
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
export GOOGLE_CLOUD_PROJECT={DEFAULT_PROJECT}
export GCP_PROJECT={DEFAULT_PROJECT}
export PYTHONPATH="$HOME/usersim/src:$HOME/usersim"
# Auth: instance service account ADC — do not expect secrets/sa.json on disk.
unset CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE || true
chmod +x scripts/vm/mvp_study_worker.sh
bash scripts/vm/mvp_study_worker.sh
"""


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
    shards = _shard_tasks(tasks, workers)
    if len(shards) > PER_STUDY_VM_CAP:
        # Coalesce into fewer larger shards.
        flat = [t for s in shards for t in s]
        chunk = max(workers, (len(flat) + PER_STUDY_VM_CAP - 1) // PER_STUDY_VM_CAP)
        shards = _shard_tasks(flat, chunk)[:PER_STUDY_VM_CAP]
    if running + len(shards) > GLOBAL_VM_CAP:
        raise RuntimeError(
            f"GCP fleet at capacity ({running} running, need {len(shards)}, cap {GLOBAL_VM_CAP})"
        )

    await _status(f"Uploading fleet job for {len(tasks)} tasks → {len(shards)} Spot copies")

    with tempfile.TemporaryDirectory(prefix="usersim-fleet-") as tmp:
        tmp_path = Path(tmp)
        tar_path = await asyncio.to_thread(_pack_payload, tmp_path)
        code_uri = f"{gcs_root}/payload.tgz"
        await asyncio.to_thread(gcs_upload_file, tar_path, code_uri)

        if study_snapshot:
            await asyncio.to_thread(write_study_state, study_id, study_snapshot)

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
                "workers": workers,
                "keep_vm": False,
                "max_steps": int(os.environ.get("MVP_MAX_STEPS", "8")),
                "shard_index": idx,
                "shard_count": len(shards),
                "finish_study": True,
                "study_snapshot": study_snapshot,
            }
            job_uri = f"{gcs_root}/job_shard_{idx}.json"
            await asyncio.to_thread(gcs_upload_json, job_uri, job)
            shard_metas.append({"index": idx, "job_uri": job_uri, "tasks": shard_tasks})

    try:
        image_link = await asyncio.to_thread(_image_self_link, IMAGE_PROJECT, IMAGE_FAMILY)
    except Exception as exc:
        raise RuntimeError(
            f"Seed image family {IMAGE_FAMILY!r} not found in {IMAGE_PROJECT}: {exc}. "
            "Run scripts/vm/bake_mvp_seed_image.sh first."
        ) from exc

    await _status(
        f"Creating {len(shard_metas)} Spot copies from {IMAGE_FAMILY} ({machine}, {workers} workers each)"
    )

    created: list[tuple[str, str]] = []  # (name, zone)
    zone_cycle = list(DEFAULT_ZONES) or [DEFAULT_ZONE]

    for meta in shard_metas:
        idx = meta["index"]
        name = f"{INSTANCE_PREFIX}{study_id[:8]}-s{idx}-{uuid.uuid4().hex[:5]}"
        startup = _startup_script(
            gcs_root=gcs_root,
            code_uri=code_uri,
            job_uri=meta["job_uri"],
            ttl_min=ttl_min,
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
                created.append((name, zone))
                meta["vm"] = name
                meta["zone"] = zone
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await _status(f"Create failed in {zone}: {exc!s:.120} — trying next zone")
                continue
        if last_err is not None and "vm" not in meta:
            # Cleanup any already created, then raise.
            for n, z in created:
                await asyncio.to_thread(_delete_instance, n, z, project)
            raise RuntimeError(f"Failed to create fleet VM for shard {idx}: {last_err}")

    await asyncio.to_thread(
        gcs_upload_json,
        f"{gcs_root}/fleet.json",
        {"study_id": study_id, "shards": shard_metas, "created": created},
    )
    await _status("Fleet copies booting — polling GCS for live frames…")

    seen_steps: dict[str, set[int]] = {t.get("id") or "": set() for t in tasks}
    deadline = time.monotonic() + float(os.environ.get("MVP_GCP_FLEET_TIMEOUT_S", "900"))
    shard_done: set[int] = set()
    results_by_agent: dict[str, dict[str, Any]] = {}
    retried: set[int] = set()

    while time.monotonic() < deadline:
        # Live frames via per-agent manifest when present, else step_*.json listing.
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
                step_no = int(fr.get("step") or 0)
                if step_no in seen_steps.setdefault(agent_id, set()):
                    continue
                seen_steps[agent_id].add(step_no)
                if on_frame:
                    maybe = on_frame(agent_id, fr)
                    if maybe is not None and hasattr(maybe, "__await__"):
                        await maybe

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
            vm = meta.get("vm")
            zone = meta.get("zone")
            if not vm or not zone:
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

        await asyncio.sleep(2.0)

    # Timeout: force-delete leftover copies.
    for name, zone in created:
        await asyncio.to_thread(_delete_instance, name, zone, project)
    raise TimeoutError(f"GCP fleet study timed out for {study_id}")
