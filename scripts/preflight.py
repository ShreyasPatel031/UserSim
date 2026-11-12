"""Preflight: is everything a real study needs working? Prints a pass/warn/fail/skip table.

  python scripts/preflight.py                      # every check except the plan dry run
  python scripts/preflight.py --url https://linear.app/   # + planner-only dry run (2-3 Gemini calls)
  python scripts/preflight.py --skip-tests --no-llm --prod-severity fail

Exits 1 when any check fails, else 0. Nothing here starts a study, opens a browser,
or calls a production POST endpoint. Secrets are read from env and never printed.

Env: GOOGLE_APPLICATION_CREDENTIALS (or GOOGLE_APPLICATION_CREDENTIALS_B64), GOOGLE_CLOUD_PROJECT,
VERTEX_LOCATION, MVP_LLM_MODEL / MVP_FAST_PLAN_MODEL, BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID,
GMAIL_REFRESH_TOKEN + GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET (or GMAIL_USER + GMAIL_APP_PASSWORD for IMAP),
CAPSOLVER_API_KEY (or MVP_CAPTCHA_API_KEY), PREFLIGHT_PROD_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import imaplib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Tests that fail on main today. The unit-test check passes when these are the only failures.
KNOWN_FAILURES = frozenset({
    "mvp/test_e2e2_gates.py::PageOpenedTests::test_strength_and_weakness_cite_step_ax_and_the_final_screenshot",
})

PROD_URL = "https://35-202-98-224.sslip.io"
CLOUD_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# Stripped from the unit-test run so no test can reach a paid or production service.
SECRET_ENV = (
    "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS_B64", "VERTEX_ADC_JSON", "VERTEX_ADC_JSON_B64",
    "GOOGLE_ADC_JSON", "GOOGLE_SERVICE_ACCOUNT_JSON", "BROWSERBASE_API_KEY", "USE_BROWSERBASE",
    "GMAIL_USER", "GMAIL_APP_PASSWORD", "MVP_GMAIL_USER", "MVP_GMAIL_APP_PASSWORD", "GMAIL_REFRESH_TOKEN",
    "GMAIL_CLIENT_SECRET", "CAPSOLVER_API_KEY", "MVP_CAPTCHA_API_KEY",
)
ACTIVE = {"running", "queued", "pending", "starting"}

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"


@dataclass
class Result:
    name: str
    status: str
    detail: str


def _env(*names: str) -> str:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return ""


def _scrub(text: str, *secrets: str) -> str:
    out = str(text)
    for s in secrets:
        if s and len(s) >= 6:
            out = out.replace(s, "***")
    return out[:300]


# (a) unit tests ---------------------------------------------------------------------------------

def parse_pytest(output: str) -> tuple[set[str], str]:
    """(failed or errored test ids, summary line) from ``pytest -q -rfE`` output."""
    failed = {m.group(2) for m in re.finditer(r"^(FAILED|ERROR) (\S+)", output, re.M)}
    summary = ""
    for line in output.splitlines()[::-1]:
        if re.search(r"\d+ (passed|failed|error)", line):
            summary = line.strip("= ").strip()
            break
    return failed, summary


def check_tests(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Result:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    try:
        proc = run(
            [sys.executable, "-m", "pytest", "mvp/", "-q", "-p", "no:cacheprovider", "-rfE"],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=900,
        )
    except subprocess.TimeoutExpired:
        return Result("unit tests", FAIL, "pytest timed out after 900s")
    failed, summary = parse_pytest(proc.stdout + proc.stderr)
    new = sorted(failed - KNOWN_FAILURES)
    fixed = sorted(KNOWN_FAILURES - failed)
    if proc.returncode not in (0, 1) or not summary:
        return Result("unit tests", FAIL, f"pytest exit {proc.returncode}: {summary or 'no summary (collection error?)'}")
    if new:
        return Result("unit tests", FAIL, f"{summary}; new failures: {', '.join(new)}")
    note = f"; known baseline failure now passes, drop it from KNOWN_FAILURES: {', '.join(fixed)}" if fixed else ""
    known = len(failed & KNOWN_FAILURES)
    return Result("unit tests", PASS, f"{summary} ({known} known baseline){note}")


# (b) production ---------------------------------------------------------------------------------

def _parse_ts(raw: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def study_problems(rows: list[dict], *, now: datetime, stuck_after_min: float, timeout_window_min: float = 60) -> tuple[list[str], list[str], int]:
    """(stuck study lines, recent timed-out study lines, active count)."""
    stuck, timed_out, active = [], [], 0
    for r in rows:
        status = str(r.get("status") or "").lower()
        phase = str(r.get("phase") or "")
        when = _parse_ts(r.get("updated_at"))
        age_min = (now - when).total_seconds() / 60 if when else None
        label = f"{str(r.get('id') or '')[:8]} {r.get('url') or ''}"
        if status in ACTIVE:
            active += 1
            if age_min is None or age_min >= stuck_after_min:
                stuck.append(f"{label} {status} for {'?' if age_min is None else int(age_min)}m")
        if "timed out" in phase.lower() and age_min is not None and age_min <= timeout_window_min:
            timed_out.append(f"{label} ({int(age_min)}m ago)")
    return stuck, timed_out, active


def check_production(http: httpx.Client, base: str, *, severity: str, stuck_after_min: float) -> list[Result]:
    base = base.rstrip("/")
    try:
        resp = http.get(f"{base}/health", timeout=10)
        ok = resp.status_code == 200 and (resp.json() or {}).get("ok") is True
        health = Result("prod /health", PASS if ok else FAIL, f"HTTP {resp.status_code} {resp.text[:80]}")
    except Exception as exc:  # noqa: BLE001
        return [Result("prod /health", FAIL, f"{type(exc).__name__}: {exc}"[:200])]
    try:
        resp = http.get(f"{base}/api/studies", params={"limit": 50}, timeout=20)
        resp.raise_for_status()
        rows = list((resp.json() or {}).get("studies") or [])
    except Exception as exc:  # noqa: BLE001
        return [health, Result("prod studies", FAIL, f"GET /api/studies: {type(exc).__name__}: {exc}"[:200])]
    stuck, timed_out, active = study_problems(rows, now=datetime.now(timezone.utc), stuck_after_min=stuck_after_min)
    bits = []
    if stuck:
        bits.append(f"stuck (no update {stuck_after_min:g}m+): {'; '.join(stuck[:4])}")
    if timed_out:
        bits.append(f"timed out in last hour: {'; '.join(timed_out[:4])}")
    if not bits:
        return [health, Result("prod studies", PASS, f"{len(rows)} studies, {active} active, none stuck or timed out")]
    return [health, Result("prod studies", severity, f"{len(rows)} studies, {active} active; " + " | ".join(bits))]


# (c) GCP credentials ----------------------------------------------------------------------------

def load_gcp_credentials() -> tuple[Any, str] | None:
    """(credentials, source) from GOOGLE_APPLICATION_CREDENTIALS or *_B64; None when neither is set."""
    import google.auth

    path = _env("GOOGLE_APPLICATION_CREDENTIALS")
    if path and Path(path).is_file():
        creds, _ = google.auth.load_credentials_from_file(path, scopes=CLOUD_SCOPES)
        return creds, "GOOGLE_APPLICATION_CREDENTIALS"
    b64 = _env("GOOGLE_APPLICATION_CREDENTIALS_B64")
    if b64:
        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds, _ = google.auth.load_credentials_from_dict(info, scopes=CLOUD_SCOPES)
        return creds, "GOOGLE_APPLICATION_CREDENTIALS_B64"
    if path:
        raise FileNotFoundError("GOOGLE_APPLICATION_CREDENTIALS points at a missing file")
    return None


def refresh_credentials(creds: Any) -> None:
    from google.auth.transport.requests import Request

    creds.refresh(Request())


def check_gcp(load: Callable = load_gcp_credentials, refresh: Callable = refresh_credentials) -> tuple[Result, Any]:
    try:
        got = load()
    except Exception as exc:  # noqa: BLE001
        return Result("gcp credentials", FAIL, f"could not load: {type(exc).__name__}: {exc}"[:200]), None
    if got is None:
        return Result("gcp credentials", SKIP, "GOOGLE_APPLICATION_CREDENTIALS not set"), None
    creds, source = got
    try:
        refresh(creds)
    except Exception as exc:  # noqa: BLE001
        return Result("gcp credentials", FAIL, f"token mint failed: {type(exc).__name__}"), None
    if not getattr(creds, "token", None):
        return Result("gcp credentials", FAIL, "refresh returned no access token"), None
    kind = "service account" if getattr(creds, "service_account_email", "") else type(creds).__name__
    return Result("gcp credentials", PASS, f"access token minted ({kind}, from {source})"), creds


# (d) Vertex -------------------------------------------------------------------------------------

def configured_models() -> list[str]:
    from capability.gemini_config import gemini_model
    from mvp.fast_plan import plan_model

    return list(dict.fromkeys([gemini_model(), plan_model()]))


def check_vertex(http: httpx.Client, creds: Any, models: list[str] | None = None) -> Result:
    if creds is None:
        return Result("vertex model", SKIP, "no GCP credentials (see gcp credentials)")
    project = _env("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT")
    if not project:
        return Result("vertex model", SKIP, "GOOGLE_CLOUD_PROJECT not set")
    loc = _env("VERTEX_LOCATION", "GCP_LOCATION") or "global"
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    headers = {"Authorization": f"Bearer {creds.token}", "x-goog-user-project": project}
    bad, good = [], []
    for model in models or configured_models():
        try:
            resp = http.get(f"https://{host}/v1/publishers/google/models/{model}", headers=headers, timeout=20)
            (good if resp.status_code == 200 else bad).append(f"{model}={resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{model}={type(exc).__name__}")
    detail = "GET model resource: " + ", ".join(good + bad)
    return Result("vertex model", FAIL if bad else PASS, detail)


# (e) Browserbase --------------------------------------------------------------------------------

def check_browserbase(http: httpx.Client, *, max_running: int) -> Result:
    key = _env("BROWSERBASE_API_KEY")
    if not key:
        return Result("browserbase", SKIP, "BROWSERBASE_API_KEY not set")
    headers = {"X-BB-API-Key": key}
    try:
        resp = http.get("https://api.browserbase.com/v1/sessions", params={"status": "RUNNING"}, headers=headers, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return Result("browserbase", FAIL, _scrub(f"{type(exc).__name__}: {exc}", key))
    if resp.status_code in (401, 403):
        return Result("browserbase", FAIL, f"API key rejected (HTTP {resp.status_code})")
    if resp.status_code != 200:
        return Result("browserbase", FAIL, _scrub(f"HTTP {resp.status_code} {resp.text[:120]}", key))
    body = resp.json()
    rows = body if isinstance(body, list) else list((body or {}).get("sessions") or body.get("data") or [])
    running = sum(1 for r in rows if str((r or {}).get("status") or "RUNNING").upper() == "RUNNING")
    limit = ""
    project = _env("BROWSERBASE_PROJECT_ID")
    if project:
        try:
            proj = http.get(f"https://api.browserbase.com/v1/projects/{project}", headers=headers, timeout=20)
            if proj.status_code == 200 and (proj.json() or {}).get("concurrency"):
                limit = f" of {proj.json()['concurrency']}"
        except Exception:  # noqa: BLE001
            pass
    detail = f"{running}{limit} sessions running (threshold {max_running})"
    return Result("browserbase", PASS if running < max_running else FAIL, detail)


# (f) Gmail signup inbox -------------------------------------------------------------------------

def check_gmail(http: httpx.Client, imap_factory: Callable[[str], Any] = imaplib.IMAP4_SSL) -> Result:
    refresh = _env("GMAIL_REFRESH_TOKEN")
    client_id, secret = _env("GMAIL_CLIENT_ID"), _env("GMAIL_CLIENT_SECRET")
    if refresh and client_id and secret:
        try:
            tok = http.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id, "client_secret": secret,
            }, timeout=20)
            if tok.status_code != 200:
                try:
                    err = str((tok.json() or {}).get("error") or "")
                except ValueError:
                    err = ""
                return Result("gmail inbox", FAIL, f"refresh token rejected (HTTP {tok.status_code} {err})".strip())
            access = tok.json()["access_token"]
            resp = http.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", params={"maxResults": 1},
                            headers={"Authorization": f"Bearer {access}"}, timeout=20)
        except Exception as exc:  # noqa: BLE001
            return Result("gmail inbox", FAIL, _scrub(f"{type(exc).__name__}: {exc}", refresh, secret))
        if resp.status_code != 200:
            return Result("gmail inbox", FAIL, f"list messages HTTP {resp.status_code}")
        n = len((resp.json() or {}).get("messages") or [])
        return Result("gmail inbox", PASS if n else WARN, f"OAuth refresh ok; listed {n} message(s)")
    user, password = _env("GMAIL_USER", "MVP_GMAIL_USER"), _env("GMAIL_APP_PASSWORD", "MVP_GMAIL_APP_PASSWORD")
    if user and password:
        try:
            box = imap_factory("imap.gmail.com")
            try:
                box.login(user, password)
                box.select("INBOX", readonly=True)
                _typ, data = box.uid("search", None, "ALL")
                uids = (data[0] or b"").split() if data else []
                if uids:
                    box.uid("fetch", uids[-1], "(BODY.PEEK[HEADER.FIELDS (DATE)])")
            finally:
                try:
                    box.logout()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            return Result("gmail inbox", FAIL, _scrub(f"IMAP: {type(exc).__name__}: {exc}", user, password))
        return Result("gmail inbox", PASS if uids else WARN, f"IMAP app-password login ok; listed {min(1, len(uids))} message")
    return Result("gmail inbox", SKIP, "GMAIL_REFRESH_TOKEN (+ GMAIL_CLIENT_ID/SECRET) or GMAIL_USER + GMAIL_APP_PASSWORD not set")


# (g) CapSolver ----------------------------------------------------------------------------------

def capsolver_balance(http: httpx.Client, key: str) -> dict[str, Any]:
    """Raw CapSolver getBalance reply ({"errorId": 0, "balance": 1.23} on success). Free call."""
    return http.post("https://api.capsolver.com/getBalance", json={"clientKey": key}, timeout=20).json()


def check_capsolver(http: httpx.Client, *, min_balance: float) -> Result:
    key = _env("CAPSOLVER_API_KEY", "MVP_CAPTCHA_API_KEY")
    if not key:
        return Result("capsolver", SKIP, "CAPSOLVER_API_KEY not set")
    try:
        body = capsolver_balance(http, key)
    except Exception as exc:  # noqa: BLE001
        return Result("capsolver", FAIL, _scrub(f"{type(exc).__name__}: {exc}", key))
    if body.get("errorId"):
        return Result("capsolver", FAIL, f"errorId {body.get('errorId')} {body.get('errorCode') or ''}".strip())
    try:
        balance = float(body.get("balance"))
    except (TypeError, ValueError):
        return Result("capsolver", FAIL, "getBalance returned no balance")
    return Result("capsolver", PASS if balance > min_balance else FAIL, f"balance ${balance:.2f} (min ${min_balance:.2f})")


# (h) planner dry run ----------------------------------------------------------------------------

def check_plan(url: str, run: Callable[[str], Any] | None = None) -> tuple[Result, dict | None]:
    if not (_env("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS_B64", "VERTEX_ADC_JSON")):
        return Result("plan dry run", SKIP, "no GCP credentials for Gemini"), None
    if run is None:
        from mvp.plan_check import dry_run_plan

        def run(u: str) -> dict:
            return asyncio.run(dry_run_plan(u))
    try:
        out = run(url)
    except Exception as exc:  # noqa: BLE001
        return Result("plan dry run", FAIL, f"{type(exc).__name__}: {exc}"[:200]), None
    usage = out.get("usage") or {}
    cost = usage.get("est_cost_usd")
    spend = (
        f"{usage.get('gemini_calls', 0)} Gemini calls, {usage.get('input_tokens', 0)} in / "
        f"{usage.get('output_tokens', 0)} out tokens, est ${cost:.4f}" if cost is not None else "cost unknown"
    )
    bad = [f"{c['name']}: {c['detail']}" for c in out.get("validation") or [] if not c.get("ok")]
    rivals = ", ".join(r["url"] for r in out.get("rivals") or [])
    if bad:
        return Result("plan dry run", FAIL, f"{out.get('plan_s')}s; {'; '.join(bad)} | {spend}"), out
    return Result("plan dry run", PASS, f"{out.get('plan_s')}s; rivals {rivals} | {spend}"), out


# -----------------------------------------------------------------------------------------------

def print_table(results: list[Result], out=None) -> None:
    out = out or sys.stdout
    width = max(len(r.name) for r in results)
    for r in results:
        out.write(f"{r.status.upper():<5} {r.name:<{width}}  {r.detail}\n")
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, WARN, FAIL, SKIP)}
    out.write(" ".join(f"{n} {s}" for s, n in counts.items()) + "\n")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", help="product URL for the planner-only dry run (2-3 Gemini calls)")
    ap.add_argument("--no-llm", action="store_true", help="skip every check that calls an LLM")
    ap.add_argument("--skip-tests", action="store_true", help="skip the offline unit tests")
    ap.add_argument("--no-prod", action="store_true", help="skip the production checks")
    ap.add_argument("--prod-url", default=os.environ.get("PREFLIGHT_PROD_URL") or PROD_URL)
    ap.add_argument("--prod-severity", choices=[WARN, FAIL], default=os.environ.get("PREFLIGHT_PROD_SEVERITY") or WARN,
                    help="how stuck or timed-out production studies are reported (default warn)")
    ap.add_argument("--stuck-after-min", type=float, default=10.0, help="an active study not updated for this long is stuck")
    ap.add_argument("--bb-max-running", type=int, default=20, help="fail at or above this many running Browserbase sessions")
    ap.add_argument("--capsolver-min", type=float, default=0.50, help="minimum CapSolver balance in USD")
    ap.add_argument("--json", action="store_true", help="also print the results (and dry-run plan) as JSON")
    return ap


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None,
         tests: Callable[[], Result] = check_tests) -> int:
    args = build_parser().parse_args(argv)
    results: list[Result] = []
    plan_out = None
    with httpx.Client(transport=transport, follow_redirects=True) as http:
        results.append(Result("unit tests", SKIP, "--skip-tests") if args.skip_tests else tests())
        if args.no_prod:
            results.append(Result("prod", SKIP, "--no-prod"))
        else:
            results += check_production(http, args.prod_url, severity=args.prod_severity, stuck_after_min=args.stuck_after_min)
        gcp, creds = check_gcp()
        results.append(gcp)
        results.append(check_vertex(http, creds))
        results.append(check_browserbase(http, max_running=args.bb_max_running))
        results.append(check_gmail(http))
        results.append(check_capsolver(http, min_balance=args.capsolver_min))
        if not args.url:
            results.append(Result("plan dry run", SKIP, "pass --url to run it"))
        elif args.no_llm:
            results.append(Result("plan dry run", SKIP, "--no-llm"))
        else:
            res, plan_out = check_plan(args.url)
            results.append(res)
    print_table(results)
    if args.json:
        print(json.dumps({"results": [r.__dict__ for r in results], "plan": plan_out}, indent=1, default=str))
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
