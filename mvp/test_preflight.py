"""scripts/preflight.py: every check offline (HTTP, IMAP, pytest and Gemini mocked)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import httpx

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "preflight.py"
_spec = importlib.util.spec_from_file_location("preflight", _PATH)
pf = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("preflight", pf)
_spec.loader.exec_module(pf)

SECRET = "sk-very-secret-value-123"
KNOWN = next(iter(pf.KNOWN_FAILURES))


def _http(routes):
    """httpx client whose requests go to routes[(method, url-without-query)] -> Response or callable."""
    seen = []

    def handler(req):
        key = (req.method, str(req.url).split("?")[0])
        seen.append(req)
        got = routes.get(key)
        if got is None:
            return httpx.Response(404, json={"error": "unrouted"})
        return got(req) if callable(got) else got

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen
    return client


def _no_env(*extra):
    names = set(pf.SECRET_ENV) | {"GMAIL_CLIENT_ID", "BROWSERBASE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT"} | set(extra)
    return {k: v for k, v in os.environ.items() if k not in names}


def _proc(stdout, code=1):
    return lambda *a, **kw: subprocess.CompletedProcess(a, code, stdout=stdout, stderr="")


class UnitTestCheckTests(unittest.TestCase):
    def test_only_known_failures_pass(self):
        out = f"FAILED {KNOWN} - AssertionError\n=== 1 failed, 330 passed, 3 skipped in 4s ==="
        got = pf.check_tests(run=_proc(out))
        self.assertEqual(got.status, pf.PASS)
        self.assertIn("1 failed, 330 passed", got.detail)

    def test_a_new_failure_fails(self):
        out = f"FAILED {KNOWN} - x\nFAILED mvp/test_new.py::T::test_x - y\n1 failed... \n2 failed, 329 passed in 4s"
        got = pf.check_tests(run=_proc(out))
        self.assertEqual(got.status, pf.FAIL)
        self.assertIn("mvp/test_new.py::T::test_x", got.detail)
        self.assertNotIn(KNOWN, got.detail)

    def test_a_collection_error_fails(self):
        out = "ERROR mvp/test_broken.py - ImportError\n1 error in 0.3s"
        self.assertEqual(pf.check_tests(run=_proc(out, code=2)).status, pf.FAIL)
        self.assertEqual(pf.check_tests(run=_proc("", code=4)).status, pf.FAIL)

    def test_a_fixed_baseline_failure_is_pointed_out(self):
        got = pf.check_tests(run=_proc("331 passed, 3 skipped in 4s", code=0))
        self.assertEqual(got.status, pf.PASS)
        self.assertIn("drop it from KNOWN_FAILURES", got.detail)

    def test_the_test_run_gets_no_secrets(self):
        seen = {}

        def run(cmd, **kw):
            seen.update(kw["env"])
            return subprocess.CompletedProcess(cmd, 0, stdout="1 passed in 1s", stderr="")

        with mock.patch.dict(os.environ, {"BROWSERBASE_API_KEY": SECRET, "CAPSOLVER_API_KEY": SECRET}):
            pf.check_tests(run=run)
        self.assertNotIn("BROWSERBASE_API_KEY", seen)
        self.assertNotIn("CAPSOLVER_API_KEY", seen)


class ProductionCheckTests(unittest.TestCase):
    BASE = "https://prod.example"

    def _rows(self):
        now = datetime.now(timezone.utc)
        ago = lambda m: (now - timedelta(minutes=m)).isoformat()
        return [
            {"id": "aaaaaaaa1", "url": "https://a.com", "status": "queued", "phase": "Queued", "updated_at": ago(30)},
            {"id": "bbbbbbbb1", "url": "https://b.com", "status": "running", "phase": "Running", "updated_at": ago(1)},
            {"id": "cccccccc1", "url": "https://c.com", "status": "abandoned", "phase": "Timed out", "updated_at": ago(20)},
            {"id": "dddddddd1", "url": "https://d.com", "status": "abandoned", "phase": "Timed out", "updated_at": ago(200)},
        ]

    def test_study_problems_finds_stuck_and_recent_timeouts(self):
        stuck, timed_out, active = pf.study_problems(self._rows(), now=datetime.now(timezone.utc), stuck_after_min=10)
        self.assertEqual(active, 2)
        self.assertEqual(len(stuck), 1)
        self.assertIn("a.com", stuck[0])
        self.assertEqual(len(timed_out), 1)
        self.assertIn("c.com", timed_out[0])

    def _check(self, rows, severity="warn", health=None):
        http = _http({
            ("GET", f"{self.BASE}/health"): health or httpx.Response(200, json={"ok": True}),
            ("GET", f"{self.BASE}/api/studies"): httpx.Response(200, json={"studies": rows}),
        })
        got = pf.check_production(http, self.BASE, severity=severity, stuck_after_min=10)
        self.assertEqual([str(r.url) for r in http.seen], [f"{self.BASE}/health", f"{self.BASE}/api/studies?limit=50"])
        self.assertTrue(all(r.method == "GET" for r in http.seen))
        return got

    def test_clean_production_passes(self):
        health, studies = self._check([self._rows()[1]])
        self.assertEqual((health.status, studies.status), (pf.PASS, pf.PASS))

    def test_problems_are_a_warn_or_a_fail_as_configured(self):
        self.assertEqual(self._check(self._rows())[1].status, pf.WARN)
        self.assertEqual(self._check(self._rows(), severity="fail")[1].status, pf.FAIL)

    def test_health_down_fails(self):
        got = self._check([], health=httpx.Response(503, text="down"))
        self.assertEqual(got[0].status, pf.FAIL)


class GcpAndVertexTests(unittest.TestCase):
    class Creds:
        token = None
        service_account_email = "sa@example.iam.gserviceaccount.com"

    def test_missing_credentials_skip(self):
        with mock.patch.dict(os.environ, _no_env(), clear=True):
            got, creds = pf.check_gcp()
        self.assertEqual(got.status, pf.SKIP)
        self.assertIsNone(creds)
        with mock.patch.dict(os.environ, _no_env(), clear=True):
            self.assertEqual(pf.check_vertex(_http({}), None).status, pf.SKIP)

    def test_a_missing_credentials_file_fails(self):
        with mock.patch.dict(os.environ, {**_no_env(), "GOOGLE_APPLICATION_CREDENTIALS": "/nope/sa.json"}, clear=True):
            got, _ = pf.check_gcp()
        self.assertEqual(got.status, pf.FAIL)

    def test_token_mint_passes_without_printing_the_token(self):
        creds = self.Creds()

        def refresh(c):
            c.token = SECRET

        got, back = pf.check_gcp(load=lambda: (creds, "GOOGLE_APPLICATION_CREDENTIALS"), refresh=refresh)
        self.assertEqual(got.status, pf.PASS)
        self.assertIs(back, creds)
        self.assertNotIn(SECRET, got.detail)
        self.assertNotIn("sa@example", got.detail)

    def test_a_refresh_error_fails(self):
        def refresh(c):
            raise RuntimeError("invalid_grant")

        got, back = pf.check_gcp(load=lambda: (self.Creds(), "x"), refresh=refresh)
        self.assertEqual(got.status, pf.FAIL)
        self.assertIsNone(back)

    def test_vertex_model_get(self):
        creds = self.Creds()
        creds.token = SECRET
        url = "https://aiplatform.googleapis.com/v1/publishers/google/models/"
        http = _http({
            ("GET", url + "gemini-2.5-flash"): httpx.Response(200, json={"name": "m"}),  # pragma: allowlist secret
            ("GET", url + "gemini-9"): httpx.Response(404, json={}),
        })
        with mock.patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "proj", "VERTEX_LOCATION": "global"}):
            ok = pf.check_vertex(http, creds, models=["gemini-2.5-flash"])  # pragma: allowlist secret
            bad = pf.check_vertex(http, creds, models=["gemini-2.5-flash", "gemini-9"])  # pragma: allowlist secret
        self.assertEqual(ok.status, pf.PASS)
        self.assertEqual(bad.status, pf.FAIL)
        self.assertIn("gemini-9=404", bad.detail)
        self.assertEqual(http.seen[0].headers["authorization"], f"Bearer {SECRET}")
        self.assertNotIn(SECRET, ok.detail + bad.detail)

    def test_regional_vertex_host(self):
        creds = self.Creds()
        creds.token = "t"
        http = _http({("GET", "https://europe-west4-aiplatform.googleapis.com/v1/publishers/google/models/m"): httpx.Response(200)})
        with mock.patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "proj", "VERTEX_LOCATION": "europe-west4"}):
            self.assertEqual(pf.check_vertex(http, creds, models=["m"]).status, pf.PASS)


class BrowserbaseTests(unittest.TestCase):
    SESSIONS = ("GET", "https://api.browserbase.com/v1/sessions")

    def _run(self, n=None, resp=None, env=None, max_running=20):
        routes = {self.SESSIONS: resp or httpx.Response(200, json=[{"id": str(i), "status": "RUNNING"} for i in range(n or 0)])}
        routes[("GET", "https://api.browserbase.com/v1/projects/proj")] = httpx.Response(200, json={"concurrency": 25})
        http = _http(routes)
        env = {"BROWSERBASE_API_KEY": SECRET, "BROWSERBASE_PROJECT_ID": "proj"} if env is None else env
        with mock.patch.dict(os.environ, {**_no_env(), **env}, clear=True):
            return pf.check_browserbase(http, max_running=max_running), http

    def test_skip_without_key(self):
        self.assertEqual(self._run(env={})[0].status, pf.SKIP)

    def test_under_threshold_passes(self):
        got, http = self._run(n=5)
        self.assertEqual(got.status, pf.PASS)
        self.assertIn("5 of 25", got.detail)
        self.assertEqual(http.seen[0].headers["x-bb-api-key"], SECRET)
        self.assertEqual(http.seen[0].url.params["status"], "RUNNING")

    def test_at_threshold_fails(self):
        self.assertEqual(self._run(n=20)[0].status, pf.FAIL)
        self.assertEqual(self._run(n=3, max_running=3)[0].status, pf.FAIL)

    def test_bad_key_fails_without_echoing_it(self):
        got, _ = self._run(resp=httpx.Response(401, text=f"bad key {SECRET}"))
        self.assertEqual(got.status, pf.FAIL)
        self.assertNotIn(SECRET, got.detail)


class GmailTests(unittest.TestCase):
    OAUTH = {"GMAIL_REFRESH_TOKEN": SECRET, "GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "csecret-123456"}

    def _oauth(self, token_resp, list_resp=None):
        http = _http({
            ("POST", "https://oauth2.googleapis.com/token"): token_resp,
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): list_resp
            or httpx.Response(200, json={"messages": [{"id": "m1"}]}),
        })
        with mock.patch.dict(os.environ, {**_no_env(), **self.OAUTH}, clear=True):
            return pf.check_gmail(http), http

    def test_skip_without_credentials(self):
        with mock.patch.dict(os.environ, _no_env(), clear=True):
            self.assertEqual(pf.check_gmail(_http({})).status, pf.SKIP)

    def test_refresh_token_lists_one_message(self):
        got, http = self._oauth(httpx.Response(200, json={"access_token": "at-xyz"}))
        self.assertEqual(got.status, pf.PASS)
        self.assertIn("listed 1", got.detail)
        self.assertEqual(http.seen[1].url.params["maxResults"], "1")
        self.assertEqual(http.seen[1].headers["authorization"], "Bearer at-xyz")

    def test_a_revoked_refresh_token_fails(self):
        got, _ = self._oauth(httpx.Response(400, json={"error": "invalid_grant"}))
        self.assertEqual(got.status, pf.FAIL)
        self.assertIn("invalid_grant", got.detail)
        self.assertNotIn(SECRET, got.detail)

    def test_imap_fallback(self):
        calls = []

        class Box:
            def __init__(self, host):
                calls.append(("connect", host))

            def login(self, user, password):
                calls.append(("login",))

            def select(self, box, readonly=False):
                calls.append(("select", box, readonly))

            def uid(self, cmd, *args):
                calls.append(("uid", cmd))
                return "OK", [b"1 2 3"]

            def logout(self):
                calls.append(("logout",))

        env = {**_no_env(), "GMAIL_USER": "someone@example.com", "GMAIL_APP_PASSWORD": SECRET}
        with mock.patch.dict(os.environ, env, clear=True):
            got = pf.check_gmail(_http({}), imap_factory=Box)
        self.assertEqual(got.status, pf.PASS)
        self.assertIn(("select", "INBOX", True), calls)
        self.assertEqual(calls[-1], ("logout",))
        self.assertNotIn("someone@example.com", got.detail)

    def test_imap_login_failure_hides_the_password(self):
        class Box:
            def __init__(self, host):
                pass

            def login(self, user, password):
                raise OSError(f"auth failed for {password}")

            def logout(self):
                pass

        env = {**_no_env(), "GMAIL_USER": "someone@example.com", "GMAIL_APP_PASSWORD": SECRET}
        with mock.patch.dict(os.environ, env, clear=True):
            got = pf.check_gmail(_http({}), imap_factory=Box)
        self.assertEqual(got.status, pf.FAIL)
        self.assertNotIn(SECRET, got.detail)


class CapSolverTests(unittest.TestCase):
    URL = ("POST", "https://api.capsolver.com/getBalance")

    def _run(self, resp, env=None, min_balance=0.5):
        http = _http({self.URL: resp})
        with mock.patch.dict(os.environ, {**_no_env(), **({"CAPSOLVER_API_KEY": SECRET} if env is None else env)}, clear=True):
            return pf.check_capsolver(http, min_balance=min_balance), http

    def test_skip_without_key(self):
        self.assertEqual(self._run(httpx.Response(200), env={})[0].status, pf.SKIP)

    def test_balance_above_minimum_passes(self):
        got, http = self._run(httpx.Response(200, json={"errorId": 0, "balance": 3.21}))
        self.assertEqual(got.status, pf.PASS)
        self.assertIn("$3.21", got.detail)
        self.assertIn(SECRET.encode(), http.seen[0].content)
        self.assertNotIn(SECRET, got.detail)

    def test_low_balance_fails(self):
        self.assertEqual(self._run(httpx.Response(200, json={"errorId": 0, "balance": 0.5}))[0].status, pf.FAIL)

    def test_error_id_fails(self):
        got, _ = self._run(httpx.Response(200, json={"errorId": 1, "errorCode": "ERROR_KEY_DENIED_ACCESS"}))
        self.assertEqual(got.status, pf.FAIL)
        self.assertIn("ERROR_KEY_DENIED_ACCESS", got.detail)

    def test_legacy_key_env_name_works(self):
        got, _ = self._run(httpx.Response(200, json={"errorId": 0, "balance": 9}), env={"MVP_CAPTCHA_API_KEY": SECRET})
        self.assertEqual(got.status, pf.PASS)


class PlanCheckTests(unittest.TestCase):
    OUT = {
        "plan_s": 12.3,
        "rivals": [{"url": "https://asana.com/"}, {"url": "https://jira.com/"}],
        "validation": [{"name": "plan", "ok": True, "detail": ""}, {"name": "plan_time", "ok": True, "detail": ""}],
        "usage": {"gemini_calls": 3, "input_tokens": 9000, "output_tokens": 2000, "est_cost_usd": 0.0077},
    }

    def _run(self, out):
        with mock.patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS_B64": "x"}):
            return pf.check_plan("https://linear.app/", run=lambda u: out)

    def test_a_good_plan_passes_and_prints_its_cost(self):
        got, _ = self._run(self.OUT)
        self.assertEqual(got.status, pf.PASS)
        self.assertIn("est $0.0077", got.detail)
        self.assertIn("9000 in / 2000 out", got.detail)

    def test_a_failed_validation_fails(self):
        out = dict(self.OUT, validation=[{"name": "live_rivals", "ok": False, "detail": "1 live of 2"}])
        got, _ = self._run(out)
        self.assertEqual(got.status, pf.FAIL)
        self.assertIn("live_rivals: 1 live of 2", got.detail)

    def test_skip_without_gcp_credentials(self):
        with mock.patch.dict(os.environ, _no_env(), clear=True):
            got, _ = pf.check_plan("https://linear.app/", run=lambda u: self.fail("must not run"))
        self.assertEqual(got.status, pf.SKIP)


class MainTests(unittest.TestCase):
    def _main(self, argv, env, tests=None):
        out = io.StringIO()
        transport = httpx.MockTransport(lambda req: httpx.Response(500))
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
            code = pf.main(argv, transport=transport, tests=tests or (lambda: pf.Result("unit tests", pf.PASS, "ok")))
        return code, out.getvalue()

    def test_everything_missing_skips_and_exits_zero(self):
        code, out = self._main(["--no-prod", "--url", "https://linear.app/"], _no_env())
        self.assertEqual(code, 0, out)
        for name in ("gcp credentials", "vertex model", "browserbase", "gmail inbox", "capsolver", "plan dry run"):
            self.assertRegex(out, rf"SKIP\s+{name}")
        self.assertIn("PASS  unit tests", out)

    def test_no_llm_skips_the_dry_run(self):
        code, out = self._main(["--no-prod", "--skip-tests", "--no-llm", "--url", "https://x.com"],
                               {**_no_env(), "GOOGLE_APPLICATION_CREDENTIALS_B64": ""})
        self.assertEqual(code, 0)
        self.assertRegex(out, r"SKIP\s+plan dry run\s+--no-llm")

    def test_any_fail_exits_one_and_no_secret_is_printed(self):
        env = {**_no_env(), "BROWSERBASE_API_KEY": SECRET, "CAPSOLVER_API_KEY": SECRET}
        code, out = self._main(["--prod-url", "https://prod.example", "--json"], env)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL\s+prod /health")
        self.assertRegex(out, r"FAIL\s+browserbase")
        self.assertNotIn(SECRET, out)


if __name__ == "__main__":
    unittest.main()
