"""Phone/SMS verification inside the in-run signup (no browser, no network)."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import mvp.signup_in_session as sis
from mvp.a11y_agent import signup_block_label

FAKE = "3175550107"  # not the owner's number


class PhoneForms(unittest.TestCase):
    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("MVP_PHONE_COUNTRY_CODE", None)
        os.environ.pop("MVP_PHONE_COUNTRY", None)

    def tearDown(self) -> None:
        self._env.stop()

    def test_bare_ten_digits_is_north_american(self) -> None:
        f = sis.phone_forms(FAKE)
        self.assertEqual(f["phone"], FAKE)
        self.assertEqual(f["phone_e164"], "+1" + FAKE)
        self.assertEqual(f["phone_country_code"], "+1")
        self.assertEqual(f["phone_country"], "United States")

    def test_formatted_and_prefixed(self) -> None:
        for raw in ("+1 (317) 555-0107", "1-317-555-0107", "+13175550107", "(317) 555 0107"):
            self.assertEqual(sis.phone_forms(raw)["phone"], FAKE, raw)
            self.assertEqual(sis.phone_forms(raw)["phone_e164"], "+1" + FAKE, raw)

    def test_international(self) -> None:
        f = sis.phone_forms("+44 7700 900123")
        self.assertEqual(f["phone_country_code"], "+44")
        self.assertEqual(f["phone"], "7700900123")
        self.assertEqual(f["phone_country"], "United Kingdom")

    def test_env_country_code(self) -> None:
        with mock.patch.dict(os.environ, {"MVP_PHONE_COUNTRY_CODE": "91"}):
            f = sis.phone_forms("9876543210")
        self.assertEqual(f["phone_e164"], "+919876543210")

    def test_unusable(self) -> None:
        self.assertEqual(sis.phone_forms(""), {})
        self.assertEqual(sis.phone_forms(None), {})
        self.assertEqual(sis.phone_forms("12345"), {})


class PhoneFill(unittest.TestCase):
    ident = sis.phone_forms(FAKE)

    def test_fill_ok_ignores_formatting_and_prefix(self) -> None:
        for got in (FAKE, "(317) 555-0107", "+1 317 555 0107", "+13175550107"):
            self.assertTrue(sis.phone_fill_ok(got, self.ident), got)

    def test_fill_not_ok_when_digits_went_into_country_code(self) -> None:
        self.assertFalse(sis.phone_fill_ok("+3 175 550 107", self.ident))
        self.assertFalse(sis.phone_fill_ok("", self.ident))
        self.assertFalse(sis.phone_fill_ok("+1", self.ident))
        self.assertFalse(sis.phone_fill_ok("+1 317 555 010", self.ident))
        self.assertFalse(sis.phone_fill_ok("99" + FAKE, self.ident))

    def test_retry_types_national_after_stuck_prefix(self) -> None:
        self.assertEqual(sis.phone_retry_values("+1", self.ident)[0], FAKE)
        self.assertEqual(sis.phone_retry_values("", self.ident), ["+1" + FAKE, FAKE])

    def test_redact_hides_phone_in_any_format(self) -> None:
        ident = {"password": "pw", **self.ident}
        for text in (f"We sent a code to {FAKE}", "sent to (317) 555-0107", "sent to +1 317-555-0107"):
            out = sis._redact(text, ident)
            self.assertNotIn("555", out, text)
            self.assertIn("<phone>", out)

    def test_country_option(self) -> None:
        opts = [{"text": "Select", "value": ""}, {"text": "CA +1", "value": "CA"}, {"text": "US +1", "value": "US"},
                {"text": "GB +44", "value": "GB"}]
        self.assertEqual(sis.country_option(opts, self.ident), 2)
        self.assertEqual(sis.country_option([{"text": "United States (+1)", "value": "x"}], self.ident), 0)
        self.assertEqual(sis.country_option([{"text": "+1", "value": "1"}], self.ident), 0)
        self.assertIsNone(sis.country_option([{"text": "+14", "value": "z"}], self.ident))

    def test_mask(self) -> None:
        self.assertEqual(sis._mask_phone(FAKE), "***07")


class Labels(unittest.TestCase):
    def test_sms_labels(self) -> None:
        self.assertIn("SMS", signup_block_label("sms_timeout"))
        self.assertIn("phone", signup_block_label("phone_required"))
        self.assertIn("phone", signup_block_label("phone_rejected: x"))
        self.assertIn("SMS code", signup_block_label("sms_code_rejected"))


class PromptKeepsDigitsPrivate(unittest.TestCase):
    def test_model_never_sees_phone_digits(self) -> None:
        seen: list[str] = []

        async def fake_chat(msgs: list[dict[str, Any]], **_: Any) -> str:
            seen.append(msgs[0]["content"])
            return '{"status":"working","actions":[]}'

        ident = {"email": "a@b.c", "password": "pw", **sis.phone_forms(FAKE)}
        with mock.patch("capability.gemini_config.gemini_chat", fake_chat):
            asyncio.run(sis._decide(snap={"url": "https://x.dev", "elements": []}, ident=ident,
                                    site_url="https://x.dev", history=[], note="", hint=""))
        self.assertTrue(seen)
        self.assertNotIn(FAKE, seen[0])
        self.assertIn("{phone}", seen[0])
        self.assertIn("need_sms", seen[0])


# ------------------------------------------------------------------ loop


class _Page:
    def __init__(self) -> None:
        self.url = "https://portal.example.dev/auth/2fa"
        self.context = SimpleNamespace(on=lambda *a: None, remove_listener=lambda *a: None, pages=[])

    def on(self, *a: Any) -> None:
        pass

    def remove_listener(self, *a: Any) -> None:
        pass

    async def goto(self, url: str, **_: Any) -> None:
        self.url = url

    async def reload(self, **_: Any) -> None:
        pass

    async def wait_for_timeout(self, ms: int) -> None:
        pass

    async def wait_for_load_state(self, *a: Any, **k: Any) -> None:
        pass


def _snap(n: int, body: str, url: str = "https://portal.example.dev/auth/2fa") -> dict[str, Any]:
    return {"url": url, "title": "t", "captcha": "", "body": body + f" #{n}",
            "elements": [{"i": 0, "tag": "input", "role": "textbox", "type": "tel", "name": "Phone", "filled": 0},
                         {"i": 1, "tag": "button", "role": "button", "name": "Continue"}]}


def _run_loop(decisions: list[dict[str, Any]], *, lease: Any, sms: Any, typed: list[str],
              prompts: list[dict[str, str]] | None = None) -> dict[str, Any]:
    it = iter(decisions)
    n = [0]

    async def fake_snapshot(page: Any) -> dict[str, Any]:
        n[0] += 1
        return _snap(n[0], "Enter your phone number for two-factor authentication")

    async def fake_decide(**kw: Any) -> dict[str, Any] | None:
        if prompts is not None:
            prompts.append(dict(kw["ident"]))
        return next(it, {"status": "working", "actions": []})

    async def fake_do(page: Any, act: dict[str, Any], ident: dict[str, str], elements: Any, home: str = "") -> str:
        return f"fill Phone = {act.get('value')}" if act.get("do") == "fill" else f"click button {act.get('i')!r}"

    async def fake_type(page: Any, code: str) -> bool:
        typed.append(code)
        return True

    async def fake_verify(snap: dict[str, Any]) -> tuple[bool, str]:
        return True, "dashboard with account menu"

    async def fake_settle(page: Any, ms: int = 0) -> None:
        pass

    inbox = SimpleNamespace(address="me+x@gmail.com", backend="gmail", wait=lambda *a: None)
    with mock.patch("mvp.signup_inbox.create_inbox", return_value=inbox), \
            mock.patch.object(sis, "_snapshot", fake_snapshot), \
            mock.patch.object(sis, "_decide", fake_decide), \
            mock.patch.object(sis, "_do", fake_do), \
            mock.patch.object(sis, "_type_code", fake_type), \
            mock.patch.object(sis, "_verify_signed_in", fake_verify), \
            mock.patch.object(sis, "_settle", fake_settle), \
            mock.patch.object(sis, "onboarding_blocks", lambda p: False), \
            mock.patch("mvp.sms_provider.lease_number", lease), \
            mock.patch("mvp.sms_provider.wait_for_sms", sms):
        page = _Page()
        return asyncio.run(sis.signup_in_session(page, "https://example.dev/", {}, timeout_s=200,
                                                 signup_url=page.url))


PHONE_FLOW = [
    {"status": "blocked", "reason": "phone_required", "actions": []},
    {"status": "working", "actions": [{"do": "fill", "i": 0, "value": "{phone}"}, {"do": "click", "i": 1}]},
    {"status": "need_sms", "actions": []},
    {"status": "signed_in", "actions": []},
]


class SmsLoop(unittest.TestCase):
    def test_phone_step_fills_owner_phone_and_types_texted_code(self) -> None:
        typed: list[str] = []
        waits: list[dict[str, Any]] = []
        number = SimpleNamespace(phone=FAKE, backend="ntfy", raw={"topic": "t-sms"})

        def fake_wait(num: Any, **kw: Any) -> str:
            waits.append(kw)
            return "482913"

        prompts: list[dict[str, str]] = []
        res = _run_loop(PHONE_FLOW, lease=mock.Mock(return_value=number), sms=fake_wait, typed=typed, prompts=prompts)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["reason"], "signed_up")
        self.assertEqual(typed, ["482913"])
        self.assertEqual(len(waits), 1)
        self.assertLessEqual(waits[0]["timeout_s"], 200)
        self.assertIsNotNone(waits[0]["newer_than"])
        self.assertGreaterEqual(waits[0]["poll_s"], 5)  # under ntfy.sh's per-IP refill rate
        self.assertEqual(res["sms"]["phone"], "***07")
        self.assertEqual(res["sms"]["codes_received"], 1)
        self.assertEqual(prompts[1].get("phone"), FAKE)  # substituted locally, masked in the prompt
        self.assertNotIn("555", " ".join(res["steps"]))

    def test_no_phone_configured_ends_phone_required(self) -> None:
        typed: list[str] = []
        lease = mock.Mock(side_effect=RuntimeError("no phone in secrets/credentials.json"))
        res = _run_loop(PHONE_FLOW, lease=lease, sms=mock.Mock(), typed=typed)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "phone_required")
        self.assertEqual(typed, [])

    def test_code_never_arrives_ends_sms_timeout(self) -> None:
        typed: list[str] = []
        number = SimpleNamespace(phone=FAKE, backend="ntfy", raw={"topic": "t-sms"})
        flow = PHONE_FLOW[:3] + [{"status": "need_sms", "actions": []}] * 3
        sms = mock.Mock(return_value=None)
        res = _run_loop(flow, lease=mock.Mock(return_value=number), sms=sms, typed=typed)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "sms_timeout")
        self.assertEqual(sms.call_count, 2)
        self.assertEqual(typed, [])

    def test_need_sms_before_phone_was_filled_does_not_wait(self) -> None:
        typed: list[str] = []
        number = SimpleNamespace(phone=FAKE, backend="ntfy", raw={})
        flow = [{"status": "need_phone", "actions": []}] + [{"status": "need_sms", "actions": []}] * 6
        sms = mock.Mock(return_value="111222")
        res = _run_loop(flow, lease=mock.Mock(return_value=number), sms=sms, typed=typed)
        self.assertFalse(res["ok"])
        self.assertTrue(res["reason"].startswith("phone_rejected"), res["reason"])
        sms.assert_not_called()


if __name__ == "__main__":
    unittest.main()
