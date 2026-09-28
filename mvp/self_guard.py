"""Keep UserSim's own agent browsers from driving UserSim.

A persona on UserSim's site once typed a URL into the Run box, which started a
study whose agents did the same, until every Browserbase session was taken.
Three layers stop that loop:

* Agent browsers mark every request they send to a UserSim host with
  ``X-UserSim-Agent: <study id>`` (``install_agent_marker``), and the server
  rejects marked requests to study and runtime endpoints
  (``agent_request_reason``). The same interception fails study-start and
  kill calls inside the browser, before they leave it.
* The agent's action filter refuses to type, press keys, or click buttons on
  a UserSim page (``agent_action_block``).
* A study whose target or rival is a UserSim host never starts without the
  admin token (``own_urls`` / ``admin_error``).

The marker is added only to requests bound for UserSim hosts, through CDP
``Fetch`` patterns scoped to those hosts. A context-wide extra header would be
sent to every site, and Chromium preflights cross-origin fetches that carry an
unknown header, which breaks third-party APIs that do not allow it.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import os
import re
import socket
import time
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from starlette.requests import Request

AGENT_HEADER = "X-UserSim-Agent"
DEFAULT_OWN_HOSTS = (
    "35-202-98-224.sslip.io",
    "35.202.98.224.sslip.io",
    "35.202.98.224",
    "usersim.vercel.app",
)
DEFAULT_OWN_IPS = ("35.202.98.224",)
SAMPLE_REPORT_URL = "/blandai"

_VERCEL_PREVIEW_RE = re.compile(r"^usersim(?:-[a-z0-9-]+)?\.vercel\.app$")
_IP_DNS_RE = re.compile(r"(?:^|[.-])(\d{1,3})[.-](\d{1,3})[.-](\d{1,3})[.-](\d{1,3})\.(?:sslip\.io|nip\.io)$")
_STUDY_API_RE = re.compile(r"^/api/(?:studies|runtime)(?:/|$)")
_SAFE_METHODS = {"GET", "HEAD"}


def _env_list(name: str) -> list[str]:
    return [x.strip().lower() for x in (os.environ.get(name) or "").split(",") if x.strip()]


def own_hosts() -> tuple[str, ...]:
    """UserSim's hosts: the defaults plus ``USERSIM_OWN_HOSTS`` (comma-separated)."""
    extra = [h.removeprefix("www.") for h in _env_list("USERSIM_OWN_HOSTS")]
    return tuple(dict.fromkeys([*DEFAULT_OWN_HOSTS, *extra]))


def own_ips() -> tuple[str, ...]:
    return tuple(dict.fromkeys([*DEFAULT_OWN_IPS, *_env_list("USERSIM_OWN_IPS")]))


def host_of(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    try:
        host = (urlsplit(raw).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host.removeprefix("www.")


def is_own_host(url_or_host: str) -> bool:
    host = host_of(url_or_host)
    if not host:
        return False
    for own in own_hosts():
        if host == own or host.endswith("." + own):
            return True
    if _VERCEL_PREVIEW_RE.match(host):
        return True
    m = _IP_DNS_RE.search(host)
    if m and ".".join(m.groups()) in own_ips():
        return True
    return host in own_ips()


_DNS_CACHE: dict[str, tuple[float, bool]] = {}


def _resolves_to_own_ip_sync(host: str) -> bool:
    ips = set(own_ips())
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return any(info[4][0] in ips for info in infos)


async def resolves_to_own_ip(url_or_host: str, timeout_s: float = 1.5) -> bool:
    """A custom domain pointed at UserSim's VM. Unknown (timeout, no DNS) counts as not ours."""
    host = host_of(url_or_host)
    if not host:
        return False
    hit = _DNS_CACHE.get(host)
    if hit and time.monotonic() - hit[0] < 300:
        return hit[1]
    try:
        found = await asyncio.wait_for(asyncio.to_thread(_resolves_to_own_ip_sync, host), timeout_s)
    except Exception:
        return False
    _DNS_CACHE[host] = (time.monotonic(), found)
    return found


async def own_urls(urls: Iterable[str]) -> list[str]:
    """The URLs in ``urls`` that are UserSim's own site (by host, sslip/nip IP, or DNS)."""
    hits: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not (url or "").strip() or host_of(url) in seen:
            continue
        seen.add(host_of(url))
        if is_own_host(url) or await resolves_to_own_ip(url):
            hits.append(url)
    return hits


# ---- admin token ---------------------------------------------------------


def admin_token() -> str:
    return (os.environ.get("USERSIM_ADMIN_TOKEN") or "").strip()


def admin_headers() -> dict[str, str]:
    """For harnesses calling admin endpoints: the bearer header when USERSIM_ADMIN_TOKEN is set."""
    token = admin_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def admin_error(authorization: str | None) -> tuple[int, str] | None:
    """None when ``Authorization: Bearer <USERSIM_ADMIN_TOKEN>``; else (status, message).

    With no token configured every admin call is refused.
    """
    expected = admin_token()
    if not expected:
        return 403, "Admin actions are disabled: USERSIM_ADMIN_TOKEN is not set on this server."
    scheme, _, supplied = (authorization or "").strip().partition(" ")
    if scheme.lower() != "bearer" or not supplied.strip():
        return 401, "Admin bearer token required."
    if not hmac.compare_digest(supplied.strip().encode(), expected.encode()):
        return 403, "Invalid admin token."
    return None


def require_admin(request: Request) -> None:
    """FastAPI dependency: runs before the body is validated, so bad callers get 401/403, not 422."""
    from fastapi import HTTPException

    err = admin_error(request.headers.get("authorization"))
    if err is not None:
        raise HTTPException(status_code=err[0], detail=err[1], headers={"WWW-Authenticate": "Bearer"})


# ---- server side: requests from agent browsers --------------------------


def _deny_networks() -> list[Any]:
    nets = []
    for raw in _env_list("USERSIM_AGENT_DENY_IPS"):
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            print(f"[self_guard] ignoring bad USERSIM_AGENT_DENY_IPS entry {raw!r}", flush=True)
    return nets


def client_ips(headers: Mapping[str, str], peer: str | None) -> list[str]:
    """Every address the request claims to come from. Spoofing one only gets the sender refused."""
    out: list[str] = []
    for raw in [peer or "", headers.get("x-real-ip") or "", *(headers.get("x-forwarded-for") or "").split(",")]:
        ip = raw.strip()
        if ip and ip not in out:
            out.append(ip)
    return out


def denied_ip(ips: Iterable[str]) -> str:
    nets = _deny_networks()
    if not nets:
        return ""
    for raw in ips:
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if any(addr in net for net in nets):
            return raw
    return ""


def guarded_request(method: str, path: str) -> bool:
    """Study submits and runtime controls. Reads (GET/HEAD) stay open."""
    return method.upper() not in _SAFE_METHODS and bool(_STUDY_API_RE.match(path or ""))


def agent_request_reason(headers: Mapping[str, str], peer: str | None) -> str:
    """Why this request looks like it came from a UserSim agent browser ('' when it does not)."""
    if (headers.get(AGENT_HEADER.lower()) or "").strip():
        return "agent header"
    if AGENT_HEADER.lower() in (headers.get("access-control-request-headers") or "").lower():
        return "agent header (preflight)"
    ip = denied_ip(client_ips(headers, peer))
    if ip:
        return f"denylisted address {ip}"
    return ""


AGENT_REFUSAL = (
    "Requests from UserSim's own agent browsers cannot start studies or use runtime controls."
)


class AgentBrowserGuard:
    """ASGI middleware: 403 for study submits and runtime controls sent by an agent browser.

    Pure ASGI so streamed study responses are not wrapped. Preflights
    (OPTIONS) that announce the agent header are refused too.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and guarded_request(str(scope.get("method") or ""), str(scope.get("path") or "")):
            from starlette.datastructures import Headers
            from starlette.responses import JSONResponse

            client = scope.get("client")
            why = agent_request_reason(Headers(scope=scope), client[0] if client else None)
            if why:
                print(f"[self_guard] refused {scope.get('method')} {scope.get('path')}: {why}", flush=True)
                resp = JSONResponse({"detail": AGENT_REFUSAL, "status": "forbidden", "reason": why}, status_code=403)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def dogfood_refusal(urls: Iterable[str], admin_dogfood: bool, authorization: str | None) -> Any:
    """A response refusing a study of UserSim's own site, or None when it may run.

    With ``admin_dogfood`` and the admin bearer token it may run; its agents
    are still refused UserSim's controls and study API.
    """
    from starlette.responses import JSONResponse

    hits = await own_urls(urls)
    if not hits:
        return None
    if admin_dogfood:
        err = admin_error(authorization)
        if err is None:
            print(f"[self_guard] admin dogfood study of {hits}", flush=True)
            return None
        status, message = err
        return JSONResponse({"detail": message, "status": "forbidden"}, status_code=status)
    return JSONResponse(
        {
            "detail": (
                f"UserSim does not run studies of its own site ({', '.join(host_of(u) for u in hits)}): "
                "its agents would be driving UserSim itself. See a sample report instead."
            ),
            "status": "dogfood_refused",
            "own_urls": hits,
            "sample_report_url": SAMPLE_REPORT_URL,
        },
        status_code=409,
    )


# ---- agent side: what the agent may do on a UserSim page ----------------

_INPUT_ROLES = {"input", "textarea", "textbox", "searchbox", "combobox", "spinbutton"}
_TRIGGER_RE = re.compile(
    r"\b(?:run|start|launch|simulat\w*|kill|stop|abort|cancel|submit|go|test|analy[sz]e|compare|study|studies|"
    r"try|begin|send|create|new)\b",
    re.I,
)


def _api_href(href: str) -> bool:
    try:
        path = urlsplit(href if "://" in href else "https://x" + (href if href.startswith("/") else "/" + href)).path
    except ValueError:
        return False
    return bool(_STUDY_API_RE.match(path))


def agent_action_block(page_url: str, action: Mapping[str, Any]) -> str:
    """Why the agent may not take ``action`` on ``page_url`` ('' when allowed).

    On a UserSim page the agent may read, scroll, go back, and follow links,
    but not type (the Run box), press keys (Enter submits), drag, or click a
    button, since those can start a study or call kill. A link to UserSim's
    study or runtime API is refused on any site.
    """
    on_own = is_own_host(page_url)
    href = str(action.get("href") or "").strip()
    if href and _api_href(href) and (is_own_host(href) or (on_own and "://" not in href)):
        return "it calls UserSim's own study or runtime API"
    if not on_own:
        return ""
    act = str(action.get("act") or "click").lower()
    if act in {"scroll", "back", "done", "blocked"}:
        return ""
    role = str(action.get("role") or "").lower()
    if act in {"type", "press", "drag"} or role in _INPUT_ROLES:
        return "typing or submitting on UserSim's own site could start a study"
    if (role == "link" or (href and not role)) and not _TRIGGER_RE.search(str(action.get("name") or "")):
        return ""
    return "buttons on UserSim's own site can start a study or stop agents"


def node_blocked(page_url: str, node: Mapping[str, Any]) -> bool:
    """A control the model should never see on a UserSim page."""
    if not is_own_host(page_url) and not str(node.get("href") or "").strip():
        return False
    role = str(node.get("role") or "").lower()
    act = "type" if role in _INPUT_ROLES else "click"
    return bool(agent_action_block(page_url, {**dict(node), "act": act}))


# ---- agent side: mark and filter the browser's requests to UserSim ------


def marker_enabled() -> bool:
    return (os.environ.get("USERSIM_AGENT_MARKER") or "1").strip().lower() not in {"0", "false", "no"}


def fetch_patterns(hosts: Iterable[str] | None = None) -> list[dict[str, str]]:
    patterns: list[dict[str, str]] = []
    for host in hosts if hosts is not None else own_hosts():
        for p in (f"*://{host}/*", f"*://{host}:*/*", f"*://*.{host}/*"):
            patterns.append({"urlPattern": p, "requestStage": "Request"})
    return patterns


def blocked_request(method: str, url: str) -> bool:
    """A request the agent browser must never send: a study submit or runtime control on UserSim."""
    try:
        path = urlsplit(url).path
    except ValueError:
        return False
    return guarded_request(method or "GET", path)


async def _guard_page(context: Any, page: Any, marker: str, patterns: list[dict[str, str]]) -> None:
    cdp = await context.new_cdp_session(page)

    async def _on_paused(event: dict[str, Any]) -> None:
        rid = event.get("requestId")
        req = event.get("request") or {}
        try:
            if blocked_request(str(req.get("method") or "GET"), str(req.get("url") or "")):
                print(f"[self_guard] blocked {req.get('method')} {req.get('url')} from agent browser", flush=True)
                await cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})
                return
            headers = [
                {"name": k, "value": str(v)}
                for k, v in (req.get("headers") or {}).items()
                if k.lower() != AGENT_HEADER.lower()
            ]
            headers.append({"name": AGENT_HEADER, "value": marker})
            await cdp.send("Fetch.continueRequest", {"requestId": rid, "headers": headers})
        except Exception:
            try:
                await cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})
            except Exception:
                pass

    cdp.on("Fetch.requestPaused", lambda event: asyncio.ensure_future(_on_paused(event)))
    await cdp.send("Fetch.enable", {"patterns": patterns})


async def install_agent_marker(context: Any, study_id: str | None, *, hosts: Iterable[str] | None = None) -> int:
    """Mark and filter this context's requests to UserSim hosts, on every open and future tab.

    Returns the number of pages guarded now. Never raises: a guard that fails
    to install leaves the server-side and action-filter layers in place.
    """
    if not marker_enabled() or context is None or getattr(context, "_usersim_guarded", False):
        return 0
    marker = str(study_id or "agent")[:80]
    patterns = fetch_patterns(hosts)

    async def _one(page: Any) -> bool:
        try:
            await _guard_page(context, page, marker, patterns)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[self_guard] marker install failed: {exc!r}", flush=True)
            return False

    try:
        context._usersim_guarded = True
        context.on("page", lambda page: asyncio.ensure_future(_one(page)))
    except Exception:
        pass
    done = await asyncio.gather(*[_one(p) for p in list(getattr(context, "pages", []) or [])])
    return sum(1 for ok in done if ok)
