#!/usr/bin/env python3
"""Run MVP study shard on a GCP Spot copy; stream frames to GCS; finish study if last."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _upload(local: Path, remote: str, *, content_type: str | None = None) -> None:
    try:
        from mvp.gcs_store import gcs_upload_file

        gcs_upload_file(local, remote, content_type=content_type)
        return
    except Exception as exc:  # noqa: BLE001
        print(f"gcs_store upload failed, trying gcloud: {exc}", flush=True)
    env = os.environ.copy()
    sa = ROOT / "secrets" / "sa.json"
    if sa.is_file():
        env.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
        env.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", str(sa))
    r = subprocess.run(
        ["gcloud", "storage", "cp", str(local), remote, "--quiet"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[-300:]
        print(f"GCS upload failed {local} -> {remote}: {err}", flush=True)


def _upload_json(uri: str, payload: Any) -> None:
    try:
        from mvp.gcs_store import gcs_upload_json

        gcs_upload_json(uri, payload)
        return
    except Exception as exc:  # noqa: BLE001
        print(f"gcs_store json upload failed: {exc}", flush=True)
    path = Path("/tmp/usersim_upload.json")
    path.write_text(json.dumps(payload, default=str))
    _upload(path, uri, content_type="application/json")


def _download_json(uri: str) -> dict[str, Any] | list[Any] | None:
    try:
        from mvp.gcs_store import gcs_download_json

        return gcs_download_json(uri)
    except Exception as exc:  # noqa: BLE001
        print(f"gcs_store download failed: {exc}", flush=True)
        return None


def _write_status(gcs_root: str, message: str, **extra: Any) -> None:
    _upload_json(f"{gcs_root.rstrip('/')}/status.json", {"message": message, **extra})


def _persist_screenshot(study_id: str, agent_id: str, step: dict[str, Any], live_dir: Path) -> None:
    """If step has a data-URL screenshot, upload PNG to GCS and rewrite URL to API proxy path."""
    shot = step.get("screenshot_url") or ""
    if not isinstance(shot, str) or not shot.startswith("data:image"):
        return
    m = re.match(r"data:image/(png|jpeg|jpg);base64,(.+)", shot, flags=re.I | re.S)
    if not m:
        return
    ext = "png" if m.group(1).lower() == "png" else "jpg"
    step_no = int(step.get("step") or 0)
    filename = f"bbox_{step_no}.{ext}" if step_no else f"step_{step_no}.{ext}"
    raw = base64.b64decode(m.group(2))
    local = live_dir / filename
    local.write_bytes(raw)
    gcs_uri = f"gs://{os.environ.get('MVP_GCS_BUCKET', 'usersim-bakeoff-347838016394')}/mvp_studies/{study_id}/screenshots/{agent_id}/{filename}"
    # Prefer study gcs root derived from env job.
    try:
        from mvp.gcs_store import screenshot_gcs_uri

        gcs_uri = screenshot_gcs_uri(study_id, agent_id, filename)
    except Exception:
        pass
    _upload(local, gcs_uri, content_type=f"image/{'png' if ext == 'png' else 'jpeg'}")
    step["screenshot_url"] = f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{filename}"
    step["screenshot_gcs"] = gcs_uri


async def _run_one(
    *,
    study_id: str,
    url: str,
    segment: str,
    persona: dict[str, Any],
    task: dict[str, Any],
    gcs_root: str,
    max_steps: int,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    from mvp.browser_agent import run_browser_agent
    from mvp.study import summarize_agent_feedback

    agent_id = task.get("id") or "agent"
    live_dir = Path(f"/tmp/usersim_live/{agent_id}")
    live_dir.mkdir(parents=True, exist_ok=True)
    manifest_steps: list[dict[str, Any]] = []

    async def on_step(step: dict[str, Any]) -> None:
        step_no = int(step.get("step") or 0)
        _persist_screenshot(study_id, agent_id, step, live_dir)
        # Keep a slim copy for the manifest (drop huge thought_detail if needed).
        slim = {k: v for k, v in step.items() if k != "thought_detail" or True}
        out = live_dir / f"step_{step_no:03d}.json"
        out.write_text(json.dumps(slim, default=str))
        _upload(out, f"{gcs_root.rstrip('/')}/live/{agent_id}/step_{step_no:03d}.json")
        manifest_steps.append(slim)
        _upload_json(
            f"{gcs_root.rstrip('/')}/live/{agent_id}/manifest.json",
            {"agent_id": agent_id, "steps": manifest_steps},
        )

    async with sem:
        run = await run_browser_agent(
            study_id=study_id,
            agent_id=agent_id,
            url=task.get("site_url") or url,
            task_prompt=task.get("prompt") or task.get("title") or "",
            persona=persona,
            segment=segment,
            max_steps=max_steps,
            on_step=on_step,
            local=True,
        )
    feedback = await summarize_agent_feedback(
        url=url,
        segment=segment,
        persona=persona,
        task=task,
        run=run,
    )
    outcomes = {
        o.get("step"): o.get("outcome") for o in feedback.pop("step_outcomes", []) or []
    }
    for step in run.get("trace") or []:
        step["outcome"] = outcomes.get(step.get("step")) or "neutral"
        _persist_screenshot(study_id, agent_id, step, live_dir)
    result = {
        **run,
        **feedback,
        "mode": "gcp_fleet",
        "persona_id": persona.get("id"),
        "persona_name": persona.get("name"),
        "persona_bio": persona.get("bio"),
        "task_id": task.get("id"),
        "task_title": task.get("title"),
        "task_prompt": task.get("prompt"),
        "site_key": task.get("site_key") or "product",
        "site_url": task.get("site_url") or url,
        "site_label": task.get("site_label") or "Product",
        "agent_id": agent_id,
    }
    done_path = live_dir / "result.json"
    done_path.write_text(json.dumps(result, default=str))
    _upload(done_path, f"{gcs_root.rstrip('/')}/live/{agent_id}/result.json")
    return result


async def _maybe_finish_study(job: dict[str, Any], shard_results: list[dict[str, Any]]) -> None:
    """If this is the last shard, synthesize summary and write final study.json + done.json."""
    if not job.get("finish_study"):
        return
    gcs_root = job["gcs_root"]
    study_id = job["study_id"]
    shard_index = int(job.get("shard_index") or 0)
    shard_count = int(job.get("shard_count") or 1)

    # Write our shard marker first.
    _upload_json(
        f"{gcs_root.rstrip('/')}/shard_{shard_index}_done.json",
        {"study_id": study_id, "shard_index": shard_index, "results": shard_results, "ok": True},
    )

    # Wait briefly for peer shards.
    all_results: list[dict[str, Any]] = []
    for _ in range(90):  # up to ~3 min
        missing = []
        collected: dict[int, list] = {}
        for i in range(shard_count):
            done = _download_json(f"{gcs_root.rstrip('/')}/shard_{i}_done.json")
            if isinstance(done, dict):
                collected[i] = list(done.get("results") or [])
            else:
                missing.append(i)
        if not missing:
            for i in range(shard_count):
                all_results.extend(collected.get(i) or [])
            break
        await asyncio.sleep(2)
    else:
        # Proceed with whatever we have + our shard.
        all_results = list(shard_results)
        for i in range(shard_count):
            if i == shard_index:
                continue
            done = _download_json(f"{gcs_root.rstrip('/')}/shard_{i}_done.json")
            if isinstance(done, dict):
                all_results.extend(list(done.get("results") or []))

    # Only the lowest-index shard among those that see all markers should finish,
    # to avoid duplicate summary writes. Use shard 0 as primary; if shard 0 is
    # gone, any shard that collected everything may finish.
    if shard_index != 0:
        # Check if shard 0 already wrote done.json
        existing = _download_json(f"{gcs_root.rstrip('/')}/done.json")
        if isinstance(existing, dict) and existing.get("results") is not None:
            return
        # If shard 0 marker missing for a while, allow takeover when we have all.
        s0 = _download_json(f"{gcs_root.rstrip('/')}/shard_0_done.json")
        if isinstance(s0, dict):
            # Shard 0 is alive / finished — let it write the summary.
            for _ in range(60):
                existing = _download_json(f"{gcs_root.rstrip('/')}/done.json")
                if isinstance(existing, dict) and existing.get("results") is not None:
                    return
                await asyncio.sleep(2)
            # Timed out waiting for shard 0 — take over.

    summary = None
    try:
        from mvp.study import synthesize_summary

        snap = job.get("study_snapshot") or {}
        summary = await synthesize_summary(
            url=job.get("url") or "",
            segment=job.get("segment") or "",
            site_summary=snap.get("site_summary") or {},
            agent_results=all_results,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"synthesize_summary failed: {exc}", flush=True)
        summary = {"headline": "Study finished (summary unavailable)", "error": str(exc)[:200]}

    done_payload = {
        "study_id": study_id,
        "results": all_results,
        "summary": summary,
        "ok": True,
        "finished_by_shard": shard_index,
    }
    _upload_json(f"{gcs_root.rstrip('/')}/done.json", done_payload)

    # Merge into study.json for the website.
    try:
        from mvp.gcs_store import read_study_state, write_study_state

        state = read_study_state(study_id) or (job.get("study_snapshot") or {})
        if not isinstance(state, dict):
            state = {}
        state["status"] = "complete"
        state["phase"] = "Complete"
        state["agent_results"] = all_results
        state["summary"] = summary
        state["live_sessions"] = state.get("live_sessions") or {}
        for r in all_results:
            aid = r.get("agent_id") or r.get("task_id")
            if not aid:
                continue
            sess = state["live_sessions"].setdefault(aid, {"agent_id": aid})
            sess["status"] = "complete"
            sess["trace"] = r.get("trace") or sess.get("trace") or []
            sess["num_steps"] = len(sess["trace"])
        write_study_state(study_id, state)
    except Exception as exc:  # noqa: BLE001
        print(f"write study.json failed: {exc}", flush=True)

    # Email is best-effort; website captures notify_email in study state.
    email = None
    try:
        from mvp.gcs_store import read_study_state

        st = read_study_state(study_id) or {}
        email = st.get("email") or st.get("notify_email")
    except Exception:
        email = (job.get("study_snapshot") or {}).get("email")
    if email:
        print(f"NOTE: email delivery deferred for {email} (hook TBD)", flush=True)

    _write_status(gcs_root, "Complete", done=True, agents=len(all_results))


async def main_async(job_path: Path) -> int:
    job = json.loads(job_path.read_text())
    study_id = job["study_id"]
    url = job["url"]
    segment = job.get("segment") or ""
    personas = job.get("personas") or []
    tasks = job.get("tasks") or []
    gcs_root = job["gcs_root"]
    workers = int(job.get("workers") or 8)
    max_steps = int(job.get("max_steps") or 8)
    persona_by_id = {p.get("id"): p for p in personas}
    shard_index = int(job.get("shard_index") or 0)

    os.environ.setdefault("MVP_FORCE_LOCAL_BROWSER", "1")
    os.environ.setdefault("MVP_BROWSER_HEADLESS", "0")
    os.environ.setdefault("MVP_BROWSER_CHANNEL", "0")
    os.environ.setdefault("BROWSER_HEADLESS", "0")
    os.environ.setdefault("DISPLAY", ":99")
    os.environ.setdefault("MVP_CHROMIUM_NO_SANDBOX", "1")
    # Public browsing this pass — skip signed-in profile clones unless flagged.
    if os.environ.get("MVP_SEED_PROFILE", "").lower() not in {"1", "true", "yes"}:
        os.environ["MVP_DISABLE_PROFILE_POOL"] = "1"

    _write_status(
        gcs_root,
        f"Shard {shard_index}: running {len(tasks)} agents ({workers} parallel, headed+Xvfb)",
        shard_index=shard_index,
    )
    sem = asyncio.Semaphore(workers)

    async def one(task: dict[str, Any]) -> dict[str, Any]:
        persona = persona_by_id.get(task.get("persona_id")) or (personas[0] if personas else {})
        try:
            return await _run_one(
                study_id=study_id,
                url=url,
                segment=segment,
                persona=persona,
                task=task,
                gcs_root=gcs_root,
                max_steps=max_steps,
                sem=sem,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "agent_id": task.get("id"),
                "task_id": task.get("id"),
                "persona_id": persona.get("id"),
                "persona_name": persona.get("name"),
                "task_title": task.get("title"),
                "status": "error",
                "error": str(exc)[:400],
                "trace": [],
                "mode": "gcp_fleet_error",
                "site_key": task.get("site_key") or "product",
                "site_url": task.get("site_url") or url,
                "site_label": task.get("site_label") or "Product",
            }

    results = list(await asyncio.gather(*[one(t) for t in tasks]))
    await _maybe_finish_study(job, results)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main_async(Path(args.job))))


if __name__ == "__main__":
    main()
