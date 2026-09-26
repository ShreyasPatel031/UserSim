"""Restart fm-sft-socrates-l4 after Spot preemption.

Only this instance (and its on-demand replacement) is touched.
Other VMs, including dose-oss-eval-l4, are ignored.

Policy
------
- First additional Spot preemption: start the Spot VM again. The guest
  startup script resumes QLoRA from the latest checkpoint.
- Second additional Spot preemption, or a Spot capacity error: leave the
  Spot VM stopped and boot an on-demand g2-standard-8 from a snapshot of
  its disk. The Spot VM is not deleted.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import functions_framework
from google.cloud import compute_v1, tasks_v2
from google.protobuf import timestamp_pb2

PROJECT = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
TASKS_LOCATION = os.environ.get("TASKS_LOCATION", "")
TASKS_QUEUE = os.environ.get("TASKS_QUEUE", "usersim-spot-retry")
FUNCTION_URL = os.environ.get("FUNCTION_URL", "").rstrip("/")
OIDC_SA = os.environ.get("OIDC_SERVICE_ACCOUNT", "")
RETRY_DELAY_SEC = int(os.environ.get("RETRY_DELAY_SEC", "45"))

SPOT_NAME = "fm-sft-socrates-l4"
OD_NAME = "fm-sft-socrates-l4-od"
# After this many watchdog Spot restarts, the next preemption is on-demand.
# 1 means: one automatic Spot resume, then on-demand (two preemptions total).
MAX_SPOT_RECOVERIES = 1

instances = compute_v1.InstancesClient()
snapshots = compute_v1.SnapshotsClient()
zone_ops = compute_v1.ZoneOperationsClient()
tasks = tasks_v2.CloudTasksClient()

STOCKOUT_MARKERS = (
    "ZONE_RESOURCE_POOL_EXHAUSTED",
    "RESOURCE_POOL_EXHAUSTED",
    "STOCKOUT",
    "does not have enough resources",
)


def _log(msg: str, **extra: Any) -> None:
    print(json.dumps({"msg": msg, **extra}, default=str), flush=True)


def _zone(zone: str) -> str:
    return zone.rsplit("/", 1)[-1] if "/" in zone else zone


def _allowed(name: str) -> bool:
    return name in {SPOT_NAME, OD_NAME}


def get_instance(zone: str, name: str) -> compute_v1.Instance | None:
    try:
        return instances.get(project=PROJECT, zone=zone, instance=name)
    except Exception as e:  # noqa: BLE001
        if "was not found" in str(e) or "404" in str(e):
            return None
        _log("get_instance_failed", name=name, error=str(e))
        return None


def find_named(name: str) -> tuple[str | None, compute_v1.Instance | None]:
    """Locate an instance by name in any zone. Used for the on-demand copy."""
    try:
        for scope, scoped in instances.aggregated_list(project=PROJECT):
            for inst in scoped.instances or []:
                if inst.name == name:
                    return _zone(inst.zone), inst
    except Exception as e:  # noqa: BLE001
        _log("aggregated_list_failed", name=name, error=str(e))
    return None, None


def candidate_zones(zone: str) -> list[str]:
    region = _zone(zone).rsplit("-", 1)[0]
    # L4 g2 capacity in this project has been in a/b/c. Try the event zone first.
    ordered = [_zone(zone)]
    for suffix in ("a", "b", "c"):
        z = f"{region}-{suffix}"
        if z not in ordered:
            ordered.append(z)
    return ordered


def meta_map(inst: compute_v1.Instance) -> dict[str, str]:
    return {item.key: item.value for item in (inst.metadata.items or [])}


def set_meta(zone: str, name: str, updates: dict[str, str]) -> None:
    inst = instances.get(project=PROJECT, zone=zone, instance=name)
    items = meta_map(inst)
    items.update(updates)
    md = compute_v1.Metadata(
        fingerprint=inst.metadata.fingerprint,
        items=[compute_v1.Items(key=k, value=v) for k, v in items.items()],
    )
    instances.set_metadata(project=PROJECT, zone=zone, instance=name, metadata_resource=md)
    _log("metadata_set", name=name, updates=updates)


def enqueue(body: dict[str, Any], delay: int | None = None) -> None:
    if not FUNCTION_URL:
        _log("skip_enqueue_no_url", body=body)
        return
    parent = tasks.queue_path(PROJECT, TASKS_LOCATION, TASKS_QUEUE)
    http_request: dict[str, Any] = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": f"{FUNCTION_URL}/",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body).encode(),
    }
    if OIDC_SA:
        http_request["oidc_token"] = tasks_v2.OidcToken(
            service_account_email=OIDC_SA,
            audience=FUNCTION_URL,
        )
    schedule = timestamp_pb2.Timestamp()
    schedule.FromSeconds(int(time.time()) + (RETRY_DELAY_SEC if delay is None else delay))
    task = {"http_request": http_request, "schedule_time": schedule}
    created = tasks.create_task(request={"parent": parent, "task": task})
    _log("enqueued", task=created.name, kind=body.get("kind"), phase=body.get("phase"))


def recent_start_error(zone: str, name: str) -> str:
    try:
        ops = zone_ops.list(
            project=PROJECT,
            zone=zone,
            filter=f'(targetLink eq ".*/instances/{name}")',
            max_results=5,
        )
    except Exception as e:  # noqa: BLE001
        _log("ops_list_failed", name=name, error=str(e))
        return ""
    texts = []
    for op in ops:
        err = getattr(op, "error", None)
        if not err or not err.errors:
            continue
        for item in err.errors:
            texts.append(f"{item.code} {item.message}")
        break
    return " | ".join(texts)


def stockout(text: str) -> bool:
    upper = text.upper()
    return any(mark.upper() in upper for mark in STOCKOUT_MARKERS)


def start_instance(zone: str, name: str) -> str:
    if not _allowed(name):
        _log("refusing_start", name=name)
        return "refused"
    try:
        op = instances.start(project=PROJECT, zone=zone, instance=name)
        _log("start_issued", name=name, op=getattr(op, "name", None))
        return "ok"
    except Exception as e:  # noqa: BLE001
        _log("start_failed", name=name, error=str(e))
        return f"fail:{e}"


def begin_ondemand(zone: str, reason: str) -> None:
    """Stop retrying Spot and boot the on-demand copy. Does not delete the Spot VM."""
    spot = get_instance(zone, SPOT_NAME)
    if spot is not None and spot.status == "RUNNING":
        _log("ondemand_skipped_spot_running", reason=reason)
        return
    if spot is not None:
        try:
            set_meta(zone, SPOT_NAME, {"distmatch-mode": "ondemand", "distmatch-od-reason": reason[:60]})
        except Exception as e:  # noqa: BLE001
            _log("mark_ondemand_failed", error=str(e))
    # New snapshot each switch so we do not boot a stale copy of the disk.
    snap_name = f"fm-sft-socrates-l4-dm-{int(time.time())}"
    enqueue(
        {
            "kind": "distmatch_od",
            "zone": zone,
            "phase": "snapshot",
            "reason": reason,
            "attempt": 1,
            "snapshot": snap_name,
        },
        delay=5,
    )
    _log("ondemand_begin", reason=reason, snapshot=snap_name)


def handle_preempt(name: str, zone: str) -> tuple[dict, int]:
    zone = _zone(zone)
    if not _allowed(name):
        _log("preempt_ignored", name=name)
        return {"status": "ignored", "name": name}, 200
    if name == OD_NAME:
        inst = get_instance(zone, OD_NAME)
        if inst is not None and inst.status != "RUNNING":
            start_instance(zone, OD_NAME)
        return {"status": "od_instance", "name": name}, 200

    inst = get_instance(zone, SPOT_NAME)
    if inst is None:
        return {"status": "missing", "name": name}, 200
    items = meta_map(inst)
    if items.get("distmatch-mode") == "ondemand":
        begin_ondemand(zone, "already_ondemand")
        return {"status": "ondemand", "name": name}, 200
    n = int(items.get("distmatch-extra-preempts") or "0")
    _log("preempt_seen", name=name, extra_preempts=n, status=inst.status)
    if n >= MAX_SPOT_RECOVERIES:
        begin_ondemand(zone, f"preempts={n + 1}")
        return {"status": "switch_ondemand", "name": name, "extra_preempts": n}, 200
    try:
        set_meta(zone, SPOT_NAME, {"distmatch-extra-preempts": str(n + 1)})
    except Exception as e:  # noqa: BLE001
        _log("counter_failed", error=str(e))
    result = start_instance(zone, SPOT_NAME)
    if stockout(result):
        begin_ondemand(zone, "spot_stockout")
        return {"status": "switch_ondemand", "reason": "stockout"}, 200
    enqueue(
        {"kind": "distmatch_spot", "name": SPOT_NAME, "zone": zone, "attempt": 1},
        delay=RETRY_DELAY_SEC,
    )
    return {"status": "spot_restart", "name": name, "extra_preempts": n + 1, "start": result}, 200


def handle_spot_retry(payload: dict[str, Any]) -> tuple[dict, int]:
    zone = _zone(payload["zone"])
    attempt = int(payload.get("attempt", 1))
    inst = get_instance(zone, SPOT_NAME)
    if inst is None:
        return {"status": "missing"}, 200
    items = meta_map(inst)
    if items.get("distmatch-mode") == "ondemand":
        return {"status": "ondemand_already"}, 200
    if inst.status == "RUNNING":
        _log("spot_up", attempt=attempt)
        return {"status": "up"}, 200
    if inst.status in {"STAGING", "PROVISIONING", "REPAIRING"}:
        enqueue({"kind": "distmatch_spot", "name": SPOT_NAME, "zone": zone, "attempt": attempt + 1})
        return {"status": "waiting", "vm_status": inst.status}, 200
    err = recent_start_error(zone, SPOT_NAME)
    _log("spot_still_down", status=inst.status, attempt=attempt, error=err)
    if stockout(err) or attempt >= 3:
        begin_ondemand(zone, "stockout" if stockout(err) else f"spot_down_attempt_{attempt}")
        return {"status": "switch_ondemand", "error": err}, 200
    start_instance(zone, SPOT_NAME)
    enqueue({"kind": "distmatch_spot", "name": SPOT_NAME, "zone": zone, "attempt": attempt + 1})
    return {"status": "restarted", "attempt": attempt}, 200


def _snapshot(name: str) -> compute_v1.Snapshot | None:
    try:
        return snapshots.get(project=PROJECT, snapshot=name)
    except Exception as e:  # noqa: BLE001
        if "was not found" in str(e) or "404" in str(e):
            return None
        _log("snapshot_get_failed", error=str(e))
        return None


def handle_od(payload: dict[str, Any]) -> tuple[dict, int]:
    zone = _zone(payload.get("try_zone") or payload["zone"])
    home = _zone(payload["zone"])
    attempt = int(payload.get("attempt", 1))
    if attempt > 40:
        _log("od_give_up", attempt=attempt)
        return {"status": "od_give_up"}, 200
    found_zone, existing = find_named(OD_NAME)
    if existing is not None and found_zone:
        zone = found_zone
    else:
        existing = None
    if existing is not None:
        if existing.status == "RUNNING":
            _log("od_running")
            return {"status": "od_up"}, 200
        if existing.status in {"TERMINATED", "STOPPED"}:
            start_instance(zone, OD_NAME)
        enqueue({"kind": "distmatch_od", "zone": zone, "phase": "wait_instance", "attempt": attempt + 1})
        return {"status": "od_starting", "vm_status": existing.status}, 200

    snap_name = payload.get("snapshot") or f"fm-sft-socrates-l4-dm-{int(time.time())}"
    snap = _snapshot(snap_name)
    if snap is None:
        spot = get_instance(home, SPOT_NAME)
        if spot is None or not spot.disks:
            return {"status": "no_source_disk"}, 200
        if spot.status == "RUNNING":
            _log("od_abort_spot_running")
            return {"status": "spot_running"}, 200
        snapshots.insert(
            project=PROJECT,
            snapshot_resource=compute_v1.Snapshot(
                name=snap_name,
                source_disk=spot.disks[0].source,
            ),
        )
        _log("snapshot_insert", snapshot=snap_name)
        enqueue(
            {
                "kind": "distmatch_od",
                "zone": home,
                "try_zone": zone,
                "phase": "wait_snapshot",
                "attempt": attempt + 1,
                "snapshot": snap_name,
            },
            delay=20,
        )
        return {"status": "snapshot_creating"}, 200
    if snap.status != "READY":
        _log("snapshot_wait", status=snap.status)
        enqueue(
            {
                "kind": "distmatch_od",
                "zone": home,
                "try_zone": zone,
                "phase": "wait_snapshot",
                "attempt": attempt + 1,
                "snapshot": snap_name,
            },
            delay=20,
        )
        return {"status": "snapshot_pending", "snapshot_status": snap.status}, 200

    spot = get_instance(home, SPOT_NAME)
    if spot is None:
        return {"status": "no_spot_template"}, 200
    zones = candidate_zones(home)
    if zone not in zones:
        zone = zones[0]
    ni = spot.network_interfaces[0]
    access = []
    if ni.access_configs:
        access = [compute_v1.AccessConfig(name="External NAT", type_="ONE_TO_ONE_NAT")]
    sa = spot.service_accounts[0]
    startup = meta_map(spot).get("startup-script", "")
    disk = compute_v1.AttachedDisk(
        auto_delete=False,
        boot=True,
        initialize_params=compute_v1.AttachedDiskInitializeParams(
            source_snapshot=f"projects/{PROJECT}/global/snapshots/{snap_name}",
            disk_size_gb=300,
            disk_type=f"zones/{zone}/diskTypes/pd-balanced",
        ),
    )
    inst = compute_v1.Instance(
        name=OD_NAME,
        machine_type=f"zones/{zone}/machineTypes/g2-standard-8",
        disks=[disk],
        network_interfaces=[
            compute_v1.NetworkInterface(
                network=ni.network,
                subnetwork=ni.subnetwork,
                access_configs=access,
            )
        ],
        service_accounts=[compute_v1.ServiceAccount(email=sa.email, scopes=list(sa.scopes))],
        guest_accelerators=[
            compute_v1.AcceleratorConfig(
                accelerator_count=1,
                accelerator_type=f"zones/{zone}/acceleratorTypes/nvidia-l4",
            )
        ],
        scheduling=compute_v1.Scheduling(
            provisioning_model="STANDARD",
            on_host_maintenance="TERMINATE",
            automatic_restart=True,
            preemptible=False,
        ),
        metadata=compute_v1.Metadata(
            items=[
                compute_v1.Items(key="startup-script", value=startup),
                compute_v1.Items(key="distmatch-mode", value="ondemand"),
            ]
        ),
        labels={
            "created-by": "cursor-agent",
            "usersim-do-not-start": "true",
            "usersim-fleet": "sft-dpo",
            "usersim-role": "distmatch-ondemand",
        },
    )
    try:
        instances.insert(project=PROJECT, zone=zone, instance_resource=inst)
        _log("od_insert", name=OD_NAME)
    except Exception as e:  # noqa: BLE001
        _log("od_insert_failed", zone=zone, error=str(e))
        if "already exists" not in str(e):
            nxt = zones[(zones.index(zone) + 1) % len(zones)] if zone in zones else zones[0]
            enqueue(
                {
                    "kind": "distmatch_od",
                    "zone": home,
                    "try_zone": nxt,
                    "phase": "create",
                    "attempt": attempt + 1,
                },
                delay=20,
            )
            return {"status": "od_insert_failed", "error": str(e), "next_zone_suffix": nxt[-2:]}, 200
    enqueue({"kind": "distmatch_od", "zone": zone, "phase": "wait_instance", "attempt": attempt + 1}, delay=30)
    return {"status": "od_created"}, 200


def parse_instance_from_audit(data: dict[str, Any]) -> tuple[str, str] | None:
    proto = data.get("protoPayload") or data
    if isinstance(proto, str):
        try:
            proto = json.loads(proto)
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(proto, dict):
        return None
    resource_name = proto.get("resourceName") or data.get("resourceName") or ""
    parts = resource_name.strip("/").split("/")
    try:
        return parts[parts.index("instances") + 1], parts[parts.index("zones") + 1]
    except (ValueError, IndexError):
        return None


def _load_json_body(request) -> dict[str, Any]:
    try:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
    except Exception:  # noqa: BLE001
        pass
    raw = request.get_data(as_text=True) or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@functions_framework.http
def distmatch_restart(request):
    # fm-gate0-spot-watchdog is the only Spot watcher. This function must not start VMs.
    body = {
        "status": "disabled",
        "reason": "fm-gate0-spot-watchdog is the only Spot watcher",
    }
    return (json.dumps(body), 200, {"Content-Type": "application/json"})

    if request.method == "GET":
        return (
            json.dumps({"ok": True, "service": "usersim-distmatch-restart", "spot": SPOT_NAME}),
            200,
            {"Content-Type": "application/json"},
        )
    payload = _load_json_body(request)
    ctype = (request.headers.get("Content-Type") or "").lower()
    ce_type = request.headers.get("ce-type") or request.headers.get("Ce-Type") or ""
    if "cloudevents" in ctype or ce_type or payload.get("protoPayload") or (
        isinstance(payload.get("data"), dict) and "protoPayload" in payload.get("data", {})
    ):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:  # noqa: BLE001
                data = {}
        parsed = parse_instance_from_audit(data if isinstance(data, dict) else {})
        if not parsed:
            return (json.dumps({"status": "unparsed"}), 204, {"Content-Type": "application/json"})
        body, code = handle_preempt(*parsed)
        return (json.dumps(body), code, {"Content-Type": "application/json"})

    kind = payload.get("kind")
    if kind == "distmatch_spot":
        body, code = handle_spot_retry(payload)
        return (json.dumps(body), code, {"Content-Type": "application/json"})
    if kind == "distmatch_od":
        body, code = handle_od(payload)
        return (json.dumps(body), code, {"Content-Type": "application/json"})
    return (json.dumps({"status": "ignored"}), 200, {"Content-Type": "application/json"})
