"""One simulated user on one product, in one Browserbase browser.

The MCP client decides each action; this module opens the browser, runs the
action on the real page, and records every step into a normal StudyState so
the website's live page, report, and e2e2 gates read it unchanged.
"""

from __future__ import annotations

import asyncio
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
    sms_number: Any = None

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

    return create_session(
        proxies=False,
        keep_alive=False,
        solve_captchas=False,
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
    try:
        await sim.page.set_viewport_size(VIEWPORT)
    except Exception:  # noqa: BLE001
        pass
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
    sim.new_page = None


# ---------------------------------------------------------------- actions

ACTION_TYPES = ("click", "double_click", "right_click", "hover", "type", "key", "scroll", "back", "wait", "navigate",
                "press_and_hold", "drag")


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
    if kind in {"click", "double_click", "right_click", "hover"}:
        _xy(action)
    elif kind == "type":
        if not isinstance(action.get("text"), str) or not action["text"]:
            raise SessionError("type needs non-empty 'text'")
        if len(action["text"]) > 2000:
            raise SessionError("type text is limited to 2000 characters")
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
    elif kind == "hover":
        await page.mouse.move(*_xy(action))
    elif kind == "type":
        await page.keyboard.type(action["text"], delay=15)
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
        if blocked_signin(sim.page.url):
            error = "Google/GitHub sign-in is not allowed; use the email signup (went back)"
            try:
                await sim.page.go_back(timeout=10000)
            except Exception:  # noqa: BLE001
                await sim.page.goto(sim.product_url, timeout=20000)
            await _settle(sim.page)
        return await record_step(
            sim,
            kind=action["type"],
            action_text=describe_action(action),
            args={k: v for k, v in action.items() if k != "type"},
            thought=thought,
            error=error,
        )


async def observe(sim: SimSession) -> dict[str, Any]:
    async with sim.lock:
        if sim.closed:
            raise SessionError(f"session is closed ({sim.close_reason or 'finished'})")
        sim.last_used = time.time()
        png = await _screenshot(sim.page, timeout_ms=10000)
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


async def _observation(sim: SimSession, png: bytes, error: str = "") -> dict[str, Any]:
    return {
        "png": png,
        "url": sim.page.url,
        "title": await _title(sim.page),
        "step": sim.step - 1,
        "steps_left": sim.steps_left(),
        "seconds_left": sim.seconds_left(),
        "error": error,
    }


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

    from mvp.e2e_smoke_local import _looks_blank

    page = sim.page
    png = await _screenshot(page, timeout_ms=15000)
    for _ in range(3):  # a click that navigates often lands on the white frame before the next page paints
        if not _looks_blank(png):
            break
        await asyncio.sleep(1.0)
        png = await _screenshot(page, timeout_ms=15000)
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
