#!/usr/bin/env python3
"""Navigate warm CDP Chromium; push first frame to UI ASAP; GCS in background."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _upload(local: Path, remote: str, *, content_type: str | None = None) -> None:
    from mvp.gcs_store import gcs_upload_file

    gcs_upload_file(local, remote, content_type=content_type)


def _upload_json(uri: str, payload: Any) -> None:
    from mvp.gcs_store import gcs_upload_json

    gcs_upload_json(uri, payload)


_PAINT_BOXES_JS = """() => {
  document.querySelectorAll('[data-usersim-box]').forEach(n => n.remove());
  const sels = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]';
  const els = Array.from(document.querySelectorAll(sels));
  const items = [];
  let i = 0;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) continue;
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    i += 1;
    if (i > 36) break;
    const label = ((el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || el.tagName) + '').trim().slice(0, 80);
    items.push({index: i, label, tag: el.tagName.toLowerCase()});
    const box = document.createElement('div');
    box.setAttribute('data-usersim-box', '1');
    box.style.cssText = [
      'position:fixed',
      `left:${r.left}px`,
      `top:${r.top}px`,
      `width:${r.width}px`,
      `height:${r.height}px`,
      'border:2px solid #ef4444',
      'box-sizing:border-box',
      'z-index:2147483646',
      'pointer-events:none',
      'background:rgba(239,68,68,.06)',
    ].join(';');
    const badge = document.createElement('div');
    badge.textContent = String(i);
    badge.style.cssText = 'position:absolute;top:-2px;left:-2px;background:#ef4444;color:#fff;font:700 11px/14px ui-sans-serif,system-ui,sans-serif;padding:1px 5px;border-radius:2px';
    box.appendChild(badge);
    document.documentElement.appendChild(box);
  }
  return items;
}"""


async def _capture(url: str, out: Path, cdp: str) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    t0 = time.monotonic()
    boxes: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp)
        context = browser.contexts[0] if browser.contexts else await browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # Let late layout (YouTube chrome) settle before measuring boxes.
        await page.wait_for_timeout(800)
        title = (await page.title()) or url
        try:
            boxes = await page.evaluate(_PAINT_BOXES_JS)
        except Exception as exc:  # noqa: BLE001
            print(f"FAST_FRAME_BOXES_FAIL {exc}", flush=True)
            boxes = []
        await page.wait_for_timeout(50)
        out.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out), type="png", full_page=False)
    return {
        "title": title,
        "url": url,
        "ms": int((time.monotonic() - t0) * 1000),
        "path": str(out),
        "boxes": boxes or [],
    }


def _push_live_http(
    *,
    push_url: str,
    token: str,
    study_id: str,
    agent_id: str,
    step: dict[str, Any],
    png: bytes,
) -> bool:
    boundary = f"----usersim{int(time.time())}"
    step_json = json.dumps(step, default=str).encode()
    body = b""
    parts = [
        (b"token", token.encode()),
        (b"study_id", study_id.encode()),
        (b"agent_id", agent_id.encode()),
        (b"step_json", step_json),
    ]
    for name, val in parts:
        body += (
            f"--{boundary}\r\n".encode()
            + f'Content-Disposition: form-data; name="{name.decode()}"\r\n\r\n'.encode()
            + val
            + b"\r\n"
        )
    body += (
        f"--{boundary}\r\n".encode()
        + b'Content-Disposition: form-data; name="png"; filename="step_0.png"\r\n'
        + b"Content-Type: image/png\r\n\r\n"
        + png
        + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        push_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Usersim-Live-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
            print(f"LIVE_PUSH_HTTP status={getattr(resp, 'status', '?')} ok={ok}", flush=True)
            return ok
    except Exception as exc:  # noqa: BLE001
        print(f"LIVE_PUSH_HTTP failed: {exc}", flush=True)
        return False


def _gcs_archive_bg(
    *,
    shot: Path,
    gcs_uri: str,
    gcs_root: str,
    agent_id: str,
    step: dict[str, Any],
    live_dir: Path,
    status_msg: str,
    shard_index: int,
) -> None:
    try:
        _upload(shot, gcs_uri, content_type="image/png")
        (live_dir / "step_000.json").write_text(json.dumps(step, default=str))
        _upload(live_dir / "step_000.json", f"{gcs_root}/live/{agent_id}/step_000.json")
        _upload_json(
            f"{gcs_root}/live/{agent_id}/manifest.json",
            {"agent_id": agent_id, "steps": [step]},
        )
        _upload_json(
            f"{gcs_root}/status.json",
            {"message": status_msg, "shard_index": shard_index},
        )
        print("GCS_ARCHIVE_OK", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"GCS_ARCHIVE_FAIL {exc}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = json.loads(Path(args.job).read_text())
    study_id = job["study_id"]
    gcs_root = job["gcs_root"].rstrip("/")
    tasks = job.get("tasks") or []
    if not tasks:
        print("FAST_FRAME_SKIP no tasks", flush=True)
        return 0
    task = tasks[0]
    agent_id = task.get("id") or "agent"
    url = task.get("site_url") or job.get("url") or "about:blank"
    cdp = os.environ.get("MVP_WARM_CDP", "http://127.0.0.1:9222")
    live_token = str(job.get("live_token") or "")
    live_push_url = str(job.get("live_push_url") or "").strip()

    live_dir = Path(os.environ.get("HOME", "/home/shreyaspatel")) / "usersim" / "live" / agent_id
    live_dir.mkdir(parents=True, exist_ok=True)
    shot = live_dir / "step_0.png"

    t0 = time.monotonic()
    meta = asyncio.run(_capture(url, shot, cdp))
    print(f"FAST_FRAME_CAPTURE {meta['ms']}ms title={meta['title'][:60]!r}", flush=True)
    png = shot.read_bytes()

    try:
        from mvp.gcs_store import screenshot_gcs_uri

        gcs_uri = screenshot_gcs_uri(study_id, agent_id, "step_0.png")
    except Exception:
        bucket = os.environ.get("MVP_GCS_BUCKET", "usersim-bakeoff-347838016394")
        gcs_uri = f"gs://{bucket}/mvp_studies/{study_id}/screenshots/{agent_id}/step_0.png"

    boxes = list(meta.get("boxes") or [])
    step = {
        "step": 0,
        "action": "Landed on page — red numbered boxes = clickable elements",
        "observation": meta["title"],
        "url": url,
        "screenshot_url": f"/api/studies/{study_id}/agents/{agent_id}/screenshots/step_0.png",
        "screenshot_gcs": gcs_uri,
        "boxes": boxes,
        "outcome": "easy",
        "evidence_label": "Landing frame · red boxes = clickable",
    }
    # Companion JSON for SSH relay (orchestrator merges boxes into the live UI).
    (live_dir / "step_0.json").write_text(json.dumps(step, default=str))
    # Ready last — include study_id so a stale PNG cannot fool the relay.
    (live_dir / "step_0.ready").write_text(f"{study_id}\n{time.time()}\n")
    # Tiny GCS signal so laptop can SCP without SSH-polling the seed.
    try:
        _upload_json(
            f"{gcs_root}/live/{agent_id}/step_0.ready.json",
            {
                "study_id": study_id,
                "agent_id": agent_id,
                "ts": time.time(),
                "action": step.get("action"),
                "observation": step.get("observation"),
                "url": step.get("url"),
                "boxes": boxes,
            },
        )
        print("GCS_READY_MARKER_OK", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"GCS_READY_MARKER_FAIL {exc}", flush=True)

    # 1) Live path first (HTTP if configured).
    if live_push_url and live_token:
        _push_live_http(
            push_url=live_push_url,
            token=live_token,
            study_id=study_id,
            agent_id=agent_id,
            step=step,
            png=png,
        )

    # 2) GCS archive in background — trajectories / replay / Live dash.
    status_msg = f"Warm CDP first frame up ({meta['ms']}ms)"
    threading.Thread(
        target=_gcs_archive_bg,
        kwargs={
            "shot": shot,
            "gcs_uri": gcs_uri,
            "gcs_root": gcs_root,
            "agent_id": agent_id,
            "step": step,
            "live_dir": live_dir,
            "status_msg": status_msg,
            "shard_index": int(job.get("shard_index") or 0),
        },
        daemon=True,
    ).start()

    total_ms = int((time.monotonic() - t0) * 1000)
    print(f"FAST_FRAME_OK {total_ms}ms agent={agent_id} live_ready=1", flush=True)
    # Brief grace so archive can start; PNG+ready already on disk for SSH relay.
    time.sleep(0.15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
