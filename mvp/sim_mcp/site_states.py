"""Saved signed-in accounts for the seed_vm backend.

Browserbase gave every user a residential IP and a built-in captcha solver; the seeds are GCP datacenter IPs with fresh
contexts, so signup walls (hCaptcha, reCAPTCHA scoring, disabled signup buttons) now stop many cells before the task
(Asana study 42a925dd, Nov 17). Most study tasks are not signups: those cells can start signed in.

One Playwright storage_state per registrable domain lives in the bucket at
    <MVP_SEED_STATES_PREFIX or DEFAULT_GCS/seed_states>/<domain>.json
as {"domain", "storage_state": {"cookies", "origins"}, "seed", "saved_at", "address", "source"}.
- Loaded into a cell's new context (sessions._open_browser) unless the task itself is a signup; the cell is routed to
  the seed that saved it when that seed has a free slot (same egress IP the site has seen).
- Saved back at finalize when the judge saw a signed-in app page, so the next cell and the next study reuse it.
- Seeded from the seeds' identity disks (site_states/ and Chrome profiles/) by scripts/vm/export_seed_states.py.
limits.json seed_saved_accounts=false turns all of it off.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

CACHE_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_LOCK = threading.Lock()

# Tasks whose goal is creating the account must sign up for real (docs/E2E_TEST.md), never start signed in.
_SIGNUP_TASK_RE = re.compile(
    r"sign ?up|create (?:a |an |your |a new )?(?:new )?account|register|registration|verify your email", re.I)


def enabled() -> bool:
    from mvp.sim_mcp import limits

    return bool(limits.get("seed_saved_accounts"))


def domain_of(url_or_host: str) -> str:
    from mvp.sim_mcp.sessions import registrable_domain

    host = urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host
    return registrable_domain(host or "")


DEFAULT_BUCKET = "gs://usersim-bakeoff-347838016394"


def prefix() -> str:
    try:
        from mvp.gcs_store import DEFAULT_GCS
    except Exception:  # noqa: BLE001 (a seed checkout without mvp.gcs_store / google-cloud-storage)
        DEFAULT_GCS = os.environ.get("MVP_GCS_PREFIX") or DEFAULT_BUCKET
    return (os.environ.get("MVP_SEED_STATES_PREFIX") or f"{DEFAULT_GCS}/seed_states").rstrip("/")


def uri(domain: str) -> str:
    return f"{prefix()}/{domain}.json"


def eligible(task: str) -> bool:
    """A cell may start signed in unless its task is the signup itself."""
    return not _SIGNUP_TASK_RE.search(task or "")


def live_cookies(state: dict[str, Any], domain: str, now: float | None = None) -> list[dict[str, Any]]:
    """Cookies for this site that have not expired (session cookies, expires -1, count as live)."""
    now = time.time() if now is None else now
    out = []
    for c in (state or {}).get("cookies") or []:
        cdom = str(c.get("domain") or "").lstrip(".").lower()
        if not (cdom == domain or cdom.endswith("." + domain)):
            continue
        exp = c.get("expires")
        if isinstance(exp, (int, float)) and exp > 0 and exp < now:
            continue
        out.append(c)
    return out


def app_domain_of(entry: dict[str, Any] | None, domain: str) -> str:
    """Where the signed-in app lives: fillout.com's app is app.zite.com (study 38eb4d03), so its cookies are zite.com's."""
    return str((entry or {}).get("app_domain") or domain)


def usable(entry: dict[str, Any] | None, domain: str) -> bool:
    state = (entry or {}).get("storage_state")
    return (isinstance(state, dict) and not (entry or {}).get("dead")
            and bool(live_cookies(state, app_domain_of(entry, domain))))


def load(domain: str) -> dict[str, Any] | None:
    """The saved entry for this site, or None. Cached CACHE_TTL_S; a GCS error reads as no state."""
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(domain)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    entry = None
    try:
        from mvp.gcs_store import gcs_download_json

        got = gcs_download_json(uri(domain))
        entry = got if isinstance(got, dict) and usable(got, domain) else None
    except Exception as exc:  # noqa: BLE001
        print(f"[site_states] load {domain} failed: {exc!r}"[:200], flush=True)
    with _LOCK:
        _CACHE[domain] = (now, entry)
    return entry


def save(domain: str, storage_state: dict[str, Any], *, seed: str, study_id: str = "", address: str = "",
         source: str = "study", app_url: str = "") -> bool:
    """Store a signed-in state for this site (newest wins). app_url: the signed-in page the run ended on; its domain
    may differ from the product's (fillout.com -> app.zite.com). False when nothing is worth saving or GCS fails."""
    parts = urlsplit(app_url or "")
    app_domain = domain_of(parts.hostname or "") if parts.hostname else domain
    if not isinstance(storage_state, dict) or not live_cookies(storage_state, app_domain):
        return False
    entry = {"domain": domain, "storage_state": storage_state, "seed": seed, "saved_at": time.time(),
             "study_id": study_id, "address": address, "source": source}
    if parts.hostname:
        entry.update(app_url=f"{parts.scheme or 'https'}://{parts.hostname}/", app_domain=app_domain)
    try:
        from mvp.gcs_store import gcs_upload_json

        gcs_upload_json(uri(domain), entry)
    except Exception as exc:  # noqa: BLE001
        print(f"[site_states] save {domain} failed: {exc!r}"[:200], flush=True)
        return False
    with _LOCK:
        _CACHE[domain] = (time.time(), entry)
    return True


def seed_endpoint(seed: str, endpoints: list[str]) -> str:
    """The configured endpoint of a seed named 'usersim-signup-seed-N' or 'seed-N' (tunnel port 19220+N for Chromium,
    19320+N for Camoufox), or ''."""
    from mvp.sim_mcp.seed_backend import seed_index

    m = re.search(r"(?:^|-)(\d+)$", seed or "")
    if not m:
        return ""
    for e in endpoints:
        url = e.split("#", 1)[0].rstrip("/")
        if seed_index(url) == int(m.group(1)):
            return url
    return ""


# ---- where a signed-in user starts, and whether the state still signs in -----------------------------------------

# Where a signed-in user of these sites lands when the state's hosts do not say (or say it badly).
APP_URLS: dict[str, str] = {
    "asana.com": "https://app.asana.com/0/home",
    "trello.com": "https://trello.com/u/me/boards",
    "clickup.com": "https://app.clickup.com/",
    "notion.so": "https://www.notion.so/",
    "hubspot.com": "https://app.hubspot.com/",
    "typeform.com": "https://admin.typeform.com/",
    "slack.com": "https://app.slack.com/client",
    "figma.com": "https://www.figma.com/files/recents-and-sharing",
    "dropbox.com": "https://www.dropbox.com/home",
    "grammarly.com": "https://app.grammarly.com/",
    "zoom.us": "https://zoom.us/profile",
    "ticktick.com": "https://ticktick.com/webapp",
    "airtable.com": "https://airtable.com/",
    "miro.com": "https://miro.com/app/dashboard/",
    "canva.com": "https://www.canva.com/",
    "linear.app": "https://linear.app/",
    "todoist.com": "https://app.todoist.com/app/today",
    "calendly.com": "https://calendly.com/event_types/user/me",
    "mailchimp.com": "https://admin.mailchimp.com/",
    "zapier.com": "https://zapier.com/app/home",
    "basecamp.com": "https://launchpad.37signals.com/",
    "smartsheet.com": "https://app.smartsheet.com/",
    "wrike.com": "https://www.wrike.com/workspace.htm",
    "tally.so": "https://tally.so/dashboard",
}
# Subdomain labels that are never the app: auth, marketing, telemetry, API, content (check_saved_states Nov 17 called
# marketing.dropbox.com, marketing.figma.com, go.grammarly.com, us.telemetry.zoom.us and xapi.ticktick.com LIVE).
_NOT_APP_RE = re.compile(
    r"(?:^|[.-])(?:auth|login|signin|signup|accounts?|id|sso|identity|oauth|secure|www|x?api\d*|cdn\d*|static|assets?|"
    r"img|images|media|help|support|docs?|blog|status|marketing|go|telemetry|track(?:ing)?|analytics|metrics|events?|ads?|"
    r"pixel|log|logs|collect|email|mail|links?|click|lp|landing|pages|info|community|forum|learn|academy|developers?|"
    r"partners?|store|shop|careers|press|news|cms|content)(?:$|[.-])", re.I)
_SIGNED_OUT_RE = re.compile(r"log-?in|sign[-_]?in|sign[-_]?up|/auth|^auth\.|register|create-account|/users/sign|forced_logout",
                            re.I)


def app_url_for(entry_or_state: dict[str, Any], domain: str) -> str:
    """The in-app URL a signed-in user would open, from the hosts the saved state touched: app.<domain> first, then a
    workspace subdomain (monday.com: <team>.monday.com), never the marketing root or an auth host. '' = none known.
    Check study 02fc3bfc (Nov 17): a signed-in state opened on monday.com's homepage, the user clicked 'Get started'
    and hit signup's reCAPTCHA."""
    if domain in APP_URLS:
        return APP_URLS[domain]
    entry = entry_or_state if isinstance(entry_or_state, dict) else {}
    if entry.get("app_url"):
        return str(entry["app_url"])  # where a signed-in run actually ended (may be another domain: app.zite.com)
    state = entry.get("storage_state", entry)
    score: dict[str, int] = {}
    # export_seed_states names its sources site_states/<host>.json / profiles/<host>: the host the seed signed in on
    for src in re.findall(r"(?:site_states|profiles)/([a-z0-9.-]+?)(?:\.json)?(?=,|$)", str(entry.get("source") or ""), re.I):
        score[src.lower()] = score.get(src.lower(), 0) + 3
    for o in state.get("origins") or []:
        host = urlsplit(str(o.get("origin") or "")).hostname or ""
        score[host] = score.get(host, 0) + 2 + len(o.get("localStorage") or [])
    for c in live_cookies(state, domain):
        host = str(c.get("domain") or "").lstrip(".").lower()
        score[host] = score.get(host, 0) + 1
    best, best_rank = "", (-1, -1)
    for host, n in score.items():
        host = host.lower()
        if not host.endswith("." + domain):
            continue  # the bare domain is the marketing site
        sub = host[: -len(domain) - 1]
        if _NOT_APP_RE.search(sub):
            continue
        rank = (1 if sub.split(".")[-1] in ("app", "admin", "dashboard", "my", "console") else 0, n)
        if rank > best_rank:
            best, best_rank = host, rank
    return f"https://{best}/" if best else ""


# Signs of a signed-in app page in the DOM: an account / profile / avatar control, a log-out item, a workspace switcher.
SIGNED_IN_JS = r"""() => {
  const q = (s) => { try { return document.querySelector(s) !== null; } catch (e) { return false; } };
  const account = q('[aria-label*="account" i],[aria-label*="profile" i],[aria-label*="avatar" i],[aria-label*="user menu" i],'
    + '[data-testid*="avatar" i],[data-testid*="account" i],[data-testid*="user-menu" i],[class*="avatar" i],'
    + 'img[alt*="avatar" i],img[alt*="profile" i],[aria-label*="workspace" i],[data-testid*="workspace" i]');
  const html = (document.body && document.body.innerHTML || '').slice(0, 2000000);
  const logout = /log ?out|sign ?out|logout|signout/i.test(html);
  return {account: account, logout: logout};
}"""


def signed_in_signals(signals: dict[str, Any] | None) -> bool:
    return bool(signals) and bool(signals.get("account") or signals.get("logout"))


def looks_signed_out(url: str, password_field: bool = False) -> bool:
    """A page a signed-in user would not be on: a login / signup / auth URL, or a visible password box."""
    parts = urlsplit(url or "")
    return password_field or bool(_SIGNED_OUT_RE.search(parts.netloc + parts.path + "?" + parts.query))


def mark_dead(domain: str, reason: str) -> None:
    """The saved state no longer signs in: flag it in the bucket so no cell starts from it until a fresh one is saved."""
    entry = None
    try:
        from mvp.gcs_store import gcs_download_json, gcs_upload_json

        entry = gcs_download_json(uri(domain))
        if isinstance(entry, dict) and not entry.get("dead"):
            gcs_upload_json(uri(domain), {**entry, "dead": True, "dead_at": time.time(), "dead_reason": reason[:200]})
    except Exception as exc:  # noqa: BLE001
        print(f"[site_states] mark_dead {domain} failed: {exc!r}"[:200], flush=True)
    with _LOCK:
        _CACHE[domain] = (time.time(), None)
