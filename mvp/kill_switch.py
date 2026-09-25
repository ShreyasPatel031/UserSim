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


def _session_user_metadata(session: Any) -> dict[str, str]:
    if isinstance(session, dict):
        raw = session.get("user_metadata") or session.get("userMetadata") or {}
    else:
        raw = getattr(session, "user_metadata", None) or getattr(session, "userMetadata", None) or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        out[str(key)] = str(value)
    return out


def list_running_browserbase(
    *,
    owner: str | None = None,
    study_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return Browserbase sessions currently RUNNING (best-effort).

    When ``owner`` is set, query Browserbase userMetadata so signup / untagged
    sessions on the shared project are never returned.
    """
    try:
        bb = _bb_client()
        list_kwargs: dict[str, Any] = {"status": "RUNNING"}
        # Prefer server-side metadata filter when scoping by owner. study_id is
        # filtered client-side — BB q only documents single field equality.
        if owner and owner != "*":
            list_kwargs["q"] = f"user_metadata['owner']:'{owner}'"
        try:
            out = bb.sessions.list(**list_kwargs)
        except TypeError:
            # Older SDK without status=/q= kwargs.
            out = bb.sessions.list()
        except Exception:
            # Metadata query unsupported / malformed — fall back to full list
            # and filter client-side (still skip non-matching owners).
            out = bb.sessions.list()
    except Exception as exc:  # noqa: BLE001
        return [{"id": "", "status": "error", "error": str(exc)[:200]}]
    items = getattr(out, "data", None) or getattr(out, "sessions", None) or out
    if not isinstance(items, (list, tuple)):
        try:
            items = list(items)
        except Exception:
            items = []
    running: list[dict[str, Any]] = []
    for s in items:
        if isinstance(s, dict):
            sid = str(s.get("id") or "")
            status = str(s.get("status") or "")
        else:
            sid = str(getattr(s, "id", "") or "")
            status = str(getattr(s, "status", "") or "")
        if status.upper() != "RUNNING" or not sid:
            continue
        meta = _session_user_metadata(s)
        sess_owner = meta.get("owner") or ""
        sess_study = meta.get("study_id") or ""
        if owner and owner != "*":
            if sess_owner != owner:
                continue
            if study_id and sess_study != study_id:
                continue
        running.append(
            {
                "id": sid,
                "status": status,
                "owner": sess_owner,
                "study_id": sess_study,
                "user_metadata": meta,
            }
        )
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


def kill_all_browserbase(
    *,
    owner: str | None = "e2e",
    study_id: str | None = None,
) -> dict[str, Any]:
    """REQUEST_RELEASE RUNNING Browserbase sessions we own.

    Default ``owner=\"e2e\"``: only release sessions tagged by our study code.
    Skips Sign Up sessions (``owner=signup``) and untagged sessions on the
    shared Browserbase project. Pass ``owner=\"*\"`` only for an explicit
    emergency release of every RUNNING session.
    """
    running = list_running_browserbase(owner=owner, study_id=study_id)
    released: list[str] = []
    failed: list[str] = []
    skipped: list[dict[str, str]] = []
    for row in running:
        if row.get("status") == "error" and not row.get("id"):
            continue
        sid = row.get("id") or ""
        if not sid:
            continue
        # Defense in depth: never release signup even if a caller widens owner.
        row_owner = str(row.get("owner") or "")
        if owner != "*" and row_owner == "signup":
            skipped.append({"id": sid, "reason": "signup"})
            continue
        if owner and owner != "*" and row_owner != owner:
            skipped.append({"id": sid, "reason": f"owner={row_owner or 'untagged'}"})
            continue
        if study_id and str(row.get("study_id") or "") != study_id:
            skipped.append({"id": sid, "reason": "study_mismatch"})
            continue
        if release_browserbase_session(sid):
            released.append(sid)
        else:
            failed.append(sid)
    return {
        "found": len(running),
        "released": len(released),
        "failed": failed,
        "skipped": skipped,
        "session_ids": released,
        "owner": owner,
        "study_id": study_id,
    }


def abandon_local_studies(*, study_id: str | None = None) -> dict[str, Any]:
    """Mark in-memory studies killed and cancel their asyncio tasks."""
    import os
    import traceback

    from mvp.study import STUDIES, STUDY_TASKS, persist_study

    if os.environ.get("MVP_DISABLE_KILL", "").lower() in {"1", "true", "yes"}:
        print(
            "abandon_local_studies skipped (MVP_DISABLE_KILL=1)\n"
            + "".join(traceback.format_stack(limit=8)),
            flush=True,
        )
        return {
            "abandoned": [],
            "gcs_abandoned": [],
            "cancelled_tasks": 0,
            "gcs_abandon_async": False,
            "target_ids": [],
            "skipped": "MVP_DISABLE_KILL",
        }

    # Snapshot targets NOW. A later GCS re-list was racing newly-started studies
    # and writing kill_requested onto them ("Killed by operator" with no click).
    if study_id and study_id in STUDIES:
        targets = [STUDIES[study_id]]
    else:
        targets = list(STUDIES.values())
    target_ids = [s.id for s in targets if getattr(s, "id", None)]
    print(
        f"abandon_local_studies targets={target_ids} study_id={study_id!r}\n"
        + "".join(traceback.format_stack(limit=6)),
        flush=True,
    )

    abandoned: list[str] = []
    cancelled_tasks = 0
    for study in targets:
        study.kill_requested = True
        if study.status in {"running", "pending", "queued"}:
            study.status = "abandoned"
            study.phase = "Killed"
            study.error = "Killed by operator"
            for sess in (study.live_sessions or {}).values():
                if isinstance(sess, dict) and sess.get("status") in {
                    "running",
                    "starting",
                    "pending",
                    "summarizing",
                }:
                    sess["status"] = "killed"
                if isinstance(sess, dict):
                    sess["live_active"] = False
            abandoned.append(study.id)
            try:
                persist_study(study)
            except Exception:
                pass
        task = STUDY_TASKS.pop(study.id, None)
        if task is not None and not task.done():
            task.cancel()
            cancelled_tasks += 1

    # Patch only the snapshotted ids in GCS — never re-list "all running".
    gcs_abandoned: list[str] = []
    try:
        from mvp.gcs_store import abandon_running_studies_in_gcs
        import threading

        ids_for_gcs = list(target_ids)
        if study_id and study_id not in ids_for_gcs:
            ids_for_gcs.append(study_id)

        def _gcs() -> None:
            nonlocal gcs_abandoned
            try:
                gcs_abandoned = abandon_running_studies_in_gcs(study_ids=ids_for_gcs)
            except Exception as exc:  # noqa: BLE001
                print(f"abandon_running_studies_in_gcs failed: {exc!r}", flush=True)

        threading.Thread(target=_gcs, name="gcs-abandon", daemon=True).start()
    except Exception as exc:  # noqa: BLE001
        print(f"abandon_running_studies_in_gcs failed: {exc!r}", flush=True)
    return {
        "abandoned": abandoned,
        "gcs_abandoned": gcs_abandoned,
        "cancelled_tasks": cancelled_tasks,
        "gcs_abandon_async": True,
        "target_ids": target_ids,
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

    # Unfiltered view for operators (includes signup / untagged on shared BB).
    bb = list_running_browserbase(owner="*")
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
    """Kill immediately. Agents = our Browserbase sessions + abandon local studies.

    Never releases Sign Up / untagged Browserbase sessions on the shared project.
    """
    result: dict[str, Any] = {"ok": True}
    if agents:
        # Release all e2e-owned sessions (any study). Scoping BB release to
        # study_id would leave orphaned e2e slots from prior abandoned runs.
        result["browserbase"] = kill_all_browserbase(owner="e2e")
        result["studies"] = abandon_local_studies(study_id=study_id)
    if vms or seeds:
        result["vms"] = kill_usersim_vms(include_seeds=bool(seeds))
    result["status"] = runtime_status()
    return result


async def kill_now_async(**kwargs: Any) -> dict[str, Any]:
    """Run blocking GCP/BB calls off the event loop."""
    return await asyncio.to_thread(kill_now, **kwargs)
