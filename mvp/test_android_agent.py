from mvp import android_agent as aa

UI = """<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation="0">
<node text="" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]" clickable="false">
<node text="Continue with Apple" class="android.widget.Button" bounds="[100,1800][980,1900]" clickable="true"/>
<node text="" class="android.widget.EditText" bounds="[100,600][980,700]" clickable="true"/>
<node text="" class="android.view.View" bounds="[0,0][2,2]" clickable="true"/>
</node></hierarchy>"""


def test_parse_ui_keeps_labelled_and_interactive_nodes():
    els = aa.parse_ui(UI)
    assert [e.label for e in els] == ["Continue with Apple", ""]
    assert els[0].center == (540, 1850) and els[0].clickable
    assert els[1].editable


def test_parse_ui_bad_xml():
    assert aa.parse_ui("not xml") == []


def test_adb_text_arg_escapes_spaces_and_quotes():
    assert aa.adb_text_arg("a b") == "a%sb"
    assert aa.adb_text_arg("it's") == "'it'\"'\"'s'"


class FakeAdb:
    def __init__(self):
        self.calls = []

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def type_text(self, text):
        self.calls.append(("type", text))


def test_execute_tap_and_secret(monkeypatch):
    adb = FakeAdb()
    els = aa.parse_ui(UI)
    assert aa.execute(adb, {"action": "tap", "element": 0}, els, (1080, 2400), {}) == "ok"
    assert aa.execute(adb, {"action": "tap_point", "point": [500, 500]}, els, (1080, 2400), {}) == "ok"
    monkeypatch.setenv("APPLE_ID_EMAIL", "agent@example.com")
    assert aa.execute(adb, {"action": "type_secret", "field": "apple_email"}, els, (1080, 2400), {}) == "ok"
    monkeypatch.delenv("APPLE_ID_PASSWORD", raising=False)
    assert aa.execute(adb, {"action": "type_secret", "field": "apple_password"}, els, (1080, 2400), {}) == "missing_secret"
    assert adb.calls == [("tap", 540, 1850), ("tap", 540, 1200), ("type", "agent@example.com")]


def test_execute_sms_code(monkeypatch):
    adb = FakeAdb()
    monkeypatch.setattr(aa, "_wait_sms", lambda since: "482913")
    assert aa.execute(adb, {"action": "sms_code"}, [], (1080, 2400), {}) == "ok"
    assert adb.calls == [("type", "482913")]


def test_execute_totp_code(monkeypatch):
    import pyotp

    adb = FakeAdb()
    secret = pyotp.random_base32()
    monkeypatch.setenv(aa.TOTP_ENV, secret)
    assert aa.execute(adb, {"action": "totp_code"}, [], (1080, 2400), {}) == "ok"
    assert pyotp.TOTP(secret).verify(adb.calls[0][1], valid_window=1)
    monkeypatch.delenv(aa.TOTP_ENV)
    assert aa.execute(adb, {"action": "totp_code"}, [], (1080, 2400), {}) == "missing_secret"
