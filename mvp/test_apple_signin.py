from mvp import apple_signin


def test_is_apple_auth_url():
    assert apple_signin.is_apple_auth_url("https://appleid.apple.com/auth/authorize?client_id=x")
    assert apple_signin.is_apple_auth_url("https://idmsa.apple.com/appleauth/auth/signin")
    assert not apple_signin.is_apple_auth_url("https://apps.apple.com/app/id1485756576")
    assert not apple_signin.is_apple_auth_url(None)


def test_apple_credentials_from_env(monkeypatch):
    monkeypatch.setattr("mvp.credentials.credentials_for_url", lambda url: None)
    monkeypatch.setenv("APPLE_ID_EMAIL", "agent@example.com")
    monkeypatch.setenv("APPLE_ID_PASSWORD", "pw-" + "x" * 8)
    creds = apple_signin.apple_credentials()
    assert creds["username"] == "agent@example.com"
    assert "appleid.apple.com" in creds["match"]


def test_apple_credentials_missing(monkeypatch):
    monkeypatch.setattr("mvp.credentials.credentials_for_url", lambda url: None)
    monkeypatch.delenv("APPLE_ID_EMAIL", raising=False)
    monkeypatch.delenv("APPLE_ID_PASSWORD", raising=False)
    assert apple_signin.apple_credentials() is None


def test_sms_wait_never_uses_leased_number(monkeypatch):
    seen = {}

    def fake_wait(number, *, timeout_s, newer_than):
        seen["backend"] = number.backend
        return "123456"

    monkeypatch.setattr("mvp.sms_provider._backend", lambda: "api")
    monkeypatch.setattr("mvp.sms_provider.vault_phone", lambda: None)
    monkeypatch.setattr("mvp.sms_provider.wait_for_sms", fake_wait)
    assert apple_signin._wait_sms_code(0.0, 1.0) == "123456"
    assert seen["backend"] == "ntfy"
