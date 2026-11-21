"""Google sign-in for token callers only (mvp/sim_mcp/google_signin.py)."""
import json
from unittest import mock

from mvp.sim_mcp import google_signin, sessions


def test_blocked_for_everyone_by_default():
    assert sessions.blocked_signin("https://accounts.google.com/o/oauth2/auth?x=1")
    assert sessions.blocked_signin("https://github.com/login")


def test_google_ok_unblocks_only_google():
    assert not sessions.blocked_signin("https://accounts.google.com/signin", google_ok=True)
    assert sessions.blocked_signin("https://github.com/login", google_ok=True)


def test_validate_navigate_respects_google_ok():
    act = {"type": "navigate", "url": "https://accounts.google.com/signin"}
    try:
        sessions.validate_action(dict(act), "https://example.com")
        raise AssertionError("anonymous navigate to Google must be refused")
    except sessions.SessionError:
        pass


def test_allowed_only_for_token_callers(monkeypatch):
    monkeypatch.setenv("MVP_GOOGLE_STATE_URI", "gs://bucket/private/google_state/signups.json")
    with mock.patch("mvp.sim_mcp.limits.get", lambda k: True if k == "google_signin_token_callers" else None):
        assert google_signin.allowed_for("a1b2c3d4e5f60718")
        assert not google_signin.allowed_for("anon:deadbeef")
        assert not google_signin.allowed_for("")
    with mock.patch("mvp.sim_mcp.limits.get", lambda k: False):
        assert not google_signin.allowed_for("a1b2c3d4e5f60718")
    monkeypatch.delenv("MVP_GOOGLE_STATE_URI")
    monkeypatch.setenv("MVP_GOOGLE_VAULT_URI", "off")
    with mock.patch("mvp.sim_mcp.limits.get", lambda k: True):
        assert not google_signin.allowed_for("a1b2c3d4e5f60718")


def test_merge_keeps_both_and_dedupes():
    site = {"cookies": [{"name": "s", "domain": "app.x.com", "path": "/"}], "origins": [{"origin": "https://app.x.com"}]}
    goog = {"cookies": [{"name": "SID", "domain": ".google.com", "path": "/"},
                        {"name": "s", "domain": "app.x.com", "path": "/"}], "origins": []}
    out = google_signin.merge(site, goog)
    assert [c["name"] for c in out["cookies"]] == ["s", "SID"]
    assert out["origins"] == [{"origin": "https://app.x.com"}]


def test_open_browser_google_only_does_not_touch_site_account():
    """Regression: a token session with the Google state but no saved site account crashed with
    "'NoneType' object has no attribute 'get'" (weaveos.com, Nov 21)."""
    import inspect

    src = inspect.getsource(sessions._open_browser)
    assert "if saved:\n            sim.row[\"saved_account\"]" in src


def test_vault_entry_picked_and_allowed_without_state(monkeypatch):
    from mvp.sim_mcp import google_login

    vault = {"sites": [{"match": ["example.com"], "username": "x", "password": "y"},
                       {"match": ["google.com", "gmail.com"], "username": "a@gmail.com", "password": "p", "totp_secret": "JBSWY3DPEHPK3PXP"}]}
    monkeypatch.setenv("MVP_GOOGLE_VAULT_URI", "gs://bucket/private/google_vault.json")
    monkeypatch.delenv("MVP_GOOGLE_STATE_URI", raising=False)
    google_login._CACHE[0] = 0.0
    with mock.patch.object(google_login, "_read_vault", lambda: vault):
        assert google_login.google_creds()["username"] == "a@gmail.com"
    with mock.patch("mvp.sim_mcp.limits.get", lambda k: True if k == "google_signin_token_callers" else None):
        assert google_signin.allowed_for("a1b2c3d4e5f60718")
        assert not google_signin.allowed_for("anon:deadbeef")


def test_sign_in_refuses_off_google():
    import asyncio
    from types import SimpleNamespace

    from mvp.sim_mcp import google_login

    page = SimpleNamespace(url="https://weaveos.com/", is_closed=lambda: False)
    sim = SimpleNamespace(page=page, context=None)
    with mock.patch.object(google_login, "google_creds", lambda: {"username": "a", "password": "b"}):
        out = asyncio.run(google_login.sign_in(sim))
    assert out["ok"] is False and out["reason"] == "not_on_google_signin"
    assert "b" not in json.dumps(out)
