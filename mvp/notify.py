"""Ping the owner when a sign-in needs a human tap.

ntfy.sh needs no account: pick a hard-to-guess topic, install the ntfy app on
the phone, subscribe to that topic, and publishes arrive as push notifications.
Also fires a local macOS notification so the desktop shows it too.
"""

from __future__ import annotations

import shutil
import subprocess

from mvp.credentials import push_topic

NTFY_BASE = "https://ntfy.sh"


def push(title: str, message: str, *, priority: str = "high") -> bool:
    """Send a push to the owner's phone. Returns True if the publish worked."""
    topic = push_topic()
    if not topic:
        _desktop_notify(title, message)
        return False
    try:
        import httpx

        resp = httpx.post(
            f"{NTFY_BASE}/{topic}",
            content=message.encode(),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "warning,key",
            },
            timeout=10.0,
        )
        ok = resp.status_code < 300
    except Exception:
        ok = False
    _desktop_notify(title, message)
    return ok


def _desktop_notify(title: str, message: str) -> None:
    if not shutil.which("osascript"):
        return
    safe_title = title.replace('"', "'")
    safe_msg = message.replace('"', "'")
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{safe_msg}" with title "{safe_title}" sound name "Ping"',
            ],
            capture_output=True,
            timeout=8,
        )
    except Exception:
        pass
