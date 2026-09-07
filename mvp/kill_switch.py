"""Immediate kill switches for Browserbase agents + UserSim GCP VMs."""

from __future__ import annotations

import asyncio
import os
from typing import Any


class StudyKilled(Exception):
    """Raised when a study is aborted via the kill switch."""


def _bb_client():
    from browserbase import Browserbase
    from capability.browserbase_client import browserbase_api_key

    return Browserbase(api_key=browserbase_api_key())


def list_running_browserbase() -> list[dict[str, str]]:
    """Return Browserbase sessions currently RUNNING (best-effort)."""
    try:
        bb = _bb_client()
        out = bb.sessions.list()
    except Exception as exc:  # noqa: BLE001
        return [{"id": "", "status": "error", "error": str(exc)[:200]}]
    items = getattr(out, "data", None) or getattr(out, "sessions", None) or out
    if not isinstance(items, (list, tuple)):
        try:
            items = list(items)
        except Exception:
            items = []
    running: list[dict[str, str]] = []
    for s in items:
        if isinstance(s, dict):
            sid = str(s.get("id") or "")
            status = str(s.get("status") or "")
        else:
            sid = str(getattr(s, "id", "") or "")
            status = str(getattr(s, "status", "") or "")
        if status.upper() == "RUNNING" and sid:
            running.append({"id": sid, "status": status})
    return running


def release_browserbase_session(session_id: str) -> bool:
    if not session_id:
        return False
    try:
        from capability.browserbase_client import close_session

        close_session(session_id)
        return True
    except Exception:
        try:
            _bb_client().sessions.update(session_id, status="REQUEST_RELEASE")
            return True
        except Exception:
            return False


def kill_all_browserbase() -> dict[str, Any]:
    """REQUEST_RELEASE every RUNNING Browserbase session. Immediate."""
    running = list_running_browserbase()
    released: list[str] = []
    failed: list[str] = []
    for row in running:
        sid = row.get("id") or ""
        if not sid:
            continue
        if release_browserbase_session(sid):
            released.append(sid)
        else:
            failed.append(sid)
    return {
        "found": len(running),
        "released": len(released),
        "failed": failed,
        "session_ids": released,
    }


def abandon_local_studies(*, study_id: str | None = None) -> dict[str, Any]:
    """Mark in-memory studies killed and cancel their asyncio tasks."""
    from mvp.study import STUDIES, STUDY_TASKS, persist_study

    targets = [STUDIES[study_id]] if study_id and study_id in STUDIES else list(STUDIES.values())
    abandoned: list[str] = []
    cancelled_tasks = 0
    for study in targets:
        if study.status in {"complete", "error", "abandoned"} and not getattr(
            study, "kill_requested", False
        ):
            # Still allow force-kill of lingering sessions belonging to finished studies.
            pass
        study.kill_requested = True
        if study.status in {"running", "pending", "queued"}:
            study.status = "abandoned"
            study.phase = "Killed"
            study.error = "Killed by operator"
            for sess in (study.live_sessions or {}).values():
                if sess.get("status") in {"running", "starting", "pending", "summarizing"}:
                    sess["status"] = "killed"
            abandoned.append(study.id)
            try:
                persist_study(study)
            except Exception:
                pass
        task = STUDY_TASKS.pop(study.id, None)
        if task is not None and not task.done():
            task.cancel()
            cancelled_tasks += 1

    # Always patch GCS too — after a server restart memory is empty but /live
    # still lists GCS study.json as "running".
    gcs_abandoned: list[str] = []
    try:
        from mvp.gcs_store import abandon_running_studies_in_gcs

        gcs_abandoned = abandon_running_studies_in_gcs(study_id=study_id)
    except Exception as exc:  # noqa: BLE001
        print(f"abandon_running_studies_in_gcs failed: {exc!r}", flush=True)
    return {
        "abandoned": abandoned,
        "gcs_abandoned": gcs_abandoned,
        "cancelled_tasks": cancelled_tasks,
    }


def _gcp_project() -> str:
    return (
        os.environ.get("GCP_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or "project-amer-scs-sandbox"
    )


def list_usersim_vms(*, include_seeds: bool = True) -> list[dict[str, str]]:
    """List UserSim-related compute instances (mvp fleet + optional seeds)."""
    try:
        from google.cloud import compute_v1
    except Exception as exc:  # noqa: BLE001
        return [{"name": "", "status": "error", "error": str(exc)[:200]}]

    project = _gcp_project()
    client = compute_v1.InstancesClient()
    out: list[dict[str, str]] = []
    try:
        for zone_path, scoped in client.aggregated_list(project=project):
            zone = zone_path.split("/")[-1] if zone_path else ""
            for inst in scoped.instances or []:
                name = inst.name or ""
                if name.startswith("usersim-mvp-"):
                    kind = "fleet"
                elif include_seeds and (
                    name.startswith("usersim-youtube-seed-")
                    or name.startswith("usersim-signup-seed-")
                    or name.startswith("usersim-mvp-seed")
                ):
                    kind = "seed"
                else:
                    continue
                out.append(
                    {
                        "name": name,
                        "zone": zone,
                        "status": str(inst.status or ""),
                        "kind": kind,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return [{"name": "", "status": "error", "error": str(exc)[:200]}]
    return out


def delete_vm(name: str, zone: str) -> bool:
    try:
        from google.cloud import compute_v1

        client = compute_v1.InstancesClient()
        op = client.delete(project=_gcp_project(), zone=zone, instance=name)
        # Don't block the HTTP response on full delete — fire and return.
        try:
            op.result(timeout=5)
        except Exception:
            pass
        return True
    except Exception:
        return False


def kill_usersim_vms(*, include_seeds: bool = False) -> dict[str, Any]:
    vms = list_usersim_vms(include_seeds=True)
    deleted: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for vm in vms:
        name = vm.get("name") or ""
        zone = vm.get("zone") or ""
        kind = vm.get("kind") or ""
        if not name or not zone:
            continue
        if kind == "seed" and not include_seeds:
            skipped.append(name)
            continue
        if delete_vm(name, zone):
            deleted.append(name)
        else:
            failed.append(name)
    return {
        "deleted": deleted,
        "skipped_seeds": skipped,
        "failed": failed,
        "include_seeds": include_seeds,
    }


def runtime_status() -> dict[str, Any]:
    from mvp.study import STUDIES

    bb = list_running_browserbase()
    local_running = [
        {"id": s.id, "status": s.status, "phase": s.phase, "url": s.url}
        for s in STUDIES.values()
        if s.status in {"running", "pending", "queued"}
    ]
    vms = list_usersim_vms(include_seeds=True)
    return {
        "browserbase_running": len([x for x in bb if x.get("id")]),
        "browserbase_sessions": bb[:50],
        "local_studies_running": len(local_running),
        "local_studies": local_running,
        "vms": vms,
        "vm_count": len(vms),
    }


def kill_now(
    *,
    agents: bool = True,
    vms: bool = False,
    seeds: bool = False,
    study_id: str | None = None,
) -> dict[str, Any]:
    """Kill immediately. Agents = Browserbase + abandon local studies."""
    result: dict[str, Any] = {"ok": True}
    if agents:
        result["browserbase"] = kill_all_browserbase()
        result["studies"] = abandon_local_studies(study_id=study_id)
    if vms or seeds:
        result["vms"] = kill_usersim_vms(include_seeds=bool(seeds))
    result["status"] = runtime_status()
    return result


async def kill_now_async(**kwargs: Any) -> dict[str, Any]:
    """Run blocking GCP/BB calls off the event loop."""
    return await asyncio.to_thread(kill_now, **kwargs)
