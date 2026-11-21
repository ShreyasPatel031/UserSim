"""Sign in to Google inside a simulated user's browser, for token callers (port of mvp/auto_signin.py to the MCP).

When a product only offers "Continue with Google", the simulated user clicks it and lands on accounts.google.com. It then
calls usersim_google_signin. The server, not the model, types the account's email, password and second factor, using
the same step handler as mvp/auto_signin.py (_handle_google_round):
account chooser, email, password, TOTP from totp_secret, a code emailed to the account (app_password), phone
confirmation, and the challenge chooser. The model never sees the password or codes.

Credentials: a vault in the shape of secrets/credentials.json ({"sites": [{"match": [...], "username", "password",
"totp_secret", "app_password", "phone"}]}), read from MVP_GOOGLE_VAULT_URI:
  gs://bucket/private/...json             (Cloud Storage, read with the server's own credentials)
  sm://projects/<p>/secrets/<name>       (Secret Manager, latest version, via gcloud)
Only callers with a valid bearer token can use it (google_signin.allowed_for). Anonymous callers stay blocked from Google.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlsplit

CACHE_TTL_S = 300.0
_CACHE: list[Any] = [0.0, None]
_LOCK = threading.Lock()
MAX_ROUNDS = 30
STOP = {"need_totp_secret", "need_sms_manual", "sms_timeout", "need_app_password", "email_code_timeout"}


DEFAULT_VAULT = "gs://usersim-bakeoff-347838016394/private/google_vault.json"


def vault_uri() -> str:
    """MVP_GOOGLE_VAULT_URI, else the private default object (so no server env change is needed). "off" disables."""
    v = (os.environ.get("MVP_GOOGLE_VAULT_URI") or "").strip()
    return "" if v.lower() == "off" else (v or DEFAULT_VAULT)


def _read_vault() -> dict[str, Any] | None:
    uri = vault_uri()
    if not uri:
        return None
    if uri.startswith("gs://"):
        from mvp.gcs_store import gcs_download_json

        got = gcs_download_json(uri)
        return got if isinstance(got, dict) else None
    if uri.startswith("sm://"):
        name = uri[len("sm://"):]
        out = subprocess.run(["gcloud", "secrets", "versions", "access", "latest", f"--secret={name}"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise RuntimeError("secret manager read failed")
        return json.loads(out.stdout)
    raise RuntimeError("MVP_GOOGLE_VAULT_URI must start with gs:// or sm://")


def google_creds() -> dict[str, Any] | None:
    """The vault entry for Google (username + password at least), or None. Cached; never logged."""
    now = time.time()
    with _LOCK:
        if now - _CACHE[0] < CACHE_TTL_S:
            return _CACHE[1]
    entry = None
    try:
        vault = _read_vault() or {}
        for site in vault.get("sites") or []:
            if any("google" in str(m).lower() or "gmail" in str(m).lower() for m in site.get("match") or []):
                if site.get("username") and site.get("password"):
                    entry = site
                    break
    except Exception as exc:  # noqa: BLE001
        print(f"[google_login] vault read failed: {type(exc).__name__}", flush=True)
    with _LOCK:
        _CACHE[0], _CACHE[1] = now, entry
    return entry


def configured() -> bool:
    return bool(vault_uri())


def _on_google(url: str) -> bool:
    from mvp.sim_mcp.google_signin import is_google_signin

    return is_google_signin(urlsplit(url or "").hostname or "")


def _live_page(sim: Any) -> Any:
    """The OAuth popup closes itself after consent: fall back to the context's newest open page."""
    page = sim.page
    if page is not None and not page.is_closed():
        return page
    pages = [p for p in (sim.context.pages if sim.context else []) if not p.is_closed()]
    if pages:
        sim.page = pages[-1]
    return sim.page


async def sign_in(sim: Any, timeout_s: float = 240.0) -> dict[str, Any]:
    """Drive Google's sign-in on the session's current page until it hands back to the product. Returns
    {"ok", "reason", "actions", "url"}; never the credentials."""
    from mvp.auto_signin import _handle_google_round

    creds = await asyncio.to_thread(google_creds)
    if not creds:
        return {"ok": False, "reason": "no_google_credentials", "actions": []}
    page = _live_page(sim)
    if not _on_google(page.url):
        return {"ok": False, "reason": "not_on_google_signin", "actions": [], "url": page.url}
    state: dict[str, Any] = {}
    actions: list[str] = []
    deadline = time.time() + timeout_s
    for _ in range(MAX_ROUNDS):
        page = _live_page(sim)
        if not _on_google(page.url):
            return {"ok": True, "reason": "left_google", "actions": actions, "url": page.url}
        if time.time() > deadline:
            break
        try:
            action = await _handle_google_round(page, creds, state)
        except Exception as exc:  # noqa: BLE001 (page closed mid-step: the popup finished)
            action = f"step_error:{type(exc).__name__}"
        actions.append(action)
        if action in STOP:
            return {"ok": False, "reason": action, "actions": actions, "url": page.url}
        if action == "no_action" and actions[-3:] == ["no_action"] * 3:
            return {"ok": False, "reason": "stuck", "actions": actions, "url": page.url}
        await asyncio.sleep(3.0 if action == "no_action" else 2.5)
    page = _live_page(sim)
    if not _on_google(page.url):
        return {"ok": True, "reason": "left_google", "actions": actions, "url": page.url}
    return {"ok": False, "reason": "timeout", "actions": actions, "url": page.url}
