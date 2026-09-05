#!/usr/bin/env python3
"""E2E: create Spot copy from usersim-mvp-seed image, run 2 agents, assert copy gone."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
    os.environ.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", str(sa))

os.environ["MVP_GCP_FLEET"] = "1"
os.environ["MVP_SNAPSHOT_ONLY"] = "0"
os.environ["MVP_GCP_IMAGE_FAMILY"] = os.environ.get("MVP_GCP_IMAGE_FAMILY", "usersim-mvp-seed")
os.environ["MVP_GCP_WORKERS"] = "2"
os.environ["MVP_GCP_MACHINE"] = os.environ.get("MVP_GCP_MACHINE", "e2-standard-4")
os.environ["MVP_MAX_STEPS"] = "4"
os.environ["MVP_GCP_FLEET_TIMEOUT_S"] = "900"
os.environ["MVP_DISABLE_PROFILE_POOL"] = "1"
# Do not pin to a standing seed — exercise image-copy path.
os.environ.pop("MVP_GCP_TARGET_VM", None)


async def main() -> int:
    from mvp.gcp_fleet import INSTANCE_PREFIX, _list_mvp_instances, run_study_on_gcp_fleet

    study_id = "e2e" + os.urandom(3).hex()
    frames_seen: list[tuple[str, int]] = []

    async def on_frame(agent_id: str, frame: dict) -> None:
        step = int(frame.get("step") or 0)
        has_shot = bool(frame.get("screenshot_url"))
        frames_seen.append((agent_id, step))
        print(f"  LIVE frame agent={agent_id} step={step} screenshot={has_shot}", flush=True)

    async def on_status(msg: str) -> None:
        print(f"  STATUS {msg}", flush=True)

    personas = [
        {"id": "p1", "name": "Alex", "bio": "Curious first-time visitor.", "goals": ["Browse homepage"]},
        {"id": "p2", "name": "Sam", "bio": "Looking for creators content.", "goals": ["Find creators"]},
    ]
    tasks = [
        {
            "id": "t1",
            "title": "Browse home",
            "prompt": "Open the homepage and note the main headline.",
            "persona_id": "p1",
            "site_key": "product",
            "site_url": "https://www.example.com/",
            "site_label": "Product",
        },
        {
            "id": "t2",
            "title": "Browse again",
            "prompt": "Open the homepage and list one link.",
            "persona_id": "p2",
            "site_key": "product",
            "site_url": "https://www.example.com/",
            "site_label": "Product",
        },
    ]
    live = {
        t["id"]: {
            "agent_id": t["id"],
            "persona_name": next(p["name"] for p in personas if p["id"] == t["persona_id"]),
            "status": "starting",
            "trace": [],
        }
        for t in tasks
    }

    print(
        f"==> E2E image-fleet study_id={study_id} family={os.environ['MVP_GCP_IMAGE_FAMILY']}",
        flush=True,
    )
    before = {
        (inst.name, zone)
        for inst, zone in _list_mvp_instances(
            os.environ.get("GCP_PROJECT", "project-amer-scs-sandbox")
        )
        if (inst.name or "").startswith(f"{INSTANCE_PREFIX}{study_id[:8]}")
    }
    results = await run_study_on_gcp_fleet(
        study_id=study_id,
        url="https://www.example.com/",
        segment="Smoke testers",
        personas=personas,
        tasks=tasks,
        live_sessions=live,
        on_frame=on_frame,
        on_status=on_status,
        workers=2,
        keep_vm=False,
        study_snapshot={
            "id": study_id,
            "url": "https://www.example.com/",
            "segment": "Smoke testers",
            "personas": personas,
            "tasks": tasks,
            "status": "running",
            "site_summary": {},
        },
    )
    print(f"==> results={len(results)} live_frames={len(frames_seen)}", flush=True)
    for r in results:
        print(
            f"  agent={r.get('agent_id')} mode={r.get('mode')} "
            f"steps={len(r.get('trace') or [])} err={r.get('error')}",
            flush=True,
        )

    # Self-delete races the orchestrator's shard-marker read; poll rather than
    # assume a fixed grace period.
    deadline = time.time() + 180
    leftover: list[str] = []
    while True:
        leftover = []
        for inst, zone in _list_mvp_instances(
            os.environ.get("GCP_PROJECT", "project-amer-scs-sandbox")
        ):
            if (inst.name or "").startswith(f"{INSTANCE_PREFIX}{study_id[:8]}"):
                leftover.append(f"{inst.name}:{zone}:{inst.status}")
        if not leftover or time.time() > deadline:
            break
        time.sleep(10)
    print(f"==> leftover copies: {leftover or '(none)'}", flush=True)
    if leftover:
        print("FAIL: Spot copies still present", flush=True)
        return 1
    if len(results) < 2:
        print("FAIL: expected 2 results", flush=True)
        return 1
    errors = [r for r in results if r.get("error") or r.get("status") == "error"]
    if errors:
        print(f"FAIL: {len(errors)} agent(s) errored", flush=True)
        return 1
    if len(frames_seen) < 2:
        print(f"FAIL: expected live frames, got {len(frames_seen)}", flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
