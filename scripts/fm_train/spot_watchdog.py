#!/usr/bin/env python3
"""Poll labeled Spot VMs and restart only after a preemption.

Runs on fm-gate0-spot-watchdog (on-demand e2-micro) from a 60s systemd timer.

A TERMINATED VM is restarted only when the newest stop since lastStartTimestamp
was a preemption (compute.instances.preempted, a maintenance simulation, or a
Spot VM that went down with no user/agent stop operation). A stop issued by a
person or an agent is left alone. usersim-train-state=done,
usersim-do-not-start=true, and a missing usersim-spot-watch label are also
left alone.

A start whose operation finishes while the VM is still TERMINATED is a
stockout, not a success. Stockouts do not increment usersim-spot-restarts.
That counter counts successful starts only. A stockout, or the cap after a
real preemption, starts the single on-demand instance named by
usersim-failover-to and resumes there. It does not try any other machine.
With no failover target, a stockout backs off and retries while
usersim-train-state=running.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LABEL_KEY = os.environ.get("WATCH_LABEL_KEY", "usersim-spot-watch")
LABEL_VALUE = os.environ.get("WATCH_LABEL_VALUE", "true")
STATE_LABEL = os.environ.get("TRAIN_STATE_LABEL", "usersim-train-state")
DENY_LABEL = os.environ.get("DENY_LABEL_KEY", "usersim-do-not-start")
RESTARTS_LABEL = os.environ.get("RESTARTS_LABEL", "usersim-spot-restarts")
TEST_LABEL = os.environ.get("TEST_PREEMPT_LABEL", "usersim-spot-test-preempt")
STOCKOUT_LABEL = os.environ.get("TEST_STOCKOUT_LABEL", "usersim-spot-test-stockout")
FAILOVER_LABEL = os.environ.get("FAILOVER_LABEL", "usersim-failover-to")
UP_OR_COMING = {"RUNNING", "STAGING", "PROVISIONING"}
STATE_DIR = Path(os.environ.get("STATE_DIR", "/var/lib/usersim-spot-watch"))
LOG = Path(os.environ.get("WATCH_LOG", "/var/log/usersim-spot-watch.log"))
MAX_RESTARTS = int(os.environ.get("MAX_RESTARTS", "6"))
DENY_PREFIXES = ("dose-oss",)

PREEMPT_TYPES = {
    "preempted",
    "compute.instances.preempted",
    "compute.instances.simulateMaintenanceEvent",
    "simulateMaintenanceEvent",
}
STOP_TYPES = {
    "stop",
    "compute.instances.stop",
    "guestTerminate",
    "compute.instances.guestTerminate",
}
DOWN = {"TERMINATED", "STOPPED"}


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + msg
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def project() -> str:
    value = os.environ.get("GCP_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")
    if value:
        return value
    result = run(["gcloud", "config", "get-value", "project"], timeout=30)
    return (result.stdout or "").strip()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def classify_start(returncode: int, status_after: str) -> tuple[bool, str]:
    """A finished start op that leaves the VM down is a stockout, not success."""
    if returncode != 0:
        return False, "start_command_failed"
    if status_after not in UP_OR_COMING:
        return False, f"start_op_done_but_still_{status_after or 'UNKNOWN'}"
    return True, "ok"


def newest_stop_kind(last_start: datetime | None, ops: list[dict]) -> tuple[str, str]:
    """Return (preempted|user_stop|none, operation type)."""
    newest_preempt: datetime | None = None
    newest_stop: datetime | None = None
    preempt_type = ""
    stop_type = ""
    for op in ops:
        stamp = op.get("time")
        if not isinstance(stamp, datetime):
            stamp = parse_time(op.get("insertTime") or op.get("time"))
        if stamp is None or (last_start is not None and stamp <= last_start):
            continue
        kind = str(op.get("type") or op.get("operationType") or "")
        if kind in PREEMPT_TYPES or "preempt" in kind.lower():
            if newest_preempt is None or stamp > newest_preempt:
                newest_preempt = stamp
                preempt_type = kind
        elif kind in STOP_TYPES or kind.endswith(".stop") or kind == "stop":
            if newest_stop is None or stamp > newest_stop:
                newest_stop = stamp
                stop_type = kind
    if newest_stop is not None and (newest_preempt is None or newest_stop > newest_preempt):
        return "user_stop", stop_type
    if newest_preempt is not None:
        return "preempted", preempt_type
    return "none", ""


def decide(
    name: str,
    status: str,
    preemptible: bool,
    last_start: datetime | None,
    ops: list[dict],
    labels: dict[str, str],
) -> tuple[str, str]:
    """Return (action, reason). action is start, failover, or skip."""
    if name.startswith(DENY_PREFIXES) or "dose-oss" in name:
        return "skip", "other_team"
    if labels.get(LABEL_KEY) != LABEL_VALUE:
        return "skip", "not_watched"
    if labels.get(STATE_LABEL) == "done":
        return "skip", "train_state_done"
    if status == "RUNNING":
        return "skip", "running"
    if labels.get(DENY_LABEL) == "true":
        return "skip", "do_not_start"
    if status in {"STAGING", "PROVISIONING", "REPAIRING", "SUSPENDING", "STOPPING"}:
        return "skip", f"waiting_{status}"
    if status not in DOWN:
        return "skip", f"status_{status}"
    if labels.get(STOCKOUT_LABEL) == "true":
        return "start", "simulated_stockout"
    if labels.get(TEST_LABEL) == "true":
        return "start", "test_preempt_marker"
    try:
        restarts = int(labels.get(RESTARTS_LABEL) or "0")
    except ValueError:
        restarts = 0
    kind, detail = newest_stop_kind(last_start, ops)
    if kind == "user_stop":
        return "skip", f"user_or_agent_stop {detail}"
    preempted = kind == "preempted" or (preemptible and kind == "none")
    if restarts >= MAX_RESTARTS:
        if preempted and labels.get(FAILOVER_LABEL):
            return "failover", f"restart_cap_{restarts}"
        return "skip", f"restart_cap_{restarts}"
    if kind == "preempted":
        return "start", f"preempted_op {detail}"
    if preemptible and kind == "none":
        return "start", "spot_termination_without_user_stop"
    return "skip", "no_preempt_evidence"


def list_watched() -> list[dict]:
    filt = f"labels.{LABEL_KEY}={LABEL_VALUE}"
    result = run(
        [
            "gcloud",
            "compute",
            "instances",
            "list",
            f"--project={project()}",
            f"--filter={filt}",
            "--format=json(name,zone,status,labels,lastStartTimestamp,scheduling.preemptible)",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        log(f"DECISION name=* action=skip reason=list_failed detail={(result.stderr or result.stdout)[-300:]}")
        return []
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        log("DECISION name=* action=skip reason=list_bad_json")
        return []
    out = []
    for row in rows:
        zone = row.get("zone") or ""
        if "/" in zone:
            zone = zone.rsplit("/", 1)[-1]
        scheduling = row.get("scheduling") or {}
        out.append(
            {
                "name": row["name"],
                "zone": zone,
                "status": row.get("status") or "UNKNOWN",
                "labels": row.get("labels") or {},
                "last_start": parse_time(row.get("lastStartTimestamp")),
                "preemptible": bool(scheduling.get("preemptible")),
            }
        )
    return out


def recent_ops(zone: str, name: str) -> list[dict]:
    result = run(
        [
            "gcloud",
            "compute",
            "operations",
            "list",
            f"--project={project()}",
            f"--zones={zone}",
            f"--filter=targetLink:{name}",
            "--sort-by=~insertTime",
            "--limit=30",
            "--format=json(operationType,insertTime,status)",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        log(f"DECISION name={name} action=skip reason=ops_list_failed detail={(result.stderr or '')[-240:]}")
        return []
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        log(f"DECISION name={name} action=skip reason=ops_bad_json")
        return []
    ops = []
    for row in rows:
        ops.append(
            {
                "type": row.get("operationType") or "",
                "time": parse_time(row.get("insertTime")),
                "status": row.get("status") or "",
            }
        )
    return ops


def state_path(name: str) -> Path:
    return STATE_DIR / f"{name}.json"


def load_state(name: str) -> dict:
    path = state_path(name)
    if not path.exists():
        return {"consecutive_failures": 0}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"consecutive_failures": 0}


def save_state(name: str, payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(name).write_text(json.dumps(payload, indent=2) + "\n")


def add_labels(inst: dict, updates: dict[str, str]) -> None:
    if not updates:
        return
    spec = ",".join(f"{key}={value}" for key, value in updates.items())
    result = run(
        [
            "gcloud",
            "compute",
            "instances",
            "add-labels",
            inst["name"],
            f"--zone={inst['zone']}",
            f"--project={project()}",
            f"--labels={spec}",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        log(f"DECISION name={inst['name']} action=note reason=label_update_failed detail={(result.stderr or '')[-240:]}")


def remove_labels(inst: dict, keys: list[str]) -> None:
    result = run(
        [
            "gcloud",
            "compute",
            "instances",
            "remove-labels",
            inst["name"],
            f"--zone={inst['zone']}",
            f"--project={project()}",
            f"--labels={','.join(keys)}",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        log(f"DECISION name={inst['name']} action=note reason=label_remove_failed detail={(result.stderr or '')[-240:]}")


def start_instance(inst: dict) -> tuple[int, str]:
    result = run(
        [
            "gcloud",
            "compute",
            "instances",
            "start",
            inst["name"],
            f"--zone={inst['zone']}",
            f"--project={project()}",
        ],
        timeout=300,
    )
    text = ((result.stdout or "") + (result.stderr or ""))[-500:]
    return result.returncode, text.replace("\n", " ")


def instance_status(inst: dict) -> str:
    result = run(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            inst["name"],
            f"--zone={inst['zone']}",
            f"--project={project()}",
            "--format=value(status)",
        ],
        timeout=60,
    )
    return (result.stdout or "").strip() or "UNKNOWN"


def wait_until_up(inst: dict, attempts: int = 4, pause: float = 5.0) -> str:
    status = "UNKNOWN"
    for _ in range(attempts):
        status = instance_status(inst)
        if status in UP_OR_COMING:
            return status
        time.sleep(pause)
    return status


def find_instance(name: str) -> dict | None:
    result = run(
        [
            "gcloud",
            "compute",
            "instances",
            "list",
            f"--project={project()}",
            "--format=json(name,zone,status,labels,lastStartTimestamp,scheduling.preemptible)",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        log(f"FAILOVER name={name} result=fail reason=list_failed detail={(result.stderr or '')[-240:]}")
        return None
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        log(f"FAILOVER name={name} result=fail reason=list_bad_json")
        return None
    for row in rows:
        if row.get("name") != name:
            continue
        zone = row.get("zone") or ""
        if "/" in zone:
            zone = zone.rsplit("/", 1)[-1]
        scheduling = row.get("scheduling") or {}
        return {
            "name": row["name"],
            "zone": zone,
            "status": row.get("status") or "UNKNOWN",
            "labels": row.get("labels") or {},
            "last_start": parse_time(row.get("lastStartTimestamp")),
            "preemptible": bool(scheduling.get("preemptible")),
        }
    return None


def do_failover(source: dict, why: str) -> bool:
    """Start the one named on-demand VM and stop watching the Spot VM."""
    target_name = (source["labels"].get(FAILOVER_LABEL) or "").strip()
    if not target_name or target_name == source["name"] or target_name.startswith(DENY_PREFIXES) or "dose-oss" in target_name:
        log(f"FAILOVER name={source['name']} result=fail reason=no_target detail={why} note=no_further_failover")
        return False
    target = find_instance(target_name)
    if target is None:
        log(f"FAILOVER name={source['name']} target={target_name} result=fail reason=target_missing detail={why} note=no_further_failover")
        return False
    remove_labels(source, [LABEL_KEY, STOCKOUT_LABEL, TEST_LABEL])
    add_labels(source, {DENY_LABEL: "true", STATE_LABEL: "yielded"})
    add_labels(
        target,
        {
            LABEL_KEY: LABEL_VALUE,
            STATE_LABEL: "running",
            RESTARTS_LABEL: "0",
        },
    )
    remove_labels(target, [DENY_LABEL, STOCKOUT_LABEL])
    if target["status"] in UP_OR_COMING:
        log(f"FAILOVER name={source['name']} target={target_name} result=ok reason=already_running detail={why}")
        return True
    code, detail = start_instance(target)
    status = wait_until_up(target)
    ok, classified = classify_start(code, status)
    if ok:
        log(f"FAILOVER name={source['name']} target={target_name} result=ok reason={why} status={status}")
        return True
    log(
        f"FAILOVER name={source['name']} target={target_name} result=fail "
        f"reason={classified} status={status} detail={detail[:240]} note=no_further_failover"
    )
    return False


def stockout_backoff_s(failures: int) -> int:
    """Seconds to wait before the next Spot start. Does not stop the retries."""
    if failures <= 0:
        return 0
    return min(300, 60 * (2 ** min(failures - 1, 3)))


def capacity_error(detail: str) -> bool:
    upper = detail.upper()
    return any(
        mark in upper
        for mark in ("ZONE_RESOURCE_POOL_EXHAUSTED", "STOCKOUT", "RESOURCE_POOL_EXHAUSTED", "QUOTA")
    )


def tick() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    watched = list_watched()
    if not watched:
        log(f"DECISION name=* action=skip reason=no_instances_with_{LABEL_KEY}={LABEL_VALUE}")
        return 0
    started = 0
    for inst in watched:
        name = inst["name"]
        ops = recent_ops(inst["zone"], name) if inst["status"] in DOWN else []
        action, reason = decide(
            name,
            inst["status"],
            inst["preemptible"],
            inst["last_start"],
            ops,
            inst["labels"],
        )
        state = load_state(name)
        if action == "failover":
            log(
                f"DECISION name={name} action=failover reason={reason} "
                f"status={inst['status']} restarts={inst['labels'].get(RESTARTS_LABEL, '0')}"
            )
            if do_failover(inst, reason):
                started += 1
            continue
        if action != "start":
            if inst["status"] == "RUNNING":
                state["consecutive_failures"] = 0
                state["next_try_epoch"] = 0
                save_state(name, state)
            log(
                f"DECISION name={name} action={action} reason={reason} "
                f"status={inst['status']} restarts={inst['labels'].get(RESTARTS_LABEL, '0')}"
            )
            continue
        if reason == "simulated_stockout":
            log(
                f"DECISION name={name} action=start reason=simulated_stockout result=fail "
                f"detail=start_op_done_but_still_TERMINATED status={inst['status']} "
                f"restarts={inst['labels'].get(RESTARTS_LABEL, '0')}/{MAX_RESTARTS}"
            )
            if do_failover(inst, "simulated_stockout"):
                started += 1
            continue
        try:
            restarts = int(inst["labels"].get(RESTARTS_LABEL) or "0")
        except ValueError:
            restarts = 0
        wait_s = int(float(state.get("next_try_epoch") or 0) - time.time())
        if wait_s > 0 and inst["labels"].get(STATE_LABEL) == "running":
            log(
                f"DECISION name={name} action=skip reason=stockout_backoff "
                f"wait_s={wait_s} status={inst['status']} restarts={restarts}/{MAX_RESTARTS}"
            )
            continue
        code, detail = start_instance(inst)
        status_after = wait_until_up(inst) if code == 0 else instance_status(inst)
        ok, classified = classify_start(code, status_after)
        if ok:
            new_count = str(restarts + 1)
            add_labels(inst, {RESTARTS_LABEL: new_count})
            state["consecutive_failures"] = 0
            state["next_try_epoch"] = 0
            save_state(name, state)
            if inst["labels"].get(TEST_LABEL) == "true":
                remove_labels(inst, [TEST_LABEL])
            log(
                f"DECISION name={name} action=start reason={reason} result=ok "
                f"status={status_after} restarts={new_count}/{MAX_RESTARTS}"
            )
            started += 1
            continue
        failures = int(state.get("consecutive_failures") or 0) + 1
        state["consecutive_failures"] = failures
        delay = stockout_backoff_s(failures)
        state["next_try_epoch"] = time.time() + delay
        save_state(name, state)
        fail_detail = detail if code != 0 else classified
        stockout = classified.startswith("start_op_done_but_still_") or capacity_error(detail) or capacity_error(classified)
        log(
            f"DECISION name={name} action=start reason={reason} result=fail "
            f"consecutive_failures={failures} restarts={restarts}/{MAX_RESTARTS} "
            f"backoff_s={delay} detail={fail_detail} "
            "note=stockout_does_not_consume_cap"
        )
        if stockout and inst["labels"].get(FAILOVER_LABEL):
            log(
                f"CAPACITY name={name} consecutive_failures={failures} restarts={restarts}/{MAX_RESTARTS} "
                "note=stockout does not consume the cap; failing over to on-demand"
            )
            if do_failover(inst, "stockout"):
                started += 1
            continue
        if stockout:
            log(
                f"CAPACITY name={name} consecutive_failures={failures} restarts={restarts}/{MAX_RESTARTS} "
                "note=Spot capacity failed; restart cap unchanged; will retry while train-state=running"
            )
    return started


def main() -> int:
    log(f"watchdog tick project={project()} label={LABEL_KEY}={LABEL_VALUE} max_restarts={MAX_RESTARTS}")
    try:
        n = tick()
    except Exception as exc:  # noqa: BLE001
        log(f"DECISION name=* action=skip reason=fatal {type(exc).__name__}: {exc}")
        return 1
    log(f"watchdog done starts_attempted_ok={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
