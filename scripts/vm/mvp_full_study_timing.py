#!/usr/bin/env python3
"""Time a full production-shape study on the GCP fleet.

Target shape: 1 product + 2 competitors x 5 personas x 6 tasks = 18 parallel
agents. Prints a per-phase breakdown so the 5-minute budget can be attributed.
"""

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
os.environ.setdefault("MVP_GCP_IMAGE_FAMILY", "usersim-mvp-seed")
os.environ.setdefault("MVP_PERSONA_COUNT", "5")
os.environ.setdefault("MVP_TASK_COUNT", "6")
os.environ.setdefault("MVP_GCP_WORKERS", "6")
os.environ.setdefault("MVP_GCP_MACHINE", "e2-standard-8")
os.environ.setdefault("MVP_MAX_STEPS", "8")
os.environ.setdefault("MVP_GCP_FLEET_TIMEOUT_S", "900")
os.environ["MVP_DISABLE_PROFILE_POOL"] = "1"
os.environ.pop("MVP_GCP_TARGET_VM", None)

URL = os.environ.get("TIMING_URL", "https://www.notion.so/")
SEGMENT = os.environ.get("TIMING_SEGMENT", "Small-team product managers")


async def main() -> int:
    from mvp.study import create_study, run_study

    t0 = time.monotonic()
    marks: list[tuple[float, str]] = []
    last_phase = {"v": ""}

    def on_update(study) -> None:
        phase = f"{study.status}: {study.phase}"
        if phase != last_phase["v"]:
            last_phase["v"] = phase
            elapsed = time.monotonic() - t0
            marks.append((elapsed, phase))
            print(f"  [{elapsed:6.1f}s] {phase}", flush=True)

    study = create_study(URL, SEGMENT)
    print(f"==> full-shape timing study={study.id} url={URL}", flush=True)

    try:
        await run_study(study.id, on_update=on_update)
    except Exception as exc:  # noqa: BLE001
        print(f"==> run_study raised: {exc}", flush=True)

    total = time.monotonic() - t0
    results = study.agent_results or []
    errors = [r for r in results if r.get("error") or r.get("status") == "error"]
    sites = {r.get("site_key") for r in results}

    print("\n==> PHASE BREAKDOWN", flush=True)
    prev = 0.0
    for elapsed, phase in marks:
        print(f"  +{elapsed - prev:6.1f}s  (t={elapsed:6.1f}s)  {phase}", flush=True)
        prev = elapsed

    print(
        f"\n==> total={total:.1f}s agents={len(results)} sites={len(sites)} "
        f"errors={len(errors)} personas={len(study.personas or [])} "
        f"tasks={len(study.tasks or [])}",
        flush=True,
    )
    for r in errors[:5]:
        print(f"  ERR agent={r.get('agent_id')} {r.get('error')}", flush=True)

    ok = total <= 300 and len(results) >= 18 and not errors
    print("PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
