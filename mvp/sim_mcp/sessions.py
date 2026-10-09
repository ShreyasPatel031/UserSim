"""One simulated user on one product, in one Browserbase browser.

The MCP client decides each action; this module opens the browser, runs the
action on the real page, and records every step into a normal StudyState so
the website's live page, report, and e2e2 gates read it unchanged.
"""

from __future__ import annotations

import asyncio
import re
import io
import ipaddress
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from mvp.paths import MVP_RUNS_DIR

VIEWPORT = {"width": 1280, "height": 800}
# Whatever MCP client drives the session; no model is hardcoded.
DRIVER = os.environ.get("MVP_MCP_DRIVER", "mcp_client")
AGENT_ID = "t1__p1__product"
SITE_KEY = "product"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def max_steps() -> int:
    return _env_int("MVP_MCP_MAX_STEPS", 40)


def budget_s() -> int:
    return _env_int("MVP_MCP_BUDGET_S", 900)


def idle_s() -> int:
    return _env_int("MVP_MCP_IDLE_S", 300)


def max_active() -> int:
    return _env_int("MVP_MCP_MAX_SESSIONS", 5)


def max_per_client() -> int:
    return _env_int("MVP_MCP_MAX_PER_CLIENT", 2)


class SessionError(Exception):
    """A request the client can fix (bad URL, unknown session, cap reached)."""


# ---------------------------------------------------------------- URL guard

# Social sign-in the simulated user must never use (signups are email only).
BLOCKED_SIGNIN_HOSTS = ("accounts.google.com", "github.com")


def blocked_signin(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in BLOCKED_SIGNIN_HOSTS)


# Webmail and third-party account sites a product's "open your inbox" buttons
# lead to. The simulated user must never sign in or create accounts there
# (Loop 12/13: UptimeRobot's "Open Yahoo Mail" button led the driver into
# Yahoo's account-creation form, typing the signup password).
BLOCKED_OFFSITE_HOSTS = (
    "mail.yahoo.com", "login.yahoo.com", "mail.google.com", "outlook.live.com",
    "login.live.com", "outlook.office.com", "outlook.office365.com", "mail.proton.me",
    "account.proton.me", "icloud.com", "mail.aol.com", "login.aol.com", "mail.zoho.com",
    "facebook.com", "twitter.com", "x.com", "linkedin.com",
)


def blocked_offsite(url: str, product_url: str = "") -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    if not host or (product_url and same_site(url, product_url)):
        return False
    return any(host == h or host.endswith("." + h) for h in BLOCKED_OFFSITE_HOSTS)


# Sign-in providers a product may hand the user to mid-task.
AUTH_HOSTS = (
    "login.microsoftonline.com",
    "appleid.apple.com",
    "auth0.com",
    "okta.com",
    "clerk.com",
    "clerk.accounts.dev",
)

_TWO_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "co.in", "co.jp", "com.br",
    "co.nz", "com.sg", "com.mx", "co.za", "vercel.app", "netlify.app", "github.io",
    "pages.dev", "web.app", "firebaseapp.com", "herokuapp.com", "onrender.com",
}


def registrable_domain(host: str) -> str:
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in _TWO_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize_public_url(raw: str) -> str:
    """https URL on a public host. localhost / private IPs are unreachable from Browserbase."""
    url = (raw or "").strip()
    if not url:
        raise SessionError("product_url is required")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise SessionError("product_url must be http(s)")
    host = (parts.hostname or "").lower()
    if not host or "." not in host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise SessionError(
            "product_url must be a public URL (the browser runs in the cloud and cannot reach localhost). "
            "Use a preview / staging deploy."
        )
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise SessionError("product_url must be a public URL, not a private IP")
    return url


def same_site(url: str, product_url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    if registrable_domain(host) == registrable_domain(urlsplit(product_url).hostname or ""):
        return True
    return any(host == h or host.endswith("." + h) for h in AUTH_HOSTS)


# ---------------------------------------------------------------- sessions


@dataclass
class SimSession:
    id: str
    study: Any
    product_url: str
    task: str
    persona: str
    client: str = ""
    bb: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    new_page: Any = None
    step: int = 0
    started: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    closed: bool = False
    close_reason: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # One cell (persona x task x site) of a multi-run study; "" = the one-run study.
    cell_id: str = ""
    # Signup state: one fresh alias inbox per session (mvp.signup_tools).
    inbox: Any = None
    identity: dict = field(default_factory=dict)
    mail_since: float = 0.0
    mail_seen: set = field(default_factory=set)
    mail_links: list = field(default_factory=list)
    mail_link_texts: dict = field(default_factory=dict)  # link -> anchor text in the mail
    sms_number: Any = None
    page_errors: list = field(default_factory=list)  # uncaught JS errors / console errors, newest last
    watched_pages: set = field(default_factory=set)

    @property
    def agent_id(self) -> str:
        return self.cell_id or AGENT_ID

    @property
    def matrix(self) -> bool:
        return bool(self.cell_id)

    @property
    def row(self) -> dict[str, Any]:
        return self.study.live_sessions[self.agent_id]

    def rules(self) -> dict[str, Any]:
        return {
            "max_steps": max_steps(),
            "budget_s": budget_s(),
            "idle_timeout_s": idle_s(),
            "viewport": dict(VIEWPORT),
            "navigate_scope": f"{registrable_domain(urlsplit(self.product_url).hostname or '')} + sign-in providers",
        }

    def steps_left(self) -> int:
        return max(0, max_steps() - self.step)

    def seconds_left(self) -> int:
        return max(0, int(budget_s() - (time.time() - self.started)))


SESSIONS: dict[str, SimSession] = {}
_PW: Any = None
_PW_LOCK = asyncio.Lock()


async def _playwright() -> Any:
    global _PW
    async with _PW_LOCK:
        if _PW is None:
            from playwright.async_api import async_playwright

            _PW = await async_playwright().start()
        return _PW


def get_session(session_id: str) -> SimSession:
    sim = SESSIONS.get(session_id or "")
    if sim is None:
        raise SessionError(f"unknown session_id {session_id!r}")
    return sim


def _active() -> list[SimSession]:
    return [s for s in SESSIONS.values() if not s.closed]


def _now() -> str:
    from mvp.study import _now as study_now

    return study_now()


def _new_study(product_url: str, task: str, persona: str) -> Any:
    from mvp.study import create_study

    host = registrable_domain(urlsplit(product_url).hostname or "") or product_url
    study = create_study(product_url, persona)
    study.driver = DRIVER
    study.backend = "mcp"
    study.skip_competitors = True
    study.study_mode = "single"
    study.product_name = host
    study.status = "running"
    study.phase = "Opening the live page"
    study.personas = [{"id": "p1", "name": "Simulated user", "bio": persona}]
    study.tasks = [
        {
            "id": AGENT_ID,
            "persona_id": "p1",
            "title": task[:80],
            "prompt": task,
            "site_url": product_url,
            "site_key": SITE_KEY,
            "site_label": host,
        }
    ]
    created = time.time()
    study.live_sessions[AGENT_ID] = {
        "agent_id": AGENT_ID,
        "persona_id": "p1",
        "persona_name": "Simulated user",
        "persona_bio": persona,
        "task_id": AGENT_ID,
        "task_title": task[:80],
        "task_prompt": task,
        "site_key": SITE_KEY,
        "site_url": product_url,
        "site_label": host,
        "status": "starting",
        "trace": [],
        "num_steps": 0,
        "live_active": False,
        "created_at": _now(),
        "created_at_ts": created,
        "live_thoughts": [{"at": _now(), "text": f"Opening {host}…", "kind": "status"}],
        "last_action": f"Opening {product_url}…",
        "driver": DRIVER,
    }
    from mvp.study import log_activity

    log_activity(study, "agents", f"MCP simulated user ({DRIVER}) opening {product_url}")
    return study


# ---------------------------------------------------------------- multi-run studies

MAX_CELLS = 60


def _site_name(url: str) -> str:
    host = registrable_domain(urlsplit(url).hostname or "") or url
    return host.split(".")[0].capitalize()


def _resolve_favors(raw: Any, sites: list[str]) -> str:
    """Which site a persona/task is aimed at: a URL, a host or a name -> that site's URL (or "")."""
    want = str(raw or "").strip().lower()
    if not want:
        return ""
    for url in sites:
        host = registrable_domain(urlsplit(url).hostname or "")
        if want in {url.lower(), host, _site_name(url).lower()} or registrable_domain(urlsplit(want if "://" in want else "https://" + want).hostname or "") == host:
            return url
    return ""


def create_matrix_study(
    *,
    product_url: str,
    competitors: list[str],
    personas: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> Any:
    """One website-shaped study: every persona x every task on the product and each competitor.

    Each cell is run later by its own MCP session (start_session with study_id + cell_id).
    When the last cell ends, the website's own end-of-study pipeline writes the report.
    """
    from mvp.study import create_study, expand_full_matrix, log_activity

    url = normalize_public_url(product_url)
    rivals: list[str] = []
    for raw in competitors or []:
        c = normalize_public_url(str(raw))
        if registrable_domain(urlsplit(c).hostname or "") == registrable_domain(urlsplit(url).hostname or ""):
            raise SessionError(f"competitor {c} is the same site as the product")
        if c not in rivals:
            rivals.append(c)
    sites = [url, *rivals]
    people: list[dict[str, Any]] = []
    for i, p in enumerate(personas or [], start=1):
        p = p if isinstance(p, dict) else {"bio": str(p)}
        bio = " ".join(str(p.get("bio") or p.get("persona") or "").split())[:600]
        name = " ".join(str(p.get("name") or f"User {i}").split())[:40]
        if not bio:
            raise SessionError(f"persona {i} needs a bio")
        people.append({"id": f"p{i}", "name": name, "role": str(p.get("role") or "")[:80], "bio": bio, "favors": _resolve_favors(p.get("favors"), sites)})
    jobs: list[dict[str, Any]] = []
    for i, t in enumerate(tasks or [], start=1):
        t = t if isinstance(t, dict) else {"prompt": str(t)}
        prompt = " ".join(str(t.get("prompt") or t.get("task") or "").split())[:600]
        if not prompt:
            raise SessionError(f"task {i} needs a prompt")
        jobs.append({"id": f"t{i}", "title": str(t.get("title") or prompt)[:80], "prompt": prompt, "favors": _resolve_favors(t.get("favors"), sites)})
    if not people or not jobs:
        raise SessionError("a study needs at least one persona and one task")
    n = len(people) * len(jobs) * len(sites)
    if n > MAX_CELLS:
        raise SessionError(f"{n} runs is over the {MAX_CELLS}-run limit for one study")

    study = create_study(url, people[0]["bio"])
    study.driver = DRIVER
    study.backend = "mcp"
    study.study_mode = "compare" if rivals else "single"
    study.product_name = _site_name(url)
    study.competitors = rivals
    study.competitor_names = {c: _site_name(c) for c in rivals}
    study.personas = people
    study.plan_personas = [dict(p) for p in people]
    study.task_specs = [{"prompt": t["prompt"], "favors": t["favors"]} for t in jobs]
    study.tasks = expand_full_matrix(jobs, people, product_url=url, competitors=rivals)
    for t in study.tasks:
        if t["site_key"] != "product":
            t["site_label"] = _site_name(t["site_url"])
    study.status = "running"
    study.phase = f"Waiting for {len(study.tasks)} simulated users"
    by_id = {p["id"]: p for p in people}
    created = time.time()
    for t in study.tasks:
        who = by_id[t["persona_id"]]
        study.live_sessions[t["id"]] = {
            "agent_id": t["id"],
            "persona_id": who["id"],
            "persona_name": who["name"],
            "persona_bio": who["bio"],
            "task_id": t["id"],
            "task_title": t.get("title") or t["prompt"][:80],
            "task_prompt": t["prompt"],
            "site_key": t["site_key"],
            "site_url": t["site_url"],
            "site_label": t.get("site_label") or "Product",
            "status": "queued",
            "trace": [],
            "num_steps": 0,
            "live_active": False,
            "created_at": _now(),
            "created_at_ts": created,
            "live_thoughts": [],
            "last_action": "Waiting for a simulated user",
            "driver": DRIVER,
        }
    log_activity(
        study,
        "plan",
        f"MCP study: {len(people)} users × {len(jobs)} tasks × {len(sites)} sites = {len(study.tasks)} runs",
    )
    return study


def matrix_phase(study: Any) -> str:
    rows = list(study.live_sessions.values())
    done = sum(1 for r in rows if r.get("status") in {"complete", "done", "error", "skipped"})
    running = sum(1 for r in rows if r.get("status") in {"starting", "running"})
    return f"{done}/{len(rows)} runs done · {running} simulated users working"


def cells_of(study: Any) -> list[dict[str, Any]]:
    """What a client needs to start each cell."""
    out = []
    for t in study.tasks:
        row = study.live_sessions.get(t["id"]) or {}
        out.append(
            {
                "cell_id": t["id"],
                "site": t["site_url"],
                "site_name": row.get("site_label") or "",
                "persona_name": row.get("persona_name"),
                "persona": row.get("persona_bio"),
                "task": t["prompt"],
                "status": row.get("status"),
            }
        )
    return out


def _create_bb(study_id: str) -> Any:
    from capability.browserbase_client import create_session, study_session_owner

    # Same Browserbase flags as the website's signup sessions (browser_agent._product_session_call_kwargs):
    # residential proxies + Browserbase's built-in captcha solving. create_session walks down the ladder.
    on = os.environ.get("MVP_MCP_BB_PROXIES", "1").lower() not in {"0", "false", "no"}
    return create_session(
        proxies=on,
        keep_alive=False,
        solve_captchas=on,
        advanced_stealth=False,
        owner=study_session_owner(),
        study_id=study_id,
        priority=0,
        wait_s=60,
    )


def _check_capacity(client: str) -> None:
    active = _active()
    if len(active) >= max_active():
        raise SessionError("UserSim is at its simulated-user limit right now; try again in a few minutes")
    if client and sum(1 for s in active if s.client == client) >= max_per_client():
        raise SessionError("this client already has the maximum number of open sessions; finish one first")


def _cell_session(study_id: str, cell_id: str, client: str) -> SimSession:
    from mvp.study import STUDIES

    study = STUDIES.get(study_id or "")
    if study is None or getattr(study, "backend", "") != "mcp":
        raise SessionError(f"unknown study_id {study_id!r}")
    row = study.live_sessions.get(cell_id or "")
    if row is None:
        raise SessionError(f"unknown cell_id {cell_id!r} for this study")
    if row.get("status") != "queued":
        raise SessionError(f"cell {cell_id} was already run (status {row.get('status')})")
    if study.status != "running":
        raise SessionError(f"study is {study.status}")
    _check_capacity(client)
    row["status"] = "starting"
    row["live_thoughts"] = [{"at": _now(), "text": f"Opening {row['site_label']}…", "kind": "status"}]
    persona = f"{row['persona_name']}: {row['persona_bio']}"
    return SimSession(
        id=uuid.uuid4().hex,
        study=study,
        product_url=row["site_url"],
        task=row["task_prompt"],
        persona=persona,
        client=client,
        cell_id=cell_id,
    )


async def start_session(
    *,
    product_url: str = "",
    task: str = "",
    persona: str = "",
    client: str = "",
    study_id: str = "",
    cell_id: str = "",
) -> SimSession:
    """One simulated user. With study_id + cell_id it runs that cell of a multi-run study;
    otherwise it creates a one-run study from product_url, task and persona."""
    if study_id or cell_id:
        sim = _cell_session(study_id, cell_id, client)
        url = sim.product_url
    else:
        url = normalize_public_url(product_url)
        task = (task or "").strip()
        persona = (persona or "").strip()
        if not task:
            raise SessionError("task is required")
        if not persona:
            raise SessionError("persona is required")
        _check_capacity(client)
        study = _new_study(url, task[:2000], persona[:2000])
        sim = SimSession(id=uuid.uuid4().hex, study=study, product_url=url, task=task, persona=persona, client=client)
    SESSIONS[sim.id] = sim
    try:
        await _open_browser(sim)
        await record_step(sim, kind="open", action_text=f"Opened {url}", args={"url": url}, thought="")
    except Exception as exc:
        await close(sim, reason=f"Browser failed to open: {exc!r}"[:300], status="error")
        raise
    asyncio.get_running_loop().create_task(_reaper(sim))
    return sim


async def _open_browser(sim: SimSession) -> None:
    from mvp.a11y_agent import apply_gate_fields

    t0 = time.time()
    sim.bb = await asyncio.to_thread(_create_bb, sim.study.id)
    ready = time.time()
    pw = await _playwright()
    sim.browser = await pw.chromium.connect_over_cdp(sim.bb.connect_url)
    sim.context = sim.browser.contexts[0] if sim.browser.contexts else await sim.browser.new_context()
    sim.page = sim.context.pages[0] if sim.context.pages else await sim.context.new_page()
    sim.context.on("page", lambda p: setattr(sim, "new_page", p))
    _watch_page(sim, sim.page)
    await ensure_viewport(sim.page)
    sim.page.set_default_timeout(10000)
    await _publish_live_view(sim)
    try:
        await sim.page.goto(sim.product_url, wait_until="domcontentloaded", timeout=25000)
    except Exception as exc:  # noqa: BLE001
        # A slow page that committed is still usable; nothing at all is not.
        if not (sim.page.url or "").startswith("http"):
            raise
        print(f"[mcp {sim.id[:8]}] goto slow: {exc!r}", flush=True)
    await _settle(sim.page)
    opened = time.time()
    row = sim.row
    row["status"] = "running"
    apply_gate_fields(
        row,
        session_ready_at_ts=ready,
        page_open_at_ts=opened,
        page_url=sim.page.url,
        phase_ms={"session_ready": int((ready - t0) * 1000), "page_open": int((opened - t0) * 1000)},
    )
    sim.study.phase = matrix_phase(sim.study) if sim.matrix else "Simulated user is working"


async def _publish_live_view(sim: SimSession) -> None:
    from capability.browserbase_client import session_live_view_url

    sid = str(getattr(sim.bb, "id", "") or "")
    row = sim.row
    row["browserbase_session_id"] = sid
    sim.study.browserbase_session_url = getattr(sim.bb, "session_url", None)
    try:
        live = await asyncio.wait_for(asyncio.to_thread(session_live_view_url, sid), timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(f"[mcp {sim.id[:8]}] live view lookup failed: {exc!r}", flush=True)
        live = None
    if live:
        row["live_view_url"] = live
        row["live_active"] = True


async def _settle(page: Any) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.6)


def _follow_new_tab(sim: SimSession) -> None:
    page = sim.new_page
    if page is not None and not page.is_closed():
        sim.page = page
        _watch_page(sim, page)
        try:
            page.set_default_timeout(10000)
        except Exception:  # noqa: BLE001
            pass
    sim.new_page = None


def _watch_page(sim: SimSession, page: Any) -> None:
    """Collect uncaught JS errors and console errors (a stuck SPA usually logs why)."""
    if page is None or id(page) in sim.watched_pages:
        return
    sim.watched_pages.add(id(page))

    def note(text: str) -> None:
        text = " ".join(str(text).split())[:200]
        if text and (not sim.page_errors or sim.page_errors[-1] != text):
            sim.page_errors.append(text)
            del sim.page_errors[:-8]

    try:
        page.on("pageerror", lambda exc: note(f"uncaught: {exc}"))
        page.on("console", lambda msg: note(f"console.error: {msg.text}") if msg.type == "error" else None)
    except Exception:  # noqa: BLE001
        pass


async def ensure_viewport(page: Any) -> None:
    """Keep every page at 1280x800 CSS px (app subdomains / new tabs came up at 2560x1440)."""
    try:
        size = await asyncio.wait_for(page.evaluate("() => [innerWidth, innerHeight]"), timeout=3)
    except Exception:  # noqa: BLE001
        size = None
    if size == [VIEWPORT["width"], VIEWPORT["height"]]:
        return
    try:
        await page.set_viewport_size(VIEWPORT)
        size = await asyncio.wait_for(page.evaluate("() => [innerWidth, innerHeight]"), timeout=3)
    except Exception:  # noqa: BLE001
        pass
    if size != [VIEWPORT["width"], VIEWPORT["height"]]:
        try:  # the CDP override wins over whatever the remote browser window imposes
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Emulation.setDeviceMetricsOverride", {"width": VIEWPORT["width"], "height": VIEWPORT["height"],
                                                                   "deviceScaleFactor": 1, "mobile": False})
            await cdp.detach()
        except Exception:  # noqa: BLE001
            pass


def fit_frame(png: bytes) -> bytes:
    """Last line of defence: the screenshot handed to clients and judge is always 1280x800."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(png))
    except Exception:  # noqa: BLE001
        return png
    w, h = VIEWPORT["width"], VIEWPORT["height"]
    if im.size == (w, h):
        return png
    sw, sh = im.size
    scale = sw / w  # device-pixel ratio, or a wider-than-asked viewport
    crop_h = min(sh, int(round(h * scale)))
    im = im.crop((0, 0, sw, crop_h)).resize((w, int(round(crop_h / scale))) if scale else (w, h))
    if im.size != (w, h):
        canvas = Image.new("RGB", (w, h), "white")
        canvas.paste(im.convert("RGB"), (0, 0))
        im = canvas
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


# ---------------------------------------------------------------- actions

ACTION_TYPES = ("click", "double_click", "right_click", "hover", "type", "key", "scroll", "back", "wait", "navigate",
                "press_and_hold", "drag", "triple_click", "select", "reload", "clear_cookies")


def _xy(action: dict[str, Any]) -> tuple[int, int]:
    try:
        x, y = int(action["x"]), int(action["y"])
    except (KeyError, TypeError, ValueError):
        raise SessionError("this action needs integer x and y (screenshot pixel coordinates)") from None
    if not (0 <= x < VIEWPORT["width"] and 0 <= y < VIEWPORT["height"]):
        raise SessionError(f"x,y must be inside the {VIEWPORT['width']}x{VIEWPORT['height']} screenshot")
    return x, y


def describe_action(action: dict[str, Any]) -> str:
    """Trace text. The verb before '—' is what e2e2_gates counts as a real action."""
    kind = str(action.get("type") or "")
    if kind in {"click", "double_click", "right_click"}:
        mode = {"click": "", "double_click": "double ", "right_click": "right "}[kind]
        return f"click — {mode}({action.get('x')}, {action.get('y')})"
    if kind == "hover":
        return f"hover — ({action.get('x')}, {action.get('y')})"
    if kind == "type":
        text = str(action.get("text") or "")
        tail = " + Enter" if action.get("submit") else ""
        return f"type — {text[:120]!r}{tail}"
    if kind == "key":
        return f"key — {action.get('keys')}"
    if kind == "scroll":
        return f"scroll — dy={action.get('dy')} at ({action.get('x')}, {action.get('y')})"
    if kind == "navigate":
        return f"navigate — {action.get('url')}"
    if kind == "wait":
        return f"wait — {action.get('ms')}ms"
    return kind


def validate_action(action: dict[str, Any], product_url: str) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise SessionError("action must be an object with a 'type'")
    kind = str(action.get("type") or "")
    if kind not in ACTION_TYPES:
        raise SessionError(f"action.type must be one of {', '.join(ACTION_TYPES)}")
    if kind in {"click", "double_click", "right_click", "hover", "triple_click"}:
        _xy(action)
    elif kind == "type":
        if not isinstance(action.get("text"), str) or not action["text"]:
            raise SessionError("type needs non-empty 'text'")
        if len(action["text"]) > 2000:
            raise SessionError("type text is limited to 2000 characters")
        from mvp.signup_tools import inbox_allowed

        for addr in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", action["text"]):
            if not inbox_allowed(addr):
                raise SessionError(
                    "refused: only the email from usersim_signup_identity may be typed "
                    "(a made-up or third-party address creates an account nobody can verify). "
                    "Call usersim_signup_identity and type its email."
                )
    elif kind == "key":
        keys = str(action.get("keys") or "")
        if not keys or len(keys) > 40:
            raise SessionError("key needs 'keys', e.g. 'Enter', 'Tab', 'Control+A'")
    elif kind == "scroll":
        try:
            int(action.get("dy"))
        except (TypeError, ValueError):
            raise SessionError("scroll needs integer 'dy' (positive = down)") from None
        action.setdefault("x", VIEWPORT["width"] // 2)
        action.setdefault("y", VIEWPORT["height"] // 2)
        _xy(action)
    elif kind == "select":
        _xy(action)
        if not str(action.get("option") or ""):
            raise SessionError("select needs x, y of the dropdown and 'option' (visible text)")
    elif kind == "press_and_hold":
        _xy(action)
        action["ms"] = max(500, min(int(action.get("ms") or 4000), 15000))
    elif kind == "drag":
        _xy(action)
        for k in ("to_x", "to_y"):
            try:
                int(action[k])
            except (KeyError, TypeError, ValueError):
                raise SessionError("drag needs x, y, to_x, to_y") from None
    elif kind == "navigate":
        target = str(action.get("url") or "")
        if blocked_signin(target):
            raise SessionError("Google/GitHub sign-in is not allowed; use the email signup")
        if not target.startswith(("http://", "https://")) or not same_site(target, product_url):
            raise SessionError("navigate is limited to the product's own site (and sign-in providers)")
    elif kind == "wait":
        try:
            ms = int(action.get("ms") or 1000)
        except (TypeError, ValueError):
            ms = 1000
        action["ms"] = max(100, min(ms, 5000))
    return action


async def _execute(page: Any, action: dict[str, Any]) -> None:
    kind = action["type"]
    if kind in {"click", "double_click", "right_click"}:
        x, y = _xy(action)
        await page.mouse.click(
            x,
            y,
            button="right" if kind == "right_click" else "left",
            click_count=2 if kind == "double_click" else 1,
        )
    elif kind == "select":
        x, y = _xy(action)
        want = str(action["option"]).strip()
        # the <select> at (x, y), or the nearest one within 80px (styled selects often sit under an overlay)
        res = await page.evaluate(_SELECT_JS, [x, y, want])
        if res.get("ok"):
            # Playwright's select_option fires the events React/Vue-controlled selects listen for
            await page.locator('[data-usersim-select="1"]').first.select_option(index=int(res["index"]), timeout=5000)
        elif res.get("options") is not None:
            raise SessionError(f"no option matching {want!r}; options: {res['options'][:40]}")
        else:  # custom dropdown: open it, then click the option text
            await page.mouse.click(x, y)
            await asyncio.sleep(0.4)
            await page.get_by_text(want, exact=False).first.click(timeout=5000)
    elif kind == "reload":
        await page.reload(wait_until="domcontentloaded", timeout=20000)
    elif kind == "clear_cookies":  # log out the hard way: cookies + this origin's storage, then reload
        await page.context.clear_cookies()
        try:
            await page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
        except Exception:  # noqa: BLE001
            pass
        await page.reload(wait_until="domcontentloaded", timeout=20000)
    elif kind == "triple_click":
        x, y = _xy(action)
        await page.mouse.click(x, y, click_count=3)
    elif kind == "hover":
        await page.mouse.move(*_xy(action))
    elif kind == "type":
        if "x" in action and "y" in action:
            await _ready_for_input(page)
            await _focus_and_clear(page, action)
        await _type_checked(page, action)
        if action.get("submit"):
            await page.keyboard.press("Enter")
    elif kind == "key":
        await page.keyboard.press(str(action["keys"]))
    elif kind == "scroll":
        await page.mouse.move(*_xy(action))
        await page.mouse.wheel(0, int(action["dy"]))
    elif kind == "back":
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=10000)
        except Exception:  # noqa: BLE001
            pass
    elif kind == "wait":
        await asyncio.sleep(int(action["ms"]) / 1000)
    elif kind == "press_and_hold":
        await page.mouse.move(*_xy(action))
        await page.mouse.down()
        await asyncio.sleep(int(action["ms"]) / 1000)
        await page.mouse.up()
    elif kind == "drag":
        import random

        x, y = _xy(action)
        tx, ty = int(action["to_x"]), int(action["to_y"])
        await page.mouse.move(x, y)
        await page.mouse.down()
        n = 18
        for i in range(1, n + 1):  # eased, slightly jittered, like a hand
            t = i / n
            e = t * t * (3 - 2 * t)
            await page.mouse.move(x + (tx - x) * e, y + (ty - y) * e + random.uniform(-1.5, 1.5))
            await asyncio.sleep(random.uniform(0.015, 0.05))
        await page.mouse.move(tx, ty)
        await page.mouse.up()
    elif kind == "navigate":
        await page.goto(action["url"], wait_until="domcontentloaded", timeout=20000)


NAVIGATING_ACTIONS = {"click", "double_click", "key", "select"}


_ACTIVE_VALUE_JS = """([x, y]) => {
  let e = document.activeElement;
  if (!e || e === document.body || !(('value' in e) || e.isContentEditable)) {
    // a re-render that wiped the field usually also dropped focus: read the field under the click point
    const t = document.elementFromPoint(x, y);
    e = t && (t.closest('input, textarea, [contenteditable=""], [contenteditable=true]') || (t.querySelector && t.querySelector('input, textarea')));
  }
  if (!e) return null;
  if (e.isContentEditable) return e.innerText || '';
  if (e.tagName === 'INPUT' && !['text', 'email', 'password', 'search', 'tel', 'url'].includes((e.type || 'text').toLowerCase())) return null;
  if (e.tagName !== 'INPUT' && e.tagName !== 'TEXTAREA') return null;
  return ('value' in e && typeof e.value === 'string') ? e.value : null; }"""


async def _ready_for_input(page: Any) -> None:
    """Typing into a page that is still loading/hydrating gets wiped when the SPA mounts (Loop 6:
    formbold/fabform/litlyx lost the first field typed after a navigation)."""
    try:
        await page.wait_for_load_state("load", timeout=10000)
    except Exception:  # noqa: BLE001
        pass


async def _focus_and_clear(page: Any, action: dict[str, Any]) -> None:
    await page.mouse.click(*_xy(action))
    await asyncio.sleep(0.15)
    if action.get("clear", True):
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")


async def _type_checked(page: Any, action: dict[str, Any]) -> None:
    """Type, then confirm the focused field kept the text; retype once if a late re-render wiped it."""
    text = action["text"]
    await page.keyboard.type(text, delay=15)
    if "x" not in action or "y" not in action:
        return
    for attempt in range(2):
        await asyncio.sleep(0.8)
        try:
            value = await page.evaluate(_ACTIVE_VALUE_JS, list(_xy(action)))
        except Exception:  # noqa: BLE001
            return
        if value is None or text in value or attempt == 1:
            return
        if value and not action.get("clear", True):
            return  # appended into existing content we cannot compare reliably
        await asyncio.sleep(1.5)
        await _focus_and_clear(page, action)
        await page.keyboard.type(text, delay=15)


async def _await_navigation(page: Any, url_before: str, nav_started: list | None = None,
                            sim: SimSession | None = None) -> None:
    """A click that navigates used to return the pre-navigation frame: give it up to ~3 s to commit
    (proxied sessions are slow to commit), then let it load. A click that opens a new tab
    (target=_blank, e.g. Litlyx 'Start Free') switches the session to that newest tab."""
    new_tab = False
    for _ in range(15):
        if sim is not None and sim.new_page is not None:
            _follow_new_tab(sim)
            page, new_tab = sim.page, True
            break
        if page.url != url_before:
            break
        if not nav_started and _ >= 5:
            break  # no main-frame navigation request / new tab after 1.2 s: this click did not navigate
        await asyncio.sleep(0.2)
    if page.url == url_before and not nav_started and not new_tab:
        return
    if new_tab:
        await ensure_viewport(page)
    try:
        await page.wait_for_load_state("load", timeout=12000)
    except Exception:  # noqa: BLE001
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=2500)
    except Exception:  # noqa: BLE001
        pass


def mask_secrets(sim: SimSession, action: dict[str, Any]) -> dict[str, Any]:
    """Never write the signup password into traces, reports or observations."""
    pw = str((sim.identity or {}).get("password") or "")
    if pw and isinstance(action.get("text"), str) and pw in action["text"]:
        action["text"] = action["text"].replace(pw, "•" * 8)
    return action


def scrub(sim: SimSession, value: Any) -> Any:
    pw = str((sim.identity or {}).get("password") or "")
    if not pw:
        return value
    if isinstance(value, str):
        return value.replace(pw, "•" * 8)
    if isinstance(value, list):
        return [scrub(sim, v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(sim, v) for k, v in value.items()}
    return value


def _check_open(sim: SimSession) -> None:
    if sim.closed:
        raise SessionError(f"session is closed ({sim.close_reason or 'finished'}); call usersim_get_report")
    if sim.steps_left() <= 0:
        raise SessionError("step limit reached; call usersim_finish")
    if sim.seconds_left() <= 0:
        raise SessionError("time budget used up; call usersim_finish")


async def act(sim: SimSession, action: dict[str, Any], thought: str) -> dict[str, Any]:
    async with sim.lock:
        _check_open(sim)
        action = validate_action(dict(action or {}), sim.product_url)
        sim.last_used = time.time()
        error = ""
        url_before = sim.page.url
        nav_started: list = []

        def _on_request(req: Any) -> None:
            try:
                if req.is_navigation_request() and req.frame == sim.page.main_frame:
                    nav_started.append(req.url)
            except Exception:  # noqa: BLE001
                pass

        watched = sim.page
        try:
            watched.on("request", _on_request)
        except Exception:  # noqa: BLE001
            watched = None
        if blocked_offsite(sim.page.url, sim.product_url):
            # Already on a webmail / third-party account page: do not type there.
            await sim.page.goto(sim.product_url, timeout=20000)
            await _settle(sim.page)
            action = {"type": "wait", "ms": 0}
            error = "Was on a mail provider / third-party account site; went back to the product instead of acting there"
        try:
            await _execute(sim.page, action)
        except SessionError:
            raise
        except Exception as exc:  # noqa: BLE001
            # The page refused the action (element gone, navigation failed).
            # Record it: a failed click is part of what the user experienced.
            error = str(exc).splitlines()[0][:200]
        _follow_new_tab(sim)
        await _settle(sim.page)
        if action["type"] in NAVIGATING_ACTIONS or action.get("submit"):
            await _await_navigation(sim.page, url_before, nav_started, sim=sim)
        if watched is not None:
            try:
                watched.remove_listener("request", _on_request)
            except Exception:  # noqa: BLE001
                pass
        if blocked_signin(sim.page.url):
            error = "Google/GitHub sign-in is not allowed; use the email signup (went back)"
            try:
                await sim.page.go_back(timeout=10000)
            except Exception:  # noqa: BLE001
                await sim.page.goto(sim.product_url, timeout=20000)
            await _settle(sim.page)
        elif blocked_offsite(sim.page.url, sim.product_url):
            error = (
                "That opened a mail provider / third-party account site, not the product. "
                "Never sign in or create accounts there; use usersim_wait_for_verification_link/_code (went back)"
            )
            try:
                await sim.page.goto(url_before if not blocked_offsite(url_before, sim.product_url) else sim.product_url, timeout=20000)
            except Exception:  # noqa: BLE001
                await sim.page.goto(sim.product_url, timeout=20000)
            await _settle(sim.page)
        shown = mask_secrets(sim, dict(action))
        return await record_step(
            sim,
            kind=action["type"],
            action_text=describe_action(shown),
            args={k: v for k, v in shown.items() if k != "type"},
            thought=thought,
            error=error,
        )


async def observe(sim: SimSession) -> dict[str, Any]:
    async with sim.lock:
        if sim.closed:
            raise SessionError(f"session is closed ({sim.close_reason or 'finished'})")
        sim.last_used = time.time()
        if sim.new_page is not None:  # a tab opened after the last action returned
            _follow_new_tab(sim)
            await _settle(sim.page)
        await ensure_viewport(sim.page)
        png = fit_frame(await _screenshot(sim.page, timeout_ms=10000))
        return await _observation(sim, png)


async def _screenshot(page: Any, *, timeout_ms: int) -> bytes:
    """Playwright's screenshot waits for web fonts; heavy pages (ClickUp) can stall it.
    Fall back to a raw CDP capture, which does not wait."""
    try:
        return await page.screenshot(type="png", timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001
        print(f"[mcp] screenshot slow, using CDP capture: {exc!r}"[:200], flush=True)
    import base64

    cdp = await page.context.new_cdp_session(page)
    try:
        res = await asyncio.wait_for(cdp.send("Page.captureScreenshot", {"format": "png"}), timeout=15)
    finally:
        try:
            await cdp.detach()
        except Exception:  # noqa: BLE001
            pass
    return base64.b64decode(res["data"])


# ---------------------------------------------------------------- recording


async def _page_text(page: Any) -> str:
    try:
        return str(
            await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 4000)")
        )
    except Exception:  # noqa: BLE001
        return ""


async def _title(page: Any) -> str:
    try:
        return str(await page.title())[:200]
    except Exception:  # noqa: BLE001
        return ""


def jpeg(png: bytes, quality: int = 75) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(out, format="JPEG", quality=quality)
    return out.getvalue()


_SELECT_JS = """([x, y, want]) => {
  let el = document.elementFromPoint(x, y);
  if (el && el.tagName !== 'SELECT') el = el.closest('select') || el.querySelector?.('select') || null;
  if (!el) {
    let best = null, bd = 1e9;
    for (const s of document.querySelectorAll('select')) {
      const r = s.getBoundingClientRect(); if (!r.width && !r.height) continue;
      const d = Math.hypot(Math.max(r.left - x, 0, x - r.right), Math.max(r.top - y, 0, y - r.bottom));
      if (d < bd) { bd = d; best = s; }
    }
    if (best && bd <= 80) el = best;
  }
  if (!el || el.tagName !== 'SELECT') return {ok: false};
  const norm = t => (t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const w = norm(want), opts = [...el.options];
  const hit = opts.find(o => norm(o.text) === w || norm(o.value) === w) || opts.find(o => o.index > 0 && (norm(o.text).includes(w) || (w && w.includes(norm(o.text)) && norm(o.text))))
    || opts.find(o => o.index > 0 && w.split(' ').some(p => p.length > 3 && norm(o.text).includes(p)));
  if (!hit) return {ok: false, options: opts.map(o => o.text.trim()).filter(Boolean)};
  document.querySelectorAll('[data-usersim-select]').forEach(e => e.removeAttribute('data-usersim-select'));
  el.setAttribute('data-usersim-select', '1');
  return {ok: true, index: hit.index, chosen: hit.text.trim()};
}"""


_FIELDS_JS = """() => {
  const out = [], hidden = [];
  const els = document.querySelectorAll('input:not([type=hidden]), textarea, select, button, [role=button], [role=checkbox], a[href]');
  // Loop 6 (Databuddy): an invisible checkbox (bot trap?) and a field below the fold were listed as clickable.
  // A control is listed only if it is painted, inside the 1280x800 frame at its centre, and is what a click there hits.
  const transparent = (e) => { for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      const st = getComputedStyle(n);
      if (+st.opacity < 0.05 || st.visibility === 'hidden' || st.display === 'none') return true;
      if (n.getAttribute('aria-hidden') === 'true' && n !== e) return true;
    } return false; };
  const shown = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return null;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) return null;
    if (transparent(e)) return null;
    const st = getComputedStyle(e);
    if (st.clipPath && st.clipPath.startsWith('inset(50%')) return null;
    if (/rect\\(0(px)?,? 0(px)?,? 0(px)?,? 0(px)?\\)/.test(st.clip || '')) return null;
    return r;
  };
  const hits = (e, r, alsoOk) => {  // the topmost element at the centre must be the control (or its own label/contents)
    const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!t) return false;
    return t === e || e.contains(t) || t.contains(e) || (alsoOk && (alsoOk === t || alsoOk.contains(t) || t.contains(alsoOk)));
  };
  const labelOf = (e) => (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) || e.closest('label');
  const trapName = (e) => /honeypot|hpot|(^|[^a-z0-9])hp([^a-z0-9]|$)|bot[_-]?(field|check|trap)|leave.?(this|it)?.?blank|do.?not.?fill/i.test(
    [e.name, e.id, e.className && e.className.baseVal === undefined ? e.className : '', e.getAttribute('autocomplete')].join(' '));
  for (const el of els) {
    let r = shown(el);
    const box = el.type === 'checkbox' || el.type === 'radio' || el.getAttribute('role') === 'checkbox';
    let label0 = null;
    if (!r && box) {  // custom-styled checkbox: the real input is hidden, its visible text label is what people click
      const l = labelOf(el);
      const lr = l && (l.innerText || '').trim() && shown(l);
      if (lr && hits(l, lr, null)) { r = {left: lr.left, top: lr.top, width: Math.min(lr.width, 24), height: lr.height}; label0 = l; }
    }
    let coveredBy = '';
    if (r && !label0 && !hits(el, r, labelOf(el))) {
      // covered by another element (chat widget, cookie banner, modal) or a decoy stacked underneath
      const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      let sig = '';
      for (let n = t; n && n !== document.body; n = n.parentElement) sig += ' ' + (n.id || '') + ' ' + (typeof n.className === 'string' ? n.className : '');
      sig = sig.toLowerCase();
      coveredBy = /crisp|intercom|drift|tawk|hubspot|zendesk|chat|messenger|livechat/.test(sig) ? 'a chat widget'
        : /cookie|consent|gdpr|onetrust|cky/.test(sig) ? 'a cookie banner' : 'another element (modal/overlay)';
      r = null;
    }
    const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
    if (r && isInput && trapName(el)) r = null;
    if (!r) {
      const text = (el.getAttribute('aria-label') || el.innerText || el.value || '').trim();
      if (coveredBy && !isInput && text && hidden.length < 6) {
        hidden.push({kind: el.tagName.toLowerCase(), hidden: true, label: text.slice(0, 40),
                     reason: 'covered by ' + coveredBy + ': close or scroll it away first'});
      } else if (isInput && hidden.length < 6) {
        const br = el.getBoundingClientRect();
        hidden.push({kind: el.tagName === 'INPUT' ? (el.type || 'text') : el.tagName.toLowerCase(), hidden: true,
                     label: (el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '').slice(0, 40),
                     reason: trapName(el) ? 'looks like a bot trap' : coveredBy ? 'covered by ' + coveredBy + ': close it first'
                       : (br.top + br.height / 2 > innerHeight ? 'below the fold: scroll first' : 'not visible / not clickable')});
      }
      continue;
    }
    let label = el.getAttribute('aria-label') || el.placeholder || '';
    if (!label) { const l = labelOf(el); if (l) label = l.innerText; }
    // never echo what was typed: a password field's value used to show up as its label
    const valueOk = el.tagName === 'BUTTON' || ['submit', 'button', 'reset'].includes(el.type);
    if (!label) label = ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') ? (valueOk ? el.value : '') || el.name || el.type || ''
                         : (el.innerText || el.name || '')).trim();
    if (el.type === 'password') label = (el.getAttribute('aria-label') || el.placeholder || (labelOf(el) || {}).innerText || el.name || 'password').trim();
    const tag = el.tagName.toLowerCase();
    const kind = tag === 'input' ? (el.type || 'text') : tag;
    const row = {kind, label: label.trim().slice(0, 60), x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)};
    if (tag === 'input' && !['checkbox','radio','submit','button'].includes(el.type)) row.filled = !!el.value;
    if (el.type === 'checkbox' || el.type === 'radio') row.checked = el.checked;
    if (tag === 'select') {  // native popups never show in screenshots: list the options so the client can use select
      const opts = [...el.options].filter(o => o.value !== '' || o.index > 0).map(o => o.text.trim()).filter(Boolean);
      row.label = (el.getAttribute('aria-label') || (el.id && document.querySelector('label[for="' + el.id + '"]') || {}).innerText || el.name || 'select').trim().slice(0, 60);
      row.options = opts.slice(0, 40); row.selected = el.selectedIndex > 0 ? (el.options[el.selectedIndex].text || '').trim() : '';
    } else if (tag === 'input' && el.list) {
      row.options = [...el.list.options].map(o => (o.value || o.text || '').trim()).filter(Boolean).slice(0, 40);
    }
    if (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.getAttribute('aria-busy') === 'true') row.disabled = true;
    out.push(row);
    if (out.length >= 40) break;
  }
  return out.concat(hidden);
}"""


_ERRORS_JS = """() => {
  const out = [], seen = new Set();
  const push = (t) => { t = (t || '').replace(/\\s+/g, ' ').trim(); if (t && t.length <= 200 && !seen.has(t)) { seen.add(t); out.push(t); } };
  const vis = (e) => { const r = e.getBoundingClientRect(), st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && st.visibility !== 'hidden' && st.display !== 'none'; };
  const sel = '[role=alert], [aria-live=assertive], .error, .errors, .invalid-feedback, .field-error, .form-error, .help-block.error, '
    + '[class*="error" i]:not(html):not(body), [class*="invalid" i]:not(input), [data-error], [id*="error" i]';
  // Loop 6 (Litlyx): utility classes such as "aria-invalid:ring-destructive" or "hover:text-error" on ordinary
  // buttons/menu items are not errors. Only plain class/id tokens that name an error count, and never controls.
  const errTok = (t) => !t.includes(':') && /(^|[-_])(error|errors|invalid|danger)([-_]|$)/i.test(t)
    && !/(^|[-_])(no|without|hide|hidden)[-_]/i.test(t) && !/boundary/i.test(t);
  const controls = 'button, a, input, select, textarea, option, label, nav, menu, [role=button], [role=menu], [role=menuitem], '
    + '[role=menubar], [role=tab], [role=link], [role=option], [role=navigation], [role=listbox]';
  for (const e of document.querySelectorAll(sel)) {
    if (out.length >= 6) break;
    if (e.matches(controls) || e.closest(controls) || e.querySelector('button, a, input, select, textarea')) continue;
    if (/route-announcer/i.test(e.id || '')) continue;
    const strong = e.matches('[role=alert], [aria-live=assertive], [data-error]');
    const named = [...e.classList].some(errTok) || (e.id && errTok(e.id));
    if (!strong && !named) continue;
    const text = (e.innerText || '').trim();
    if (text.length < 3) continue;
    if (e.children.length <= 3 && vis(e)) push(text);
  }
  for (const e of document.querySelectorAll('input, textarea, select')) {
    let bad = e.getAttribute('aria-invalid') === 'true';
    try { bad = bad || e.matches(':user-invalid'); } catch (x) {}
    if (bad && e.validationMessage && out.length < 8) push((e.getAttribute('aria-label') || e.name || e.type) + ': ' + e.validationMessage);
  }
  return out;
}"""


_CAPTCHA_JS = """() => {
  const f = [...document.querySelectorAll('iframe')].map(i => i.src || '');
  const scripts = [...document.scripts].map(x => x.src || '');
  const kind = f.some(u => u.includes('challenges.cloudflare.com')) || scripts.some(u => u.includes('turnstile')) || document.querySelector('.cf-turnstile, [name="cf-turnstile-response"]') ? 'turnstile'
    : f.some(u => u.includes('hcaptcha.com')) ? 'hcaptcha'
    : f.some(u => u.includes('/recaptcha/')) ? 'recaptcha' : '';
  if (!kind) return null;
  const tokens = [...document.querySelectorAll('[name="cf-turnstile-response"], [name="captcha"], [name="g-recaptcha-response"], [name="h-captcha-response"]')];
  const ready = tokens.some(t => (t.value || '').length > 20);
  // invisible / score reCAPTCHA (v3 badge, size=invisible) has nothing to click: it runs on submit
  const invisible = kind === 'recaptcha' && !f.some(u => u.includes('/recaptcha/') && !u.includes('size=invisible') && !u.includes('/bframe'))
    && ![...document.querySelectorAll('iframe[src*="/recaptcha/"][src*="bframe"]')].some(i => { const r = i.getBoundingClientRect(); return r.width > 100 && r.height > 100 && r.top < innerHeight && r.bottom > 0; });
  return invisible ? {kind, token_ready: ready, invisible: true} : {kind, token_ready: ready};
}"""


_ALIAS_RE = __import__("re").compile(r"(?i)(alias|\+|plus)[^.]{0,60}(not allowed|not supported|isn.t allowed|invalid)|(not allowed|cannot)[^.]{0,40}(alias|\+)")


async def _alias_rejected(page: Any) -> bool:
    try:
        text = await asyncio.wait_for(page.inner_text("body"), timeout=3)
    except Exception:  # noqa: BLE001
        return False
    return bool(_ALIAS_RE.search(text or ""))


async def captcha_state(page: Any) -> dict[str, Any] | None:
    try:
        return await asyncio.wait_for(page.evaluate(_CAPTCHA_JS), timeout=3)
    except Exception:  # noqa: BLE001
        return None


async def _fields(page: Any) -> list[dict[str, Any]]:
    """Visible controls with their exact centre (the website driver's element list, for the MCP client)."""
    try:
        return await asyncio.wait_for(page.evaluate(_FIELDS_JS), timeout=4)
    except Exception:  # noqa: BLE001
        return []


def _split_fields(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Clickable controls go in `fields`; hidden/off-screen/trap inputs are named apart, without coordinates."""
    rows = rows or []
    out: dict[str, Any] = {"fields": [r for r in rows if not r.get("hidden")]}
    hidden = [r for r in rows if r.get("hidden")]
    if hidden:
        out["hidden_fields"] = hidden
    return out


async def _inline_errors(page: Any) -> list[str]:
    try:
        return await asyncio.wait_for(page.evaluate(_ERRORS_JS), timeout=3)
    except Exception:  # noqa: BLE001
        return []


async def _observation(sim: SimSession, png: bytes, error: str = "") -> dict[str, Any]:
    errors = {"inline": await _inline_errors(sim.page), "console": list(sim.page_errors[-4:])}
    sim.page_errors.clear()
    return scrub(sim, {
        "page_errors": errors if (errors["inline"] or errors["console"]) else None,
        **_split_fields(await _fields(sim.page)),
        "captcha": await captcha_state(sim.page),
        "alias_rejected": await _alias_rejected(sim.page),
        "png": png,
        "url": sim.page.url,
        "title": await _title(sim.page),
        "step": sim.step - 1,
        "steps_left": sim.steps_left(),
        "seconds_left": sim.seconds_left(),
        "error": error,
    })


async def record_step(
    sim: SimSession,
    *,
    kind: str,
    action_text: str,
    args: dict[str, Any],
    thought: str,
    error: str = "",
) -> dict[str, Any]:
    from mvp.a11y_agent import apply_gate_fields
    from mvp.opening_shot import upload_screenshot
    from mvp.study import note_first_value, schedule_persist

    page = sim.page
    await ensure_viewport(page)
    png = fit_frame(await _screenshot(page, timeout_ms=15000))
    from mvp.sim_mcp.report import frame_unrendered

    for _ in range(3):  # a click that navigates often lands on the white frame / spinner before the next page paints
        if not frame_unrendered(png):
            break
        await asyncio.sleep(1.0)
        png = fit_frame(await _screenshot(page, timeout_ms=15000))
    n = sim.step
    sim.step += 1
    study = sim.study
    shots = MVP_RUNS_DIR / study.id / sim.agent_id / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    name = f"step_{n}.png"
    (shots / name).write_bytes(png)
    (shots / "final.png").write_bytes(png)
    for f in (name, "final.png"):
        asyncio.get_running_loop().create_task(upload_screenshot(study.id, sim.agent_id, shots / f))
    url = page.url
    title = await _title(page)
    text = await _page_text(page)
    shot_url = f"/api/studies/{study.id}/agents/{sim.agent_id}/screenshots/{name}"
    step = {
        "step": n,
        "at": _now(),
        "action": action_text,
        "action_kind": kind,
        "action_args": args,
        "thought": (thought or "").strip()[:1000],
        "thought_detail": {},
        "observation": title,
        "url": url,
        "screenshot_url": shot_url,
        "final_screenshot_url": shot_url,
        "boxes": [],
        "outcome": "error" if error else "neutral",
        "error": error,
        "state_sig": {"text": text[:1500], "canvas": "", "shapes": 0},
    }
    if n == 0:
        step["evidence_label"] = "Opening frame · before agent steps"
        step["opening_placeholder"] = False
        step["opening_blankish"] = False
    row = sim.row
    row["trace"] = [*row.get("trace", []), step]
    row["num_steps"] = len(row["trace"])
    row["last_action"] = action_text
    row["final_url"] = url
    row["final_dom"] = text[:1500]
    row["final_screenshot_url"] = f"/api/studies/{study.id}/agents/{sim.agent_id}/screenshots/final.png"
    row["final_screenshot"] = row["final_screenshot_url"]
    row["page_url"] = row.get("page_url") or url
    if step["thought"]:
        thoughts = [*row.get("live_thoughts", []), {"at": _now(), "text": step["thought"][:400], "kind": "thinking"}]
        row["live_thoughts"] = thoughts[-24:]
    if kind in {"click", "double_click", "right_click", "type", "scroll"} and not row.get("first_action_at_ts"):
        apply_gate_fields(row, first_action_at_ts=time.time(), phase_ms={"first_action": int((time.time() - sim.started) * 1000)})
        note_first_value(study, row)
    study.phase = matrix_phase(study) if sim.matrix else f"Simulated user is working — step {n}"
    study.updated_at = _now()
    schedule_persist(study)
    return await _observation(sim, png, error)


# ---------------------------------------------------------------- end


async def settle_final(sim: SimSession, max_s: float = 12.0) -> bool:
    """Before judging: if the last frame is a blank/spinner page (the client finished right after a click,
    e.g. FormBold 'Go to dashboard'), give the page up to max_s to paint and use that as final.png.
    A page still unrendered after that really is stuck, and the judge's hard rule fails it. Returns True if replaced."""
    from mvp.opening_shot import upload_screenshot
    from mvp.sim_mcp.report import frame_unrendered

    if sim.closed or sim.page is None or sim.study is None:
        return False
    shots = MVP_RUNS_DIR / sim.study.id / sim.agent_id / "screenshots"
    try:
        last = (shots / "final.png").read_bytes()
    except OSError:
        return False
    if not frame_unrendered(last):
        return False
    deadline = time.time() + max_s
    png = last
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        try:
            if sim.new_page is not None:
                _follow_new_tab(sim)
            await ensure_viewport(sim.page)
            png = fit_frame(await _screenshot(sim.page, timeout_ms=8000))
        except Exception:  # noqa: BLE001
            continue
        if not frame_unrendered(png):
            break
    if png is last or frame_unrendered(png):
        sim.row["final_settle"] = f"still blank/spinner after {max_s:.0f}s"
        return False
    (shots / "final.png").write_bytes(png)
    asyncio.get_running_loop().create_task(upload_screenshot(sim.study.id, sim.agent_id, shots / "final.png"))
    sim.row["final_url"] = sim.page.url
    sim.row["final_dom"] = (await _page_text(sim.page))[:1500]
    sim.row["final_settle"] = "final frame re-taken after the page finished loading"
    return True


async def close(sim: SimSession, *, reason: str, status: str = "") -> None:
    """Release the browser. status='' leaves the study state to the caller."""
    if sim.closed:
        return
    sim.closed = True
    sim.close_reason = reason
    row = sim.row
    row["live_active"] = False
    if status and sim.matrix:
        row["status"] = "error" if status == "error" else "done"
        row["error"] = reason[:500] if status == "error" else ""
    elif status:
        row["status"] = "error" if status == "error" else "done"
        sim.study.status = status
        sim.study.phase = reason[:200]
        if status == "error":
            sim.study.error = reason[:500]
    try:
        if sim.browser is not None:
            await sim.browser.close()
    except Exception:  # noqa: BLE001
        pass
    sid = str(getattr(sim.bb, "id", "") or "")
    if sid:
        from capability.browserbase_client import close_session

        await asyncio.to_thread(close_session, sid)
    from mvp.study import persist_study

    if status and not sim.matrix:
        from mvp.study import finish_clocks

        finish_clocks(sim.study)
        await asyncio.to_thread(persist_study, sim.study)
    elif status:
        from mvp.sim_mcp.report import maybe_finish_study

        await maybe_finish_study(sim.study)


async def _reaper(sim: SimSession) -> None:
    """Idle or over-budget sessions are closed so our Browserbase seats come back."""
    while not sim.closed:
        await asyncio.sleep(10)
        if sim.closed:
            return
        idle = time.time() - sim.last_used
        over = time.time() - sim.started > budget_s() + 60
        if idle > idle_s() or over:
            why = "Timed out (no action from the client)" if idle > idle_s() else "Time budget used up"
            async with sim.lock:
                if not sim.closed:
                    from mvp.sim_mcp.report import finalize

                    await finalize(sim, outcome="abandoned", notes=why)
            return
