"""Eventarc + Cloud Tasks Spot restart for Gate-0 FM VMs.

Flow
----
1. Eventarc (Audit Log: compute.instances.preempted) → HTTP Cloud Function
2. Function filters to instances labeled usersim-spot-watch=true
3. Attempts instances.start; enqueues a Cloud Task retry
4. Task handler: if TERMINATED/STOPPED → start + re-enqueue;
   if RUNNING → stop retrying (session cleared)

Env
---
  GCP_PROJECT, TASKS_LOCATION, TASKS_QUEUE, FUNCTION_URL,
  OIDC_SERVICE_ACCOUNT, WATCH_LABEL_*, RETRY_DELAY_SEC, MAX_ATTEMPTS
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import functions_framework
from google.cloud import compute_v1, tasks_v2
from google.protobuf import timestamp_pb2

PROJECT = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
TASKS_LOCATION = os.environ.get("TASKS_LOCATION") or os.environ.get("FUNCTION_REGION") or ""
TASKS_QUEUE = os.environ.get("TASKS_QUEUE", "usersim-spot-retry")
FUNCTION_URL = os.environ.get("FUNCTION_URL", "").rstrip("/")
WATCH_KEY = os.environ.get("WATCH_LABEL_KEY", "usersim-spot-watch")
WATCH_VAL = os.environ.get("WATCH_LABEL_VALUE", "true")
RETRY_DELAY_SEC = int(os.environ.get("RETRY_DELAY_SEC", "60"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "180"))
OIDC_SA = os.environ.get("OIDC_SERVICE_ACCOUNT", "")

instances_client = compute_v1.InstancesClient()
tasks_client = tasks_v2.CloudTasksClient()


def _log(msg: str, **extra: Any) -> None:
    print(json.dumps({"msg": msg, **extra}, default=str), flush=True)


def _zone_from_url(zone: str) -> str:
    return zone.rsplit("/", 1)[-1] if "/" in zone else zone


def get_instance(project: str, zone: str, name: str) -> compute_v1.Instance | None:
    try:
        return instances_client.get(project=project, zone=zone, instance=name)
    except Exception as e:  # noqa: BLE001
        _log("get_instance_failed", name=name, zone=zone, error=str(e))
        return None


def is_watched(inst: compute_v1.Instance) -> bool:
    return dict(inst.labels or {}).get(WATCH_KEY) == WATCH_VAL


def start_instance(project: str, zone: str, name: str) -> str:
    try:
        op = instances_client.start(project=project, zone=zone, instance=name)
        _log("start_issued", name=name, zone=zone, op=getattr(op, "name", None))
        return "ok"
    except Exception as e:  # noqa: BLE001
        _log("start_failed", name=name, zone=zone, error=str(e))
        return f"fail:{e}"


def enqueue_retry(name: str, zone: str, attempt: int, reason: str) -> str | None:
    if not FUNCTION_URL:
        _log("skip_enqueue_no_FUNCTION_URL", name=name)
        return None
    if attempt > MAX_ATTEMPTS:
        _log("max_attempts_reached", name=name, attempt=attempt)
        return None

    parent = tasks_client.queue_path(PROJECT, TASKS_LOCATION, TASKS_QUEUE)
    body = {
        "kind": "spot_retry",
        "name": name,
        "zone": zone,
        "attempt": attempt,
        "reason": reason,
        "enqueued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
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

    task: dict[str, Any] = {"http_request": http_request}
    schedule = timestamp_pb2.Timestamp()
    schedule.FromSeconds(int(time.time()) + RETRY_DELAY_SEC)
    task["schedule_time"] = schedule

    created = tasks_client.create_task(request={"parent": parent, "task": task})
    _log("enqueued", name=name, attempt=attempt, task=created.name, delay=RETRY_DELAY_SEC)
    return created.name


def handle_retry(payload: dict[str, Any]) -> tuple[dict, int]:
    name = payload["name"]
    zone = _zone_from_url(payload["zone"])
    attempt = int(payload.get("attempt", 1))
    inst = get_instance(PROJECT, zone, name)
    if inst is None:
        return {"status": "missing", "name": name}, 200
    if not is_watched(inst):
        _log("unwatched_stop_retry", name=name)
        return {"status": "unwatched", "name": name}, 200

    status = inst.status
    _log("retry_tick", name=name, status=status, attempt=attempt)
    if status == "RUNNING":
        _log("session_clear", name=name, reason="RUNNING")
        return {"status": "up", "name": name}, 200
    if status in {"STAGING", "PROVISIONING", "REPAIRING"}:
        enqueue_retry(name, zone, attempt + 1, reason=f"wait:{status}")
        return {"status": "waiting", "name": name, "vm_status": status}, 200
    if status in {"TERMINATED", "STOPPED"}:
        start_instance(PROJECT, zone, name)
        enqueue_retry(name, zone, attempt + 1, reason=f"restart:{status}")
        return {"status": "restarted", "name": name, "vm_status": status}, 200

    enqueue_retry(name, zone, attempt + 1, reason=f"other:{status}")
    return {"status": "other", "name": name, "vm_status": status}, 200


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
        zi = parts.index("zones")
        ii = parts.index("instances")
        return parts[ii + 1], parts[zi + 1]
    except (ValueError, IndexError):
        return None


def handle_preempt(name: str, zone: str) -> tuple[dict, int]:
    zone = _zone_from_url(zone)
    inst = get_instance(PROJECT, zone, name)
    if inst is None:
        _log("preempt_instance_missing_try_start", name=name, zone=zone)
        start_instance(PROJECT, zone, name)
        enqueue_retry(name, zone, 1, reason="preempt_missing")
        return {"status": "started_blind", "name": name}, 200

    if not is_watched(inst):
        _log("preempt_ignored_unwatched", name=name)
        return {"status": "ignored", "name": name}, 200

    status = inst.status
    _log("preempt_seen", name=name, status=status)
    if status != "RUNNING":
        start_instance(PROJECT, zone, name)
    enqueue_retry(name, zone, 1, reason=f"preempt:{status}")
    return {"status": "watching", "name": name, "vm_status": status}, 200


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
def spot_restart(request):
    """HTTP entry for Eventarc CloudEvents + Cloud Tasks retries."""
    if request.method == "GET":
        return (
            json.dumps({"ok": True, "service": "usersim-spot-restart"}),
            200,
            {"Content-Type": "application/json"},
        )

    ctype = (request.headers.get("Content-Type") or "").lower()
    ce_type = request.headers.get("ce-type") or request.headers.get("Ce-Type") or ""

    payload = _load_json_body(request)

    # Eventarc binary/structured CloudEvent carrying audit log
    if "cloudevents" in ctype or ce_type or payload.get("protoPayload") or (
        isinstance(payload.get("data"), dict) and "protoPayload" in payload.get("data", {})
    ):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:  # noqa: BLE001
                data = {}
        _log("eventarc_delivery", ce_type=ce_type, keys=list(data.keys())[:12])
        parsed = parse_instance_from_audit(data if isinstance(data, dict) else {})
        if not parsed:
            _log("unparsed_eventarc", sample=str(payload)[:400])
            return (json.dumps({"status": "unparsed"}), 204, {"Content-Type": "application/json"})
        body, code = handle_preempt(*parsed)
        return (json.dumps(body), code, {"Content-Type": "application/json"})

    # Pub/Sub push wrapper
    if "message" in payload and "data" in payload.get("message", {}):
        raw = base64.b64decode(payload["message"]["data"]).decode()
        payload = json.loads(raw)

    kind = payload.get("kind")
    if kind == "spot_retry" or (
        "name" in payload and "zone" in payload and "attempt" in payload
    ):
        body, code = handle_retry(payload)
        return (json.dumps(body), code, {"Content-Type": "application/json"})

    if kind == "preempt" or (payload.get("name") and payload.get("zone")):
        body, code = handle_preempt(payload["name"], payload["zone"])
        return (json.dumps(body), code, {"Content-Type": "application/json"})

    return (
        json.dumps({"error": "unknown payload", "payload": payload}),
        400,
        {"Content-Type": "application/json"},
    )
