"""Pub/Sub push → Cursor Cloud Agent steer (real-time fleet-cursor wake).

Deploy with scripts/vm/ph_fleet_cursor_wake_deploy.sh. Requires:
  CURSOR_API_KEY, FLEET_CURSOR_BC_ID (env or Secret Manager on Cloud Run).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any

import functions_framework
from google.cloud import storage


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _bc_id() -> str:
    bid = _env("FLEET_CURSOR_BC_ID")
    if bid:
        return bid
    # Fallback: latest id published by check-in to GCS
    bucket = _env("MVP_GCS_BUCKET")
    if not bucket:
        return ""
    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob("usersim_sim/mailbox/from_cursor/cursor_agent.json")
        if not blob.exists():
            return ""
        data = json.loads(blob.download_as_text())
        return str(data.get("bc_id") or data.get("id") or "")
    except Exception:
        return ""


def _dedupe_seen(message_id: str) -> bool:
    """Skip duplicate Pub/Sub deliveries (push + 15m pull share the same topic)."""
    bucket = _env("MVP_GCS_BUCKET")
    if not bucket or not message_id:
        return False
    key = hashlib.sha256(message_id.encode()).hexdigest()[:32]
    path = f"usersim_sim/mailbox/from_cursor/wake_dedupe/{key}.txt"
    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob(path)
        if blob.exists():
            return True
        blob.upload_from_string("1\n", content_type="text/plain")
        return False
    except Exception:
        return False


def _decode_pubsub(body: dict[str, Any]) -> tuple[dict[str, str], str, str]:
    msg = body.get("message") or {}
    message_id = str(msg.get("messageId") or "")
    attrs = {str(k): str(v) for k, v in (msg.get("attributes") or {}).items()}
    raw = msg.get("data") or ""
    text = ""
    if raw:
        try:
            text = base64.b64decode(raw).decode("utf-8", "replace")
        except Exception:
            text = str(raw)
    return attrs, text, message_id


def _should_wake(attrs: dict[str, str], text: str) -> bool:
    to = attrs.get("to", "")
    fr = attrs.get("from", "")
    if fr == "fleet-cursor":
        return False
    if to == "fleet-cursor":
        return True
    if to == "all" and fr and fr != "fleet-cursor":
        # Ignore our own 15m check-in blurbs on the broadcast channel.
        if text.startswith("fleet-cursor check-in"):
            return False
        return True
    return False


def _cursor_steer(bc_id: str, prompt: str) -> tuple[int, str]:
    api_key = _env("CURSOR_API_KEY")
    if not api_key or not bc_id:
        return 503, "missing CURSOR_API_KEY or FLEET_CURSOR_BC_ID"
    url = f"https://api.cursor.com/v1/agents/{bc_id}/runs"
    body = json.dumps(
        {"prompt": {"text": prompt}, "delivery": "steer"}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(4096).decode("utf-8", "replace")
    except Exception as e:
        return 500, str(e)


@functions_framework.http
def wake(request):
    """Cloud Run / Functions entry: Pub/Sub push envelope JSON POST."""
    if request.method != "POST":
        return ("method not allowed", 405)
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        return ("bad json", 400)

    attrs, text, message_id = _decode_pubsub(body)
    if not _should_wake(attrs, text):
        return ("", 204)

    if message_id and _dedupe_seen(message_id):
        return ("", 204)

    fr = attrs.get("from") or "unknown"
    ts = attrs.get("ts") or ""
    snippet = text.strip().replace("\n", " ")
    if len(snippet) > 1200:
        snippet = snippet[:1200] + "…"

    prompt = (
        "[agent-msgs wake] Pub/Sub message for fleet-cursor.\n"
        f"from={fr} to={attrs.get('to','')} ts={ts} messageId={message_id}\n\n"
        f"{snippet}\n\n"
        "Actions: read durable inbox under results/ph_fleet_full/…/agent_inbox/fleet-cursor.jsonl "
        "if you need full text; relay ACK via scripts/vm/ph_fleet_agent_relay.sh to the sender. "
        "Do not scale historical fleet up while live feeds are critical-stale (LIVE_PRIORITY_HOLD)."
    )
    bc_id = _bc_id()
    code, detail = _cursor_steer(bc_id, prompt)
    # Pub/Sub retries on 5xx; 2xx acks even when steer queued (202).
    if code in (202, 200, 201):
        return (detail or "ok", 204)
    if code == 409:
        # Busy — treat as ack so Pub/Sub does not storm; message still in pull inbox.
        return ("agent_busy", 204)
    if code == 403:
        return (detail, 204)
    return (detail, 502)
